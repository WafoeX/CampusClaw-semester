from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    value, agent = s.conversation()
    s.stream(value["id"], "UNINDEXED_ZEBRA")
    path = f"/api/agents/{agent['id']}/conversations/{value['id']}"
    messages = s.messages(value["id"])
    for deleted in (False, True):
        if deleted:
            s.call("DELETE", f"/api/conversations/{value['id']}", account="student.alpha")
        audit = s.call("GET", path)
        s.verify_conversation(audit)
        checks.require(
            (audit["deleted_at"] is not None) == deleted
            and [item["content"] for item in audit["messages"]]
            == [row["content"] for row in messages],
            "database.messages",
        )
        first = s.call("GET", path + "?limit=1")
        second = s.call("GET", path + "?after_ordinal=1&limit=1")
        checks.require(
            first["messages"] + second["messages"] == audit["messages"], "response.bounds"
        )
        s.hidden(
            "GET",
            path,
            f"/api/agents/{MISSING}/conversations/{MISSING}",
            accounts=("teacher.alpha.other", "teacher.beta", "student.alpha", "student.beta"),
        )
    other_agent = s.agent()
    s.call("GET", f"/api/agents/{other_agent['id']}/conversations/{value['id']}", status=404)
    s.call("GET", path, account=None, status=401)
    checks.require(messages == s.messages(value["id"]), "database.unchanged")


OPERATION = Operation("GET", "/api/agents/{agent_id}/conversations/{conversation_id}", run)
