"""Stub contracts with all outbound sockets forbidden."""

from __future__ import annotations

import json
import socket
import unittest
from typing import Any, cast
from unittest.mock import patch

from fastapi.testclient import TestClient

from apitest.provider_stub import DIMENSION, FACTS, app


class StubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        blocker = patch.object(
            socket.socket, "connect", side_effect=AssertionError("external_egress")
        )
        blocker.start()
        self.addCleanup(blocker.stop)

    def complete(
        self, topic: str, *, chat: bool = True, model: str = "fixture-guidance"
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = [
            {"field": "current_question" if chat else "question", "value": topic + " 只要最终答案"},
        ]
        source = {"source_id": "S1", "text": FACTS["ALPHA_FERN"]}
        rows.append(
            {"field": "current_authorized_evidence", "sources": [source]}
            if chat
            else {"field": "untrusted_evidence", **source}
        )
        response = self.client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "user", "content": json.dumps(rows)},
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        return cast(dict[str, Any], json.loads(response.json()["choices"][0]["message"]["content"]))

    def test_health_and_deterministic_embeddings(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        body = {"model": "fixture-embedding", "input": list(FACTS.values())}
        first = self.client.post("/v1/embeddings", json=body)
        self.assertEqual(first.json(), self.client.post("/v1/embeddings", json=body).json())
        vectors = [row["embedding"] for row in first.json()["data"]]
        self.assertEqual(len(vectors[0]), DIMENSION)
        self.assertNotEqual(vectors[0], vectors[1])

    def test_guidance_and_legacy_json(self) -> None:
        chat = self.complete("ALPHA_FERN")
        self.assertEqual(chat["status"], "answered")
        self.assertEqual(chat["citation_ids"], ["S1"])
        self.assertEqual(chat["answer"], "\n".join(row["text"] for row in chat["guidance"]))
        self.assertEqual(chat["guidance"][-1]["kind"], "question")
        self.assertNotIn("final_answer", chat)
        self.assertNotIn("最终答案", chat["answer"])
        legacy = self.complete("ALPHA_FERN", chat=False)
        self.assertEqual(set(legacy), {"status", "answer", "citation_ids"})

    def test_cross_topic_and_explicit_refusal(self) -> None:
        for result in (
            self.complete("BETA_CRYSTAL"),
            self.complete("ALPHA_FERN", model="fixture-refusal"),
        ):
            self.assertEqual(
                result,
                {
                    "status": "insufficient_evidence",
                    "answer": "",
                    "guidance": [],
                    "citation_ids": [],
                },
            )

    def test_malformed_and_failure_fixtures(self) -> None:
        response = self.client.post(
            "/v1/chat/completions",
            json={
                "model": "fixture-malformed",
                "messages": [],
            },
        )
        self.assertEqual(response.status_code, 422)
        for model, status in (("fixture-malformed", 200), ("fixture-failure", 503)):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "[]"}],
                },
            )
            self.assertEqual(response.status_code, status)
            if status == 200:
                self.assertEqual(response.json()["choices"][0]["message"]["content"], "not-json")


if __name__ == "__main__":
    unittest.main()
