from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    value, agent = s.conversation()
    s.stream(value["id"], "UNINDEXED_ZEBRA")
    path = f"/api/conversations/{value['id']}"
    before, messages = s.conversation_rows(value["id"]), s.messages(value["id"])
    s.hidden(
        "DELETE",
        path,
        f"/api/conversations/{MISSING}",
        accounts=(
            "student.alpha.other",
            "student.beta",
            "teacher.alpha",
            "teacher.alpha.other",
            "teacher.beta",
        ),
    )
    s.call("DELETE", path, account=None, status=401)
    checks.require(before == s.conversation_rows(value["id"]), "database.unchanged")
    deleted = s.call("DELETE", path, account="student.alpha")
    s.verify_conversation(deleted)
    checks.require(deleted["deleted_at"] is not None, "database.rows")
    s.call("GET", path, account="student.alpha", status=404)
    s.call(
        "POST",
        path + "/messages",
        account="student.alpha",
        body={"content": "ALPHA_FERN"},
        status=404,
    )
    checks.require(
        value["id"]
        not in {
            item["id"] for item in s.call("GET", "/api/conversations", account="student.alpha")
        },
        "response.values",
    )
    audit = s.call("GET", f"/api/agents/{agent['id']}/conversations/{value['id']}")
    checks.require(
        audit["deleted_at"] == deleted["deleted_at"]
        and [item["content"] for item in audit["messages"]] == [row["content"] for row in messages]
        and s.messages(value["id"]) == messages,
        "database.messages",
    )


OPERATION = Operation("DELETE", "/api/conversations/{conversation_id}", run)
