"""Run uppercase method scripts: python -m apitest.run_all [--list]."""

from __future__ import annotations

import argparse
import contextlib
import html
import importlib.util
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Also support the requested `python apitest/run_all.py` entry point.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "apitest"

from .support import Operation, Result, execute, safe_label

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
SEGMENT = re.compile(r"(?:[a-zA-Z0-9_-][a-zA-Z0-9_.-]*|\{[a-z][a-z0-9_]*\})\Z")


class DiscoveryError(ValueError):
    pass


def discover(root: Path) -> list[Operation]:
    operations: list[Operation] = []
    seen: set[tuple[str, str]] = set()
    if not root.is_dir():
        raise DiscoveryError("cases_missing")
    for index, path in enumerate(sorted(root.rglob("*.py"))):
        if path.name == "__init__.py":
            continue
        relative = path.relative_to(root)
        parts = relative.parts[:-1]
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(root.resolve())
            or path.stem not in METHODS
            or not parts
            or any(not SEGMENT.fullmatch(part) for part in parts)
        ):
            raise DiscoveryError("malformed_operation")
        expected = "/" + "/".join(parts)
        try:
            spec = importlib.util.spec_from_file_location(f"apitest_case_{index}", path)
            if spec is None or spec.loader is None:
                raise ValueError
            module = importlib.util.module_from_spec(spec)
            with (
                open(os.devnull, "w") as sink,
                contextlib.redirect_stdout(sink),
                contextlib.redirect_stderr(sink),
            ):
                spec.loader.exec_module(module)
            operation = module.OPERATION
        except (Exception, SystemExit):
            raise DiscoveryError("registration_failed") from None
        if (
            not isinstance(operation, Operation)
            or operation.method != path.stem
            or operation.path != expected
            or not callable(operation.run)
        ):
            raise DiscoveryError("registration_mismatch")
        # Parameter names do not distinguish HTTP operations.
        key = (operation.method, re.sub(r"\{[^}]+\}", "{}", operation.path))
        if key in seen:
            raise DiscoveryError("duplicate_operation")
        seen.add(key)
        operations.append(operation)
    return operations


def write_report(results: list[Result], output: Path) -> None:
    passed = sum(row.status == "passed" for row in results)
    duration = sum(row.duration for row in results)
    rows: list[str] = []
    for row in results:
        cells = [
            row.method,
            row.path,
            row.status,
            f"{row.duration:.3f}s",
            ", ".join(safe_label(detail) for detail in row.details[:100]),
        ]
        rows.append("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in cells) + "</tr>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'\">"
        "<title>CampusClaw isolated API tests</title>"
        "<style>body{font:16px system-ui;margin:2em}td,th{padding:.5em;border:1px solid #aaa}"
        "table{border-collapse:collapse}</style><h1>API test report</h1>"
        f"<p>{passed}/{len(results)} passed; {len(results) - passed} failed/error; "
        f"duration {duration:.3f}s</p>"
        "<table><thead><tr><th>Method</th><th>URL</th><th>Status</th><th>Duration</th>"
        "<th>Safe assertion identifiers</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></html>",
        encoding="utf-8",
    )


def run(root: Path, output: Path, context: Any = None, operation_filter: str | None = None) -> int:
    try:
        operations = discover(root)
    except DiscoveryError:
        results = [Result("HARNESS", "/", "error", 0, ("discovery_failed",))]
    else:
        if operation_filter is not None:
            operations = [
                operation
                for operation in operations
                if f"{operation.method} {operation.path}" == operation_filter
            ]
        results = [execute(operation, context) for operation in operations]
        if not results:
            results = [Result("HARNESS", "/", "error", 0, ("empty_suite",))]
    write_report(results, output)
    passed = sum(row.status == "passed" for row in results)
    print(f"API tests: {passed}/{len(results)} passed; diagnostics in HTML report")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).parent / "cases")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".html"),
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--operation", help="Run exactly METHOD /path; unmatched selection fails")
    args = parser.parse_args()
    if args.list:
        try:
            for operation in discover(args.cases):
                print(f"{operation.method} {operation.path}")
            return 0
        except DiscoveryError:
            print("API tests: discovery_failed")
            return 1
    from .clients import Context

    try:
        with Context.from_environment() as context:
            return run(args.cases, args.report, context, args.operation)
    except Exception:
        write_report([Result("HARNESS", "/", "error", 0, ("setup_failed",))], args.report)
        print("API tests: setup_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
