# pyright: basic, reportMissingImports=false
"""Authentication and database dependencies shared by protected routes."""

import uuid
from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DatabaseSession

from campusclaw.application.tokens import TokenService
from campusclaw.config import Settings
from campusclaw.domain.models import Class, User, UserRole
from campusclaw.persistence.database import Database


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    account: str
    role: UserRole
    class_id: uuid.UUID


def unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthenticated", "message": "Authentication required"},
    )


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_token_service(request: Request) -> TokenService:
    return cast(TokenService, request.app.state.token_service)


def get_db(
    database: Annotated[Database, Depends(get_database)],
) -> Generator[DatabaseSession, None, None]:
    """Yield a request session; routes and application services own commits."""
    session = database.session_factory()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    return parts[1]


class CampusBearer(HTTPBearer):
    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials | None:
        # Preserve legacy whitespace/case parsing and the exact domain 401 body;
        # HTTPBearer's default 403/malformed-header behavior is deliberately disabled.
        token = bearer_token(request)
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token) if token else None


bearer_security = CampusBearer(auto_error=False, scheme_name="BearerJWT", bearerFormat="JWT")


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_security)],
    database: Annotated[DatabaseSession, Depends(get_db)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> Principal:
    token = credentials.credentials if credentials else None
    user_id = tokens.subject(token) if token else None
    if user_id is None:
        raise unauthenticated()
    user = database.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthenticated()
    try:
        role = UserRole(user.role)
    except ValueError:
        raise unauthenticated() from None
    if user.class_id is None or database.get(Class, user.class_id) is None:
        raise unauthenticated()
    return Principal(user.id, user.account, role, user.class_id)


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


def require_teacher(
    principal: Annotated[Principal, Depends(require_supported_role)],
) -> Principal:
    """Authorize a teacher-only operation at the API boundary."""
    if principal.role is not UserRole.TEACHER:
        raise forbidden()
    return principal
