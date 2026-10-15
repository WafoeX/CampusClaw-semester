from apitest.clients import Context
from apitest.scenarios import Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    own, draft, peer, beta = (
        s.agent(published=True),
        s.agent(),
        s.agent("teacher.alpha.other", published=True),
        s.agent("teacher.beta", published=True),
    )
    values = s.call("GET", "/api/agents")
    ids = {item["id"] for item in values}
    checks.require(
        {own["id"], draft["id"]} <= ids and peer["id"] not in ids and beta["id"] not in ids,
        "auth.private_fields",
    )
    for item in values:
        s.verify_resource(item, "agents")
    catalog = s.call("GET", "/api/agents", account="student.alpha")
    ids = {item["id"] for item in catalog}
    checks.require(
        {own["id"], peer["id"]} <= ids and draft["id"] not in ids and beta["id"] not in ids,
        "auth.private_fields",
    )
    checks.require(
        all(set(item) == {"id", "name", "description"} for item in catalog), "auth.private_fields"
    )
    for item in catalog:
        row = s.agent_rows(item["id"])[0]
        checks.require(
            row["state"] == "published"
            and str(row["class_id"]) == s.identity("student.alpha")["class_id"],
            "database.scope",
        )
    s.call("GET", "/api/agents", account=None, status=401)


OPERATION = Operation("GET", "/api/agents", run)
