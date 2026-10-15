from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    conversation, agent = s.conversation()
    path = f"/api/agents/{agent['id']}/unpublish"
    before = s.agent_rows(agent["id"])
    s.hidden("POST", path, f"/api/agents/{MISSING}/unpublish")
    s.call("POST", path, account="student.alpha", status=404)
    s.call("POST", path, account=None, status=401)
    checks.require(before == s.agent_rows(agent["id"]), "database.unchanged")
    unpublished = s.call("POST", path)
    s.verify_resource(unpublished, "agents")
    checks.require(
        unpublished["state"] == "draft" and unpublished["published_revision_id"] is None,
        "database.rows",
    )
    checks.require(s.call("POST", path) == unpublished, "response.values")
    s.call(
        "POST",
        "/api/conversations",
        account="student.alpha",
        body={"agent_id": agent["id"]},
        status=409,
        code="agent_not_ready",
    )
    s.call(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        account="student.alpha",
        body={"content": "ALPHA_FERN"},
        status=409,
        code="agent_not_ready",
    )
    checks.require(s.messages(conversation["id"]) == [], "database.unchanged")
    checks.require(
        agent["id"]
        not in {item["id"] for item in s.call("GET", "/api/agents", account="student.alpha")},
        "response.values",
    )


OPERATION = Operation("POST", "/api/agents/{agent_id}/unpublish", run)
