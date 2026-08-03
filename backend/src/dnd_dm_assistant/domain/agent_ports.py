from __future__ import annotations

from typing import Protocol

from dnd_dm_assistant.domain.agent import (
    AgentPlan,
    CampaignAIMessage,
    GeneratedDMHint,
    ModelRunRecord,
    ProposalDecision,
    StateChangeProposal,
    StateOperation,
)
from dnd_dm_assistant.domain.campaign_state import CampaignState
from dnd_dm_assistant.domain.rag import GroundedAnswer, SearchQuery


class AgentPlanner(Protocol):
    @property
    def model_name(self) -> str: ...

    async def plan(self, system_prompt: str, user_prompt: str) -> AgentPlan: ...


class DMHintGenerator(Protocol):
    @property
    def model_name(self) -> str: ...

    async def generate_hint(self, system_prompt: str, user_prompt: str) -> GeneratedDMHint: ...


class RulesKnowledge(Protocol):
    async def answer(self, question: str, query: SearchQuery | None = None) -> GroundedAnswer: ...


class CampaignStateReader(Protocol):
    def state(self, campaign_id: str, *, limit: int = 100) -> CampaignState: ...


class AgentPersistence(Protocol):
    def conversation_history(
        self, campaign_id: str, *, limit: int = 12
    ) -> tuple[CampaignAIMessage, ...]: ...

    def append_conversation_turn(
        self,
        campaign_id: str,
        *,
        user_message: str,
        assistant_message: str,
        request_id: str,
    ) -> None: ...

    def create_proposal(
        self,
        campaign_id: str,
        operation: StateOperation,
        *,
        model_name: str,
        request_id: str,
    ) -> StateChangeProposal: ...

    def list_proposals(
        self, campaign_id: str, *, status: str = "pending", limit: int = 100
    ) -> tuple[StateChangeProposal, ...]: ...

    def confirm(
        self, campaign_id: str, proposal_id: str, *, request_id: str
    ) -> ProposalDecision: ...

    def reject(
        self, campaign_id: str, proposal_id: str, *, request_id: str
    ) -> ProposalDecision: ...

    def record_model_run(self, record: ModelRunRecord) -> None: ...
