#!/usr/bin/env python3
"""Exercise the documented coordinated PostgreSQL/material-volume restore flow."""

from __future__ import annotations

import os
import secrets
import subprocess
import tempfile
import uuid
from pathlib import Path
from subprocess import CompletedProcess
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "campusclaw-api:local"


def compose(
    project: str,
    environment: dict[str, str],
    *args: str,
    input_bytes: bytes | None = None,
) -> CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", "compose", "-p", project, *args],
        cwd=ROOT,
        env=environment,
        input=input_bytes,
        capture_output=True,
        check=True,
    )


def database_rows(project: str, environment: dict[str, str]) -> str:
    query = (
        "SELECT storage_key || '|' || sha256 FROM materials "
        "WHERE state = 'ready' ORDER BY storage_key"
    )
    result = compose(
        project,
        environment,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        environment["POSTGRES_USER"],
        "-d",
        environment["POSTGRES_DB"],
        "-At",
        "-c",
        query,
    )
    return result.stdout.decode().strip()


def volume_rows(project: str, environment: dict[str, str]) -> str:
    code = (
        "import hashlib, pathlib; "
        "root=pathlib.Path('/source'); "
        "files=[p for p in root.rglob('*') if p.is_file() and 'tmp' not in p.parts]; "
        "print('\\n'.join(f'{p.relative_to(root)}|{hashlib.sha256(p.read_bytes()).hexdigest()}' "
        "for p in sorted(files)))"
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{project}_materials-data:/source:ro",
            IMAGE,
            "python",
            "-c",
            code,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode().strip()


def clear_material_volume(project: str, environment: dict[str, str]) -> None:
    code = (
        "import pathlib, shutil; root=pathlib.Path('/target'); "
        "[shutil.rmtree(p) if p.is_dir() else p.unlink() for p in root.iterdir()]"
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{project}_materials-data:/target",
            IMAGE,
            "python",
            "-c",
            code,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
    )


def create_material_archive(project: str, environment: dict[str, str], destination: Path) -> None:
    code = (
        "import tarfile; "
        "archive=tarfile.open('/backup/materials.tar.gz', 'w:gz'); "
        "archive.add('/source', arcname='.'); archive.close()"
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{project}_materials-data:/source:ro",
            "-v",
            f"{destination}:/backup",
            IMAGE,
            "python",
            "-c",
            code,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
    )


def restore_material_archive(project: str, environment: dict[str, str], source: Path) -> None:
    code = (
        "import pathlib, shutil, tarfile; root=pathlib.Path('/target'); "
        "[shutil.rmtree(p) if p.is_dir() else p.unlink() for p in root.iterdir()]; "
        "tarfile.open('/backup/materials.tar.gz').extractall(root, filter='data')"
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{project}_materials-data:/target",
            "-v",
            f"{source.parent}:/backup",
            IMAGE,
            "python",
            "-c",
            code,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
    )


def main() -> None:
    project = f"campusclaw_backup_acceptance_{uuid.uuid4().hex[:10]}"
    password = secrets.token_hex(16)
    environment = os.environ.copy()
    environment.update(
        {
            "COMPOSE_PROJECT_NAME": project,
            "APP_ENV": "demo",
            "POSTGRES_DB": "campusclaw",
            "POSTGRES_USER": "campusclaw",
            "POSTGRES_PASSWORD": password,
            "DATABASE_URL": f"postgresql+psycopg://campusclaw:{password}@db/campusclaw",
            "JWT_SIGNING_KEY": secrets.token_hex(32),
            "SEED_DEMO_DATA": "true",
            "DEMO_ALPHA_TEACHER_PASSWORD": secrets.token_hex(16),
            "DEMO_ALPHA_STUDENT_PASSWORD": secrets.token_hex(16),
            "DEMO_BETA_TEACHER_PASSWORD": secrets.token_hex(16),
            "DEMO_BETA_STUDENT_PASSWORD": secrets.token_hex(16),
            "WEB_PORT": "18082",
        }
    )
    try:
        compose(project, environment, "up", "-d", "db", "migrate", "seed", "api", "web")
        before_database = database_rows(project, environment)
        before_files = volume_rows(project, environment)
        assert before_database.count("\n") + 1 == 2
        assert before_files.count("\n") + 1 == 2

        with tempfile.TemporaryDirectory() as temporary:
            backup_dir = Path(temporary)
            dump = compose(
                project,
                environment,
                "exec",
                "-T",
                "db",
                "pg_dump",
                "-U",
                environment["POSTGRES_USER"],
                "-d",
                environment["POSTGRES_DB"],
                "--format=custom",
            ).stdout
            (backup_dir / "database.dump").write_bytes(dump)
            create_material_archive(project, environment, backup_dir)

            compose(project, environment, "stop", "web", "api")
            compose(
                project,
                environment,
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                environment["POSTGRES_USER"],
                "-d",
                environment["POSTGRES_DB"],
                "-c",
                "TRUNCATE materials, users, classes CASCADE",
            )
            clear_material_volume(project, environment)

            compose(
                project,
                environment,
                "exec",
                "-T",
                "db",
                "pg_restore",
                "-U",
                environment["POSTGRES_USER"],
                "-d",
                environment["POSTGRES_DB"],
                "--clean",
                "--if-exists",
                "--no-owner",
                "--exit-on-error",
                input_bytes=(backup_dir / "database.dump").read_bytes(),
            )
            restore_material_archive(project, environment, backup_dir / "materials.tar.gz")

        assert database_rows(project, environment) == before_database
        assert volume_rows(project, environment) == before_files
        compose(project, environment, "up", "-d", "api", "web")
        with urlopen("http://127.0.0.1:18082/health", timeout=10) as response:
            assert response.status == 200
        print("coordinated backup/restore passed")
    finally:
        subprocess.run(
            ["docker", "compose", "-p", project, "down", "-v", "--remove-orphans"],
            cwd=ROOT,
            env=environment,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
