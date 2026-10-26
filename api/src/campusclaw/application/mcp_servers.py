"""Class-shared MCP registrations and short-transaction generation lifecycle."""

import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal
from campusclaw.application.mcp_client import McpClient, McpFailure
from campusclaw.config import Settings
from campusclaw.domain.models import McpDiscoveredTool, McpServer
from campusclaw.persistence.mcp import McpRepository


class MissingMcpServer(Exception):
    pass


class ConnectionSuperseded(Exception):
    pass


class McpServerService:
    def __init__(self, settings: Settings, *, client: McpClient | None = None) -> None:
        self.settings = settings
        self.repository = McpRepository()
        self.client = client or McpClient(settings)

    def require_server(
        self,
        session: Session,
        principal: Principal,
        server_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> McpServer:
        server = self.repository.get_server(
            session,
            class_id=principal.class_id,
            server_id=server_id,
            lock=lock,
        )
        if server is None:
            raise MissingMcpServer
        return server

    def register(
        self,
        session: Session,
        principal: Principal,
        *,
        name: str,
        base_url: str,
    ) -> McpServer:
        return self.repository.add_server(
            session,
            class_id=principal.class_id,
            created_by=principal.user_id,
            name=name,
            base_url=self.settings.approved_mcp_origin(base_url),
        )

    def _invalidate(self, session: Session, server: McpServer, state: str) -> None:
        server.connection_generation += 1
        server.state = state
        server.safe_error_code = None
        session.execute(
            delete(McpDiscoveredTool).where(
                McpDiscoveredTool.server_id == server.id,
                McpDiscoveredTool.class_id == server.class_id,
            )
        )
        session.flush()

    def disconnect(self, session: Session, principal: Principal, server_id: uuid.UUID) -> McpServer:
        server = self.require_server(session, principal, server_id, lock=True)
        self._invalidate(session, server, "disconnected")
        session.commit()
        return server

    async def connect(
        self, session: Session, principal: Principal, server_id: uuid.UUID
    ) -> McpServer:
        server = self.require_server(session, principal, server_id, lock=True)
        self._invalidate(session, server, "connecting")
        generation, base_url = server.connection_generation, server.base_url
        session.commit()  # No row locks or open transaction across the remote handshake.
        try:
            tools = await self.client.discover(base_url)
        except McpFailure as error:
            session.expire_all()
            current = self.require_server(session, principal, server_id, lock=True)
            if current.connection_generation != generation:
                session.rollback()
                raise ConnectionSuperseded from None
            current.state, current.safe_error_code = "error", error.code
            session.commit()
            raise
        except BaseException:
            session.expire_all()
            current = self.require_server(session, principal, server_id, lock=True)
            if current.connection_generation == generation:
                current.state, current.safe_error_code = "error", "remote_unavailable"
            session.commit()
            raise
        session.expire_all()
        current = self.require_server(session, principal, server_id, lock=True)
        if current.connection_generation != generation or current.state != "connecting":
            session.rollback()
            raise ConnectionSuperseded
        session.add_all(
            [
                McpDiscoveredTool(
                    server_id=server_id,
                    class_id=principal.class_id,
                    generation=generation,
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                )
                for tool in tools
            ]
        )
        current.state, current.safe_error_code = "connected", None
        session.commit()
        return current
