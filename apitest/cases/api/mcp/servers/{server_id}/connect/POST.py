from apitest.clients import Context
from apitest.mcp_scenarios import McpScenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = McpScenario(context, checks)
    server = s.server()
    path = f"/api/mcp/servers/{server['id']}/connect"
    s.server_access("POST", path, server["id"])
    connected = s.call("POST", path, account="teacher.alpha.other")
    checks.require(
        connected["state"] == "connected" and connected["tool_count"] == 2, "mcp.discovery"
    )
    s.verify_server(connected)
    s.discovery(connected)
    for url, code in (
        ("http://mcp-wrong-token:8090", "remote_unauthorized"),
        ("http://mcp-invalid:8000", "invalid_discovery"),
        ("http://mcp-timeout:8000", "tool_timeout"),
    ):
        failed = s.server(base_url=url)
        s.call("POST", f"/api/mcp/servers/{failed['id']}/connect", status=503, code=code)
        rows = context.database.rows(
            "SELECT state, safe_error_code FROM mcp_servers WHERE id = %s", (failed["id"],)
        )
        checks.require(rows[0] == {"state": "error", "safe_error_code": code}, "mcp.failure")
        s.discovery({**failed, "state": "error"})
    checks.require(s.call("GET", "/health")["status"] == "ok", "response.values")
    answer = s.call(
        "POST",
        "/api/knowledge/query",
        account="student.alpha",
        body={"question": "ALPHA_FERN", "mode": "keyword"},
    )
    checks.require(answer["status"] == "answered", "response.values")


OPERATION = Operation("POST", "/api/mcp/servers/{server_id}/connect", run)
