"""Single-turn, class-scoped grounded knowledge endpoint."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal, get_db, require_supported_role
from campusclaw.api.schemas import CitationSource, KnowledgeAnswerResponse, QuestionRequest
from campusclaw.application.generation import (
    REFUSAL_ANSWER,
    GroundedAnswerService,
    InvalidGenerationOutput,
    source_response,
)
from campusclaw.application.providers import ProviderFailure
from campusclaw.application.retrieval import RetrievalService, VectorModeUnavailable
from campusclaw.config import Settings

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "invalid_question", "message": message},
    )


@router.post("/query", response_model=KnowledgeAnswerResponse)
async def query_knowledge(
    request: Request,
    principal: Annotated[Principal, Depends(require_supported_role)],
    database: Annotated[Session, Depends(get_db)],
) -> KnowledgeAnswerResponse:
    try:
        raw: Any = await request.json()
        payload = QuestionRequest.model_validate(raw)
    except (ValueError, ValidationError):
        raise _bad_request("Invalid knowledge question") from None
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise HTTPException(status_code=503, detail={"code": "not_ready", "message": "Unavailable"})
    try:
        retrieval = RetrievalService(settings).retrieve(
            database,
            class_id=principal.class_id,
            question=payload.question,
            mode=payload.mode,
            result_limit=payload.result_limit,
        )
    except ValueError as exc:
        raise _bad_request("Invalid knowledge question") from exc
    except VectorModeUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "vector_unavailable", "message": "Semantic retrieval unavailable"},
        ) from None

    try:
        parsed, evidence = GroundedAnswerService(settings).answer(
            database,
            class_id=principal.class_id,
            question=payload.question,
            retrieval=retrieval,
        )
    except ProviderFailure:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "answer_generation_unavailable",
                "message": "Answer generation is temporarily unavailable",
                "retryable": True,
            },
        ) from None
    except InvalidGenerationOutput:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "generation_invalid",
                "message": "Answer generation returned an invalid result",
                "retryable": True,
            },
        ) from None

    if parsed.status == "insufficient_evidence":
        return KnowledgeAnswerResponse(
            status="insufficient_evidence",
            answer=REFUSAL_ANSWER,
            requested_mode=payload.mode,
            effective_mode=retrieval.effective_mode,
        )
    cited = [item for item in evidence if item.source_id in parsed.citation_ids]
    return KnowledgeAnswerResponse(
        status="answered",
        answer=parsed.answer,
        citations=parsed.citation_ids,
        sources=[CitationSource.model_validate(source_response(item)) for item in cited],
        requested_mode=payload.mode,
        effective_mode=retrieval.effective_mode,
    )
