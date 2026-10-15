from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    conversation, agent = s.conversation()
    identifier = agent["skill_ids"][0]
    path = f"/api/skills/{identifier}"
    before = s.skill_rows(identifier)
    s.hidden("DELETE", path, f"/api/skills/{MISSING}")
    s.call("DELETE", path, account="student.alpha", status=403)
    s.call("DELETE", path, account=None, status=401)
    checks.require(before == s.skill_rows(identifier), "database.unchanged")
    retired = s.call("DELETE", path)
    s.verify_resource(retired, "skills")
    checks.require(retired["state"] == "retired", "response.values")
    changed = s.call("GET", f"/api/agents/{agent['id']}")
    s.verify_resource(changed, "agents")
    checks.require(changed["state"] == "draft", "database.bindings")
    s.call("POST", f"/api/agents/{agent['id']}/publish", status=409, code="agent_not_ready")
    s.call(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        account="student.alpha",
        body={"content": "ALPHA_FERN"},
        status=409,
        code="agent_not_ready",
    )
    checks.require(s.messages(conversation["id"]) == [], "database.unchanged")


OPERATION = Operation("DELETE", "/api/skills/{skill_id}", run)
