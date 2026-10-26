from apitest.clients import Context
from apitest.mcp_scenarios import McpScenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = McpScenario(context, checks)
    s.call("GET", "/api/mcp/servers", account=None, status=401)
    s.call("GET", "/api/mcp/servers", account="student.alpha", status=403)
    foreign = s.server(account="teacher.beta")
    first = s.server()
    second = s.server()
    page = s.call("GET", "/api/mcp/servers?limit=1", account="teacher.alpha.other")
    checks.require(len(page["items"]) == 1 and page["next_cursor"], "response.bounds")
    next_page = s.call(
        "GET",
        "/api/mcp/servers?limit=1&cursor=" + page["next_cursor"],
        account="teacher.alpha.other",
    )
    checks.require(next_page["items"][0]["id"] != page["items"][0]["id"], "response.values")
    seen: set[str] = set()
    cursor = None
    while True:
        page = s.call("GET", "/api/mcp/servers?limit=100" + ("&cursor=" + cursor if cursor else ""))
        for row in page["items"]:
            checks.require(row["id"] not in seen and row["id"] != foreign["id"], "database.scope")
            seen.add(row["id"])
            s.verify_server(row)
        cursor = page["next_cursor"]
        if cursor is None:
            break
    checks.require({first["id"], second["id"]} <= seen, "response.values")
    s.call("GET", "/api/mcp/servers?limit=0", status=400)
    s.call("GET", "/api/mcp/servers?cursor=invalid", status=400)


OPERATION = Operation("GET", "/api/mcp/servers", run)
