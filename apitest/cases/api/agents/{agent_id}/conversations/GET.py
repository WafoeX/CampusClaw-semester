from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    active, agent = s.conversation()
    deleted = s.call(
        "POST",
        "/api/conversations",
        account="student.alpha",
        body={"agent_id": agent["id"]},
        status=201,
    )
    s.stream(deleted["id"], "UNINDEXED_ZEBRA")
    s.call("DELETE", f"/api/conversations/{deleted['id']}", account="student.alpha")
    path = f"/api/agents/{agent['id']}/conversations"
    values = s.call("GET", path)
    checks.require(
        {item["id"] for item in values} == {active["id"], deleted["id"]}, "response.values"
    )
    for value in values:
        s.verify_conversation(value)
        checks.require(
            [item["content"] for item in value["messages"]]
            == [row["content"] for row in s.messages(value["id"])],
            "database.messages",
        )
    checks.require(
        [item["id"] for item in s.call("GET", path + "?deleted=true")] == [deleted["id"]]
        and [item["id"] for item in s.call("GET", path + "?deleted=false")] == [active["id"]],
        "response.values",
    )
    before = s.messages(deleted["id"])
    s.hidden(
        "GET",
        path,
        f"/api/agents/{MISSING}/conversations",
        accounts=("teacher.alpha.other", "teacher.beta", "student.alpha", "student.beta"),
    )
    s.call("GET", path, account=None, status=401)
    checks.require(before == s.messages(deleted["id"]), "database.unchanged")


OPERATION = Operation("GET", "/api/agents/{agent_id}/conversations", run)
