from apitest.clients import Context
from apitest.scenarios import AGENT, MISSING, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    agent = s.agent(published=True)
    identifier, path = agent["id"], f"/api/agents/{agent['id']}"
    before = s.agent_rows(identifier)
    revisions = context.database.rows(
        "SELECT * FROM agent_revisions WHERE agent_id = %s ORDER BY revision_number", (identifier,)
    )
    bindings = context.database.rows(
        "SELECT * FROM agent_skill_bindings WHERE agent_revision_id = %s ORDER BY id",
        (agent["current_revision_id"],),
    )
    for payload in (
        {**AGENT, "system_prompt": ""},
        {**AGENT, "name": "x" * 121},
        {**AGENT, "system_prompt": "x" * 20001},
        {**AGENT, "class_id": MISSING},
        {**AGENT, "skill_ids": [agent["skill_ids"][0]] * 2},
    ):
        s.call("PATCH", path, body=payload, status=400)
    foreign = [s.skill("teacher.alpha.other"), s.skill("teacher.beta"), s.skill()]
    s.call("DELETE", f"/api/skills/{foreign[-1]['id']}")
    for skill_id in [MISSING, *(item["id"] for item in foreign)]:
        s.call("PATCH", path, body={**AGENT, "skill_ids": [skill_id]}, status=404)
    s.hidden("PATCH", path, f"/api/agents/{MISSING}", body=AGENT)
    s.call("PATCH", path, account="student.alpha", body=AGENT, status=404)
    s.call("PATCH", path, account=None, body=AGENT, status=401)
    checks.require(
        before == s.agent_rows(identifier)
        and bindings
        == context.database.rows(
            "SELECT * FROM agent_skill_bindings WHERE agent_revision_id = %s ORDER BY id",
            (agent["current_revision_id"],),
        ),
        "database.unchanged",
    )
    payload = {**AGENT, "system_prompt": "更新后的逐步观察提示。", "skill_ids": agent["skill_ids"]}
    changed = s.call("PATCH", path, body=payload)
    s.verify_resource(changed, "agents")
    after = context.database.rows(
        "SELECT * FROM agent_revisions WHERE agent_id = %s ORDER BY revision_number", (identifier,)
    )
    checks.require(
        after[:-1] == revisions and len(after) == 2 and changed["state"] == "draft",
        "database.revisions",
    )
    repeated = s.call("PATCH", path, body=payload)
    s.verify_resource(repeated, "agents")
    checks.require(
        repeated["skill_ids"] == changed["skill_ids"] and len(repeated["skill_ids"]) == 1,
        "database.bindings",
    )
    checks.require(
        bindings
        == context.database.rows(
            "SELECT * FROM agent_skill_bindings WHERE agent_revision_id = %s ORDER BY id",
            (agent["current_revision_id"],),
        ),
        "database.revisions",
    )


OPERATION = Operation("PATCH", "/api/agents/{agent_id}", run)
