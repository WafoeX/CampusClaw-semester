# pyright: basic, reportMissingImports=false
"""FastAPI application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from campusclaw.api.chat_limits import ChatBodyLimitMiddleware
from campusclaw.api.documentation import install_documentation
from campusclaw.api.routes_agents import router as agents_router
from campusclaw.api.routes_auth import router as auth_router
from campusclaw.api.routes_conversations import router as conversations_router
from campusclaw.api.routes_health import router as health_router
from campusclaw.api.routes_knowledge import router as knowledge_router
from campusclaw.api.routes_materials import router as materials_router
from campusclaw.api.routes_mcp import router as mcp_router
from campusclaw.api.routes_skills import router as skills_router
from campusclaw.application.materials import reconcile_storage
from campusclaw.application.mcp_execution import recover_pending_mcp
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
        app.state.chat_tasks = set()
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
        with suppress(SQLAlchemyError):
            recover_pending_mcp(runtime_database, runtime_settings)
        try:
            yield
        finally:
            # Accepted work is shielded from connection cancellation but bounded by
            # its supervisor timeout. Drain it before disposing the connection pool.
            if app.state.chat_tasks:
                await asyncio.gather(*app.state.chat_tasks, return_exceptions=True)
            if owns_database:
                runtime_database.dispose()

    application = FastAPI(
        title="CampusClaw API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    application.add_middleware(ChatBodyLimitMiddleware)

    @application.exception_handler(RequestValidationError)
    async def safe_resource_validation(
        request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        # Preserve legacy validation status codes while replacing framework input
        # echoes with the documented safe error. The knowledge route's own 400
        # handling and its single-turn response contract are unchanged.
        path = request.url.path
        resource_input = any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in ("/api/agents", "/api/skills", "/api/conversations", "/api/mcp")
        )
        return JSONResponse(
            status_code=400 if resource_input else 422,
            content={"detail": {"code": "invalid_request", "message": "Invalid request"}},
        )

    application.include_router(auth_router)
    application.include_router(agents_router)
    application.include_router(skills_router)
    application.include_router(mcp_router)
    application.include_router(conversations_router)
    application.include_router(materials_router)
    application.include_router(knowledge_router)
    application.include_router(health_router)
    install_documentation(application)
    return application


app = create_app()
