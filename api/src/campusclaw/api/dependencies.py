# pyright: basic, reportMissingImports=false
"""Authentication and database dependencies shared by protected routes."""

import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DatabaseSession

from campusclaw.application.sessions import SessionService
from campusclaw.config import Settings
from campusclaw.domain.models import Class, User, UserRole
from campusclaw.domain.models import Session as SessionModel
from campusclaw.persistence.database import Database


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    account: str
    role: UserRole
    class_id: uuid.UUID
    session_id: uuid.UUID
    session_token: str
    session_expires_at: datetime


def unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthenticated", "message": "Authentication required"},
    )


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_session_service(request: Request) -> SessionService:
    return cast(SessionService, request.app.state.session_service)


def get_db(
    database: Annotated[Database, Depends(get_database)],
) -> Generator[DatabaseSession, None, None]:
    yield from database.dependency()


def get_current_principal(
    request: Request,
    database: Annotated[DatabaseSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
) -> Principal:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise unauthenticated()
    record = sessions.resolve(database, token)
    if record is None:
        raise unauthenticated()
    user = database.get(User, record.user_id)
    if user is None or not user.is_active:
        raise unauthenticated()
    try:
        role = UserRole(user.role)
    except ValueError:
        raise unauthenticated() from None
    if user.class_id is None or database.get(Class, user.class_id) is None:
        raise unauthenticated()
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return Principal(user.id, user.account, role, user.class_id, record.id, token, expires_at)


def forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "forbidden", "message": "You do not have permission for this operation"},
    )


def require_supported_role(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> Principal:
    """Expose the already-validated supported role to protected routes."""
    if principal.role not in (UserRole.TEACHER, UserRole.STUDENT):
        raise unauthenticated()
    return principal


def require_csrf(
    request: Request,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[DatabaseSession, Depends(get_db)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
) -> Principal:
    """Require same-origin plus the current session's CSRF token."""
    record = database.get(SessionModel, principal.session_id)
    expected_origin = str(request.base_url).rstrip("/")
    if (
        record is None
        or request.headers.get("origin") != expected_origin
        or not sessions.csrf_is_valid(record, request.headers.get("x-csrf-token"))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_failed", "message": "Request origin or CSRF token is invalid"},
        )
    return principal


def require_teacher(
    principal: Annotated[Principal, Depends(require_supported_role)],
) -> Principal:
    """Authorize a teacher-only operation at the API boundary."""
    if principal.role is not UserRole.TEACHER:
        raise forbidden()
    return principal
