import json
import uuid

import pytest

from campusclaw.application.generation import (
    EvidenceItem,
    InvalidGenerationOutput,
    ParsedAnswer,
    parse_model_output,
    serialize_user_payload,
)
from campusclaw.domain.models import KnowledgeChunk, Material


def evidence() -> list[EvidenceItem]:
    material = Material(
        id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        uploader_id=uuid.uuid4(),
        title="课程",
        original_filename="lesson.txt",
        content_type="text/plain",
        byte_size=4,
        sha256="a" * 64,
        storage_key="safe/file",
        state="ready",
    )
    chunk = KnowledgeChunk(
        id=uuid.uuid4(),
        index_version_id=uuid.uuid4(),
        material_id=material.id,
        class_id=material.class_id,
        ordinal=0,
        text="课程内容",
        normalized_text="课程内容",
        text_hash="b" * 64,
        line_start=1,
        line_end=1,
    )
    return [EvidenceItem("S1", chunk, material)]


def test_structured_answer_requires_known_citation_and_no_extra_fields() -> None:
    parsed = parse_model_output(
        json.dumps({"status": "answered", "answer": "课程内容 [S1]", "citation_ids": ["S1"]}),
        evidence(),
        max_chars=1000,
    )
    assert isinstance(parsed, ParsedAnswer)
    assert parsed.citation_ids == ["S1"]
    with pytest.raises(InvalidGenerationOutput):
        parse_model_output(
            json.dumps({"status": "answered", "answer": "课程内容", "citation_ids": ["S9"]}),
            evidence(),
            max_chars=1000,
        )
    with pytest.raises(InvalidGenerationOutput):
        parse_model_output(
            json.dumps(
                {
                    "status": "answered",
                    "answer": "课程内容 [S1]",
                    "citation_ids": ["S1"],
                    "reasoning": "secret",
                }
            ),
            evidence(),
            max_chars=1000,
        )


def test_insufficient_output_is_normalized_and_payload_contains_no_class_or_path() -> None:
    assert (
        parse_model_output(
            '{"status":"insufficient_evidence","answer":"","citation_ids":[]}',
            evidence(),
            max_chars=1000,
        ).status
        == "insufficient_evidence"
    )
    payload = serialize_user_payload("问题", evidence())
    assert "class_id" not in payload
    assert "storage_key" not in payload
    assert "课程内容" in payload
