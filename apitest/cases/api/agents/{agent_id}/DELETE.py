from apitest.clients import Context
from apitest.scenarios import MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    conversation, agent = s.conversation()
    s.stream(conversation["id"], "UNINDEXED_ZEBRA")
    messages = s.messages(conversation["id"])
    path = f"/api/agents/{agent['id']}"
    before = s.agent_rows(agent["id"])
    s.hidden("DELETE", path, f"/api/agents/{MISSING}")
    s.call("DELETE", path, account="student.alpha", status=404)
    s.call("DELETE", path, account=None, status=401)
    checks.require(before == s.agent_rows(agent["id"]), "database.unchanged")
    retired = s.call("DELETE", path)
    s.verify_resource(retired, "agents")
    checks.require(
        retired["state"] == "retired"
        and agent["id"] not in {item["id"] for item in s.call("GET", "/api/agents")},
        "database.rows",
    )
    s.call(
        "POST",
        "/api/conversations",
        account="student.alpha",
        body={"agent_id": agent["id"]},
        status=409,
    )
    s.call(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        account="student.alpha",
        body={"content": "ALPHA_FERN"},
        status=409,
    )
    audit = s.call("GET", f"/api/agents/{agent['id']}/conversations/{conversation['id']}")
    checks.require(
        audit["agent_name"] == agent["name"]
        and len(audit["messages"]) == 2
        and messages == s.messages(conversation["id"]),
        "database.messages",
    )


OPERATION = Operation("DELETE", "/api/agents/{agent_id}", run)
