from apitest.clients import Context
from apitest.scenarios import MISSING, SKILL, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    agent = s.agent(published=True)
    identifier = agent["skill_ids"][0]
    path = f"/api/skills/{identifier}"
    before = s.skill_rows(identifier)
    revisions = context.database.rows(
        "SELECT * FROM skill_revisions WHERE skill_id = %s ORDER BY revision_number", (identifier,)
    )
    for payload in (
        {**SKILL, "instructions": " "},
        {**SKILL, "name": "x" * 121},
        {**SKILL, "instructions": "x" * 20001},
        {**SKILL, "creator_id": MISSING},
    ):
        s.call("PATCH", path, body=payload, status=400)
    s.call("PATCH", path, account="student.alpha", body=SKILL, status=403)
    s.call("PATCH", path, account=None, body=SKILL, status=401)
    s.hidden("PATCH", path, f"/api/skills/{MISSING}", body=SKILL)
    checks.require(before == s.skill_rows(identifier), "database.unchanged")
    updated = s.call("PATCH", path, body={**SKILL, "instructions": "先核对观察，再提出追问。"})
    s.verify_resource(updated, "skills")
    after = context.database.rows(
        "SELECT * FROM skill_revisions WHERE skill_id = %s ORDER BY revision_number", (identifier,)
    )
    checks.require(
        after[:-1] == revisions
        and len(after) == 2
        and updated["current_revision_id"] != str(before[0]["current_revision_id"]),
        "database.revisions",
    )
    changed = s.call("GET", f"/api/agents/{agent['id']}")
    s.verify_resource(changed, "agents")
    checks.require(
        changed["state"] == "draft"
        and changed["current_revision_id"] != agent["current_revision_id"],
        "database.bindings",
    )


OPERATION = Operation("PATCH", "/api/skills/{skill_id}", run)
