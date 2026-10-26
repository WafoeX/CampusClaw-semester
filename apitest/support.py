"""Operation registration and deliberately content-free report diagnostics."""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass, field
from typing import Any


class CheckFailed(AssertionError):
    """Only a validated assertion identifier may reach a generated report."""


# Audited diagnostic vocabulary, not a regex that might accept a token/body as a label.
SAFE_LABELS = frozenset(
    {
        "assertion_failed",
        "case_crashed",
        "discovery_failed",
        "empty_suite",
        "setup_failed",
        "response.status",
        "response.schema",
        "response.shape",
        "response.media_type",
        "response.fields",
        "response.values",
        "response.bounds",
        "response.refusal",
        "auth.identity",
        "auth.denied",
        "auth.indistinguishable",
        "auth.private_fields",
        "database.rows",
        "database.scope",
        "database.unchanged",
        "database.bindings",
        "database.revisions",
        "database.messages",
        "database.citations",
        "database.read_only",
        "stream.order",
        "stream.identifiers",
        "stream.sequence",
        "stream.answer",
        "stream.citations",
        "stream.terminal",
        "stream.configuration",
        "stream.tool_calls",
        "mcp.registration",
        "mcp.discovery",
        "mcp.disconnected",
        "mcp.no_dispatch",
        "mcp.audit",
        "mcp.safe_fields",
        "mcp.failure",
        "safe",
    }
)


def safe_label(value: str) -> str:
    return value if value in SAFE_LABELS else "assertion_failed"


@dataclass
class Checks:
    details: list[str] = field(default_factory=lambda: list[str]())

    def require(self, condition: object, label: str) -> None:
        # Never stringify condition/actual values: they may contain arbitrary secrets.
        label = safe_label(label)
        if not condition:
            raise CheckFailed(label)
        if label not in self.details and len(self.details) < 100:
            self.details.append(label)


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    run: Any


@dataclass(frozen=True)
class Result:
    method: str
    path: str
    status: str
    duration: float
    details: tuple[str, ...]


def execute(operation: Operation, context: Any) -> Result:
    checks = Checks()
    start = time.monotonic()
    try:
        with (
            open(os.devnull, "w") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            operation.run(context, checks)
        status = "passed"
    except CheckFailed as exc:
        status = "failed"
        checks.details.append(safe_label(str(exc)))
    except (Exception, SystemExit):
        # Exception strings, tracebacks and reprs can contain tokens, bodies and DSNs.
        status = "error"
        checks.details.append("case_crashed")
    return Result(
        operation.method,
        operation.path,
        status,
        time.monotonic() - start,
        tuple(checks.details[:100]),
    )
