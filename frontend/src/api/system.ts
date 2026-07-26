import { apiFetch } from "./client";
import type { HealthResponse, IndexStatus, RuntimeModelStatus } from "./types";

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health", { signal });
}

export function getIndexStatus(signal?: AbortSignal): Promise<IndexStatus> {
  return apiFetch<IndexStatus>("/knowledge/index/status", { signal });
}

export function getModelStatus(signal?: AbortSignal): Promise<RuntimeModelStatus> {
  return apiFetch<RuntimeModelStatus>("/runtime/models", { signal });
}
