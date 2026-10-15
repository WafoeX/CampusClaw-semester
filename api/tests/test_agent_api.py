import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from campusclaw.application.tokens import TokenService
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base, Class, User
from campusclaw.domain.security import PasswordService
from campusclaw.main import create_app
from campusclaw.persistence.database import Database


@pytest.fixture
def agent_api(tmp_path: Path) -> Iterator[tuple[TestClient, Database, dict[str, str]]]:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'agent-api.db'}")
    Base.metadata.create_all(database.engine)
    class_id, teacher_id, student_id = (uuid.uuid4() for _ in range(3))
    with database.transaction() as session:
        session.add(Class(id=class_id, name="Agent API Class"))
        session.add_all(
            [
                User(
                    id=teacher_id,
                    account="teacher.agent",
                    password_hash="hash",
                    role="teacher",
                    class_id=class_id,
                ),
                User(
                    id=student_id,
                    account="student.agent",
                    password_hash="hash",
                    role="student",
                    class_id=class_id,
                ),
            ]
        )
    settings = Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=f"sqlite+pysqlite:///{tmp_path / 'agent-api.db'}",
        JWT_SIGNING_KEY=SecretStr("a" * 32),
        UPLOAD_ROOT=tmp_path / "uploads",
    )
    tokens = TokenService("a" * 32, 3600)
    app = create_app(settings=settings, database=database, password_service=PasswordService())
    with TestClient(app) as client:
        yield (
            client,
            database,
            {
                "teacher": tokens.issue(teacher_id).token,
                "student": tokens.issue(student_id).token,
            },
        )
    database.dispose()


def authorization(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def test_publish_requires_guidance_and_controls_student_catalog(
    agent_api: tuple[TestClient, Database, dict[str, str]],
) -> None:
    client, _, tokens = agent_api
    teacher_headers = authorization(tokens["teacher"])
    student_headers = authorization(tokens["student"])

    created = client.post(
        "/api/agents",
        headers=teacher_headers,
        json={
            "name": "Tutor",
            "description": None,
            "system_prompt": "Use evidence.",
            "skill_ids": [],
        },
    )
    assert created.status_code == 201
    agent_id = created.json()["id"]
    not_ready = client.post(f"/api/agents/{agent_id}/publish", headers=teacher_headers)
    assert not_ready.status_code == 409
    assert client.get("/api/agents", headers=student_headers).json() == []

    skill = client.post(
        "/api/skills",
        headers=teacher_headers,
        json={
            "name": "Guidance",
            "skill_type": "solution_guidance",
            "instructions": "Give hints and checks.",
        },
    )
    assert skill.status_code == 201
    updated = client.patch(
        f"/api/agents/{agent_id}",
        headers=teacher_headers,
        json={
            "name": "Tutor",
            "description": "Class guide",
            "system_prompt": "Use evidence.",
            "skill_ids": [skill.json()["id"]],
        },
    )
    assert updated.status_code == 200
    published = client.post(f"/api/agents/{agent_id}/publish", headers=teacher_headers)
    assert published.status_code == 200
    assert published.json()["state"] == "published"

    catalog = client.get("/api/agents", headers=student_headers)
    assert catalog.status_code == 200
    assert catalog.json() == [{"id": agent_id, "name": "Tutor", "description": "Class guide"}]
    assert "system_prompt" not in catalog.text
    assert "instructions" not in catalog.text

    unpublished = client.post(f"/api/agents/{agent_id}/unpublish", headers=teacher_headers)
    assert unpublished.status_code == 200
    assert unpublished.json()["state"] == "draft"
    assert client.get("/api/agents", headers=student_headers).json() == []


def test_student_private_agent_identifiers_are_hidden_without_mutation(
    agent_api: tuple[TestClient, Database, dict[str, str]],
) -> None:
    client, database, tokens = agent_api
    from sqlalchemy import select

    from campusclaw.domain.models import Agent, AgentRevision

    payload: dict[str, Any] = {
        "name": "Private tutor",
        "system_prompt": "Use hints.",
        "skill_ids": [],
    }
    created = client.post("/api/agents", headers=authorization(tokens["teacher"]), json=payload)
    assert created.status_code == 201
    identifier = created.json()["id"]
    missing = str(uuid.uuid4())
    with database.transaction() as session:
        revision_ids = list(session.scalars(select(AgentRevision.id)))
    for method, suffix in (
        ("GET", ""),
        ("PATCH", ""),
        ("DELETE", ""),
        ("POST", "/publish"),
        ("POST", "/unpublish"),
    ):
        real = client.request(
            method,
            f"/api/agents/{identifier}{suffix}",
            headers=authorization(tokens["student"]),
            json=payload if method == "PATCH" else None,
        )
        absent = client.request(
            method,
            f"/api/agents/{missing}{suffix}",
            headers=authorization(tokens["student"]),
            json=payload if method == "PATCH" else None,
        )
        assert real.status_code == absent.status_code == 404
        assert (
            real.json()
            == absent.json()
            == {"detail": {"code": "agent_not_found", "message": "Agent not found"}}
        )
    assert (
        client.post(
            "/api/agents", headers=authorization(tokens["student"]), json=payload
        ).status_code
        == 403
    )
    with database.transaction() as session:
        agent = session.get(Agent, uuid.UUID(identifier))
        assert agent is not None and agent.state == "draft"
        assert list(session.scalars(select(AgentRevision.id))) == revision_ids
