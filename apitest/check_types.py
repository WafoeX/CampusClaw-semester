"""Strict mypy for support plus each URL-named script, without duplicate GET modules.

Braced/dotted URL directories are deliberately not Python package names. Check
operation files independently instead of suppressing or excluding their errors.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    project = root.parent
    support = sorted(path for path in root.rglob("*.py") if "cases" not in path.parts)
    cases = sorted((root / "cases").rglob("*.py"))
    batches = [support, *[[path] for path in cases]]
    failures = 0
    for paths in batches:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--config-file",
                "api/pyproject.toml",
                *[str(path.relative_to(project)) for path in paths],
            ],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            failures += 1
            print(result.stdout)
            print(result.stderr)
    print(f"Strict mypy: {len(batches)} batches, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
