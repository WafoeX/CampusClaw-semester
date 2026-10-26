"""Black-box HTTP and SELECT-only observation of the dedicated test database."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, LiteralString, TypeGuard, cast
from urllib.parse import urlsplit

import httpx
import psycopg
from psycopg.rows import dict_row


class UnsafeTarget(ValueError):
    def __init__(self) -> None:
        super().__init__("unsafe_test_target")


def validate_database_target(dsn: str) -> None:
    try:
        target = urlsplit(dsn)
        if (
            target.scheme != "postgresql"
            or target.hostname != "db"
            or target.port not in (None, 5432)
            or target.path != "/campusclaw_apitest"
            or target.username != "apitest_reader"
            or not target.password
            or target.query
            or target.fragment
        ):
            raise UnsafeTarget()
    except ValueError:
        raise UnsafeTarget() from None


class Observer:
    def __init__(self, dsn: str) -> None:
        validate_database_target(dsn)
        try:
            self.connection = psycopg.Connection[dict[str, Any]].connect(
                dsn, row_factory=dict_row, autocommit=True
            )
            self.connection.execute("SET default_transaction_read_only = on")
            self.connection.execute("SET statement_timeout = '5s'")
            self.connection.execute("SET lock_timeout = '2s'")
            row = self.connection.execute(
                "SELECT current_database() AS db, current_user AS role"
            ).fetchone()
            if not row or row["db"] != "campusclaw_apitest" or row["role"] != "apitest_reader":
                self.connection.close()
                raise UnsafeTarget()
        except Exception:
            raise UnsafeTarget() from None

    def rows(self, query: LiteralString, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        # Only a single SELECT, in a read-only transaction, under a SELECT-only role.
        if not re.match(r"\ASELECT\s", query, re.I) or ";" in query:
            raise UnsafeTarget()
        try:
            with self.connection.transaction():
                self.connection.execute("SET TRANSACTION READ ONLY")
                rows = self.connection.execute(query, parameters).fetchmany(1001)
                if len(rows) > 1000:
                    raise ValueError
                return list(rows)
        except Exception:
            raise ValueError("database_assertion_failed") from None

    def close(self) -> None:
        self.connection.close()


@dataclass(frozen=True)
class Fixtures:
    run_id: str

    @classmethod
    def create(cls) -> Fixtures:
        return cls(uuid.uuid4().hex)

    def name(self, suffix: str) -> str:
        if not re.fullmatch(r"[a-z0-9_-]{1,30}", suffix):
            raise ValueError("invalid_fixture_label")
        return f"apitest-{self.run_id}-{suffix}"


class Client:
    def __init__(self, base_url: str) -> None:
        target = urlsplit(base_url)
        if (
            target.scheme != "http"
            or target.hostname != "gateway"
            or target.port not in (None, 8080)
            or target.path not in ("", "/")
            or target.username
            or target.password
            or target.query
            or target.fragment
        ):
            raise UnsafeTarget()
        self.http = httpx.Client(
            base_url=base_url, timeout=60, trust_env=False, follow_redirects=False
        )

    def request(
        self, method: str, path: str, *, token: str | None = None, body: Any = None
    ) -> httpx.Response:
        if not path.startswith(("/api/", "/health")) or "//" in path or ".." in path:
            raise UnsafeTarget()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = self.http.request(method, path, headers=headers, json=body)
            if len(response.content) > 2_000_000:
                raise ValueError
            return response
        except Exception:
            raise ValueError("http_request_failed") from None

    def json(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        response = self.request(method, path, **kwargs)
        try:
            if response.headers.get("content-type", "").split(";")[0] != "application/json":
                raise ValueError
            return response.status_code, response.json()
        except Exception:
            raise ValueError("json_contract_failed") from None

    def login(self, account: str, password: str) -> str:
        status, body = self.json(
            "POST", "/api/auth/login", body={"account": account, "password": password}
        )
        if status != 200 or not isinstance(body, dict):
            raise ValueError("login_failed")
        body = cast(dict[str, Any], body)
        if not isinstance(body.get("access_token"), str):
            raise ValueError("login_failed")
        return cast(str, body["access_token"])

    def close(self) -> None:
        self.http.close()


def _is_array(value: object) -> TypeGuard[list[Any]]:
    return isinstance(value, list)


def parse_sse_chunks(chunks: Iterable[bytes]) -> list[dict[str, Any]]:
    """Bound streamed bytes before joining; UTF-8 codepoints may span HTTP chunks."""
    data = bytearray()
    try:
        for chunk in chunks:
            if len(data) + len(chunk) > 2_000_000:
                raise ValueError
            data.extend(chunk)
        return parse_sse(bytes(data))
    except Exception:
        raise ValueError("sse_contract_failed") from None


def parse_sse(raw: bytes) -> list[dict[str, Any]]:
    """Strict framing/order/identity/digest checks; never echo an invalid frame."""
    try:
        return _parse_sse(raw)
    except Exception:
        raise ValueError("sse_contract_failed") from None


def _parse_sse(raw: bytes) -> list[dict[str, Any]]:
    if len(raw) > 2_000_000:
        raise ValueError
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if not text.endswith("\n\n"):
        raise ValueError
    events: list[dict[str, Any]] = []
    phase = "start"
    identifiers: tuple[str, ...] | None = None
    answer = ""
    citations: set[str] = set()
    revision: tuple[Any, Any] | None = None
    common = {"sequence", "conversation_id", "user_message_id", "assistant_message_id"}
    extra = {
        "message.started": {"configuration_revision_id", "configuration_updated"},
        "answer.delta": {"delta"},
        "citation": {"source"},
        "message.completed": {
            "status",
            "answer_length",
            "answer_sha256",
            "requested_mode",
            "retrieval_mode",
            "configuration_revision_id",
            "configuration_updated",
            "completed_at",
            "meta",
        },
        "message.error": {"code", "retryable", "meta"},
    }
    for frame in text.split("\n\n")[:-1]:
        lines = [line for line in frame.split("\n") if not line.startswith(":")]
        if not lines:
            continue
        if (
            len(events) >= 1000
            or len(lines) != 2
            or not lines[0].startswith("event: ")
            or not lines[1].startswith("data: ")
        ):
            raise ValueError
        name = lines[0][7:]
        try:
            decoded: object = json.loads(lines[1][6:])
        except ValueError:
            raise ValueError("invalid_frame") from None
        if not isinstance(decoded, dict):
            raise ValueError
        body = cast(dict[str, Any], decoded)
        if name not in extra or set(body) != common | extra[name]:
            raise ValueError
        if name in {"message.completed", "message.error"}:
            meta = body["meta"]
            if not isinstance(meta, dict) or set(cast(dict[str, Any], meta)) != {"tool_calls"}:
                raise ValueError
            meta = cast(dict[str, Any], meta)
            calls = meta["tool_calls"]
            if not _is_array(calls):
                raise ValueError
            refs: set[str] = set()
            for entry in calls:
                if not isinstance(entry, dict) or set(cast(dict[str, Any], entry)) != {
                    "tool_ref",
                    "status",
                    "code",
                }:
                    raise ValueError
                entry = cast(dict[str, Any], entry)
                if (
                    not isinstance(entry["tool_ref"], str)
                    or not 1 <= len(entry["tool_ref"]) <= 264
                    or entry["tool_ref"] in refs
                    or entry["status"] not in {"ok", "denied", "error"}
                    or not isinstance(entry["code"], str)
                    or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", entry["code"]) is None
                ):
                    raise ValueError
                refs.add(entry["tool_ref"])
        if type(body["sequence"]) is not int or body["sequence"] != len(events) + 1:
            raise ValueError
        current = tuple(
            str(uuid.UUID(body[key]))
            for key in ("conversation_id", "user_message_id", "assistant_message_id")
        )
        if identifiers is not None and current != identifiers or phase == "terminal":
            raise ValueError
        identifiers = current
        if name == "message.started":
            if phase != "start":
                raise ValueError
            uuid.UUID(body["configuration_revision_id"])
            if type(body["configuration_updated"]) is not bool:
                raise ValueError
            revision = body["configuration_revision_id"], body["configuration_updated"]
            phase = "answer"
        elif phase == "start":
            raise ValueError
        elif name == "answer.delta":
            if (
                phase != "answer"
                or not isinstance(body["delta"], str)
                or not 1 <= len(body["delta"]) <= 512
            ):
                raise ValueError
            answer += body["delta"]
            if len(answer) > 20_000:
                raise ValueError
        elif name == "citation":
            phase = "citation"
            source = cast(dict[str, Any], body["source"])
            source_id = source["source_id"]
            if set(source) != {
                "source_id",
                "material_id",
                "title",
                "original_filename",
                "excerpt",
                "page",
                "line_start",
                "line_end",
                "section",
                "action",
            }:
                raise ValueError
            if (
                any(
                    not isinstance(source[key], str)
                    for key in ("source_id", "title", "original_filename", "excerpt", "action")
                )
                or not 1 <= len(source["excerpt"]) <= 4000
                or any(
                    source[key] is not None and (type(source[key]) is not int or source[key] < 1)
                    for key in ("page", "line_start", "line_end")
                )
                or source["section"] is not None
                and (not isinstance(source["section"], str) or len(source["section"]) > 200)
            ):
                raise ValueError
            if not re.fullmatch(r"S[1-9][0-9]{0,2}", source_id) or source_id in citations:
                raise ValueError
            material_id = str(uuid.UUID(source["material_id"]))
            if source["action"] != f"/api/materials/{material_id}/download":
                raise ValueError
            citations.add(source_id)
        elif name == "message.completed":
            if (
                not answer
                or type(body["answer_length"]) is not int
                or body["answer_length"] != len(answer)
                or body["answer_sha256"] != hashlib.sha256(answer.encode()).hexdigest()
                or revision != (body["configuration_revision_id"], body["configuration_updated"])
                or set(re.findall(r"\[(S[1-9][0-9]{0,2})\]", answer)) != citations
                or body["status"] not in {"answered", "insufficient_evidence"}
                or body["requested_mode"] != "hybrid"
                or body["retrieval_mode"] not in {"keyword", "vector", "hybrid", "keyword_only"}
            ):
                raise ValueError
            if body["status"] == "insufficient_evidence" and (
                citations or answer != "根据本班资料无法回答该问题"
            ):
                raise ValueError
            if datetime.fromisoformat(body["completed_at"]).tzinfo is None:
                raise ValueError
            phase = "terminal"
        elif name == "message.error":
            if (
                answer
                or citations
                or type(body["retryable"]) is not bool
                or body["code"]
                not in {
                    "generation_failed",
                    "generation_invalid",
                    "answer_generation_unavailable",
                    "generation_timeout",
                    "source_unavailable",
                }
            ):
                raise ValueError
            phase = "terminal"
        events.append({"event": name, "data": body})
    if phase != "terminal":
        raise ValueError
    return events


@dataclass
class Context:
    client: Client
    database: Observer
    fixtures: Fixtures

    @classmethod
    def from_environment(cls) -> Context:
        client = Client(os.environ["APITEST_BASE_URL"])
        try:
            database = Observer(os.environ["APITEST_DATABASE_URL"])
        except Exception:
            client.close()
            raise
        return cls(client, database, Fixtures.create())

    def __enter__(self) -> Context:
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()
        self.database.close()
