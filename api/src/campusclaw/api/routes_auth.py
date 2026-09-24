# pyright: basic, reportMissingImports=false
"""Authentication HTTP routes."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from campusclaw.api.dependencies import (
    Principal,
    get_current_principal,
    get_db,
    get_session_service,
    get_settings,
)
from campusclaw.api.schemas import IdentityResponse, LoginRequest
from campusclaw.application.sessions import SessionService
from campusclaw.config import Settings
from campusclaw.domain.models import Class, User, UserRole
from campusclaw.domain.security import PasswordService

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def get_password_service(request: Request) -> PasswordService:
    return cast(PasswordService, request.app.state.password_service)


def get_dummy_password_hash(request: Request) -> str:
    return cast(str, request.app.state.dummy_password_hash)


def invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "invalid_credentials", "message": "Invalid account or password"},
    )


@router.post("/login", response_model=IdentityResponse)
def login(
    credentials: LoginRequest,
    response: Response,
    database: Annotated[DatabaseSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
    passwords: Annotated[PasswordService, Depends(get_password_service)],
    dummy_hash: Annotated[str, Depends(get_dummy_password_hash)],
) -> IdentityResponse:
    account = credentials.account.strip()
    user = database.scalar(select(User).where(User.account == account)) if account else None
    candidate_hash = user.password_hash if user is not None else dummy_hash
    valid, replacement = passwords.verify_and_rehash(
        candidate_hash, credentials.password.get_secret_value()
    )
    if user is None or not user.is_active or not valid:
        raise invalid_credentials()
    try:
        role = UserRole(user.role)
    except ValueError:
        raise invalid_credentials() from None
    if database.get(Class, user.class_id) is None:
        raise invalid_credentials()

    if replacement is not None:
        user.password_hash = replacement
    issued = sessions.issue(database, user.id)
    database.commit()
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=issued.token,
        max_age=settings.SESSION_LIFETIME_SECONDS,
        expires=issued.expires_at,
        path="/",
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return IdentityResponse(
        user_id=user.id,
        account=user.account,
        role=role.value,
        class_id=user.class_id,
        csrf_token=issued.csrf_token,
        expires_at=issued.expires_at,
    )


@router.get("/me", response_model=IdentityResponse)
def me(
    principal: Annotated[Principal, Depends(get_current_principal)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
) -> IdentityResponse:
    return IdentityResponse(
        user_id=principal.user_id,
        account=principal.account,
        role=principal.role.value,
        class_id=principal.class_id,
        csrf_token=sessions.csrf_token(principal.session_token),
        expires_at=principal.session_expires_at,
    )


def csrf_failed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "csrf_failed", "message": "Request origin or CSRF token is invalid"},
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    database: Annotated[DatabaseSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
) -> None:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        record = sessions.resolve(database, token)
        if record is not None:
            expected_origin = str(request.base_url).rstrip("/")
            if request.headers.get("origin") != expected_origin or not sessions.csrf_is_valid(
                record, request.headers.get("x-csrf-token")
            ):
                raise csrf_failed()
            sessions.revoke(database, token)
            database.commit()
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
