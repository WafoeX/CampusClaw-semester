from apitest.clients import Context
from apitest.mcp_scenarios import McpScenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = McpScenario(context, checks)
    data = {"name": context.fixtures.name("register"), "base_url": "http://mcp-demo:8090"}
    s.call("POST", "/api/mcp/servers", body=data, account=None, status=401)
    s.call("POST", "/api/mcp/servers", body=data, account="student.alpha", status=403)
    for payload in (
        {**data, "class_id": s.identity("teacher.beta")["class_id"]},
        {**data, "name": "INVALID"},
        {**data, "base_url": "http://127.0.0.1"},
        {**data, "base_url": "http://user:secret@mcp-demo:8090"},
        {**data, "token": "DO_NOT_ECHO"},
    ):
        s.call("POST", "/api/mcp/servers", body=payload, status=400)
    server = s.call("POST", "/api/mcp/servers", body=data, status=201)
    s.verify_server(server)
    checks.require(
        server["state"] == "disconnected" and server["tool_count"] == 0, "mcp.registration"
    )
    s.call("POST", "/api/mcp/servers", body=data, status=409, code="server_name_conflict")
    other = s.call("POST", "/api/mcp/servers", body=data, account="teacher.beta", status=201)
    s.verify_server(other, "teacher.beta")
    checks.require(server["id"] != other["id"], "database.scope")


OPERATION = Operation("POST", "/api/mcp/servers", run)
