"""No network clients: deterministic, internal-only OpenAI-compatible fixtures."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

FACTS = {
    "ALPHA_FERN": "ALPHA_FERN 使用先观察叶脉再比较边缘的记录步骤。",
    "BETA_CRYSTAL": "BETA_CRYSTAL 使用先测量棱角再记录纹理的步骤。",
}
DIMENSION = 8
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    input: list[str] = Field(min_length=1, max_length=128)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[dict[str, str]] = Field(min_length=1, max_length=10)
    temperature: float = 0
    max_tokens: int = Field(default=1000, ge=1, le=10000)
    response_format: dict[str, str] | None = None


def vector(text: str) -> list[float]:
    # Disjoint one-hot class topics; unmatched text cannot retrieve those topics.
    values = [0.0] * DIMENSION
    for index, topic in enumerate(FACTS):
        if topic in text:
            values[index] = 1.0
    if not any(values):
        values[2 + hashlib.sha256(text.encode()).digest()[0] % (DIMENSION - 2)] = 1.0
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
async def controlled_mcp_failure(request: Request) -> Response:
    """Test-only protocol faults selected by deployment aliases, never question text."""
    host = request.headers.get("host", "").split(":")[0]
    if host not in {"mcp-invalid", "mcp-timeout"}:
        raise HTTPException(404, "fixture_not_found")
    if request.headers.get("authorization") != (
        "Bearer apitest-only-mcp-runtime-not-for-deployment"
    ):
        raise HTTPException(401, "fixture_unauthorized")
    if host == "mcp-timeout":
        await asyncio.sleep(4)
    payload: dict[str, Any] = await request.json()
    method = payload.get("method")
    if method == "notifications/initialized":
        return Response(status_code=202)
    result: dict[str, Any] = {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "controlled-fault", "version": "1"},
    }
    if method == "tools/list":
        result = {"tools": [{"name": "INVALID-NAME", "inputSchema": {"type": "object"}}]}
    return JSONResponse({"jsonrpc": "2.0", "id": payload.get("id"), "result": result})


@app.post("/v1/embeddings")
def embeddings(request: EmbeddingRequest) -> dict[str, Any]:
    if any(not item or len(item) > 8000 for item in request.input):
        raise HTTPException(400, "invalid_fixture_request")
    return {
        "object": "list",
        "model": request.model,
        "data": [
            {"object": "embedding", "index": index, "embedding": vector(text)}
            for index, text in enumerate(request.input)
        ],
    }


def generation(request: ChatRequest) -> str:
    content = next((row["content"] for row in request.messages if row.get("role") == "user"), "")
    # Only test fixture models select failures; untrusted question text cannot enable them.
    if request.model == "fixture-failure":
        raise HTTPException(503, "fixture_unavailable")
    if request.model == "fixture-malformed":
        return "not-json"
    payload: list[dict[str, Any]]
    try:
        decoded, _ = json.JSONDecoder().raw_decode(content)
        payload = cast(list[dict[str, Any]], decoded) if isinstance(decoded, list) else []
    except ValueError:
        payload = []
    sources: list[dict[str, str]] = []
    is_chat = False
    question = ""
    for row in payload:
        if row.get("field") == "current_authorized_evidence":
            sources.extend(row["sources"])
            is_chat = True
        if row.get("field") == "untrusted_evidence":
            sources.append(row)
        if row.get("field") in {"question", "current_question"}:
            question = row["value"]
    selected = next(
        (
            (topic, source)
            for topic in FACTS
            for source in sources
            if topic in source.get("text", "") and topic in question
        ),
        None,
    )
    refusal: dict[str, Any] = {"status": "insufficient_evidence", "answer": "", "citation_ids": []}
    if is_chat:
        refusal["guidance"] = []
    if selected is None or request.model == "fixture-refusal":
        return json.dumps(refusal, ensure_ascii=False)
    topic, source = selected
    source_id = source["source_id"]
    hint = f"请按材料中的观察步骤分别记录 {topic} 的特征 [{source_id}]"
    question_text = "你准备先记录哪一项特征？"
    output: dict[str, Any] = {
        "status": "answered",
        "answer": f"{FACTS[topic]} [{source_id}]",
        "citation_ids": [source_id],
    }
    if is_chat:
        output["guidance"] = [
            {"kind": "hint", "text": hint},
            {"kind": "question", "text": question_text},
        ]
        output["answer"] = hint + "\n" + question_text
    return json.dumps(output, ensure_ascii=False)


@app.post("/v1/chat/completions")
async def completions(request: ChatRequest) -> dict[str, Any]:
    # Test-only latency makes in-flight conflict acceptance reproducible over the gateway.
    # Selected by server model configuration, never by untrusted question text.
    if request.model == "fixture-delayed":
        await asyncio.sleep(2)
    return {
        "id": "synthetic-completion",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": generation(request)},
                "finish_reason": "stop",
            }
        ],
    }
