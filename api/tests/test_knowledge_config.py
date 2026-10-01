from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from campusclaw.api.schemas import QuestionRequest
from campusclaw.config import Settings

BASE: dict[str, object] = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+psycopg://test:test@db/test",
    "JWT_SIGNING_KEY": "k" * 32,
    "UPLOAD_ROOT": Path("/tmp/campusclaw-test"),
}


def test_embedding_and_generation_settings_are_independent_and_secret() -> None:
    settings = Settings.model_validate(
        BASE
        | {
            "EMBEDDING_ENDPOINT": "http://embedding.internal/v1",
            "EMBEDDING_API_KEY": SecretStr("embedding-secret"),
            "GENERATION_ENDPOINT": "http://generation.internal/v1",
            "GENERATION_API_KEY": SecretStr("generation-secret"),
        }
    )
    assert settings.EMBEDDING_ENDPOINT != settings.GENERATION_ENDPOINT
    assert "embedding-secret" not in repr(settings)
    assert "generation-secret" not in repr(settings)


def test_approved_external_provider_requires_https_and_key() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings.model_validate(
            BASE
            | {
                "EMBEDDING_ENDPOINT": "http://public.example",
                "EMBEDDING_DATA_BOUNDARY": "approved_external",
            }
        )
    with pytest.raises(ValidationError, match="API_KEY"):
        Settings.model_validate(
            BASE
            | {
                "EMBEDDING_ENDPOINT": "https://public.example",
                "EMBEDDING_DATA_BOUNDARY": "approved_external",
            }
        )


def test_question_defaults_to_hybrid_and_rejects_class_scope() -> None:
    assert QuestionRequest(question="课程内容").mode == "hybrid"
    with pytest.raises(ValidationError):
        QuestionRequest.model_validate({"question": "课程内容", "class_id": "forged"})
