"""Student conversation lifecycle, creator audit, and safe SSE message delivery."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import (
    Principal,
    get_database,
    get_db,
    get_settings,
    require_supported_role,
)
from campusclaw.api.schemas import (
    CitationSource,
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationMessageRequest,
    ConversationMessageResponse,
    ConversationResponse,
    DomainErrorResponse,
)
from campusclaw.api.sse import (
    AnswerDelta,
    CitationEvent,
    MessageCompleted,
    MessageError,
    MessageStarted,
    serialize_event,
)
from campusclaw.application.agents import AgentNotReadyError
from campusclaw.application.chat_tasks import execute_turn
from campusclaw.application.conversations import (
    ConversationRateLimitError,
    ConversationService,
    MissingConversationError,
    TurnInProgressError,
)
from campusclaw.config import Settings
from campusclaw.domain.models import (
    Agent,
    AgentRevision,
    Conversation,
    ConversationMessage,
    User,
)
from campusclaw.persistence.conversations import ConversationRepository
from campusclaw.persistence.database import Database

router = APIRouter(
    prefix="/api",
    tags=["conversations"],
    responses={code: {"model": DomainErrorResponse} for code in (400, 401, 403, 404, 409)},
)


def _not_found() -> HTTPException:
    return HTTPException(
        404, detail={"code": "conversation_not_found", "message": "Conversation not found"}
    )


def _not_ready() -> HTTPException:
    return HTTPException(409, detail={"code": "agent_not_ready", "message": "Agent is not ready"})


def _turn_in_progress() -> HTTPException:
    return HTTPException(
        409, detail={"code": "turn_in_progress", "message": "Message already in progress"}
    )


def _service(settings: Settings) -> ConversationService:
    return ConversationService(settings)


def _message_response(
    session: Session, message: ConversationMessage
) -> ConversationMessageResponse:
    return ConversationMessageResponse(
        id=message.id,
        ordinal=message.ordinal,
        role=cast(Literal["user", "assistant"], message.role),
        state=cast(Literal["processing", "completed", "failed"], message.state),
        content=message.content,
        safe_error_code=message.safe_error_code,
        retrieval_mode=message.retrieval_mode,
        applied_agent_revision_id=message.applied_agent_revision_id,
        configuration_updated=message.configuration_updated,
        created_at=message.created_at,
        completed_at=message.completed_at,
        citations=[
            CitationSource.model_validate(item.source_snapshot)
            for item in ConversationRepository().citations(session, message=message)
            if item.source_snapshot
        ],
    )


def _response(
    service: ConversationService,
    session: Session,
    conversation: Conversation,
    *,
    after_ordinal: int = 0,
    limit: int = 100,
) -> ConversationResponse:
    messages = ConversationRepository().messages(
        session, conversation=conversation, after_ordinal=after_ordinal, limit=limit + 1
    )
    return ConversationResponse(
        id=conversation.id,
        agent_id=conversation.agent_id,
        **_display_metadata(session, conversation),
        deleted_at=conversation.deleted_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_message_response(session, message) for message in messages[:limit]],
        next_after_ordinal=messages[limit - 1].ordinal if len(messages) > limit else None,
    )


def _display_metadata(session: Session, conversation: Conversation) -> dict[str, Any]:
    row = session.execute(
        select(AgentRevision.name, User.account)
        .select_from(Agent)
        .join(AgentRevision, AgentRevision.id == Agent.current_revision_id)
        .join(User, User.id == conversation.student_id)
        .where(Agent.id == conversation.agent_id, Agent.class_id == conversation.class_id)
    ).one()
    return {
        "agent_name": row.name,
        "student_id": conversation.student_id,
        "student_account": row.account,
    }


def _list_response(session: Session, conversation: Conversation) -> ConversationListResponse:
    return ConversationListResponse(
        id=conversation.id,
        agent_id=conversation.agent_id,
        **_display_metadata(session, conversation),
        deleted_at=conversation.deleted_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get("/conversations", response_model=list[ConversationListResponse])
def list_conversations(
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[ConversationListResponse]:
    try:
        return [
            _list_response(database, item)
            for item in _service(settings).list_for_student(database, principal)
        ]
    except PermissionError:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Forbidden"}) from None


@router.post(
    "/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED
)
def create_conversation(
    payload: ConversationCreateRequest,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationResponse:
    service = _service(settings)
    try:
        conversation = service.create(database, principal, agent_id=payload.agent_id)
        database.commit()
        return _response(service, database, conversation)
    except PermissionError:
        database.rollback()
        raise HTTPException(403, detail={"code": "forbidden", "message": "Forbidden"}) from None
    except AgentNotReadyError:
        database.rollback()
        raise _not_ready() from None


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def read_conversation(
    conversation_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    after_ordinal: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> ConversationResponse:
    service = _service(settings)
    try:
        conversation = service.read(database, principal, conversation_id)
        return _response(service, database, conversation, after_ordinal=after_ordinal, limit=limit)
    except (MissingConversationError, PermissionError):
        raise _not_found() from None


@router.delete("/conversations/{conversation_id}", response_model=ConversationListResponse)
def delete_conversation(
    conversation_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationListResponse:
    service = _service(settings)
    try:
        conversation = service.soft_delete(database, principal, conversation_id)
        database.commit()
        return _list_response(database, conversation)
    except (MissingConversationError, PermissionError):
        database.rollback()
        raise _not_found() from None


@router.get("/agents/{agent_id}/conversations", response_model=list[ConversationResponse])
def list_agent_conversations(
    agent_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    deleted: bool | None = None,
) -> list[ConversationResponse]:
    service = _service(settings)
    try:
        conversations = service.list_for_creator(database, principal, agent_id, deleted=deleted)
    except (MissingConversationError, PermissionError):
        raise _not_found() from None
    return [_response(service, database, item) for item in conversations]


@router.get(
    "/agents/{agent_id}/conversations/{conversation_id}", response_model=ConversationResponse
)
def read_agent_conversation(
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    after_ordinal: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> ConversationResponse:
    service = _service(settings)
    try:
        conversation = service.read_for_creator(database, principal, agent_id, conversation_id)
    except (MissingConversationError, PermissionError):
        raise _not_found() from None
    return _response(service, database, conversation, after_ordinal=after_ordinal, limit=limit)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={
        413: {"model": DomainErrorResponse},
        429: {"model": DomainErrorResponse},
        503: {"model": DomainErrorResponse},
    },
)
async def send_message(
    request: Request,
    conversation_id: uuid.UUID,
    payload: ConversationMessageRequest,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    runtime_database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    service = _service(settings)
    try:
        conversation, user, assistant = service.accept_turn(
            database, principal, conversation_id, content=payload.content
        )
        event_ids = (conversation.id, user.id, assistant.id, assistant.applied_agent_revision_id)
        configuration_updated = assistant.configuration_updated
        database.commit()
    except PermissionError:
        database.rollback()
        raise HTTPException(403, detail={"code": "forbidden", "message": "Forbidden"}) from None
    except MissingConversationError:
        database.rollback()
        raise _not_found() from None
    except AgentNotReadyError:
        database.rollback()
        raise _not_ready() from None
    except TurnInProgressError:
        database.rollback()
        raise _turn_in_progress() from None
    except ConversationRateLimitError:
        database.rollback()
        raise HTTPException(
            429,
            detail={"code": "rate_limited", "message": "Too many messages"},
            headers={"Retry-After": "60"},
        ) from None
    except ValueError:
        database.rollback()
        raise HTTPException(
            400, detail={"code": "invalid_message", "message": "Invalid message"}
        ) from None

    conversation_id_value, user_id, assistant_id, revision_id = event_ids
    assert revision_id is not None
    # Strong application-owned reference: disconnect cancels the stream, not accepted work.
    task = asyncio.create_task(
        execute_turn(
            runtime_database,
            settings,
            principal,
            conversation_id_value,
            user_id,
            assistant_id,
        )
    )
    request.app.state.chat_tasks.add(task)
    task.add_done_callback(request.app.state.chat_tasks.discard)

    async def events() -> AsyncIterator[bytes]:
        common: dict[str, Any] = {
            "conversation_id": conversation_id_value,
            "user_message_id": user_id,
            "assistant_message_id": assistant_id,
        }
        sequence = 1
        yield serialize_event(
            "message.started",
            MessageStarted(
                **common,
                sequence=sequence,
                configuration_revision_id=revision_id,
                configuration_updated=configuration_updated,
            ),
        )
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), settings.SSE_HEARTBEAT_SECONDS)
            except TimeoutError:
                yield b": heartbeat\n\n"
        outcome = task.result()
        if outcome.code is not None:
            yield serialize_event(
                "message.error",
                MessageError(
                    **common,
                    sequence=sequence + 1,
                    code=cast(Any, outcome.code),
                    retryable=outcome.retryable,
                ),
            )
            return
        assert outcome.result is not None and outcome.completed_at is not None
        for index in range(0, len(outcome.answer), 512):
            sequence += 1
            yield serialize_event(
                "answer.delta",
                AnswerDelta(
                    **common,
                    sequence=sequence,
                    delta=outcome.answer[index : index + 512],
                ),
            )
        for source in outcome.sources:
            sequence += 1
            yield serialize_event(
                "citation",
                CitationEvent(
                    **common,
                    sequence=sequence,
                    source=source,
                ),
            )
        yield serialize_event(
            "message.completed",
            MessageCompleted(
                **common,
                sequence=sequence + 1,
                status=cast(Any, outcome.result.parsed.status),
                answer_length=len(outcome.answer),
                answer_sha256=hashlib.sha256(outcome.answer.encode()).hexdigest(),
                retrieval_mode=cast(Any, outcome.result.retrieval_mode),
                configuration_revision_id=revision_id,
                configuration_updated=configuration_updated,
                completed_at=outcome.completed_at,
            ),
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
