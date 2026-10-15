# pyright: basic, reportMissingImports=false
"""Agent maintenance, publication, and student catalog endpoints."""

import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import (
    Principal,
    get_db,
    get_settings,
    require_supported_role,
    require_teacher,
)
from campusclaw.api.schemas import (
    AgentCatalogResponse,
    AgentCreateRequest,
    AgentResponse,
    AgentUpdateRequest,
    DomainErrorResponse,
)
from campusclaw.application.agent_revisions import latest_agent_revision
from campusclaw.application.agents import AgentNotReadyError, AgentService, MissingAgentError
from campusclaw.config import Settings
from campusclaw.domain.models import Agent, AgentSkillBinding, SkillRevision, UserRole
from campusclaw.persistence.agents import AgentRepository

router = APIRouter(
    prefix="/api/agents",
    tags=["agents"],
    responses={code: {"model": DomainErrorResponse} for code in (400, 401, 403, 404, 409)},
)


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "agent_not_found", "message": "Agent not found"})


def _not_ready() -> HTTPException:
    return HTTPException(409, detail={"code": "agent_not_ready", "message": "Agent is not ready"})


def _service(settings: object) -> AgentService:
    if not isinstance(settings, Settings):
        raise HTTPException(503, detail={"code": "not_ready", "message": "Unavailable"})
    return AgentService(settings)


def _response(session: Session, agent: Agent) -> AgentResponse:
    revision = latest_agent_revision(session, agent)
    if revision is None:
        raise RuntimeError("agent has no revision")
    skills = list(
        session.scalars(
            select(SkillRevision.skill_id)
            .join(AgentSkillBinding, AgentSkillBinding.skill_revision_id == SkillRevision.id)
            .where(AgentSkillBinding.agent_revision_id == revision.id)
            .order_by(SkillRevision.skill_id)
        )
    )
    return AgentResponse(
        id=agent.id,
        state=cast(Literal["draft", "published", "retired"], agent.state),
        name=revision.name,
        description=revision.description,
        system_prompt=revision.system_prompt,
        skill_ids=skills,
        current_revision_id=agent.current_revision_id,
        published_revision_id=agent.published_revision_id,
    )


@router.get("", response_model=list[AgentResponse | AgentCatalogResponse])
def list_agents(
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
) -> list[AgentResponse | AgentCatalogResponse]:
    repository = AgentRepository()
    if principal.role is UserRole.STUDENT:
        result: list[AgentResponse | AgentCatalogResponse] = []
        for agent in repository.list_published_for_class(database, class_id=principal.class_id):
            revision = latest_agent_revision(database, agent)
            if revision is not None and agent.published_revision_id == revision.id:
                result.append(
                    AgentCatalogResponse(
                        id=agent.id, name=revision.name, description=revision.description
                    )
                )
        return result
    return [
        _response(database, agent)
        for agent in repository.list_for_creator(
            database, class_id=principal.class_id, creator_id=principal.user_id
        )
        if agent.state != "retired"
    ]


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: AgentCreateRequest,
    principal: Annotated[Principal, Depends(require_teacher)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentResponse:
    try:
        agent = _service(settings).create(database, principal, **payload.model_dump())
        database.commit()
        return _response(database, agent)
    except MissingAgentError:
        database.rollback()
        raise _not_found() from None
    except ValueError:
        database.rollback()
        raise HTTPException(
            400, detail={"code": "invalid_agent", "message": "Invalid agent"}
        ) from None


@router.get("/{agent_id}", response_model=AgentResponse)
def read_agent(
    agent_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentResponse:
    try:
        return _response(database, _service(settings).read(database, principal, agent_id))
    except MissingAgentError:
        raise _not_found() from None


@router.patch("/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdateRequest,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentResponse:
    try:
        agent = _service(settings).update(database, principal, agent_id, **payload.model_dump())
        database.commit()
        return _response(database, agent)
    except MissingAgentError:
        database.rollback()
        raise _not_found() from None
    except ValueError:
        database.rollback()
        raise HTTPException(
            400, detail={"code": "invalid_agent", "message": "Invalid agent"}
        ) from None


@router.delete("/{agent_id}", response_model=AgentResponse)
def retire_agent(
    agent_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentResponse:
    try:
        agent = _service(settings).retire(database, principal, agent_id)
        database.commit()
        return _response(database, agent)
    except MissingAgentError:
        raise _not_found() from None


@router.post("/{agent_id}/publish", response_model=AgentResponse)
def publish_agent(
    agent_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentResponse:
    try:
        agent = _service(settings).publish(database, principal, agent_id)
        database.commit()
        return _response(database, agent)
    except MissingAgentError:
        raise _not_found() from None
    except AgentNotReadyError:
        database.rollback()
        raise _not_ready() from None


@router.post("/{agent_id}/unpublish", response_model=AgentResponse)
def unpublish_agent(
    agent_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentResponse:
    try:
        agent = _service(settings).unpublish(database, principal, agent_id)
        database.commit()
        return _response(database, agent)
    except MissingAgentError:
        raise _not_found() from None
