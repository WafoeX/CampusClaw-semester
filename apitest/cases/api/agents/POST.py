from apitest.clients import Context
from apitest.scenarios import AGENT, MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    before = context.database.rows("SELECT id FROM agents ORDER BY id")
    for payload in (
        {**AGENT, "name": ""},
        {**AGENT, "system_prompt": " "},
        {**AGENT, "system_prompt": "x" * 20001},
        {**AGENT, "description": "x" * 1001},
        {**AGENT, "name": "x" * 121},
        {**AGENT, "skill_ids": [MISSING, MISSING]},
        {**AGENT, "class_id": MISSING},
        {**AGENT, "creator_id": MISSING},
    ):
        s.call("POST", "/api/agents", body=payload, status=400)
    s.call("POST", "/api/agents", account="student.alpha", body=AGENT, status=403)
    s.call("POST", "/api/agents", account=None, body=AGENT, status=401)
    checks.require(
        before == context.database.rows("SELECT id FROM agents ORDER BY id"), "database.unchanged"
    )
    drafts = [
        s.call(
            "POST", "/api/agents", body={**AGENT, "name": context.fixtures.name(label)}, status=201
        )
        for label in ("draft-one", "draft-two")
    ]
    checks.require(drafts[0]["id"] != drafts[1]["id"], "response.values")
    for draft in drafts:
        s.verify_resource(draft, "agents")
        checks.require(
            draft["state"] == "draft"
            and draft["published_revision_id"] is None
            and s.agent_rows(draft["id"])[0]["revision_number"] == 1,
            "database.revisions",
        )


OPERATION = Operation("POST", "/api/agents", run)
