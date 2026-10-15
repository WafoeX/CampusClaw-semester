from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    skill = s.skill()
    path = f"/api/skills/{skill['id']}"
    before = s.skill_rows(skill["id"])
    checks.require(s.call("GET", path) == skill, "response.values")
    s.verify_resource(skill, "skills")
    s.hidden("GET", path, f"/api/skills/{MISSING}")
    s.call("GET", path, account="student.alpha", status=403)
    s.call("GET", path, account=None, status=401)
    checks.require(s.skill_rows(skill["id"]) == before, "database.unchanged")


OPERATION = Operation("GET", "/api/skills/{skill_id}", run)
