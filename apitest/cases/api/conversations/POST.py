from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    draft, beta, agent = s.agent(), s.agent("teacher.beta", published=True), s.agent(published=True)
    before = context.database.rows("SELECT id FROM conversations ORDER BY id")
    for identifier in (draft["id"], beta["id"], MISSING):
        s.call(
            "POST",
            "/api/conversations",
            account="student.alpha",
            body={"agent_id": identifier},
            status=409,
            code="agent_not_ready",
        )
    payload = {"agent_id": agent["id"]}
    for field in ("class_id", "student_id", "creator_id", "history"):
        s.call(
            "POST",
            "/api/conversations",
            account="student.alpha",
            body={**payload, field: MISSING},
            status=400,
        )
    s.call("POST", "/api/conversations", account="teacher.alpha", body=payload, status=403)
    s.call("POST", "/api/conversations", account=None, body=payload, status=401)
    checks.require(
        before == context.database.rows("SELECT id FROM conversations ORDER BY id"),
        "database.unchanged",
    )
    value = s.call("POST", "/api/conversations", account="student.alpha", body=payload, status=201)
    s.verify_conversation(value)
    checks.require(
        value["messages"] == []
        and value["deleted_at"] is None
        and value["agent_id"] == agent["id"],
        "response.values",
    )


OPERATION = Operation("POST", "/api/conversations", run)
