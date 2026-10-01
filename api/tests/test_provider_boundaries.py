from pathlib import Path

import httpx
import pytest

from campusclaw.application.providers import EmbeddingClient, GenerationClient, ProviderFailure
from campusclaw.config import Settings

BASE = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+psycopg://test:test@db/test",
    "JWT_SIGNING_KEY": "p" * 32,
    "UPLOAD_ROOT": Path("/tmp/campusclaw-provider-test"),
}


def test_embedding_adapter_accepts_openai_shape_and_bounds_dimension() -> None:
    settings = Settings.model_validate(
        BASE | {"EMBEDDING_ENDPOINT": "http://embedding.internal/v1", "EMBEDDING_DIMENSION": 2}
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        )
    )
    assert EmbeddingClient(settings, client).embed_one("bounded text") == [0.1, 0.2]


def test_generation_provider_errors_are_safe_and_do_not_echo_response_body() -> None:
    settings = Settings.model_validate(
        BASE | {"GENERATION_ENDPOINT": "http://generation.internal/v1"}
    )
    sentinel = "provider-secret-body"
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text=sentinel))
    )
    with pytest.raises(ProviderFailure) as caught:
        GenerationClient(settings, client).complete(system_prompt="policy", user_payload="evidence")
    assert caught.value.code == "generation_unavailable"
    assert sentinel not in str(caught.value)


def test_missing_endpoint_fails_closed_without_network() -> None:
    settings = Settings.model_validate(BASE)
    with pytest.raises(ProviderFailure, match="embedding_unavailable"):
        EmbeddingClient(settings).embed_one("question")
    with pytest.raises(ProviderFailure, match="generation_unavailable"):
        GenerationClient(settings).complete(system_prompt="policy", user_payload="evidence")


def test_embedding_adapter_rejects_bad_requests_and_responses() -> None:
    settings = Settings.model_validate(
        BASE | {"EMBEDDING_ENDPOINT": "http://embedding.internal/v1", "EMBEDDING_DIMENSION": 2}
    )
    with pytest.raises(ProviderFailure, match="embedding_request_bounds"):
        EmbeddingClient(settings).embed([])
    with pytest.raises(ProviderFailure, match="embedding_request_bounds"):
        EmbeddingClient(settings).embed(["x" * 8_001])

    rejected = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(400, request=request))
    )
    with pytest.raises(ProviderFailure) as caught:
        EmbeddingClient(settings, rejected).embed_one("question")
    assert caught.value.code == "embedding_rejected"
    assert not caught.value.retryable

    malformed = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, request=request, json={"data": [{}]})
        )
    )
    with pytest.raises(ProviderFailure, match="embedding_malformed"):
        EmbeddingClient(settings, malformed).embed_one("question")

    wrong_dimension = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, request=request, json={"data": [{"embedding": [0.1]}]}
            )
        )
    )
    with pytest.raises(ProviderFailure, match="embedding_dimension_mismatch"):
        EmbeddingClient(settings, wrong_dimension).embed_one("question")


def test_provider_timeouts_are_sanitized() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("sentinel-secret", request=request)

    transport = httpx.MockTransport(timeout)
    embedding = Settings.model_validate(BASE | {"EMBEDDING_ENDPOINT": "http://embed/v1"})
    with pytest.raises(ProviderFailure) as caught:
        EmbeddingClient(embedding, httpx.Client(transport=transport)).embed_one("question")
    assert caught.value.code == "embedding_timeout"
    assert "sentinel" not in str(caught.value)

    generation = Settings.model_validate(BASE | {"GENERATION_ENDPOINT": "http://chat/v1"})
    with pytest.raises(ProviderFailure) as caught:
        GenerationClient(generation, httpx.Client(transport=transport)).complete(
            system_prompt="policy", user_payload="evidence"
        )
    assert caught.value.code == "generation_timeout"
    assert "sentinel" not in str(caught.value)


def test_generation_adapter_accepts_json_and_rejects_invalid_shapes() -> None:
    settings = Settings.model_validate(BASE | {"GENERATION_ENDPOINT": "http://chat/v1"})

    def success(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert b'"response_format"' in request.content
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": '{"status":"answered"}'}}]},
        )

    client = GenerationClient(settings, httpx.Client(transport=httpx.MockTransport(success)))
    assert client.complete(system_prompt="policy", user_payload="evidence").startswith("{")

    with pytest.raises(ProviderFailure, match="generation_request_bounds"):
        client.complete(system_prompt="x" * 8_001, user_payload="evidence")

    rejected = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(422, request=request))
    )
    with pytest.raises(ProviderFailure) as caught:
        GenerationClient(settings, rejected).complete(
            system_prompt="policy", user_payload="evidence"
        )
    assert caught.value.code == "generation_rejected"
    assert not caught.value.retryable

    malformed = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, request=request, json={"choices": [{"message": {"content": 42}}]}
            )
        )
    )
    with pytest.raises(ProviderFailure, match="generation_malformed"):
        GenerationClient(settings, malformed).complete(
            system_prompt="policy", user_payload="evidence"
        )
