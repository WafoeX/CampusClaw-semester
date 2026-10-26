"""MCP persistence, always scoped by the authenticated class."""

import uuid
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from campusclaw.domain.models import McpDiscoveredTool, McpServer, McpToolCall


class McpRepository:
    def add_server(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        created_by: uuid.UUID,
        name: str,
        base_url: str,
    ) -> McpServer:
        server = McpServer(class_id=class_id, created_by=created_by, name=name, base_url=base_url)
        session.add(server)
        session.flush()
        return server

    def get_server(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        server_id: uuid.UUID,
        lock: bool = False,
    ) -> McpServer | None:
        statement = select(McpServer).where(
            McpServer.class_id == class_id, McpServer.id == server_id
        )
        if lock:
            statement = statement.with_for_update()
        return session.scalar(statement)

    def list_servers(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        limit: int = 100,
        before: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[McpServer]:
        statement = select(McpServer).where(McpServer.class_id == class_id)
        if before is not None:
            statement = statement.where(tuple_(McpServer.created_at, McpServer.id) < before)
        return list(
            session.scalars(
                statement.order_by(McpServer.created_at.desc(), McpServer.id.desc()).limit(
                    max(1, min(limit, 100)) + 1
                )
            )
        )

    def list_tools(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        server_id: uuid.UUID,
    ) -> list[McpDiscoveredTool]:
        return list(
            session.scalars(
                select(McpDiscoveredTool)
                .join(
                    McpServer,
                    (McpDiscoveredTool.server_id == McpServer.id)
                    & (McpDiscoveredTool.class_id == McpServer.class_id),
                )
                .where(
                    McpServer.class_id == class_id,
                    McpServer.id == server_id,
                    McpServer.state == "connected",
                    McpDiscoveredTool.generation == McpServer.connection_generation,
                )
                .order_by(McpDiscoveredTool.name)
                .limit(50)
            )
        )

    def list_audits(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        limit: int = 100,
        server_id: uuid.UUID | None = None,
        before: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[McpToolCall]:
        statement = select(McpToolCall).where(
            McpToolCall.class_id == class_id, McpToolCall.execution_state == "finalized"
        )
        if server_id is not None:
            statement = statement.where(McpToolCall.server_id == server_id)
        if before is not None:
            statement = statement.where(tuple_(McpToolCall.created_at, McpToolCall.id) < before)
        return list(
            session.scalars(
                statement.order_by(McpToolCall.created_at.desc(), McpToolCall.id.desc()).limit(
                    max(1, min(limit, 100)) + 1
                )
            )
        )
