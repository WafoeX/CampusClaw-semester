from apitest.clients import Context
from apitest.mcp_scenarios import McpScenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = McpScenario(context, checks)
    server = s.server(connected=True)
    path = f"/api/mcp/servers/{server['id']}/tools"
    s.server_access("GET", path, server["id"])
    tools = s.discovery(server)
    for tool in tools:
        checks.require(
            set(tool) == {"name", "tool_ref", "description", "input_schema", "supported", "code"},
            "mcp.safe_fields",
        )
        checks.require(tool["input_schema"]["required"] == ["question"], "mcp.discovery")
    checks.require(s.call("GET", path, account="teacher.alpha.other") == tools, "response.values")
    s.call("POST", f"/api/mcp/servers/{server['id']}/disconnect")
    s.discovery({**server, "state": "disconnected"})


OPERATION = Operation("GET", "/api/mcp/servers/{server_id}/tools", run)
