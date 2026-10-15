"""Client support tests; errors must never echo remote content."""

from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any
from unittest.mock import patch

import httpx

from ..clients import (
    Client,
    Fixtures,
    Observer,
    UnsafeTarget,
    parse_sse,
    parse_sse_chunks,
    validate_database_target,
)

IDS = {
    "conversation_id": "10000000-0000-0000-0000-000000000001",
    "user_message_id": "10000000-0000-0000-0000-000000000002",
    "assistant_message_id": "10000000-0000-0000-0000-000000000003",
}
REVISION = {
    "configuration_revision_id": "10000000-0000-0000-0000-000000000004",
    "configuration_updated": False,
}


def stream() -> list[tuple[str, dict[str, Any]]]:
    answer = "根据本班资料无法回答该问题"
    return [
        ("message.started", {**REVISION}),
        ("answer.delta", {"delta": answer}),
        (
            "message.completed",
            {
                **REVISION,
                "status": "insufficient_evidence",
                "answer_length": len(answer),
                "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
                "requested_mode": "hybrid",
                "retrieval_mode": "keyword",
                "completed_at": "2026-10-15T00:00:00Z",
            },
        ),
    ]


def encode(rows: list[tuple[str, dict[str, Any]]]) -> bytes:
    return (
        ": heartbeat\n\n"
        + "".join(
            f"event: {name}\n"
            f"data: {json.dumps({**IDS, 'sequence': index, **body}, ensure_ascii=False)}\n\n"
            for index, (name, body) in enumerate(rows, 1)
        )
    ).encode()


class ClientTests(unittest.TestCase):
    def test_database_target_allowlist(self) -> None:
        validate_database_target("postgresql://apitest_reader:synthetic@db:5432/campusclaw_apitest")
        for target in (
            "postgresql://apitest_reader:SECRET@localhost/campusclaw_apitest",
            "postgresql://apitest_reader:SECRET@db/campusclaw",
            "postgresql://postgres:SECRET@db/campusclaw_apitest",
            "postgresql://apitest_reader:SECRET@db/campusclaw_apitest?host=prod",
            "postgresql://apitest_reader:SECRET@db:bad/campusclaw_apitest",
            "postgresql://apitest_reader:SECRET@prod/campusclaw_apitest",
        ):
            with self.subTest(target=target), self.assertRaises(UnsafeTarget) as error:
                validate_database_target(target)
            self.assertNotIn("SECRET", str(error.exception))
        with patch("psycopg.Connection.connect", side_effect=RuntimeError("SECRET")):
            with self.assertRaises(UnsafeTarget) as error:
                Observer("postgresql://apitest_reader:SECRET@db/campusclaw_apitest")
            self.assertNotIn("SECRET", str(error.exception))

    def test_http_target_guards_and_transport_redaction(self) -> None:
        for target in (
            "https://example.com",
            "http://api:8000",
            "http://gateway:8080/?token=SECRET",
        ):
            with self.assertRaises(UnsafeTarget):
                Client(target)
        client = Client("http://gateway:8080")
        self.addCleanup(client.close)
        for path in ("https://example.com", "//example.com", "/api/../secret"):
            with self.assertRaises(UnsafeTarget):
                client.request("GET", path)
        with (
            patch.object(client.http, "request", side_effect=RuntimeError("Bearer SECRET")),
            self.assertRaisesRegex(ValueError, "^http_request_failed$"),
        ):
            client.request("GET", "/api/auth/me", token="SECRET")

    def test_json_login_helpers_with_no_secret_echo(self) -> None:
        client = Client("http://gateway:8080")
        self.addCleanup(client.close)

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "gateway")
            return httpx.Response(200, json={"access_token": "SECRET"})

        client.http.close()
        client.http = httpx.Client(
            base_url="http://gateway:8080", transport=httpx.MockTransport(handler)
        )
        self.assertEqual(client.login("synthetic", "password"), "SECRET")
        with (
            patch.object(client, "request", return_value=httpx.Response(400, text="SECRET")),
            self.assertRaisesRegex(ValueError, "^json_contract_failed$"),
        ):
            client.json("GET", "/api/auth/me")

    def test_run_scoped_fixture_names(self) -> None:
        first, second = Fixtures.create(), Fixtures.create()
        self.assertNotEqual(first.name("skill"), second.name("skill"))
        self.assertEqual(first.name("skill"), first.name("skill"))

    def test_sse_unicode_heartbeat_and_failure(self) -> None:
        raw = encode(stream())
        events = parse_sse(raw)
        self.assertEqual(parse_sse_chunks(bytes([byte]) for byte in raw), events)
        self.assertEqual(len(events), 3)
        events = parse_sse(
            encode(
                [
                    stream()[0],
                    ("message.error", {"code": "generation_failed", "retryable": True}),
                ]
            )
        )
        self.assertEqual(events[-1]["event"], "message.error")

    def test_sse_rejects_interruption_sequence_identity_order_digest_and_secrets(self) -> None:
        variants = [encode(stream())[:-1], b"data: SECRET\n\n", b"\xff\n\n"]
        for key, value in (
            ("sequence", 9),
            ("conversation_id", "bad"),
            ("answer_sha256", "SECRET"),
            ("hidden_prompt", "SECRET"),
        ):
            rows = stream()
            rows[-1][1][key] = value
            variants.append(encode(rows))
        variants.extend(
            [
                encode(stream() + [stream()[-1]]),
                encode([stream()[1], stream()[0], stream()[-1]]),
                encode([stream()[0], ("message.error", {"code": "SECRET", "retryable": True})]),
                encode(stream()[:-1]),
            ]
        )
        for raw in variants:
            with (
                self.subTest(size=len(raw)),
                self.assertRaisesRegex(ValueError, "^sse_contract_failed$"),
            ):
                parse_sse(raw)


if __name__ == "__main__":
    unittest.main()
