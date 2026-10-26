"""Bearer-protected, stateless HTTP JSON-RPC subset (not a general MCP SDK)."""

import hmac
import json
import os
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from campusclaw_mcp.tools import HANDLERS, TOOLS

PROTOCOL_VERSION = "2024-11-05"
MAX_REQUEST_BYTES = 65536
ERRORS = {
    -32700: "Parse error",
    -32600: "Invalid Request",
    -32601: "Method not found",
    -32602: "Invalid params",
}


def object_dict(value: object) -> dict[str, Any] | None:
    """JSON decoding guarantees string object keys; narrow the object boundary."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def rpc_error(code: int, request_id: object = None) -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": ERRORS[code]},
        }
    )


def valid_id(value: object) -> bool:
    return value is None or type(value) in (str, int)


def invalid_constant(_value: str) -> None:
    raise ValueError("Non-JSON constant")


def dispatch(method: str, value: object) -> tuple[object, int | None]:
    params = object_dict(value)
    if method == "initialize":
        if params is None:
            return None, -32602
        client = object_dict(params.get("clientInfo"))
        if (
            params.get("protocolVersion") != PROTOCOL_VERSION
            or object_dict(params.get("capabilities")) is None
            or client is None
            or not isinstance(client.get("name"), str)
            or not isinstance(client.get("version"), str)
        ):
            return None, -32602
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "campusclaw-demo", "version": "0.1.0"},
        }, None
    if method == "tools/list":
        if value not in (None, {}):
            return None, -32602
        return {"tools": TOOLS}, None
    if method == "tools/call":
        if params is None or set(params) != {"name", "arguments"}:
            return None, -32602
        name = params["name"]
        arguments = object_dict(params["arguments"])
        if not isinstance(name, str) or name not in HANDLERS:
            return None, -32602
        if arguments is None or set(arguments) != {"question"}:
            return None, -32602
        question = arguments["question"]
        if not isinstance(question, str) or not 1 <= len(question) <= 2000:
            return None, -32602
        return HANDLERS[name](question), None
    if method == "notifications/initialized":
        return (None, None) if value in (None, {}) else (None, -32602)
    return None, -32601


def create_app() -> FastAPI:
    token = os.environ.get("MCP_AUTH_TOKEN", "")
    if not token.strip():
        raise RuntimeError("MCP runtime credential is required")
    expected = f"Bearer {token}".encode()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/mcp")
    async def mcp(request: Request) -> Response:
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected):
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return JSONResponse({"detail": "JSON required"}, status_code=415)
        accepts = request.headers.get("accept", "*/*").split(",")
        if not any(
            item.split(";", 1)[0].strip() in {"*/*", "application/json"} for item in accepts
        ):
            return JSONResponse({"detail": "JSON response required"}, status_code=406)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
            body.extend(chunk)
        try:
            decoded: object = json.loads(body, parse_constant=invalid_constant)
        except (ValueError, UnicodeError, RecursionError):
            return rpc_error(-32700)
        payload = object_dict(decoded)
        if payload is None:
            return rpc_error(-32600)
        request_id: object = payload.get("id")
        method = payload.get("method")
        if (
            payload.get("jsonrpc") != "2.0"
            or not isinstance(method, str)
            or not valid_id(request_id)
            or set(payload) - {"jsonrpc", "id", "method", "params"}
        ):
            return rpc_error(-32600, request_id if valid_id(request_id) else None)
        result, error = dispatch(method, payload.get("params"))
        if "id" not in payload:
            return Response(status_code=202)
        if error is not None:
            return rpc_error(error, request_id)
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

    return app
