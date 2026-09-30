# pyright: basic, reportMissingImports=false
"""Authentication HTTP routes."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from campusclaw.api.dependencies import Principal, get_current_principal, get_db, get_token_service
from campusclaw.api.schemas import IdentityResponse, LoginRequest, LoginResponse
from campusclaw.application.tokens import TokenService
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


@router.post("/login", response_model=LoginResponse)
def login(
    credentials: LoginRequest,
    database: Annotated[DatabaseSession, Depends(get_db)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
    passwords: Annotated[PasswordService, Depends(get_password_service)],
    dummy_hash: Annotated[str, Depends(get_dummy_password_hash)],
) -> LoginResponse:
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
    issued = tokens.issue(user.id)
    database.commit()
    return LoginResponse(
        user_id=user.id,
        account=user.account,
        role=role.value,
        class_id=user.class_id,
        expires_at=issued.expires_at,
        access_token=issued.token,
    )


@router.get("/me", response_model=IdentityResponse)
def me(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> IdentityResponse:
    return IdentityResponse(
        user_id=principal.user_id,
        account=principal.account,
        role=principal.role.value,
        class_id=principal.class_id,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout() -> None:
    """Logout is client-side because access tokens have no server-side state."""
