# pyright: basic, reportMissingImports=false
"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from campusclaw.api.routes_auth import router as auth_router
from campusclaw.api.routes_health import router as health_router
from campusclaw.api.routes_knowledge import router as knowledge_router
from campusclaw.api.routes_materials import router as materials_router
from campusclaw.application.materials import reconcile_storage
from campusclaw.application.tokens import TokenService
from campusclaw.config import Settings, get_settings
from campusclaw.domain.security import PasswordService
from campusclaw.persistence.database import Database


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    password_service: PasswordService | None = None,
) -> FastAPI:
    """Create the CampusClaw API application and own runtime resources when not injected."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime_settings = settings or get_settings()
        owns_database = database is None
        runtime_database = database or Database(runtime_settings.DATABASE_URL)
        runtime_passwords = password_service or PasswordService()
        app.state.settings = runtime_settings
        app.state.database = runtime_database
        app.state.password_service = runtime_passwords
        app.state.dummy_password_hash = runtime_passwords.hash("dummy-not-a-user-password")
        app.state.token_service = TokenService(
            runtime_settings.JWT_SIGNING_KEY.get_secret_value(),
            runtime_settings.JWT_ACCESS_TOKEN_LIFETIME_SECONDS,
        )
        # Readiness reports unavailable dependencies without preventing the
        # process from serving the public health endpoint.
        with suppress(OSError, ValueError, SQLAlchemyError):
            reconcile_storage(runtime_database, runtime_settings.UPLOAD_ROOT)
        try:
            yield
        finally:
            if owns_database:
                runtime_database.dispose()

    application = FastAPI(title="CampusClaw API", version="0.1.0", lifespan=lifespan)
    application.include_router(auth_router)
    application.include_router(materials_router)
    application.include_router(knowledge_router)
    application.include_router(health_router)
    return application


app = create_app()
