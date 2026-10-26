"""Bounded MCP JSON-RPC client with fixed safe failures and server-only credentials."""

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, TypeGuard, cast

import httpx
from jsonschema.exceptions import SchemaError
from jsonschema.validators import Draft202012Validator

from campusclaw.application.mcp_transport import mcp_http_client
from campusclaw.config import Settings

PROTOCOL = "2024-11-05"
RPC_TIMEOUT = 3.0
CONNECT_TIMEOUT = 8.0
MAX_RESPONSE_BYTES = 65536
SAFE_ERRORS = {
    "credential_unavailable": "请联系部署者配置 MCP 运行时凭证。",
    "remote_unauthorized": "远端拒绝认证，请联系部署者检查运行时凭证。",
    "tool_timeout": "MCP 请求超时，请检查服务状态后重新连接。",
    "remote_unavailable": "MCP 服务不可用，请检查内部网络与服务状态。",
    "protocol_error": "MCP 协议响应无效，请检查协议版本与服务实现。",
    "response_too_large": "MCP 响应超出限制，请缩小工具元数据或结果。",
    "invalid_discovery": "工具发现内容无效，请检查工具名称、数量及 schema。",
    "tool_error": "工具未能处理该问题，请检查工具支持范围。",
    "invalid_tool_result": "工具未返回有效的有界文本，请检查远端实现。",
}


class McpFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code if code in SAFE_ERRORS else "protocol_error"
        super().__init__(SAFE_ERRORS[self.code])


def obj(value: object) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def invalid_json_constant(_value: str) -> Never:
    raise ValueError("Non-JSON constant")


def is_array(value: object) -> TypeGuard[list[Any]]:
    return isinstance(value, list)


def compatible_question_schema(schema: dict[str, Any]) -> bool:
    properties = obj(schema.get("properties"))
    question = obj(properties.get("question")) if properties is not None else None
    required = schema.get("required")
    if (
        schema.get("type") != "object"
        or question is None
        or required != ["question"]
        or question.get("type") != "string"
        or set(schema)
        - {"type", "properties", "required", "additionalProperties", "description", "title"}
        or set(question) - {"type", "minLength", "maxLength", "description", "title"}
    ):
        return False
    minimum, maximum = question.get("minLength", 1), question.get("maxLength", 2000)
    return type(minimum) is int and type(maximum) is int and minimum <= 1 and maximum >= 2000


@dataclass(frozen=True)
class DiscoveredTool:
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def supported(self) -> bool:
        return compatible_question_schema(self.input_schema)


def _bounded_json(value: object, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if isinstance(value, dict):
        return all(_bounded_json(v, depth + 1) for v in cast(dict[str, Any], value).values())
    if is_array(value):
        return all(_bounded_json(v, depth + 1) for v in value)
    return value is None or type(value) in (str, int, float, bool)


def validate_discovery(result: dict[str, Any]) -> list[DiscoveredTool]:
    tools = result.get("tools")
    if not is_array(tools) or len(tools) > 50 or result.get("nextCursor") is not None:
        raise McpFailure("invalid_discovery")
    found: list[DiscoveredTool] = []
    names: set[str] = set()
    for value in tools:
        tool = obj(value)
        if tool is None:
            raise McpFailure("invalid_discovery")
        name, description = tool.get("name"), tool.get("description", "")
        schema = obj(tool.get("inputSchema"))
        if (
            not isinstance(name, str)
            or len(name) > 200
            or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None
            or name in names
            or not isinstance(description, str)
            or len(description) > 1000
            or schema is None
            or not _bounded_json(schema)
            or len(json.dumps(schema, ensure_ascii=True)) > 8000
        ):
            raise McpFailure("invalid_discovery")
        # Validate schema structure only; never resolve remote references or
        # instantiate a validator for remote-controlled arguments.
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError:
            raise McpFailure("invalid_discovery") from None
        names.add(name)
        found.append(DiscoveredTool(name, description, schema))
    return found


class McpClient:
    def __init__(
        self,
        settings: Settings,
        *,
        factory: Callable[[], httpx.AsyncClient] = mcp_http_client,
    ) -> None:
        self.settings = settings
        self.factory = factory

    def credential(self, base_url: str) -> str:
        try:
            credential = self.settings.mcp_credential(base_url)
        except ValueError:
            raise McpFailure("credential_unavailable") from None
        if credential is None:
            raise McpFailure("credential_unavailable")
        return credential.get_secret_value()

    async def rpc(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        method: str,
        params: dict[str, Any],
        *,
        notification: bool = False,
    ) -> dict[str, Any]:
        token = self.credential(base_url)
        request_id = uuid.uuid4().hex
        request: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            request["id"] = request_id
        try:
            async with (
                asyncio.timeout(RPC_TIMEOUT),
                client.stream(
                    "POST",
                    self.settings.approved_mcp_origin(base_url) + "/mcp",
                    json=request,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    follow_redirects=False,
                ) as response,
            ):
                if response.status_code == 401:
                    raise McpFailure("remote_unauthorized")
                if response.status_code != (202 if notification else 200):
                    raise McpFailure("protocol_error")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise McpFailure("response_too_large")
                    body.extend(chunk)
                if notification:
                    if body:
                        raise McpFailure("protocol_error")
                    return {}
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip()
                    != "application/json"
                ):
                    raise McpFailure("protocol_error")
                payload = obj(json.loads(body, parse_constant=invalid_json_constant))
                if (
                    payload is None
                    or payload.get("jsonrpc") != "2.0"
                    or payload.get("id") != request_id
                    or "error" in payload
                    or obj(payload.get("result")) is None
                    or token in json.dumps(payload, ensure_ascii=False)
                ):
                    raise McpFailure("protocol_error")
                return cast(dict[str, Any], payload["result"])
        except (TimeoutError, httpx.TimeoutException):
            raise McpFailure("tool_timeout") from None
        except httpx.HTTPError:
            raise McpFailure("remote_unavailable") from None
        except (ValueError, RecursionError):
            raise McpFailure("protocol_error") from None

    async def discover(self, base_url: str) -> list[DiscoveredTool]:
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT), self.factory() as client:
                result = await self.rpc(
                    client,
                    base_url,
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL,
                        "capabilities": {},
                        "clientInfo": {"name": "campusclaw", "version": "0.1.0"},
                    },
                )
                capabilities, info = obj(result.get("capabilities")), obj(result.get("serverInfo"))
                if (
                    result.get("protocolVersion") != PROTOCOL
                    or capabilities is None
                    or obj(capabilities.get("tools")) is None
                    or info is None
                    or not isinstance(info.get("name"), str)
                    or not isinstance(info.get("version"), str)
                ):
                    raise McpFailure("protocol_error")
                await self.rpc(client, base_url, "notifications/initialized", {}, notification=True)
                return validate_discovery(await self.rpc(client, base_url, "tools/list", {}))
        except TimeoutError:
            raise McpFailure("tool_timeout") from None

    async def call(self, base_url: str, name: str, question: str) -> str:
        async with self.factory() as client:
            result = await self.rpc(
                client,
                base_url,
                "tools/call",
                {
                    "name": name,
                    "arguments": {"question": question[:2000]},
                },
            )
        if result.get("isError", False) is not False:
            raise McpFailure("tool_error")
        content = result.get("content")
        if not is_array(content) or not content:
            raise McpFailure("invalid_tool_result")
        texts: list[str] = []
        for value in content:
            part = obj(value)
            if part is None or part.get("type") != "text" or not isinstance(part.get("text"), str):
                raise McpFailure("invalid_tool_result")
            texts.append(part["text"])
        text = "\n".join(texts)
        if not text.strip() or len(text) > 4000:
            raise McpFailure("invalid_tool_result")
        try:
            text.encode("utf-8")
        except UnicodeError:
            raise McpFailure("invalid_tool_result") from None
        return text
