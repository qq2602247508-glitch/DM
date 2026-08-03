from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from dnd_dm_assistant.api.dependencies import (
    get_agent_orchestrator,
    get_agent_persistence,
)
from dnd_dm_assistant.api.schemas import AssistantConversationTurnRequest, AssistantTurnRequest
from dnd_dm_assistant.application.agent import (
    AgentOrchestrator,
    AgentUnavailableError,
    InvalidAgentOutputError,
)
from dnd_dm_assistant.domain.agent import (
    AgentRequest,
    AgentResponse,
    CampaignAIMessage,
    ProposalDecision,
    ProposalStatus,
    StateChangeProposal,
)
from dnd_dm_assistant.domain.agent_ports import AgentPersistence
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError

router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["assistant"])


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


@router.post("/assistant/turns", response_model=AgentResponse)
async def assistant_turn(
    campaign_id: str,
    body: AssistantTurnRequest,
    request: Request,
    orchestrator: Annotated[AgentOrchestrator, Depends(get_agent_orchestrator)],
) -> AgentResponse:
    try:
        return await orchestrator.run(
            AgentRequest(
                campaign_id=campaign_id,
                action=body.action,
                request_id=_request_id(request),
                mode=body.mode,
                user_message=body.user_message,
                remember_conversation=body.remember_conversation,
                use_conversation_history=body.use_conversation_history,
                include_campaign_state=body.include_campaign_state,
            )
        )
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc
    except AgentUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidAgentOutputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/assistant/conversation-turns", status_code=204)
def record_assistant_conversation_turn(
    campaign_id: str,
    body: AssistantConversationTurnRequest,
    request: Request,
    persistence: Annotated[AgentPersistence, Depends(get_agent_persistence)],
) -> None:
    try:
        persistence.append_conversation_turn(
            campaign_id,
            user_message=body.user_message,
            assistant_message=body.assistant_message,
            request_id=_request_id(request),
        )
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc


@router.get("/assistant/conversation-turns", response_model=tuple[CampaignAIMessage, ...])
def list_assistant_conversation_turns(
    campaign_id: str,
    persistence: Annotated[AgentPersistence, Depends(get_agent_persistence)],
    limit: int = Query(12, ge=1, le=24),
) -> tuple[CampaignAIMessage, ...]:
    try:
        return persistence.conversation_history(campaign_id, limit=limit)
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc


@router.get("/change-proposals", response_model=tuple[StateChangeProposal, ...])
def list_proposals(
    campaign_id: str,
    persistence: Annotated[AgentPersistence, Depends(get_agent_persistence)],
    status: ProposalStatus = ProposalStatus.PENDING,
    limit: int = Query(100, ge=1, le=200),
) -> tuple[StateChangeProposal, ...]:
    try:
        return persistence.list_proposals(campaign_id, status=status.value, limit=limit)
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc


@router.post(
    "/change-proposals/{proposal_id}/confirm",
    response_model=ProposalDecision,
)
def confirm_proposal(
    campaign_id: str,
    proposal_id: str,
    request: Request,
    persistence: Annotated[AgentPersistence, Depends(get_agent_persistence)],
) -> ProposalDecision:
    try:
        decision = persistence.confirm(campaign_id, proposal_id, request_id=_request_id(request))
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="proposal not found") from exc
    if decision.proposal.status is ProposalStatus.CONFLICT:
        raise HTTPException(
            status_code=409,
            detail="proposal conflicts with the current entity version",
        )
    return decision


@router.post(
    "/change-proposals/{proposal_id}/reject",
    response_model=ProposalDecision,
)
def reject_proposal(
    campaign_id: str,
    proposal_id: str,
    request: Request,
    persistence: Annotated[AgentPersistence, Depends(get_agent_persistence)],
) -> ProposalDecision:
    try:
        return persistence.reject(campaign_id, proposal_id, request_id=_request_id(request))
    except StateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="proposal not found") from exc
