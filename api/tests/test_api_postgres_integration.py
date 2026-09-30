# pyright: basic, reportMissingImports=false, reportMissingTypeStubs=false
"""PostgreSQL-backed API integration coverage for the stable demo manifest."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from campusclaw.domain.models import User


def authorization(login: Any) -> dict[str, str]:
    return {"authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.integration
def test_demo_manifest_has_isolated_bearer_tokens_and_material_lists(
    postgres_api_fixture: Any,
) -> None:
    fixture = postgres_api_fixture
    with fixture.client() as alpha_client, fixture.client() as beta_client:
        alpha_login = alpha_client.post(
            "/api/auth/login",
            json={"account": "teacher.alpha", "password": fixture.passwords["alpha_teacher"]},
        )
        beta_login = beta_client.post(
            "/api/auth/login",
            json={"account": "student.beta", "password": fixture.passwords["beta_student"]},
        )
        assert alpha_login.status_code == beta_login.status_code == 200
        assert alpha_login.json()["access_token"] != beta_login.json()["access_token"]
        assert "set-cookie" not in alpha_login.headers
        alpha_materials = alpha_client.get("/api/materials", headers=authorization(alpha_login))
        beta_materials = beta_client.get("/api/materials", headers=authorization(beta_login))
        assert [item["title"] for item in alpha_materials.json()] == ["Alpha welcome"]
        assert [item["title"] for item in beta_materials.json()] == ["Beta welcome"]
        cross_class = beta_client.get(
            f"/api/materials/{alpha_materials.json()[0]['id']}", headers=authorization(beta_login)
        )
        assert cross_class.status_code == 404


@pytest.mark.integration
def test_fixture_uses_temporary_storage_and_password_hashes_only(postgres_api_fixture: Any) -> None:
    fixture = postgres_api_fixture
    with fixture.database.transaction() as session:
        users = session.scalars(select(User)).all()
        assert {user.account for user in users} == {
            "teacher.alpha",
            "student.alpha",
            "teacher.beta",
            "student.beta",
        }
        assert all(
            password not in user.password_hash
            for user in users
            for password in fixture.passwords.values()
        )
    material_files = [path for path in fixture.settings.UPLOAD_ROOT.rglob("*") if path.is_file()]
    assert len(material_files) == 2
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() for path in material_files)


@pytest.mark.integration
def test_adversarial_bearer_material_requests_leave_no_leaks_or_partial_files(
    postgres_api_fixture: Any,
) -> None:
    fixture = postgres_api_fixture
    with fixture.client() as client:
        assert (
            client.get("/api/materials", headers={"authorization": "Bearer malformed"}).status_code
            == 401
        )
        teacher_login = client.post(
            "/api/auth/login",
            json={"account": "teacher.alpha", "password": fixture.passwords["alpha_teacher"]},
        )
        assert teacher_login.status_code == 200
        headers = authorization(teacher_login)
        forged_class = client.post(
            "/api/materials",
            data={"title": "Forged class", "class_id": "10000000-0000-0000-0000-000000000002"},
            files={"file": ("../outside.txt", b"alpha only", "text/plain")},
            headers=headers,
        )
        assert forged_class.status_code == 201
        assert forged_class.json()["original_filename"] == "outside.txt"
        fixture.settings.UPLOAD_MAX_BYTES = 3
        oversized = client.post(
            "/api/materials",
            data={"title": "Too large"},
            files={"file": ("large.txt", b"1234")},
            headers=headers,
        )
        assert oversized.status_code == 413
        fixture.settings.UPLOAD_MAX_BYTES = 52_428_800
        token_service = fixture.app.state.token_service
        expired = token_service.issue(
            teacher_login.json()["user_id"], now=datetime.now(UTC) - timedelta(days=1)
        ).token
        assert (
            client.get("/api/materials", headers={"authorization": f"Bearer {expired}"}).status_code
            == 401
        )
    with fixture.client() as student_client:
        student_login = student_client.post(
            "/api/auth/login",
            json={"account": "student.beta", "password": fixture.passwords["beta_student"]},
        )
        assert (
            student_client.post(
                "/api/materials",
                data={"title": "student attempt"},
                files={"file": ("student.txt", b"forbidden", "text/plain")},
                headers=authorization(student_login),
            ).status_code
            == 403
        )
