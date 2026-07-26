import { apiFetch } from "./client";
import type {
  AgentResponse,
  ProposalDecision,
  ProposalStatus,
  StateChangeProposal,
} from "./types";

export function runAssistantTurn(
  campaignId: string,
  action: string,
  options: { mode?: "general" | "narrative"; signal?: AbortSignal } = {},
): Promise<AgentResponse> {
  return apiFetch<AgentResponse>(`/campaigns/${campaignId}/assistant/turns`, {
    method: "POST",
    body: { action, mode: options.mode ?? "general" },
    signal: options.signal,
  });
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
