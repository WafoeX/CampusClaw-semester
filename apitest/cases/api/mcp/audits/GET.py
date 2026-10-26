from apitest.clients import Context
from apitest.mcp_scenarios import McpScenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = McpScenario(context, checks)
    server, _, conversation = s.bound_conversation()
    s.call("GET", "/api/mcp/audits", account=None, status=401)
    s.call("GET", "/api/mcp/audits", account="student.alpha", status=403)
    path = f"/api/mcp/audits?server_id={server['id']}"
    s.call("GET", path, account="teacher.beta", status=404)
    for _ in range(2):
        events = s.stream(conversation["id"], "ALPHA_FERN 欧姆定律")
        s.verify_tool_turn(events, server, "ok", "ok")
    page = s.call("GET", path + "&limit=1", account="teacher.alpha.other")
    checks.require(len(page["items"]) == 1 and page["next_cursor"], "response.bounds")
    next_page = s.call(
        "GET", path + "&limit=1&cursor=" + page["next_cursor"], account="teacher.alpha.other"
    )
    checks.require(
        len(next_page["items"]) == 1 and next_page["next_cursor"] is None, "response.bounds"
    )
    checks.require(page["items"][0]["id"] != next_page["items"][0]["id"], "mcp.audit")
    for row in page["items"] + next_page["items"]:
        checks.require(
            set(row)
            == {
                "id",
                "server_id",
                "tool_ref",
                "status",
                "code",
                "user_id",
                "conversation_id",
                "assistant_message_id",
                "created_at",
                "completed_at",
            },
            "mcp.safe_fields",
        )
        observed = context.database.rows(
            "SELECT status, code, tool_ref FROM mcp_tool_calls WHERE id = %s", (row["id"],)
        )
        checks.require(
            len(observed) == 1
            and observed[0] == {key: row[key] for key in ("status", "code", "tool_ref")},
            "mcp.audit",
        )
        checks.require(row["user_id"] == s.identity("student.alpha")["user_id"], "database.scope")
    s.call("GET", "/api/mcp/audits?limit=0", status=400)
    s.call("GET", "/api/mcp/audits?cursor=invalid", status=400)


OPERATION = Operation("GET", "/api/mcp/audits", run)
