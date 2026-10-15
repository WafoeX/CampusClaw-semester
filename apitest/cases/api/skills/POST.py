from apitest.clients import Context
from apitest.scenarios import SKILL, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    before = context.database.rows("SELECT id FROM skills ORDER BY id")
    for payload in (
        {**SKILL, "name": " "},
        {**SKILL, "name": "x" * 121},
        {**SKILL, "instructions": ""},
        {**SKILL, "instructions": "x" * 20001},
        {**SKILL, "skill_type": "tool"},
        {**SKILL, "class_id": s.identity("teacher.beta")["class_id"]},
        {**SKILL, "creator_id": s.identity("teacher.beta")["user_id"]},
    ):
        s.call("POST", "/api/skills", body=payload, status=400)
    s.call("POST", "/api/skills", account="student.alpha", body=SKILL, status=403)
    s.call("POST", "/api/skills", account=None, body=SKILL, status=401)
    checks.require(
        before == context.database.rows("SELECT id FROM skills ORDER BY id"), "database.unchanged"
    )
    skill = s.skill()
    s.verify_resource(skill, "skills")
    checks.require(
        skill["state"] == "active" and s.skill_rows(skill["id"])[0]["revision_number"] == 1,
        "database.revisions",
    )


OPERATION = Operation("POST", "/api/skills", run)
