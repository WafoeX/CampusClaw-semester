"""Test-only fixture provisioning, never imported by operation scripts."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from campusclaw.application.seed import seed_demo
from campusclaw.config import get_settings
from campusclaw.domain.models import Class, Material, User
from campusclaw.domain.security import PasswordService
from campusclaw.persistence.database import Database
from sqlalchemy import select, text

from .provider_stub import FACTS


def prepare() -> None:
    settings = get_settings()
    target = urlsplit(settings.DATABASE_URL.replace("postgresql+psycopg", "postgresql"))
    if (
        target.hostname != "db"
        or target.path != "/campusclaw_apitest"
        or target.username != "apitest_owner"
        or os.environ.get("APITEST_FIXTURES") != "yes"
    ):
        raise ValueError("unsafe_fixture_target")
    database = Database(settings.DATABASE_URL)
    try:
        seed_demo(database, settings)
        hasher = PasswordService()
        with database.transaction() as session:
            alpha = session.scalar(select(Class).where(Class.name == "Alpha Class"))
            if alpha is None:
                raise ValueError("fixture_class_missing")
            for account, role in (
                ("teacher.alpha.other", "teacher"),
                ("student.alpha.other", "student"),
            ):
                if session.scalar(select(User.id).where(User.account == account)) is None:
                    session.add(
                        User(
                            account=account,
                            role=role,
                            class_id=alpha.id,
                            password_hash=hasher.hash("apitest-account-only"),
                        )
                    )
            for index, (topic, fact) in enumerate(FACTS.items(), 1):
                material_id = uuid.UUID(f"40000000-0000-0000-0000-{index:012d}")
                if session.get(Material, material_id) is not None:
                    continue
                teacher = session.scalar(
                    select(User).where(
                        User.account == ("teacher.alpha" if index == 1 else "teacher.beta")
                    )
                )
                if teacher is None:
                    raise ValueError("fixture_teacher_missing")
                data = (fact + "\n").encode()
                storage_key = f"{teacher.class_id}/{material_id}"
                path = Path(settings.UPLOAD_ROOT) / storage_key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                session.add(
                    Material(
                        id=material_id,
                        class_id=teacher.class_id,
                        uploader_id=teacher.id,
                        title=topic,
                        original_filename=f"{topic}.txt",
                        content_type="text/plain",
                        byte_size=len(data),
                        sha256=hashlib.sha256(data).hexdigest(),
                        storage_key=storage_key,
                        state="ready",
                    )
                )
            session.flush()
            # No access to password hashes, no writes, no schema/database creation.
            session.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO apitest_reader"))
            # MCP observation excludes remote descriptions/schema and does not
            # grant broad table access that could expose future secret columns.
            session.execute(
                text(
                    "REVOKE SELECT ON mcp_servers, mcp_discovered_tools, mcp_tool_calls "
                    "FROM apitest_reader"
                )
            )
            session.execute(
                text(
                    "GRANT SELECT (id, class_id, created_by, name, base_url, state, "
                    "connection_generation, safe_error_code, created_at, updated_at) "
                    "ON mcp_servers TO apitest_reader"
                )
            )
            session.execute(
                text(
                    "GRANT SELECT (id, server_id, class_id, generation, name) "
                    "ON mcp_discovered_tools TO apitest_reader"
                )
            )
            session.execute(
                text(
                    "GRANT SELECT (id, class_id, user_id, conversation_id, assistant_message_id, "
                    "server_id, tool_ref, generation, execution_state, status, code, "
                    "created_at, completed_at) ON mcp_tool_calls TO apitest_reader"
                )
            )
            session.execute(text("REVOKE SELECT ON users FROM apitest_reader"))
            session.execute(
                text(
                    "GRANT SELECT (id, account, role, class_id, is_active, created_at) "
                    "ON users TO apitest_reader"
                )
            )
        print("isolated synthetic fixtures ready")
    finally:
        database.dispose()


if __name__ == "__main__":
    try:
        prepare()
    except Exception:
        print("fixture_setup_failed")
        raise SystemExit(1) from None
