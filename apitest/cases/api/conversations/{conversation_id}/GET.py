from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    value, _ = s.conversation()
    s.stream(value["id"], "UNINDEXED_ZEBRA")
    path = f"/api/conversations/{value['id']}"
    before = s.messages(value["id"])
    read = s.call("GET", path, account="student.alpha")
    s.verify_conversation(read)
    checks.require(
        [item["content"] for item in read["messages"]] == [row["content"] for row in before],
        "database.messages",
    )
    first = s.call("GET", path + "?limit=1", account="student.alpha")
    second = s.call("GET", path + "?limit=1&after_ordinal=1", account="student.alpha")
    checks.require(
        first["next_after_ordinal"] == 1
        and second["next_after_ordinal"] is None
        and first["messages"] + second["messages"] == read["messages"],
        "response.bounds",
    )
    s.hidden(
        "GET",
        path,
        f"/api/conversations/{MISSING}",
        accounts=("student.alpha.other", "student.beta", "teacher.alpha.other", "teacher.beta"),
    )
    s.call("GET", path, account=None, status=401)
    s.call("GET", path + "?limit=101", account="student.alpha", status=400)
    checks.require(before == s.messages(value["id"]), "database.unchanged")


OPERATION = Operation("GET", "/api/conversations/{conversation_id}", run)
