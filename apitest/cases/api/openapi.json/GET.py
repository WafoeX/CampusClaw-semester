from apitest.clients import Context
from apitest.scenarios import Scenario
from apitest.support import Checks, Operation

EXPECTED: dict[str, dict[str, set[str]]] = {
    "/health": {"get": {"200", "503"}},
    "/api/auth/login": {"post": {"200", "401"}},
    "/api/auth/logout": {"post": {"204"}},
    "/api/auth/me": {"get": {"200", "401"}},
    "/api/materials": {"get": {"200", "401", "403"}, "post": {"201", "400", "401", "403", "413"}},
    "/api/materials/{material_id}/download": {"get": {"200", "401", "403", "404", "500"}},
    "/api/knowledge/query": {"post": {"200", "400", "401", "403", "503"}},
    "/api/agents": {"get": {"200", "401", "403"}, "post": {"201", "400", "401", "403", "404"}},
    "/api/agents/{agent_id}": {
        method: {success, "400", "401", "403", "404"}
        for method, success in (("get", "200"), ("patch", "200"), ("delete", "200"))
    },
    "/api/agents/{agent_id}/publish": {"post": {"200", "400", "401", "403", "404", "409"}},
    "/api/agents/{agent_id}/unpublish": {"post": {"200", "401", "403", "404"}},
    "/api/skills": {"get": {"200", "401", "403"}, "post": {"201", "400", "401", "403"}},
    "/api/skills/{skill_id}": {
        method: {"200", "400", "401", "403", "404"} for method in ("get", "patch", "delete")
    },
    "/api/conversations": {
        "get": {"200", "401", "403"},
        "post": {"201", "400", "401", "403", "409"},
    },
    "/api/conversations/{conversation_id}": {
        method: {"200", "400", "401", "403", "404"} for method in ("get", "delete")
    },
    "/api/agents/{agent_id}/conversations": {"get": {"200", "400", "401", "403", "404"}},
    "/api/agents/{agent_id}/conversations/{conversation_id}": {
        "get": {"200", "400", "401", "403", "404"}
    },
    "/api/conversations/{conversation_id}/messages": {
        "post": {"200", "400", "401", "403", "404", "409", "413", "429", "503"}
    },
    "/api/docs": {"get": {"200"}},
    "/api/openapi.json": {"get": {"200"}},
}


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    document = s.document
    checks.require(
        document["openapi"].startswith("3.1.") and set(EXPECTED) <= document["paths"].keys(),
        "response.fields",
    )
    checks.require(
        document["components"]["securitySchemes"]
        == {"BearerJWT": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
        "auth.identity",
    )
    operation_ids: list[str] = []
    public = {"/health", "/api/auth/login", "/api/auth/logout", "/api/docs", "/api/openapi.json"}
    for path, methods in EXPECTED.items():
        for method, statuses in methods.items():
            operation = document["paths"][path][method]
            checks.require(
                statuses <= operation["responses"].keys()
                and bool(operation["tags"])
                and bool(operation["summary"])
                and bool(operation["operationId"]),
                "response.schema",
            )
            checks.require(
                operation["security"] == ([] if path in public else [{"BearerJWT": []}]),
                "auth.identity",
            )
            operation_ids.append(operation["operationId"])
            if method in {"post", "patch"} and path in {
                "/api/auth/login",
                "/api/knowledge/query",
                "/api/agents",
                "/api/skills",
                "/api/agents/{agent_id}",
                "/api/skills/{skill_id}",
                "/api/conversations",
                "/api/conversations/{conversation_id}/messages",
            }:
                checks.require(
                    "application/json" in operation["requestBody"]["content"], "response.schema"
                )
    checks.require(len(operation_ids) == len(set(operation_ids)), "response.fields")
    message = document["paths"]["/api/conversations/{conversation_id}/messages"]["post"]
    media = message["responses"]["200"]["content"]["text/event-stream"]
    checks.require(
        set(media["x-event-schemas"])
        == {"message.started", "answer.delta", "citation", "message.completed", "message.error"}
        and "Pre-stream" in message["description"]
        and "monotonically" in message["description"],
        "stream.order",
    )
    for reference in media["x-event-schemas"].values():
        schema = document["components"]["schemas"][reference["$ref"].split("/")[-1]]
        checks.require(
            {"sequence", "conversation_id", "user_message_id", "assistant_message_id"}
            <= set(schema["required"])
            and type(schema["additionalProperties"]) is bool
            and not schema["additionalProperties"],
            "stream.identifiers",
        )
    s.call("GET", "/api/auth/me", account=None, status=401)


OPERATION = Operation("GET", "/api/openapi.json", run)
