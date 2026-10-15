from apitest.clients import Context
from apitest.scenarios import REFUSAL, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    before = context.database.rows(
        "SELECT id, text_hash, index_version_id, class_id FROM knowledge_chunks ORDER BY id"
    )
    for account, topic in (("student.alpha", "ALPHA_FERN"), ("student.beta", "BETA_CRYSTAL")):
        answer = s.call(
            "POST",
            "/api/knowledge/query",
            account=account,
            body={"question": topic, "mode": "keyword"},
        )
        checks.require(
            answer["status"] == "answered"
            and answer["requested_mode"] == answer["effective_mode"] == "keyword"
            and type(answer["retryable"]) is bool
            and not answer["retryable"],
            "response.values",
        )
        checks.require(
            len(answer["sources"]) == len(answer["citations"]) == 1
            and answer["citations"] == [answer["sources"][0]["source_id"]]
            and "[S1]" in answer["answer"],
            "response.fields",
        )
        source = answer["sources"][0]
        rows = context.database.rows(
            "SELECT m.class_id, m.title, m.original_filename, k.text FROM materials m "
            "JOIN knowledge_chunks k ON k.material_id = m.id "
            "JOIN material_search_states st ON st.material_id = m.id "
            "AND st.active_version_id = k.index_version_id "
            "WHERE m.id = %s AND m.state = 'ready'",
            (source["material_id"],),
        )
        checks.require(
            len(rows) == 1
            and str(rows[0]["class_id"]) == s.identity(account)["class_id"]
            and source["title"] == rows[0]["title"] == topic
            and source["original_filename"] == rows[0]["original_filename"]
            and source["excerpt"] in rows[0]["text"]
            and source["action"] == f"/api/materials/{source['material_id']}/download",
            "database.citations",
        )
    other = s.call(
        "POST",
        "/api/knowledge/query",
        account="student.alpha",
        body={"question": "BETA_CRYSTAL", "mode": "keyword"},
    )
    absent = s.call(
        "POST",
        "/api/knowledge/query",
        account="student.alpha",
        body={"question": "UNINDEXED_ZEBRA", "mode": "keyword"},
    )
    checks.require(
        other == absent
        and other["answer"] == REFUSAL
        and other["status"] == "insufficient_evidence"
        and other["citations"] == other["sources"] == [],
        "response.refusal",
    )
    for payload in (
        {"question": ""},
        {"question": "x" * 2001},
        {"question": "ALPHA_FERN", "class_id": s.identity("student.beta")["class_id"]},
        {"question": "x", "mode": "invalid"},
    ):
        s.call("POST", "/api/knowledge/query", account="student.alpha", body=payload, status=400)
    s.call(
        "POST", "/api/knowledge/query", account=None, body={"question": "ALPHA_FERN"}, status=401
    )
    checks.require(
        before
        == context.database.rows(
            "SELECT id, text_hash, index_version_id, class_id FROM knowledge_chunks ORDER BY id"
        ),
        "database.unchanged",
    )


OPERATION = Operation("POST", "/api/knowledge/query", run)
