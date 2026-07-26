from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from dnd_dm_assistant.api.dependencies import get_runtime_integrations
from dnd_dm_assistant.api.schemas import KnowledgeAnswerRequest, KnowledgeSearchResponse
from dnd_dm_assistant.application.rag import (
    IndexCompatibilityError,
    RuntimeUnavailableError,
)
from dnd_dm_assistant.domain.content import NormalizedEntity
from dnd_dm_assistant.domain.rag import GroundedAnswer, IndexStatus, SearchQuery
from dnd_dm_assistant.integrations.runtime import RuntimeIntegrations

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/index/status", response_model=IndexStatus)
async def index_status(
    runtime: Annotated[RuntimeIntegrations, Depends(get_runtime_integrations)],
) -> IndexStatus:
    try:
        return await runtime.status()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Local vector index is unavailable") from exc


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search(
    request: SearchQuery,
    runtime: Annotated[RuntimeIntegrations, Depends(get_runtime_integrations)],
) -> KnowledgeSearchResponse:
    try:
        hits = await runtime.search(request)
    except (RuntimeUnavailableError, IndexCompatibilityError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return KnowledgeSearchResponse(hits=hits)


@router.post("/answer", response_model=GroundedAnswer)
async def answer(
    request: KnowledgeAnswerRequest,
    runtime: Annotated[RuntimeIntegrations, Depends(get_runtime_integrations)],
) -> GroundedAnswer:
    try:
        return await runtime.answer(request.question, request.search)
    except (RuntimeUnavailableError, IndexCompatibilityError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/documents/{record_id}", response_model=NormalizedEntity)
def document(
    record_id: str,
    runtime: Annotated[RuntimeIntegrations, Depends(get_runtime_integrations)],
) -> NormalizedEntity:
    entity = runtime.get_document(record_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Rule document not found")
    return entity
