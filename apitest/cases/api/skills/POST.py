from apitest.clients import Context
from apitest.mcp_scenarios import McpScenario
from apitest.scenarios import SKILL
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = McpScenario(context, checks)
    before = context.database.rows("SELECT id FROM skills ORDER BY id")
    for payload in (
        {**SKILL, "name": " "},
        {**SKILL, "name": "x" * 121},
        {**SKILL, "instructions": ""},
        {**SKILL, "instructions": "x" * 20001},
        {**SKILL, "skill_type": "tool"},
        {**SKILL, "class_id": s.identity("teacher.beta")["class_id"]},
        {**SKILL, "creator_id": s.identity("teacher.beta")["user_id"]},
    ):
        s.call("POST", "/api/skills", body=payload, status=400)
    s.call("POST", "/api/skills", account="student.alpha", body=SKILL, status=403)
    s.call("POST", "/api/skills", account=None, body=SKILL, status=401)
    checks.require(
        before == context.database.rows("SELECT id FROM skills ORDER BY id"), "database.unchanged"
    )
    skill = s.skill()
    s.verify_resource(skill, "skills")
    checks.require(
        skill["state"] == "active" and s.skill_rows(skill["id"])[0]["revision_number"] == 1,
        "database.revisions",
    )
    checks.require(skill["tools"] == ["knowledge_search"], "database.bindings")
    server = s.server(connected=True)
    reference = f"formula_hint@{server['name']}"
    bound = s.call("POST", "/api/skills", body={**SKILL, "tools": [reference]}, status=201)
    checks.require(bound["tools"] == [reference], "database.bindings")
    rows = context.database.rows(
        "SELECT tools FROM skill_revisions WHERE id = %s", (bound["current_revision_id"],)
    )
    checks.require(
        rows[0]["tools"]
        == [{"server_id": server["id"], "tool_name": "formula_hint", "reference": reference}],
        "database.bindings",
    )
    for refs in (
        [reference, reference],
        ["invalid reference"],
        [f"tool{i}@{server['name']}" for i in range(9)],
    ):
        s.call("POST", "/api/skills", body={**SKILL, "tools": refs}, status=400)


OPERATION = Operation("POST", "/api/skills", run)
