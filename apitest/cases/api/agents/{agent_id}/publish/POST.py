from apitest.clients import Context
from apitest.scenarios import AGENT, MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    draft = s.call("POST", "/api/agents", body=AGENT, status=201)
    path = f"/api/agents/{draft['id']}/publish"
    before = s.agent_rows(draft["id"])
    s.call("POST", path, status=409, code="agent_not_ready")
    checks.require(before == s.agent_rows(draft["id"]), "database.unchanged")
    agent = s.agent()
    path = f"/api/agents/{agent['id']}/publish"
    before = s.agent_rows(agent["id"])
    s.hidden("POST", path, f"/api/agents/{MISSING}/publish")
    s.call("POST", path, account="student.alpha", status=404)
    s.call("POST", path, account=None, status=401)
    checks.require(before == s.agent_rows(agent["id"]), "database.unchanged")
    published = s.call("POST", path)
    s.verify_resource(published, "agents")
    checks.require(
        published["state"] == "published"
        and published["published_revision_id"] == published["current_revision_id"],
        "database.revisions",
    )
    checks.require(s.call("POST", path) == published, "response.values")
    catalog = s.call("GET", "/api/agents", account="student.alpha")
    checks.require(agent["id"] in {item["id"] for item in catalog}, "response.values")


OPERATION = Operation("POST", "/api/agents/{agent_id}/publish", run)
