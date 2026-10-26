"""Teacher-only, class-shared MCP management and minimal tool audits."""

import base64
import binascii
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal, get_db, get_settings, require_teacher
from campusclaw.api.mcp_schemas import (
    McpAuditPage,
    McpAuditResponse,
    McpRegisterRequest,
    McpServerPage,
    McpServerResponse,
    McpToolResponse,
)
from campusclaw.api.schemas import DomainErrorResponse, StrictModel
from campusclaw.application.mcp_client import McpFailure, compatible_question_schema
from campusclaw.application.mcp_servers import (
    ConnectionSuperseded,
    McpServerService,
    MissingMcpServer,
)
from campusclaw.config import Settings
from campusclaw.domain.models import McpServer
from campusclaw.persistence.mcp import McpRepository

router = APIRouter(
    prefix="/api/mcp",
    tags=["mcp"],
    responses={code: {"model": DomainErrorResponse} for code in (400, 401, 403, 404, 409, 503)},
)
Teacher = Annotated[Principal, Depends(require_teacher)]
Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


def missing() -> HTTPException:
    return HTTPException(
        404, detail={"code": "mcp_server_not_found", "message": "Server not found"}
    )


def cursor_before(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    if value is None:
        return None
    try:
        if len(value) > 256:
            raise ValueError
        raw = base64.b64decode(value, altchars=b"-_", validate=True).decode()
        timestamp, identity = raw.split("|")
        moment = datetime.fromisoformat(timestamp)
        if moment.tzinfo is None:
            raise ValueError
        return moment, uuid.UUID(identity)
    except (ValueError, UnicodeError, binascii.Error):
        raise HTTPException(
            400, detail={"code": "invalid_cursor", "message": "Invalid cursor"}
        ) from None


def next_cursor(moment: datetime, identity: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{moment.isoformat()}|{identity}".encode()).decode()


def server_response(session: Session, server: McpServer) -> McpServerResponse:
    response = McpServerResponse.model_validate(server, from_attributes=True)
    response.tool_count = len(
        McpRepository().list_tools(
            session,
            class_id=server.class_id,
            server_id=server.id,
        )
    )
    return response


@router.post(
    "/servers",
    response_model=McpServerResponse,
    status_code=201,
    summary="登记本班批准的 MCP 服务器（无浏览器凭证）",
)
def register(
    payload: McpRegisterRequest, principal: Teacher, session: Db, settings: Config
) -> McpServerResponse:
    try:
        server = McpServerService(settings).register(session, principal, **payload.model_dump())
        session.commit()
        return server_response(session, server)
    except ValueError:
        session.rollback()
        raise HTTPException(
            400, detail={"code": "invalid_server", "message": "Invalid approved server"}
        ) from None
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409,
            detail={"code": "server_name_conflict", "message": "Class server name already exists"},
        ) from None


@router.get("/servers", response_model=McpServerPage, summary="分页列出本班共享 MCP 服务器")
def list_servers(
    principal: Teacher,
    session: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
) -> McpServerPage:
    rows = McpRepository().list_servers(
        session,
        class_id=principal.class_id,
        limit=limit,
        before=cursor_before(cursor),
    )
    selected = rows[:limit]
    after = next_cursor(selected[-1].created_at, selected[-1].id) if len(rows) > limit else None
    return McpServerPage(items=[server_response(session, s) for s in selected], next_cursor=after)


@router.post(
    "/servers/{server_id}/connect",
    response_model=McpServerResponse,
    summary="握手发现并原子发布当前连接代次工具",
)
async def connect(
    server_id: uuid.UUID,
    principal: Teacher,
    session: Db,
    settings: Config,
    payload: StrictModel | None = None,
) -> McpServerResponse:
    try:
        server = await McpServerService(settings).connect(session, principal, server_id)
        return server_response(session, server)
    except MissingMcpServer:
        raise missing() from None
    except ConnectionSuperseded:
        raise HTTPException(
            409,
            detail={
                "code": "connection_superseded",
                "message": "Connection replaced; refresh server state",
            },
        ) from None
    except McpFailure as error:
        raise HTTPException(503, detail={"code": error.code, "message": str(error)}) from None


@router.post(
    "/servers/{server_id}/disconnect",
    response_model=McpServerResponse,
    summary="幂等断开并清空发现缓存、作废旧代次",
)
def disconnect(
    server_id: uuid.UUID,
    principal: Teacher,
    session: Db,
    settings: Config,
    payload: StrictModel | None = None,
) -> McpServerResponse:
    try:
        server = McpServerService(settings).disconnect(session, principal, server_id)
        return server_response(session, server)
    except MissingMcpServer:
        raise missing() from None


@router.get(
    "/servers/{server_id}/tools",
    response_model=list[McpToolResponse],
    summary="读取当前代次安全工具元数据及参数适配状态",
)
def tools(
    server_id: uuid.UUID, principal: Teacher, session: Db, settings: Config
) -> list[McpToolResponse]:
    try:
        server = McpServerService(settings).require_server(session, principal, server_id)
    except MissingMcpServer:
        raise missing() from None
    return [
        McpToolResponse(
            name=tool.name,
            tool_ref=f"{tool.name}@{server.name}",
            description=tool.description,
            input_schema=tool.input_schema,
            supported=compatible_question_schema(tool.input_schema),
            code=None
            if compatible_question_schema(tool.input_schema)
            else "tool_schema_unsupported",
        )
        for tool in McpRepository().list_tools(
            session, class_id=principal.class_id, server_id=server_id
        )
    ]


@router.get(
    "/audits", response_model=McpAuditPage, summary="分页查看本班最小工具审计（不含对话正文）"
)
def audits(
    principal: Teacher,
    session: Db,
    settings: Config,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
    server_id: uuid.UUID | None = None,
) -> McpAuditPage:
    if server_id is not None:
        try:
            McpServerService(settings).require_server(session, principal, server_id)
        except MissingMcpServer:
            raise missing() from None
    rows = McpRepository().list_audits(
        session,
        class_id=principal.class_id,
        limit=limit,
        server_id=server_id,
        before=cursor_before(cursor),
    )
    selected = rows[:limit]
    after = next_cursor(selected[-1].created_at, selected[-1].id) if len(rows) > limit else None
    return McpAuditPage(
        items=[McpAuditResponse.model_validate(row, from_attributes=True) for row in selected],
        next_cursor=after,
    )
