"""Private/approved-external OpenAI-compatible adapters with redacted failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from campusclaw.config import Settings


@dataclass(frozen=True)
class ProviderFailure(RuntimeError):
    code: str
    retryable: bool = True

    def __str__(self) -> str:
        return self.code


def _url(endpoint: str, suffix: str) -> str:
    base = endpoint.rstrip("/")
    return base if base.endswith(suffix) else f"{base}{suffix}"


def _headers(api_key: Any | None) -> dict[str, str]:
    if api_key is None:
        return {"content-type": "application/json"}
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {api_key.get_secret_value()}",
    }


class EmbeddingClient:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.http = http_client or httpx.Client()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text or len(text) > 8_000 for text in texts):
            raise ProviderFailure("embedding_request_bounds", retryable=False)
        endpoint = self.settings.EMBEDDING_ENDPOINT
        if endpoint is None:
            raise ProviderFailure("embedding_unavailable")
        try:
            response = self.http.post(
                _url(endpoint, "/embeddings"),
                headers=_headers(self.settings.EMBEDDING_API_KEY),
                json={"model": self.settings.EMBEDDING_MODEL, "input": texts},
                timeout=self.settings.EMBEDDING_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as exc:
            raise ProviderFailure("embedding_timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderFailure("embedding_unavailable") from exc
        if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
            raise ProviderFailure("embedding_unavailable")
        if response.status_code >= 400:
            raise ProviderFailure("embedding_rejected", retryable=False)
        try:
            body = response.json()
            rows = body["data"]
            vectors = [list(map(float, row["embedding"])) for row in rows]
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderFailure("embedding_malformed", retryable=False) from exc
        if len(vectors) != len(texts) or any(
            len(vector) != self.settings.EMBEDDING_DIMENSION for vector in vectors
        ):
            raise ProviderFailure("embedding_dimension_mismatch", retryable=False)
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class GenerationClient:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.http = http_client or httpx.Client()

    def complete(self, *, system_prompt: str, user_payload: str) -> str:
        if len(system_prompt) > 8_000 or len(user_payload) > (
            self.settings.GENERATION_EVIDENCE_CHAR_BUDGET + 4_000
        ):
            raise ProviderFailure("generation_request_bounds", retryable=False)
        endpoint = self.settings.GENERATION_ENDPOINT
        if endpoint is None:
            raise ProviderFailure("generation_unavailable")
        body: dict[str, Any] = {
            "model": self.settings.GENERATION_MODEL,
            "temperature": self.settings.GENERATION_TEMPERATURE,
            "max_tokens": self.settings.GENERATION_MAX_OUTPUT_TOKENS,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
        }
        if self.settings.GENERATION_STRUCTURED_OUTPUT:
            body["response_format"] = {"type": "json_object"}
        try:
            response = self.http.post(
                _url(endpoint, "/chat/completions"),
                headers=_headers(self.settings.GENERATION_API_KEY),
                json=body,
                timeout=self.settings.GENERATION_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as exc:
            raise ProviderFailure("generation_timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderFailure("generation_unavailable") from exc
        if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
            raise ProviderFailure("generation_unavailable")
        if response.status_code >= 400:
            raise ProviderFailure("generation_rejected", retryable=False)
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or len(content) > (
                self.settings.GENERATION_MAX_OUTPUT_TOKENS * 8
            ):
                raise ValueError
            return content
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderFailure("generation_malformed", retryable=False) from exc
