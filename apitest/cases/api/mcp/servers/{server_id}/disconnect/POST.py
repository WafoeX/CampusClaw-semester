from apitest.clients import Context
from apitest.mcp_scenarios import McpScenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = McpScenario(context, checks)
    server = s.server(connected=True)
    path = f"/api/mcp/servers/{server['id']}/disconnect"
    s.server_access("POST", path, server["id"])
    disconnected = s.call("POST", path, account="teacher.alpha.other")
    checks.require(
        disconnected["state"] == "disconnected"
        and disconnected["connection_generation"] > server["connection_generation"],
        "mcp.disconnected",
    )
    s.verify_server(disconnected)
    s.discovery(disconnected)
    again = s.call("POST", path)
    checks.require(
        again["state"] == "disconnected" and again["tool_count"] == 0, "mcp.disconnected"
    )
    s.verify_server(again)
    s.discovery(again)


OPERATION = Operation("POST", "/api/mcp/servers/{server_id}/disconnect", run)
