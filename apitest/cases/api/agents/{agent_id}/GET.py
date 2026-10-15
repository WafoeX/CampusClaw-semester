from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    agent = s.agent()
    path = f"/api/agents/{agent['id']}"
    before = s.agent_rows(agent["id"])
    checks.require(s.call("GET", path) == agent, "response.values")
    s.verify_resource(agent, "agents")
    s.hidden(
        "GET",
        path,
        f"/api/agents/{MISSING}",
        accounts=("teacher.alpha.other", "teacher.beta", "student.alpha", "student.beta"),
    )
    s.call("GET", path, account=None, status=401)
    checks.require(before == s.agent_rows(agent["id"]), "database.unchanged")


OPERATION = Operation("GET", "/api/agents/{agent_id}", run)
