"""Real PostgreSQL checks for MCP uniqueness and scope isolation."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from campusclaw.domain.models import (
    Agent,
    Conversation,
    ConversationMessage,
    McpDiscoveredTool,
    McpToolCall,
    User,
)
from campusclaw.persistence.mcp import McpRepository

pytestmark = pytest.mark.integration


def test_servers_are_class_shared_but_never_cross_class(postgres_api_fixture: Any) -> None:
    database = postgres_api_fixture.database
    repository = McpRepository()
    with database.transaction() as session:
        teachers = list(
            session.scalars(select(User).where(User.role == "teacher").order_by(User.account))
        )
        alpha, beta = teachers
        alpha_class, beta_class = alpha.class_id, beta.class_id
        alpha_user, beta_user = alpha.id, beta.id
        first = repository.add_server(
            session,
            class_id=alpha_class,
            created_by=alpha_user,
            name="campus-tools",
            base_url="http://mcp-demo:8090",
        )
        first_id = first.id
        repository.add_server(
            session,
            class_id=beta_class,
            created_by=beta_user,
            name="campus-tools",
            base_url="http://mcp-demo:8090",
        )
    with pytest.raises(IntegrityError), database.transaction() as session:
        repository.add_server(
            session,
            class_id=alpha_class,
            created_by=alpha_user,
            name="campus-tools",
            base_url="http://mcp-demo:8090",
        )
    with database.transaction() as session:
        assert len(repository.list_servers(session, class_id=alpha_class)) == 1
        assert len(repository.list_servers(session, class_id=beta_class)) == 1
        assert repository.get_server(session, class_id=beta_class, server_id=first_id) is None
        server = repository.get_server(session, class_id=alpha_class, server_id=first_id, lock=True)
        assert server is not None
        server.state = "connected"
        server.connection_generation = 2
        session.add_all(
            [
                McpDiscoveredTool(
                    server_id=first_id,
                    class_id=alpha_class,
                    generation=generation,
                    name="formula_hint",
                    description="hint",
                    input_schema={},
                )
                for generation in [1, 2]
            ]
        )
    with database.transaction() as session:
        assert [
            t.generation
            for t in repository.list_tools(session, class_id=alpha_class, server_id=first_id)
        ] == [2]
        assert repository.list_tools(session, class_id=beta_class, server_id=first_id) == []
    with pytest.raises(IntegrityError), database.transaction() as session:
        session.add(
            McpDiscoveredTool(
                server_id=first_id,
                class_id=beta_class,
                generation=2,
                name="foreign",
                description="",
                input_schema={},
            )
        )
        session.flush()


def test_audit_uniqueness_terminal_state_and_class_filter(postgres_api_fixture: Any) -> None:
    database = postgres_api_fixture.database
    repository = McpRepository()
    with database.transaction() as session:
        users = {u.account: u for u in session.scalars(select(User))}
        student = users["student.alpha"]
        teacher = users["teacher.alpha"]
        class_id = teacher.class_id
        other_class = users["teacher.beta"].class_id
        agent = Agent(class_id=class_id, creator_id=teacher.id)
        session.add(agent)
        session.flush()
        conversation = Conversation(class_id=class_id, student_id=student.id, agent_id=agent.id)
        session.add(conversation)
        session.flush()
        message = ConversationMessage(
            conversation_id=conversation.id,
            class_id=class_id,
            student_id=student.id,
            agent_id=agent.id,
            ordinal=1,
            role="assistant",
            state="processing",
        )
        session.add(message)
        session.flush()
        values = dict(
            class_id=class_id,
            user_id=student.id,
            conversation_id=conversation.id,
            assistant_message_id=message.id,
            tool_ref="formula_hint@campus-tools",
        )
        session.add(McpToolCall(**values))
    with database.transaction() as session:
        assert repository.list_audits(session, class_id=class_id) == []
        call = session.scalar(select(McpToolCall))
        assert call is not None
        call.execution_state = "finalized"
        call.status = "denied"
        call.code = "server_disconnected"
        call.completed_at = datetime.now(UTC)
    with database.transaction() as session:
        assert len(repository.list_audits(session, class_id=class_id)) == 1
        assert repository.list_audits(session, class_id=other_class) == []
    with pytest.raises(IntegrityError), database.transaction() as session:
        session.add(McpToolCall(**values))
        session.flush()
    with pytest.raises(IntegrityError), database.transaction() as session:
        session.add(
            McpToolCall(
                **(values | {"tool_ref": "unit_convert@campus-tools"}), execution_state="finalized"
            )
        )
        session.flush()
    assert not {"question", "arguments", "raw_result", "token"} & set(
        McpToolCall.__table__.columns.keys()
    )
