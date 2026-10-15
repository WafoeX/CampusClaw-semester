"""OpenAPI is a generated static contract, not a dump of runtime state."""

import base64
import hashlib
import json
import re
from importlib.resources import files
from typing import Any, cast
from urllib.parse import unquote_to_bytes

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from campusclaw.api.schemas import DomainErrorResponse, SafeValidationErrorResponse
from campusclaw.api.sse import EVENT_MODELS
from campusclaw.application.chat import CHAT_PLATFORM_POLICY
from campusclaw.main import create_app
from campusclaw.persistence.database import Database
from tests.test_chat_streaming import seed_evidence
from tests.test_conversation_api import auth, create_published_agent

pytest_plugins = ("tests.test_conversation_api",)


def test_vendored_assets_match_upstream_hashes_and_csp_images_are_exact_decodings() -> None:
    root = files("campusclaw.swagger_assets")
    expected = {
        "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        "swagger-ui.css": "40170f0ee859d17f92131ba707329a88a070e4f66874d11365e9a77d232f6117",
        "swagger-ui-bundle.js": "c2e4a9ef08144839ff47c14202063ecfe4e59e70a4e7154a26bd50d880c88ba1",
    }
    for name, digest in expected.items():
        assert hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest() == digest
    css = root.joinpath("swagger-ui.css").read_text()
    overrides = root.joinpath("local.css").read_text()
    rules = [rule for rule in css.split("}") if "data:" in rule]
    assert len(rules) == 8
    for index, rule in enumerate(rules):
        match = re.search(r"url\((.*?)\)", rule)
        assert match is not None
        mime, data = match.group(1).strip("\"'").split(",", 1)
        decoded = base64.b64decode(data) if ";base64" in mime else unquote_to_bytes(data)
        extension = "png" if "image/png" in mime else "svg"
        name = f"csp-image-{index}.{extension}"
        assert root.joinpath(name).read_bytes() == decoded
        assert rule[: rule.index("{")] in overrides and name in overrides


def test_all_operations_security_input_output_errors_and_references() -> None:
    app = create_app()
    document = app.openapi()
    assert document["openapi"].startswith("3.1")
    assert document["components"]["securitySchemes"] == {
        "BearerJWT": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
    }
    public = {"/health", "/api/auth/login", "/api/auth/logout", "/api/docs", "/api/openapi.json"}
    operation_ids: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        for method in route.methods:
            operation = document["paths"][route.path][method.lower()]
            assert operation["summary"] and operation["tags"]
            operation_ids.append(operation["operationId"])
            assert operation["security"] == ([] if route.path in public else [{"BearerJWT": []}])
            success = operation["responses"][str(route.status_code or 200)]
            if route.path != "/api/auth/logout":
                assert success["content"]
            if route.path not in public:
                assert "401" in operation["responses"]
            if route.path.startswith(("/api/agents", "/api/skills", "/api/conversations")):
                assert {"400", "401", "403", "404", "409"} <= operation["responses"].keys()
                assert "422" not in operation["responses"]
            if route.body_field is not None:
                assert operation["requestBody"]["content"]
    assert len(operation_ids) == len(set(operation_ids))
    for path in ("/api/knowledge/query", "/api/materials"):
        assert document["paths"][path]["post"]["requestBody"]["required"] is True
    download = document["paths"]["/api/materials/{material_id}/download"]["get"]
    assert "application/octet-stream" in download["responses"]["200"]["content"]
    assert {"401", "403", "404", "500"} <= download["responses"].keys()
    assert {"400", "401", "403", "503"} <= document["paths"]["/api/knowledge/query"]["post"][
        "responses"
    ].keys()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in cast(dict[str, Any], value).items():
                if key == "$ref":
                    assert item.startswith("#/")
                    resolved: Any = document
                    for part in item[2:].split("/"):
                        resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in cast(list[object], value):
                walk(item)

    walk(document)


def test_sse_contract_declares_all_serializer_models_and_temporal_rules() -> None:
    document = create_app().openapi()
    operation = document["paths"]["/api/conversations/{conversation_id}/messages"]["post"]
    media = operation["responses"]["200"]["content"]
    assert set(media) == {"text/event-stream"}
    assert set(media["text/event-stream"]["x-event-schemas"]) == set(EVENT_MODELS)
    for name, model in EVENT_MODELS.items():
        reference = media["text/event-stream"]["x-event-schemas"][name]["$ref"]
        schema = document["components"]["schemas"][reference.split("/")[-1]]
        assert set(schema["properties"]) == set(model.model_fields)
        assert {"sequence", "conversation_id", "user_message_id", "assistant_message_id"} <= set(
            schema["required"]
        )
        assert schema["additionalProperties"] is False
    assert {"400", "401", "403", "404", "409", "413", "429", "503"} <= operation["responses"].keys()
    for text in (
        "exactly one message.started",
        "message.error",
        "JSON errors",
        "Disconnect",
        "persisted",
        "starting at 1",
        "never raw provider tokens",
    ):
        assert text in operation["description"]


def test_public_swagger_is_same_origin_without_inline_script_or_cdn(
    conversation_api: tuple[TestClient, Database, dict[str, str]],
) -> None:
    client, _, _ = conversation_api
    response = client.get("/api/docs")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    assert "SwaggerUIBundle" in client.get("/api/docs/init.js").text
    assert "persistAuthorization: false" in client.get("/api/docs/init.js").text
    assert not re.search(r"<script[^>]*>\s*[^<\s]", response.text)
    for url in re.findall(r'(?:src|href)="([^"]+)"', response.text):
        assert url.startswith("/api/docs/")
        asset = client.get(url)
        assert asset.status_code == 200 and asset.content
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_documentation_never_serializes_runtime_secrets_or_private_database_content(
    conversation_api: tuple[TestClient, Database, dict[str, str]],
) -> None:
    client, database, tokens = conversation_api
    teacher_headers = auth(tokens["teacher"])
    agent_id = create_published_agent(client, tokens["teacher"])
    student_sentinel = "PRIVATE_STUDENT_MESSAGE_SENTINEL_50121"
    conversation = client.post(
        "/api/conversations", headers=auth(tokens["student"]), json={"agent_id": agent_id}
    ).json()["id"]
    assert (
        client.post(
            f"/api/conversations/{conversation}/messages",
            headers=auth(tokens["student"]),
            json={"content": student_sentinel},
        ).status_code
        == 200
    )
    seed_evidence(client, database, tokens)
    sentinel = "PRIVATE_TEACHER_PROMPT_SENTINEL_89172"
    agent = client.get(f"/api/agents/{agent_id}", headers=teacher_headers).json()
    client.patch(
        f"/api/agents/{agent_id}",
        headers=teacher_headers,
        json={
            "name": "Tutor",
            "description": None,
            "system_prompt": sentinel,
            "skill_ids": agent["skill_ids"],
        },
    )
    skill_sentinel = "PRIVATE_SKILL_INSTRUCTIONS_SENTINEL_77521"
    assert (
        client.patch(
            f"/api/skills/{agent['skill_ids'][0]}",
            headers=teacher_headers,
            json={
                "name": "Guide",
                "skill_type": "solution_guidance",
                "instructions": skill_sentinel,
            },
        ).status_code
        == 200
    )
    settings = cast(FastAPI, client.app).state.settings
    settings.GENERATION_API_KEY = SecretStr("PRIVATE_MODEL_KEY_SENTINEL_44213")
    settings.DATABASE_URL = "postgresql+psycopg://PRIVATE_DB_PASSWORD@internal/db"
    document = client.get("/api/openapi.json").text
    assets = "".join(
        client.get(url).text
        for url in (
            "/api/docs",
            "/api/docs/init.js",
            "/api/docs/assets/swagger-ui-bundle.js",
            "/api/docs/assets/swagger-ui.css",
            "/api/docs/assets/local.css",
        )
    )
    for secret in (
        *tokens.values(),
        sentinel,
        student_sentinel,
        skill_sentinel,
        "PRIVATE_DB_PASSWORD",
        "PRIVATE_MODEL_KEY_SENTINEL_44213",
        CHAT_PLATFORM_POLICY,
        "课程主题：检查已知条件。",
        settings.JWT_SIGNING_KEY.get_secret_value(),
        "Use hints.",
        "Use evidence.",
        "根据本班资料无法回答该问题",
    ):
        assert secret not in document + assets
    for forbidden in ("password_hash", "storage_key", "GENERATION_API_KEY", "DATABASE_URL"):
        assert forbidden not in document
    assert "SafeValidationErrorResponse" in json.loads(document)["components"]["schemas"]
    assert "HTTPValidationError" not in json.loads(document)["components"]["schemas"]


def test_actual_auth_and_domain_errors_match_documented_safe_shape(
    conversation_api: tuple[TestClient, Database, dict[str, str]],
) -> None:
    client, _, tokens = conversation_api
    expected = {"detail": {"code": "unauthenticated", "message": "Authentication required"}}
    for header in (None, "Basic invalid", "Bearer", "Bearer a b", "Bearer invalid"):
        response = client.get(
            "/api/auth/me", headers={} if header is None else {"Authorization": header}
        )
        assert response.status_code == 401 and response.json() == expected
        DomainErrorResponse.model_validate(response.json())
    for invalid_body in (
        {"account": "x", "password": {"secret": "PRIVATE_PASSWORD_SENTINEL"}},
        {"account": "x" * 121, "password": "PRIVATE_PASSWORD_SENTINEL"},
    ):
        invalid_login = client.post("/api/auth/login", json=invalid_body)
        assert (
            invalid_login.status_code == 422
            and "PRIVATE_PASSWORD_SENTINEL" not in invalid_login.text
        )
        SafeValidationErrorResponse.model_validate(invalid_login.json())
    me = client.get("/api/auth/me", headers={"Authorization": f"  bEaReR\t{tokens['student']}  "})
    assert me.status_code == 200 and me.json()["role"] == "student"
    invalid = client.post(
        "/api/agents", headers=auth(tokens["teacher"]), json={"secret": "DO_NOT_ECHO"}
    )
    assert invalid.status_code == 400 and "DO_NOT_ECHO" not in invalid.text
    DomainErrorResponse.model_validate(invalid.json())
