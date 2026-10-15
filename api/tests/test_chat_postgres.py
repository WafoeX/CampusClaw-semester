"""Task 5 PostgreSQL stream/citation and cross-conversation admission boundaries."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from sqlalchemy import select

from campusclaw.domain.models import ConversationMessage, MessageCitation
from tests import test_agent_conversation_postgres as postgres_fixtures
from tests.test_agent_conversation_postgres import Context
from tests.test_chat_generation import guidance
from tests.test_chat_streaming import seed_evidence, stream_events

api34 = postgres_fixtures.api34
pytestmark = pytest.mark.integration


def test_postgres_guidance_stream_equals_messages_and_source_snapshots(
    api34: Context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = api34
    tokens = {"teacher": c.headers["teacher.alpha"]["authorization"].split()[1]}
    material_id = seed_evidence(c.client, c.database, tokens)
    agent = c.agent()
    conversation = c.conversation(agent["id"])
    captured: list[str] = []

    def complete(_self: object, **kwargs: Any) -> str:
        captured.append(kwargs["user_payload"])
        return guidance()

    monkeypatch.setattr("campusclaw.application.providers.GenerationClient.complete", complete)
    response = c.client.post(
        f"/api/conversations/{conversation['id']}/messages",
        headers=c.headers["student.alpha"],
        json={"content": "课程主题"},
    )
    assert response.status_code == 200
    events = stream_events(response.text)
    assert [name for name, _ in events] == [
        "message.started",
        "answer.delta",
        "citation",
        "message.completed",
    ]
    assert len(captured) == 1
    assert json.loads(captured[0])[1]["messages"] == []
    with c.database.transaction() as session:
        rows = list(
            session.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == uuid.UUID(conversation["id"]))
                .order_by(ConversationMessage.ordinal)
            )
        )
        assert len(rows) == 2
        assert rows[1].content == events[1][1]["delta"]
        assert str(rows[1].applied_agent_revision_id) == events[0][1]["configuration_revision_id"]
        citations = list(
            session.scalars(select(MessageCitation).where(MessageCitation.message_id == rows[1].id))
        )
        assert len(citations) == 1 and citations[0].material_id == material_id
        assert citations[0].source_snapshot == events[2][1]["source"]


def test_postgres_rate_admission_is_atomic_across_conversations(api34: Context) -> None:
    c = api34
    agent = c.agent()
    ids = [c.conversation(agent["id"])["id"] for _ in range(2)]
    c.settings.CONVERSATION_RATE_LIMIT_PER_MINUTE = 1
    barrier = Barrier(2)

    def send(conversation_id: str) -> int:
        barrier.wait(timeout=5)
        return c.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=c.headers["student.alpha"],
            json={"content": "no evidence"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(send, ids))
    assert statuses == [200, 429]
    with c.database.transaction() as session:
        messages = list(session.scalars(select(ConversationMessage)))
        assert len(messages) == 2
        assert [message.state for message in messages] == ["completed", "completed"]
