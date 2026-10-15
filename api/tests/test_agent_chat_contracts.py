"""Task 3/4 request contracts, independent of provider generation."""

import uuid

import pytest
from pydantic import ValidationError

from campusclaw.api.schemas import (
    AgentCatalogResponse,
    AgentCreateRequest,
    AgentUpdateRequest,
    ConversationCreateRequest,
    ConversationMessageRequest,
    DomainErrorResponse,
    SkillCreateRequest,
    SkillUpdateRequest,
)


@pytest.mark.parametrize("model", [AgentCreateRequest, AgentUpdateRequest])
@pytest.mark.parametrize(
    "field,value",
    [
        ("name", ""),
        ("name", " "),
        ("name", "x" * 121),
        ("description", "x" * 1001),
        ("system_prompt", ""),
        ("system_prompt", "\t"),
        ("system_prompt", "x" * 20001),
        ("skill_ids", [uuid.uuid4()] * 2),
        ("skill_ids", [uuid.uuid4() for _ in range(51)]),
        ("class_id", uuid.uuid4()),
        ("creator_id", uuid.uuid4()),
        ("state", "published"),
    ],
)
def test_agent_schemas_reject_invalid_fields(
    model: type[AgentCreateRequest], field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"name": "Tutor", "system_prompt": "Evidence only", field: value})


@pytest.mark.parametrize("model", [SkillCreateRequest, SkillUpdateRequest])
@pytest.mark.parametrize(
    "field,value",
    [
        ("name", " "),
        ("name", "x" * 121),
        ("instructions", ""),
        ("instructions", "\n"),
        ("instructions", "x" * 20001),
        ("skill_type", "tool"),
        ("creator_id", uuid.uuid4()),
        ("class_id", uuid.uuid4()),
    ],
)
def test_skill_schemas_reject_invalid_fields(
    model: type[SkillCreateRequest], field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "name": "Guide",
                "skill_type": "solution_guidance",
                "instructions": "Hints",
                field: value,
            }
        )


@pytest.mark.parametrize(
    "field",
    [
        "history",
        "messages",
        "class_id",
        "student_id",
        "creator_id",
        "system_prompt",
        "assistant_content",
        "citations",
        "agent_id",
    ],
)
def test_current_message_does_not_accept_fabricated_state(field: str) -> None:
    with pytest.raises(ValidationError):
        ConversationMessageRequest.model_validate({"content": "Question", field: "private"})


@pytest.mark.parametrize("field", ["class_id", "student_id", "history", "prompt", "citations"])
def test_conversation_creation_accepts_only_agent(field: str) -> None:
    with pytest.raises(ValidationError):
        ConversationCreateRequest.model_validate({"agent_id": uuid.uuid4(), field: "private"})


@pytest.mark.parametrize("value", ["", " ", "x" * 20001])
def test_message_bounds(value: str) -> None:
    with pytest.raises(ValidationError):
        ConversationMessageRequest(content=value)


def test_catalog_and_safe_errors_are_strict() -> None:
    catalog = {"id": uuid.uuid4(), "name": "Tutor", "description": None}
    assert set(AgentCatalogResponse.model_validate(catalog).model_dump()) == set(catalog)
    for private in ("system_prompt", "instructions", "skill_ids", "creator_id", "class_id"):
        with pytest.raises(ValidationError):
            AgentCatalogResponse.model_validate({**catalog, private: "private"})
    error = DomainErrorResponse.model_validate(
        {"detail": {"code": "invalid_request", "message": "Invalid request"}}
    )
    assert error.detail.code == "invalid_request"
