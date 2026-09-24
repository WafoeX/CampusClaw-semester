#!/usr/bin/env python3
"""Acceptance check for production's disabled-by-default, explicit seed override."""

from __future__ import annotations

import os
import secrets
import subprocess
import uuid
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("-f", "docker-compose.yml", "-f", "docker-compose.prod.yml")


def compose(project: str, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-p", project, *COMPOSE_FILES, *args],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def scalar(compose_env: dict[str, str], project: str, query: str) -> int:
    result = compose(
        project,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        compose_env["POSTGRES_USER"],
        "-d",
        compose_env["POSTGRES_DB"],
        "-Atqc",
        query,
        env=compose_env,
    )
    return int(result.stdout.strip())


def material_file_count(compose_env: dict[str, str], project: str) -> int:
    result = compose(
        project,
        "run",
        "--rm",
        "--no-deps",
        "api",
        "sh",
        "-c",
        "find /var/lib/campusclaw/materials -type f ! -path '*/tmp/*' | wc -l",
        env=compose_env,
    )
    return int(result.stdout.strip())


def assert_counts(compose_env: dict[str, str], project: str, expected: tuple[int, int, int, int]) -> None:
    actual = (
        scalar(compose_env, project, "SELECT count(*) FROM classes"),
        scalar(compose_env, project, "SELECT count(*) FROM users"),
        scalar(compose_env, project, "SELECT count(*) FROM materials"),
        material_file_count(compose_env, project),
    )
    assert actual == expected, (actual, expected)


def main() -> None:
    postgres_password = secrets.token_hex(16)
    compose_env = os.environ.copy()
    compose_env.update(
        {
            "APP_ENV": "production",
            "POSTGRES_DB": "campusclaw",
            "POSTGRES_USER": "campusclaw",
            "POSTGRES_PASSWORD": postgres_password,
            "DATABASE_URL": (
                "postgresql+psycopg://campusclaw:"
                f"{quote(postgres_password, safe='')}@db/campusclaw"
            ),
            "SESSION_HMAC_KEY": secrets.token_hex(32),
            "SESSION_COOKIE_SECURE": "true",
            "SEED_DEMO_DATA": "false",
            "DEMO_ALPHA_TEACHER_PASSWORD": secrets.token_hex(16),
            "DEMO_ALPHA_STUDENT_PASSWORD": secrets.token_hex(16),
            "DEMO_BETA_TEACHER_PASSWORD": secrets.token_hex(16),
            "DEMO_BETA_STUDENT_PASSWORD": secrets.token_hex(16),
            "WEB_PORT": "18081",
        }
    )
    project = f"campusclaw_prod_acceptance_{uuid.uuid4().hex[:10]}"
    try:
        compose(project, "up", "-d", "db", "migrate", "seed", "api", "web", env=compose_env)
        assert_counts(compose_env, project, (0, 0, 0, 0))

        compose_env["SEED_DEMO_DATA"] = "true"
        compose(project, "run", "--rm", "-e", "SEED_DEMO_DATA=true", "seed", env=compose_env)
        assert_counts(compose_env, project, (2, 4, 2, 2))
        print("production seed acceptance passed")
    finally:
        subprocess.run(
            ["docker", "compose", "-p", project, *COMPOSE_FILES, "down", "-v", "--remove-orphans"],
            cwd=ROOT,
            env=compose_env,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
