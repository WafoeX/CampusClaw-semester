"""Task 3/4 authorization, persistence, and real PostgreSQL concurrency checks."""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Barrier, Event
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from campusclaw.api.dependencies import Principal
from campusclaw.application.chat import ChatResult
from campusclaw.application.conversations import ConversationService, TurnInProgressError
from campusclaw.application.generation import EvidenceItem, ParsedAnswer
from campusclaw.application.tokens import TokenService
from campusclaw.config import Settings
from campusclaw.domain.models import (
    Agent,
    AgentRevision,
    Class,
    Conversation,
    ConversationMessage,
    KnowledgeChunk,
    Material,
    MaterialIndexVersion,
    MessageCitation,
    Skill,
    SkillRevision,
    User,
    UserRole,
)
from campusclaw.persistence.database import Database

pytestmark = pytest.mark.integration


@dataclass
class Context:
    client: TestClient
    database: Database
    settings: Settings
    principals: dict[str, Principal]
    headers: dict[str, dict[str, str]]

    def skill(self, actor: str = "teacher.alpha") -> dict[str, Any]:
        response = self.client.post(
            "/api/skills",
            headers=self.headers[actor],
            json={"name": "Guide", "skill_type": "solution_guidance", "instructions": "Use hints."},
        )
        assert response.status_code == 201
        return dict(response.json())

    def agent(self, *, publish: bool = True, actor: str = "teacher.alpha") -> dict[str, Any]:
        skill = self.skill(actor)
        response = self.client.post(
            "/api/agents",
            headers=self.headers[actor],
            json={
                "name": "Tutor",
                "description": "Class guide",
                "system_prompt": "Evidence only.",
                "skill_ids": [skill["id"]],
            },
        )
        assert response.status_code == 201
        assert response.json()["skill_ids"] == [skill["id"]]
        if publish:
            response = self.client.post(
                f"/api/agents/{response.json()['id']}/publish", headers=self.headers[actor]
            )
            assert response.status_code == 200
        return dict(response.json())

    def conversation(self, agent_id: str) -> dict[str, Any]:
        response = self.client.post(
            "/api/conversations", headers=self.headers["student.alpha"], json={"agent_id": agent_id}
        )
        assert response.status_code == 201
        return dict(response.json())


@pytest.fixture
def api34(postgres_api_fixture: Any) -> Iterator[Context]:
    fixture = postgres_api_fixture
    with fixture.database.transaction() as session:
        alpha = session.scalar(select(Class).join(User).where(User.account == "teacher.alpha"))
        assert alpha is not None
        session.add_all(
            [
                User(
                    id=uuid.uuid4(),
                    account="teacher.peer",
                    role="teacher",
                    class_id=alpha.id,
                    password_hash="not-a-login-hash",
                ),
                User(
                    id=uuid.uuid4(),
                    account="student.peer",
                    role="student",
                    class_id=alpha.id,
                    password_hash="not-a-login-hash",
                ),
            ]
        )
    tokens = TokenService(fixture.settings.JWT_SIGNING_KEY.get_secret_value(), 3600)
    with fixture.database.transaction() as session:
        users = list(session.scalars(select(User)))
        principals = {
            user.account: Principal(user.id, user.account, UserRole(user.role), user.class_id)
            for user in users
        }
    headers = {
        name: {"authorization": f"Bearer {tokens.issue(p.user_id).token}"}
        for name, p in principals.items()
    }
    with fixture.client() as client:
        yield Context(client, fixture.database, fixture.settings, principals, headers)


def test_agent_and_skill_crud_match_database_and_revision_identity(api34: Context) -> None:
    c = api34
    agent = c.agent()
    c.agent(publish=False)
    headers = c.headers["teacher.alpha"]
    assert len(c.client.get("/api/agents", headers=headers).json()) == 2
    skill_id = agent["skill_ids"][0]
    skill = c.client.get(f"/api/skills/{skill_id}", headers=headers).json()
    updated_skill = c.client.patch(
        f"/api/skills/{skill_id}",
        headers=headers,
        json={
            "name": "Guide 2",
            "skill_type": "solution_guidance",
            "instructions": "Ask a question.",
        },
    )
    assert updated_skill.status_code == 200
    assert updated_skill.json()["current_revision_id"] != skill["current_revision_id"]
    assert c.client.get("/api/agents", headers=c.headers["student.alpha"]).json() == []
    updated = c.client.patch(
        f"/api/agents/{agent['id']}",
        headers=headers,
        json={
            "name": "Tutor 2",
            "description": None,
            "system_prompt": "New prompt.",
            "skill_ids": [skill_id],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["skill_ids"] == [skill_id]
    assert updated.json()["state"] == "draft"
    assert c.client.post(f"/api/agents/{agent['id']}/publish", headers=headers).status_code == 200
    catalog = c.client.get("/api/agents", headers=c.headers["student.alpha"]).json()
    assert catalog == [{"id": agent["id"], "name": "Tutor 2", "description": None}]
    with c.database.transaction() as session:
        stored = session.get(Agent, uuid.UUID(agent["id"]))
        assert stored is not None
        assert (stored.class_id, stored.creator_id) == (
            c.principals["teacher.alpha"].class_id,
            c.principals["teacher.alpha"].user_id,
        )
        revision = session.get(AgentRevision, stored.current_revision_id)
        assert revision is not None and revision.system_prompt == "New prompt."
        old = session.get(SkillRevision, uuid.UUID(skill["current_revision_id"]))
        assert old is not None and old.instructions == "Use hints."
    retired_skill = c.client.delete(f"/api/skills/{skill_id}", headers=headers)
    assert retired_skill.status_code == 200 and retired_skill.json()["state"] == "retired"
    assert c.client.get("/api/agents", headers=c.headers["student.alpha"]).json() == []
    assert c.client.post(f"/api/agents/{agent['id']}/publish", headers=headers).status_code == 409
    assert (
        c.client.delete(f"/api/agents/{agent['id']}", headers=headers).json()["state"] == "retired"
    )
    assert agent["id"] not in [x["id"] for x in c.client.get("/api/agents", headers=headers).json()]
    assert skill_id not in [x["id"] for x in c.client.get("/api/skills", headers=headers).json()]
    with c.database.transaction() as session:
        stored_skill = session.get(Skill, uuid.UUID(skill_id))
        assert stored_skill is not None and stored_skill.state == "retired"


@pytest.mark.parametrize("resource", ["agents", "skills"])
@pytest.mark.parametrize("actor", ["teacher.peer", "teacher.beta"])
def test_maintenance_hides_noncreator_and_other_class(
    api34: Context, resource: str, actor: str
) -> None:
    c = api34
    record = c.agent() if resource == "agents" else c.skill()
    payload: dict[str, Any] = (
        {"name": "Override", "system_prompt": "Prompt", "skill_ids": []}
        if resource == "agents"
        else {"name": "Override", "skill_type": "solution_guidance", "instructions": "Hints"}
    )
    paths = [("GET", ""), ("PATCH", ""), ("DELETE", "")]
    if resource == "agents":
        paths += [("POST", "/publish"), ("POST", "/unpublish")]
    for method, suffix in paths:
        kwargs: dict[str, Any] = {"headers": c.headers[actor]}
        if method == "PATCH":
            kwargs["json"] = payload
        actual = c.client.request(method, f"/api/{resource}/{record['id']}{suffix}", **kwargs)
        absent = c.client.request(method, f"/api/{resource}/{uuid.uuid4()}{suffix}", **kwargs)
        assert actual.status_code == absent.status_code == 404
        assert actual.json() == absent.json()
    assert c.client.get(f"/api/{resource}", headers=c.headers[actor]).json() == []
    assert (
        c.client.get(f"/api/{resource}/{record['id']}", headers=c.headers["teacher.alpha"]).json()
        == record
    )


@pytest.mark.parametrize("resource", ["agents", "skills"])
def test_students_cannot_maintain_or_mutate_resources(api34: Context, resource: str) -> None:
    c = api34
    record = c.agent() if resource == "agents" else c.skill()
    payload = (
        {"name": "Bad", "system_prompt": "Prompt"}
        if resource == "agents"
        else {"name": "Bad", "skill_type": "solution_guidance", "instructions": "Hints"}
    )
    headers = c.headers["student.alpha"]
    assert c.client.post(f"/api/{resource}", headers=headers, json=payload).status_code == 403
    for method in ("GET", "PATCH", "DELETE"):
        kwargs: dict[str, Any] = {"headers": headers}
        if method == "PATCH":
            kwargs["json"] = payload
        actual = c.client.request(method, f"/api/{resource}/{record['id']}", **kwargs)
        assert actual.status_code == (404 if resource == "agents" else 403)
        if resource == "agents":
            absent = c.client.request(method, f"/api/{resource}/{uuid.uuid4()}", **kwargs)
            assert actual.json() == absent.json()
    if resource == "agents":
        for transition in ("publish", "unpublish"):
            assert (
                c.client.post(
                    f"/api/agents/{record['id']}/{transition}", headers=headers
                ).status_code
                == 404
            )
    else:
        assert c.client.get("/api/skills", headers=headers).status_code == 403
    assert c.client.get(f"/api/{resource}").status_code == 401


def test_publication_idempotence_readiness_and_invalid_updates_are_atomic(api34: Context) -> None:
    c = api34
    agent = c.agent(publish=False)
    headers = c.headers["teacher.alpha"]
    for _ in range(2):
        assert (
            c.client.post(f"/api/agents/{agent['id']}/publish", headers=headers).json()["state"]
            == "published"
        )
    for _ in range(2):
        assert (
            c.client.post(f"/api/agents/{agent['id']}/unpublish", headers=headers).json()["state"]
            == "draft"
        )
    before = c.client.get(f"/api/agents/{agent['id']}", headers=headers).json()
    peer_skill = c.skill("teacher.peer")
    other_class_skill = c.skill("teacher.beta")
    retired_skill = c.skill()
    assert c.client.delete(f"/api/skills/{retired_skill['id']}", headers=headers).status_code == 200
    for ids, status in [
        ([peer_skill["id"]], 404),
        ([other_class_skill["id"]], 404),
        ([retired_skill["id"]], 404),
        ([str(uuid.uuid4())], 404),
        ([agent["skill_ids"][0]] * 2, 400),
    ]:
        response = c.client.patch(
            f"/api/agents/{agent['id']}",
            headers=headers,
            json={"name": "Changed", "system_prompt": "Changed", "skill_ids": ids},
        )
        assert response.status_code == status
        assert c.client.get(f"/api/agents/{agent['id']}", headers=headers).json() == before
    empty = c.client.post(
        "/api/agents", headers=headers, json={"name": "Draft", "system_prompt": "Prompt"}
    ).json()
    for _ in range(2):
        assert (
            c.client.post(f"/api/agents/{empty['id']}/publish", headers=headers).status_code == 409
        )
        assert c.client.get(f"/api/agents/{empty['id']}", headers=headers).json() == empty


@pytest.mark.parametrize(
    "path,payload",
    [
        ("agents", {"name": "Tutor", "system_prompt": "private-rejected", "class_id": "forged"}),
        ("agents", {"name": " ", "system_prompt": "private-rejected"}),
        ("skills", {"name": "Guide", "skill_type": "tool", "instructions": "private-rejected"}),
        (
            "skills",
            {
                "name": "x" * 121,
                "skill_type": "solution_guidance",
                "instructions": "private-rejected",
            },
        ),
        ("conversations", {"agent_id": str(uuid.uuid4()), "history": "private-rejected"}),
    ],
)
def test_invalid_requests_are_safe_400_without_partial_rows(
    api34: Context, path: str, payload: dict[str, Any]
) -> None:
    c = api34
    actor = "student.alpha" if path == "conversations" else "teacher.alpha"
    response = c.client.post(f"/api/{path}", headers=c.headers[actor], json=payload)
    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_request", "message": "Invalid request"}}
    assert "private-rejected" not in response.text
    with c.database.transaction() as session:
        for model in (Agent, Skill, Conversation, ConversationMessage):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_conversation_lifecycle_audit_deleted_filters_and_history_paging(api34: Context) -> None:
    c = api34
    agent = c.agent()
    conversation = c.conversation(agent["id"])
    cid = conversation["id"]
    headers = c.headers["student.alpha"]
    assert conversation["agent_name"] == "Tutor"
    assert conversation["student_account"] == "student.alpha"
    assert conversation["creator_retains_audit_access"] is True
    service = ConversationService(c.settings)
    with c.database.transaction() as session:
        _, _, assistant = service.accept_turn(
            session, c.principals["student.alpha"], uuid.UUID(cid), content="First"
        )
        service.complete_turn(
            session,
            assistant,
            answer="Hint",
            retrieval_mode="keyword",
            evidence=[],
            citation_ids=[],
        )
    for actor in ("teacher.alpha", "student.alpha"):
        page = c.client.get(f"/api/conversations/{cid}?limit=1", headers=c.headers[actor])
        assert page.status_code == 200
        assert page.json()["messages"][0]["content"] == "First"
        assert page.json()["next_after_ordinal"] == 1
        next_page = c.client.get(
            f"/api/conversations/{cid}?limit=1&after_ordinal=1", headers=c.headers[actor]
        ).json()
        assert next_page["messages"][0]["content"] == "Hint"
        assert next_page["next_after_ordinal"] is None
    deleted = c.client.delete(f"/api/conversations/{cid}", headers=headers)
    assert deleted.status_code == 200 and deleted.json()["deleted_at"] is not None
    assert deleted.json()["creator_retains_audit_access"] is True
    assert c.client.get("/api/conversations", headers=headers).json() == []
    assert c.client.get(f"/api/conversations/{cid}", headers=headers).status_code == 404
    assert c.client.delete(f"/api/conversations/{cid}", headers=headers).status_code == 404
    assert (
        c.client.post(
            f"/api/conversations/{cid}/messages", headers=headers, json={"content": "Blocked"}
        ).status_code
        == 404
    )
    teacher = c.headers["teacher.alpha"]
    audit = c.client.get(f"/api/conversations/{cid}", headers=teacher).json()
    assert audit["deleted_at"] is not None
    assert [m["content"] for m in audit["messages"]] == ["First", "Hint"]
    assert (
        c.client.get(
            f"/api/agents/{agent['id']}/conversations?deleted=false", headers=teacher
        ).json()
        == []
    )
    assert (
        len(
            c.client.get(
                f"/api/agents/{agent['id']}/conversations?deleted=true", headers=teacher
            ).json()
        )
        == 1
    )
    c.client.delete(f"/api/agents/{agent['id']}", headers=teacher)
    assert c.client.get(f"/api/conversations/{cid}", headers=teacher).status_code == 200
    with c.database.transaction() as session:
        stored = session.get(Conversation, uuid.UUID(cid))
        assert stored is not None and stored.deleted_at is not None
        assert stored.student_id == c.principals["student.alpha"].user_id
        assert stored.class_id == c.principals["student.alpha"].class_id
        assert session.scalar(select(func.count()).select_from(ConversationMessage)) == 2


@pytest.mark.parametrize("actor", ["student.peer", "student.beta", "teacher.peer", "teacher.beta"])
def test_conversation_identifier_isolation_and_current_class(api34: Context, actor: str) -> None:
    c = api34
    agent = c.agent()
    cid = c.conversation(agent["id"])["id"]
    for method in ("GET", "DELETE"):
        response = c.client.request(method, f"/api/conversations/{cid}", headers=c.headers[actor])
        absent = c.client.request(
            method, f"/api/conversations/{uuid.uuid4()}", headers=c.headers[actor]
        )
        assert response.status_code == absent.status_code == 404
        assert response.json() == absent.json()
    for suffix in ("", f"/{cid}"):
        response = c.client.get(
            f"/api/agents/{agent['id']}/conversations{suffix}", headers=c.headers[actor]
        )
        assert response.status_code == 404
    if actor.startswith("student"):
        response = c.client.post(
            f"/api/conversations/{cid}/messages",
            headers=c.headers[actor],
            json={"content": "Forbidden"},
        )
        assert response.status_code == 404
    with c.database.transaction() as session:
        user = session.get(User, c.principals["student.alpha"].user_id)
        assert user is not None
        user.class_id = c.principals["student.beta"].class_id
    assert (
        c.client.get(f"/api/conversations/{cid}", headers=c.headers["student.alpha"]).status_code
        == 404
    )
    assert (
        c.client.post(
            f"/api/conversations/{cid}/messages",
            headers=c.headers["student.alpha"],
            json={"content": "Moved class"},
        ).status_code
        == 404
    )
    with c.database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ConversationMessage)) == 0


def test_conversations_order_by_timestamp_then_id_and_creation_readiness(api34: Context) -> None:
    c = api34
    agent = c.agent()
    ids = [c.conversation(agent["id"])["id"] for _ in range(3)]
    with c.database.transaction() as session:
        for conversation in session.scalars(select(Conversation)):
            conversation.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    listed = c.client.get("/api/conversations", headers=c.headers["student.alpha"]).json()
    assert [x["id"] for x in listed] == sorted(ids, reverse=True)
    for actor in ("teacher.alpha", "teacher.peer"):
        assert c.client.get("/api/conversations", headers=c.headers[actor]).status_code == 403
        assert (
            c.client.post(
                "/api/conversations", headers=c.headers[actor], json={"agent_id": agent["id"]}
            ).status_code
            == 403
        )
    c.client.post(f"/api/agents/{agent['id']}/unpublish", headers=c.headers["teacher.alpha"])
    for agent_id in (agent["id"], str(uuid.uuid4()), c.agent(actor="teacher.beta")["id"]):
        assert (
            c.client.post(
                "/api/conversations",
                headers=c.headers["student.alpha"],
                json={"agent_id": agent_id},
            ).status_code
            == 409
        )
    with c.database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 3


def test_concurrent_acceptance_returns_one_409_and_does_not_block_other_conversation(
    api34: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = api34
    agent = c.agent()
    cid = c.conversation(agent["id"])["id"]
    other = c.conversation(agent["id"])["id"]
    started, release = Event(), Event()

    def generate(*_args: object, **kwargs: Any) -> ChatResult:
        if str(kwargs["conversation"].id) == cid:
            started.set()
            assert release.wait(15)
        return ChatResult(
            ParsedAnswer("insufficient_evidence", None, []),
            [],
            "keyword",
            False,
            uuid.UUID(agent["current_revision_id"]),
        )

    monkeypatch.setattr("campusclaw.application.chat.ChatService.generate", generate)

    def send(conversation_id: str) -> Any:
        return c.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=c.headers["student.alpha"],
            json={"content": "Question"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send, cid)
        try:
            assert started.wait(15)
            second = send(cid)
            assert second.status_code == 409
            assert second.json()["detail"]["code"] == "turn_in_progress"
            assert send(other).status_code == 200
            with c.database.transaction() as session:
                messages = list(
                    session.scalars(
                        select(ConversationMessage)
                        .where(ConversationMessage.conversation_id == uuid.UUID(cid))
                        .order_by(ConversationMessage.ordinal)
                    )
                )
                assert [(m.role, m.state, m.ordinal) for m in messages] == [
                    ("user", "completed", 1),
                    ("assistant", "processing", 2),
                ]
        finally:
            release.set()
        assert first.result().status_code == 200
    with c.database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ConversationMessage)) == 4


def test_full_audit_history_is_retrievable_in_bounded_pages(api34: Context) -> None:
    c = api34
    # Fixture setup creates 51 turns in one transaction; exercise pagination,
    # not the separately verified default 30/minute generation admission limit.
    c.settings.CONVERSATION_RATE_LIMIT_PER_MINUTE = 100
    cid = uuid.UUID(c.conversation(c.agent()["id"])["id"])
    service = ConversationService(c.settings)
    with c.database.transaction() as session:
        for turn in range(51):
            _, _, assistant = service.accept_turn(
                session, c.principals["student.alpha"], cid, content=f"Question {turn}"
            )
            service.complete_turn(
                session,
                assistant,
                answer=f"Hint {turn}",
                retrieval_mode="keyword",
                evidence=[],
                citation_ids=[],
            )
    headers = c.headers["teacher.alpha"]
    page = c.client.get(f"/api/conversations/{cid}", headers=headers).json()
    assert len(page["messages"]) == 100
    assert page["next_after_ordinal"] == 100
    remainder = c.client.get(f"/api/conversations/{cid}?after_ordinal=100", headers=headers).json()
    assert [m["ordinal"] for m in remainder["messages"]] == [101, 102]
    assert remainder["next_after_ordinal"] is None
    assert c.client.get(f"/api/conversations/{cid}?limit=101", headers=headers).status_code == 400


def test_simultaneous_postgres_transactions_allocate_one_pair(api34: Context) -> None:
    c = api34
    cid = uuid.UUID(c.conversation(c.agent()["id"])["id"])
    gate = Barrier(2)

    def accept() -> str:
        with c.database.transaction() as session:
            gate.wait(timeout=10)
            try:
                ConversationService(c.settings).accept_turn(
                    session, c.principals["student.alpha"], cid, content="Question"
                )
                return "accepted"
            except TurnInProgressError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(accept) for _ in range(2)]
        outcomes = [future.result() for future in futures]
    assert sorted(outcomes) == ["accepted", "conflict"]
    with c.database.transaction() as session:
        rows = list(
            session.scalars(select(ConversationMessage).order_by(ConversationMessage.ordinal))
        )
        assert [(row.role, row.ordinal) for row in rows] == [("user", 1), ("assistant", 2)]


def test_configured_bounds_and_retirement_do_not_allow_partial_updates(api34: Context) -> None:
    c = api34
    agent = c.agent()
    headers = c.headers["teacher.alpha"]
    c.settings.AGENT_PROMPT_MAX_CHARS = 8
    c.settings.SKILL_INSTRUCTIONS_MAX_CHARS = 8
    for path, payload in [
        ("agents", {"name": "Tutor", "system_prompt": "private-too-long"}),
        (
            "skills",
            {
                "name": "Guide",
                "skill_type": "solution_guidance",
                "instructions": "private-too-long",
            },
        ),
    ]:
        response = c.client.post(f"/api/{path}", headers=headers, json=payload)
        assert response.status_code == 400
        assert "private-too-long" not in response.text
        target = agent["id"] if path == "agents" else agent["skill_ids"][0]
        assert (
            c.client.patch(f"/api/{path}/{target}", headers=headers, json=payload).status_code
            == 400
        )
    c.client.delete(f"/api/agents/{agent['id']}", headers=headers)
    assert (
        c.client.patch(
            f"/api/agents/{agent['id']}",
            headers=headers,
            json={"name": "Revive", "system_prompt": "Prompt"},
        ).status_code
        == 404
    )
    assert c.client.post(f"/api/agents/{agent['id']}/publish", headers=headers).status_code == 409
    with c.database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Agent)) == 1
        assert session.scalar(select(func.count()).select_from(Skill)) == 1
        assert session.scalar(select(func.count()).select_from(AgentRevision)) == 1
        assert session.scalar(select(func.count()).select_from(SkillRevision)) == 1


def test_terminal_snapshots_are_immutable_and_failures_store_only_safe_codes(
    api34: Context,
) -> None:
    c = api34
    agent = c.agent()
    cid = uuid.UUID(c.conversation(agent["id"])["id"])
    service = ConversationService(c.settings)
    principal = c.principals["student.alpha"]
    with c.database.transaction() as session:
        material = session.scalar(select(Material).where(Material.class_id == principal.class_id))
        assert material is not None
        version = MaterialIndexVersion(
            id=uuid.uuid4(),
            material_id=material.id,
            class_id=principal.class_id,
            source_sha256=material.sha256,
            extraction_version="test",
            chunking_version="test",
            embedding_model="test",
            vector_dimension=3,
            build_state="ready",
        )
        session.add(version)
        session.flush()
        chunk = KnowledgeChunk(
            id=uuid.uuid4(),
            material_id=material.id,
            class_id=principal.class_id,
            index_version_id=version.id,
            ordinal=0,
            text_hash="a" * 64,
            normalized_text="synthetic evidence",
            text="Synthetic evidence",
            line_start=1,
            line_end=1,
        )
        session.add(chunk)
        session.flush()
        evidence = [EvidenceItem(source_id="S1", material=material, chunk=chunk)]
        _, _, assistant = service.accept_turn(session, principal, cid, content="Question")
        service.complete_turn(
            session,
            assistant,
            answer="Hint [S1]",
            retrieval_mode="keyword",
            evidence=evidence,
            citation_ids=["S1"],
        )
        revision_id = assistant.applied_agent_revision_id
        citation = session.scalar(
            select(MessageCitation).where(MessageCitation.message_id == assistant.id)
        )
        assert citation is not None
        snapshot = dict(citation.source_snapshot)
        material.title = "Changed title"
        chunk.text = "Changed text"
        with pytest.raises(ValueError):
            service.complete_turn(
                session,
                assistant,
                answer="Overwrite",
                retrieval_mode="keyword",
                evidence=[],
                citation_ids=[],
            )
        service.fail_turn(session, assistant, code="unsafe provider body")
        _, _, failed = service.accept_turn(session, principal, cid, content="Next")
        service.fail_turn(session, failed, code="raw provider secret/body")
        service.fail_turn(session, failed, code="generation_invalid")
    response = c.client.get(f"/api/conversations/{cid}", headers=c.headers["teacher.alpha"]).json()
    assert response["messages"][1]["content"] == "Hint [S1]"
    assert response["messages"][1]["citations"] == [snapshot]
    assert response["messages"][1]["applied_agent_revision_id"] == str(revision_id)
    assert response["messages"][3]["state"] == "failed"
    assert response["messages"][3]["safe_error_code"] == "generation_failed"
    assert response["messages"][3]["content"] is None
    assert response["messages"][3]["citations"] == []
    assert "provider" not in str(response)


@pytest.mark.parametrize(
    "forged", ["history", "class_id", "prompt", "assistant_content", "citations"]
)
def test_message_validation_precedes_persistence(api34: Context, forged: str) -> None:
    c = api34
    cid = c.conversation(c.agent()["id"])["id"]
    response = c.client.post(
        f"/api/conversations/{cid}/messages",
        headers=c.headers["student.alpha"],
        json={"content": "Question", forged: "private-input"},
    )
    assert response.status_code == 400
    assert "private-input" not in response.text
    with c.database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ConversationMessage)) == 0
