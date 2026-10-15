import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from campusclaw.application.chat import ChatResult
from campusclaw.application.generation import REFUSAL_ANSWER, ParsedAnswer
from campusclaw.application.tokens import TokenService
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base, Class, ConversationMessage, User
from campusclaw.domain.security import PasswordService
from campusclaw.main import create_app
from campusclaw.persistence.database import Database


@pytest.fixture
def conversation_api(tmp_path: Path) -> Iterator[tuple[TestClient, Database, dict[str, str]]]:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'conversation-api.db'}")
    Base.metadata.create_all(database.engine)
    class_id, teacher_id, student_id, peer_id = (uuid.uuid4() for _ in range(4))
    with database.transaction() as session:
        session.add(Class(id=class_id, name="Conversation API Class"))
        session.add_all(
            [
                User(
                    id=teacher_id,
                    account="teacher",
                    password_hash="hash",
                    role="teacher",
                    class_id=class_id,
                ),
                User(
                    id=student_id,
                    account="student",
                    password_hash="hash",
                    role="student",
                    class_id=class_id,
                ),
                User(
                    id=peer_id,
                    account="peer",
                    password_hash="hash",
                    role="student",
                    class_id=class_id,
                ),
            ]
        )
    settings = Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=f"sqlite+pysqlite:///{tmp_path / 'conversation-api.db'}",
        JWT_SIGNING_KEY=SecretStr("c" * 32),
        UPLOAD_ROOT=tmp_path / "uploads",
    )
    tokens = TokenService("c" * 32, 3600)
    app = create_app(settings=settings, database=database, password_service=PasswordService())
    with TestClient(app) as client:
        yield (
            client,
            database,
            {
                "teacher": tokens.issue(teacher_id).token,
                "student": tokens.issue(student_id).token,
                "peer": tokens.issue(peer_id).token,
            },
        )
    database.dispose()


def auth(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def create_published_agent(client: TestClient, teacher_token: str) -> str:
    headers = auth(teacher_token)
    skill = client.post(
        "/api/skills",
        headers=headers,
        json={"name": "Guide", "skill_type": "solution_guidance", "instructions": "Use hints."},
    )
    assert skill.status_code == 201
    agent = client.post(
        "/api/agents",
        headers=headers,
        json={
            "name": "Tutor",
            "description": None,
            "system_prompt": "Use evidence.",
            "skill_ids": [skill.json()["id"]],
        },
    )
    assert agent.status_code == 201
    agent_id = agent.json()["id"]
    assert isinstance(agent_id, str)
    assert client.post(f"/api/agents/{agent_id}/publish", headers=headers).status_code == 200
    return agent_id


def test_student_lifecycle_and_creator_audit(
    conversation_api: tuple[TestClient, Database, dict[str, str]],
) -> None:
    client, _, tokens = conversation_api
    agent_id = create_published_agent(client, tokens["teacher"])
    created = client.post(
        "/api/conversations", json={"agent_id": agent_id}, headers=auth(tokens["student"])
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert (
        client.get("/api/conversations", headers=auth(tokens["student"])).json()[0]["id"]
        == conversation_id
    )
    assert (
        client.get(
            f"/api/conversations/{conversation_id}", headers=auth(tokens["peer"])
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/agents/{agent_id}/conversations/{conversation_id}",
            headers=auth(tokens["teacher"]),
        ).status_code
        == 200
    )
    deleted = client.delete(
        f"/api/conversations/{conversation_id}", headers=auth(tokens["student"])
    )
    assert deleted.status_code == 200
    assert client.get("/api/conversations", headers=auth(tokens["student"])).json() == []
    audited = client.get(f"/api/agents/{agent_id}/conversations", headers=auth(tokens["teacher"]))
    assert audited.status_code == 200
    assert audited.json()[0]["deleted_at"] is not None


def test_unpublished_agent_blocks_existing_conversation_messages(
    conversation_api: tuple[TestClient, Database, dict[str, str]],
) -> None:
    client, _, tokens = conversation_api
    agent_id = create_published_agent(client, tokens["teacher"])
    created = client.post(
        "/api/conversations", json={"agent_id": agent_id}, headers=auth(tokens["student"])
    )
    assert created.status_code == 201
    assert (
        client.post(
            f"/api/agents/{agent_id}/unpublish", headers=auth(tokens["teacher"])
        ).status_code
        == 200
    )
    blocked = client.post(
        f"/api/conversations/{created.json()['id']}/messages",
        headers=auth(tokens["student"]),
        json={"content": "Continue."},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "agent_not_ready"


def test_message_sse_persists_exact_terminal_answer(
    conversation_api: tuple[TestClient, Database, dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database, tokens = conversation_api
    agent_id = create_published_agent(client, tokens["teacher"])
    created = client.post(
        "/api/conversations", json={"agent_id": agent_id}, headers=auth(tokens["student"])
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    revision_id = uuid.UUID(
        client.get(f"/api/agents/{agent_id}", headers=auth(tokens["teacher"])).json()[
            "published_revision_id"
        ]
    )

    def fake_generate(*_args: object, **_kwargs: object) -> ChatResult:
        return ChatResult(
            parsed=ParsedAnswer("insufficient_evidence", None, []),
            evidence=[],
            retrieval_mode="keyword",
            configuration_updated=False,
            revision_id=revision_id,
        )

    monkeypatch.setattr("campusclaw.application.chat.ChatService.generate", fake_generate)
    response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        headers=auth(tokens["student"]),
        json={"content": "Explain this."},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: message.started") == 1
    assert response.text.count("event: answer.delta") == 1
    assert response.text.count("event: message.completed") == 1
    with database.transaction() as session:
        messages = list(
            session.scalars(select(ConversationMessage).order_by(ConversationMessage.ordinal))
        )
    assert [message.content for message in messages] == ["Explain this.", REFUSAL_ANSWER]
