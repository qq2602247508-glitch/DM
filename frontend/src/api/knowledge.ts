import { apiFetch } from "./client";
import type { GroundedAnswer, RuleDocument, SearchHit, SearchQuery } from "./types";

type SearchResponse = {
  hits: SearchHit[];
};

export async function searchKnowledge(
  query: SearchQuery,
  signal?: AbortSignal,
): Promise<SearchHit[]> {
  const response = await apiFetch<SearchResponse>("/knowledge/search", {
    method: "POST",
    body: query,
    signal,
  });
  return response.hits;
}

export function answerKnowledge(
  question: string,
  search?: SearchQuery,
  signal?: AbortSignal,
): Promise<GroundedAnswer> {
  return apiFetch<GroundedAnswer>("/knowledge/answer", {
    method: "POST",
    body: search ? { question, search } : { question },
    signal,
  });
}

export function getRuleDocument(recordId: string, signal?: AbortSignal): Promise<RuleDocument> {
  return apiFetch<RuleDocument>(`/knowledge/documents/${encodeURIComponent(recordId)}`, { signal });
}
