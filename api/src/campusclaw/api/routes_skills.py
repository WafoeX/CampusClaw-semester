# pyright: basic, reportMissingImports=false
"""Creator-owned skill maintenance endpoints."""

import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal, get_db, get_settings, require_teacher
from campusclaw.api.schemas import (
    DomainErrorResponse,
    SkillCreateRequest,
    SkillResponse,
    SkillUpdateRequest,
)
from campusclaw.application.agent_revisions import latest_skill_revision
from campusclaw.application.skills import MissingSkillError, SkillService
from campusclaw.application.tool_bindings import (
    MissingToolBinding,
    ToolBindingConflict,
    reference_list,
)
from campusclaw.config import Settings
from campusclaw.domain.models import Skill

router = APIRouter(
    prefix="/api/skills",
    tags=["skills"],
    responses={code: {"model": DomainErrorResponse} for code in (400, 401, 403, 404, 409)},
)


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "skill_not_found", "message": "Skill not found"})


def _service(settings: Settings) -> SkillService:
    return SkillService(settings)


def _response(session: Session, skill: Skill) -> SkillResponse:
    revision = latest_skill_revision(session, skill)
    if revision is None:
        raise RuntimeError("skill has no revision")
    return SkillResponse(
        id=skill.id,
        state=cast(Literal["active", "retired"], skill.state),
        name=revision.name,
        skill_type=cast(Literal["solution_guidance"], revision.skill_type),
        instructions=revision.instructions,
        tools=reference_list(revision.tools),
        current_revision_id=skill.current_revision_id,
    )


@router.get("", response_model=list[SkillResponse])
def list_skills(
    principal: Annotated[Principal, Depends(require_teacher)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[SkillResponse]:
    return [
        _response(database, skill)
        for skill in _service(settings).list(database, principal)
        if skill.state != "retired"
    ]


@router.post("", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
def create_skill(
    payload: SkillCreateRequest,
    principal: Annotated[Principal, Depends(require_teacher)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SkillResponse:
    try:
        skill = _service(settings).create(database, principal, **payload.model_dump())
        database.commit()
        return _response(database, skill)
    except MissingToolBinding:
        database.rollback()
        raise _not_found() from None
    except ToolBindingConflict as error:
        database.rollback()
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from None
    except ValueError:
        database.rollback()
        raise HTTPException(
            400, detail={"code": "invalid_skill", "message": "Invalid skill"}
        ) from None


@router.get("/{skill_id}", response_model=SkillResponse)
def read_skill(
    skill_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_teacher)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SkillResponse:
    try:
        return _response(database, _service(settings).read(database, principal, skill_id))
    except MissingSkillError:
        raise _not_found() from None


@router.patch("/{skill_id}", response_model=SkillResponse)
def update_skill(
    skill_id: uuid.UUID,
    payload: SkillUpdateRequest,
    principal: Annotated[Principal, Depends(require_teacher)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SkillResponse:
    try:
        skill = _service(settings).update(
            database, principal, skill_id, **payload.model_dump(exclude_unset=True)
        )
        database.commit()
        return _response(database, skill)
    except (MissingSkillError, MissingToolBinding):
        database.rollback()
        raise _not_found() from None
    except ToolBindingConflict as error:
        database.rollback()
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from None
    except ValueError:
        database.rollback()
        raise HTTPException(
            400, detail={"code": "invalid_skill", "message": "Invalid skill"}
        ) from None


@router.delete("/{skill_id}", response_model=SkillResponse)
def retire_skill(
    skill_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_teacher)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SkillResponse:
    try:
        skill = _service(settings).retire(database, principal, skill_id)
        database.commit()
        return _response(database, skill)
    except MissingSkillError:
        raise _not_found() from None
