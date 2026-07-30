import { apiFetch } from "./client";
import type {
  AgentResponse,
  AssistantConversationMessage,
  ProposalDecision,
  ProposalStatus,
  StateChangeProposal,
} from "./types";

export type AssistantMode = "quick" | "narrative" | "combat";
export type LegacyAssistantMode = "general";

export function runAssistantTurn(
  campaignId: string,
  action: string,
  options: {
    mode?: AssistantMode | LegacyAssistantMode;
    signal?: AbortSignal;
    userMessage?: string;
    rememberConversation?: boolean;
    useConversationHistory?: boolean;
    includeCampaignState?: boolean;
  } = {},
): Promise<AgentResponse> {
  return apiFetch<AgentResponse>(`/campaigns/${campaignId}/assistant/turns`, {
    method: "POST",
    body: {
      action,
      mode: options.mode ?? "quick",
      ...(options.userMessage ? { user_message: options.userMessage } : {}),
      ...(options.rememberConversation ? { remember_conversation: true } : {}),
      ...(options.useConversationHistory ? { use_conversation_history: true } : {}),
      ...(options.includeCampaignState === false ? { include_campaign_state: false } : {}),
    },
    signal: options.signal,
  });
}

export function recordAssistantConversationTurn(
  campaignId: string,
  userMessage: string,
  assistantMessage: string,
): Promise<void> {
  return apiFetch<void>(`/campaigns/${campaignId}/assistant/conversation-turns`, {
    method: "POST",
    body: { user_message: userMessage, assistant_message: assistantMessage },
  });
}

export function listAssistantConversationTurns(
  campaignId: string,
  limit = 12,
): Promise<AssistantConversationMessage[]> {
  return apiFetch<AssistantConversationMessage[]>(
    `/campaigns/${campaignId}/assistant/conversation-turns?limit=${limit}`,
  );
}

export function listProposals(
  campaignId: string,
  status: ProposalStatus,
  signal?: AbortSignal,
): Promise<StateChangeProposal[]> {
  return apiFetch<StateChangeProposal[]>(
    `/campaigns/${campaignId}/change-proposals?status=${status}&limit=200`,
    { signal },
  );
}

export function confirmProposal(
  campaignId: string,
  proposalId: string,
): Promise<ProposalDecision> {
  return apiFetch<ProposalDecision>(
    `/campaigns/${campaignId}/change-proposals/${proposalId}/confirm`,
    { method: "POST" },
  );
}

export function rejectProposal(
  campaignId: string,
  proposalId: string,
): Promise<ProposalDecision> {
  return apiFetch<ProposalDecision>(
    `/campaigns/${campaignId}/change-proposals/${proposalId}/reject`,
    { method: "POST" },
  );
}
