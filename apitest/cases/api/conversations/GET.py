from apitest.clients import Context
from apitest.scenarios import Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    own, _ = s.conversation()
    deleted, _ = s.conversation()
    peer, _ = s.conversation(student="student.alpha.other")
    beta, _ = s.conversation(student="student.beta", teacher="teacher.beta")
    s.call("DELETE", f"/api/conversations/{deleted['id']}", account="student.alpha")
    before = s.conversation_rows(own["id"])
    values = s.call("GET", "/api/conversations", account="student.alpha")
    ids = [item["id"] for item in values]
    checks.require(
        own["id"] in ids
        and not {deleted["id"], peer["id"], beta["id"]}.intersection(ids)
        and len(ids) == len(set(ids)),
        "response.values",
    )
    checks.require(
        values == s.call("GET", "/api/conversations", account="student.alpha"), "response.values"
    )
    for value in values:
        s.verify_conversation(value)
    s.call("GET", "/api/conversations", status=403)
    s.call("GET", "/api/conversations", account=None, status=401)
    checks.require(before == s.conversation_rows(own["id"]), "database.unchanged")


OPERATION = Operation("GET", "/api/conversations", run)
