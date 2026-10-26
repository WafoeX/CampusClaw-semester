"""Generated MCP documentation matches safe HTTP/skill/SSE contracts, without runtime secrets."""

import json

from pydantic import SecretStr

from campusclaw.api.mcp_schemas import McpRegisterRequest
from campusclaw.api.schemas import ToolCallMeta, ToolCallStatus
from campusclaw.config import Settings
from campusclaw.main import create_app


def test_mcp_paths_security_safe_errors_and_registration_example(settings: Settings) -> None:
    settings.MCP_AUTH_TOKEN = SecretStr("PRIVATE_MCP_DOCUMENTATION_SENTINEL")
    document = create_app(settings=settings).openapi()
    paths = {
        "/api/mcp/servers": {"get", "post"},
        "/api/mcp/servers/{server_id}/connect": {"post"},
        "/api/mcp/servers/{server_id}/tools": {"get"},
        "/api/mcp/servers/{server_id}/disconnect": {"post"},
        "/api/mcp/audits": {"get"},
    }
    for path, methods in paths.items():
        for method in methods:
            operation = document["paths"][path][method]
            assert operation["security"] == [{"BearerJWT": []}]
            assert operation["summary"] and "Teacher-only" in operation["description"]
            assert {"400", "401", "403", "404", "409", "503"} <= operation["responses"].keys()
            assert "422" not in operation["responses"]
            for code in (400, 401, 403, 404, 409, 503):
                assert operation["responses"][str(code)]["content"]["application/json"][
                    "schema"
                ] == {"$ref": "#/components/schemas/DomainErrorResponse"}
    schemas = document["components"]["schemas"]
    request = schemas["McpRegisterRequest"]
    assert set(request["properties"]) == {"name", "base_url"}
    McpRegisterRequest.model_validate(
        {name: field["examples"][0] for name, field in request["properties"].items()}
    )
    for name in ("McpServerResponse", "McpToolResponse", "McpAuditResponse"):
        assert not {"token", "authorization", "arguments", "raw_result", "question"} & set(
            schemas[name]["properties"]
        )
    assert "PRIVATE_MCP_DOCUMENTATION_SENTINEL" not in json.dumps(document)
    assert "MCP_AUTH_TOKEN" not in json.dumps(document)


def test_skill_omission_and_terminal_metadata_contracts_are_documented() -> None:
    document = create_app().openapi()
    schemas = document["components"]["schemas"]
    for name in ("SkillCreateRequest", "SkillUpdateRequest", "SkillResponse"):
        tools = schemas[name]["properties"]["tools"]
        assert tools["type"] == "array" and tools["maxItems"] == 8
    for path, method in (("/api/skills", "post"), ("/api/skills/{skill_id}", "patch")):
        description = document["paths"][path][method]["description"]
        assert "omitted on update preserves" in description
        assert "explicit empty list" in description
        assert "409" in description and "404" in description
    assert set(schemas["ToolCallStatus"]["properties"]) == set(ToolCallStatus.model_fields)
    assert set(schemas["ToolCallMeta"]["properties"]) == set(ToolCallMeta.model_fields)
    for name in ("MessageCompleted", "MessageError"):
        assert schemas[name]["properties"]["meta"]["$ref"] == "#/components/schemas/ToolCallMeta"
    assert (
        schemas["ConversationMessageResponse"]["properties"]["tool_calls"]["items"]["$ref"]
        == "#/components/schemas/ToolCallStatus"
    )
    stream = document["paths"]["/api/conversations/{conversation_id}/messages"]["post"]
    assert "meta.tool_calls" in stream["description"]
    assert "even when generation fails" in stream["description"]
