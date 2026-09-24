# pyright: basic, reportMissingImports=false, reportMissingTypeStubs=false
"""PostgreSQL-backed API integration coverage for the stable demo manifest."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from campusclaw.domain.models import Material, User
from campusclaw.domain.models import Session as SessionModel


@pytest.mark.integration
def test_demo_manifest_has_isolated_sessions_and_material_lists(
    postgres_api_fixture: Any,
) -> None:
    fixture = postgres_api_fixture
    with fixture.client() as alpha_client, fixture.client() as beta_client:
        alpha_login = alpha_client.post(
            "/api/auth/login",
            json={
                "account": "teacher.alpha",
                "password": fixture.passwords["alpha_teacher"],
            },
        )
        beta_login = beta_client.post(
            "/api/auth/login",
            json={
                "account": "student.beta",
                "password": fixture.passwords["beta_student"],
            },
        )

        assert alpha_login.status_code == beta_login.status_code == 200
        assert alpha_client.cookies.get(fixture.settings.SESSION_COOKIE_NAME)
        assert beta_client.cookies.get(fixture.settings.SESSION_COOKIE_NAME)
        assert alpha_client.cookies.get(
            fixture.settings.SESSION_COOKIE_NAME
        ) != beta_client.cookies.get(fixture.settings.SESSION_COOKIE_NAME)

        alpha_materials = alpha_client.get("/api/materials")
        beta_materials = beta_client.get("/api/materials")
        assert alpha_materials.status_code == beta_materials.status_code == 200
        assert [item["title"] for item in alpha_materials.json()] == ["Alpha welcome"]
        assert [item["title"] for item in beta_materials.json()] == ["Beta welcome"]

        alpha_material_id = alpha_materials.json()[0]["id"]
        cross_class = beta_client.get(f"/api/materials/{alpha_material_id}")
        assert cross_class.status_code == 404
        assert cross_class.json() == {
            "detail": {"code": "material_not_found", "message": "Material not found"}
        }


@pytest.mark.integration
def test_fixture_uses_temporary_storage_and_hashes_only(
    postgres_api_fixture: Any,
) -> None:
    fixture = postgres_api_fixture
    with fixture.database.transaction() as session:
        users = session.scalars(select(User)).all()
        assert {user.account for user in users} == {
            "teacher.alpha",
            "student.alpha",
            "teacher.beta",
            "student.beta",
        }
        for user in users:
            assert all(
                password not in user.password_hash for password in fixture.passwords.values()
            )

    material_files = [path for path in fixture.settings.UPLOAD_ROOT.rglob("*") if path.is_file()]
    assert len(material_files) == 2
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() for path in material_files)


@pytest.mark.integration
def test_adversarial_material_requests_leave_no_leaks_or_partial_files(
    postgres_api_fixture: Any,
) -> None:
    fixture = postgres_api_fixture
    with fixture.client() as student_client:
        student_login = student_client.post(
            "/api/auth/login",
            json={
                "account": "student.beta",
                "password": fixture.passwords["beta_student"],
            },
        )
        assert student_login.status_code == 200
        student_upload = student_client.post(
            "/api/materials",
            data={"title": "student attempt", "class_id": "10000000-0000-0000-0000-000000000001"},
            files={"file": ("student.txt", b"forbidden", "text/plain")},
        )
        assert student_upload.status_code == 403

    with fixture.client() as teacher_client:
        teacher_login = teacher_client.post(
            "/api/auth/login",
            json={
                "account": "teacher.alpha",
                "password": fixture.passwords["alpha_teacher"],
            },
        )
        assert teacher_login.status_code == 200
        csrf_headers = {
            "origin": "http://testserver",
            "x-csrf-token": teacher_login.json()["csrf_token"],
        }

        csrf_failure = teacher_client.post(
            "/api/materials",
            data={"title": "csrf failure"},
            files={"file": ("csrf.txt", b"blocked", "text/plain")},
        )
        assert csrf_failure.status_code == 403

        forged_class = teacher_client.post(
            "/api/materials",
            data={"title": "Forged class", "class_id": "10000000-0000-0000-0000-000000000002"},
            files={"file": ("../outside.txt", b"alpha only", "text/plain")},
            headers=csrf_headers,
        )
        assert forged_class.status_code == 201
        assert forged_class.json()["original_filename"] == "outside.txt"
        forged_id = forged_class.json()["id"]

        fixture.settings.UPLOAD_MAX_BYTES = 3
        oversized = teacher_client.post(
            "/api/materials",
            data={"title": "Too large"},
            files={"file": ("large.txt", b"1234", "text/plain")},
            headers=csrf_headers,
        )
        assert oversized.status_code == 413
        fixture.settings.UPLOAD_MAX_BYTES = 52_428_800

        alpha_materials = teacher_client.get("/api/materials")
        assert alpha_materials.status_code == 200
        assert forged_id in {item["id"] for item in alpha_materials.json()}
        alpha_material_id = alpha_materials.json()[0]["id"]

        with fixture.database.transaction() as session:
            expired = session.scalar(select(SessionModel).order_by(SessionModel.created_at.desc()))
            assert expired is not None
            expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            forged_material = session.get(Material, forged_id)
            assert forged_material is not None
            assert str(forged_material.class_id) == "10000000-0000-0000-0000-000000000001"

        expired_response = teacher_client.get("/api/materials")
        assert expired_response.status_code == 401

    with fixture.client() as beta_client:
        beta_login = beta_client.post(
            "/api/auth/login",
            json={
                "account": "student.beta",
                "password": fixture.passwords["beta_student"],
            },
        )
        assert beta_login.status_code == 200
        cross_class = beta_client.get(f"/api/materials/{forged_id}")
        missing = beta_client.get("/api/materials/30000000-0000-0000-0000-000000000099")
        assert cross_class.status_code == missing.status_code == 404
        assert cross_class.json() == missing.json()

    with fixture.client() as file_client:
        login = file_client.post(
            "/api/auth/login",
            json={
                "account": "teacher.alpha",
                "password": fixture.passwords["alpha_teacher"],
            },
        )
        assert login.status_code == 200
        material_path = (
            fixture.settings.UPLOAD_ROOT
            / "10000000-0000-0000-0000-000000000001"
            / alpha_material_id
        )
        material_path.unlink()
        unavailable = file_client.get(f"/api/materials/{alpha_material_id}/download")
        assert unavailable.status_code == 500
        assert b"Material file unavailable" in unavailable.content
        assert b"alpha only" not in unavailable.content

    temp_files = [path for path in (fixture.settings.UPLOAD_ROOT / "tmp").glob("*")]
    assert temp_files == []
