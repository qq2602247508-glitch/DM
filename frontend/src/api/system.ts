import { apiFetch } from "./client";
import type { AuditEntry, Diagnostics, HealthResponse, HouseRuleOverride, IndexStatus, RecoveryPoint, RuntimeModelStatus } from "./types";

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health", { signal });
}

export function getIndexStatus(signal?: AbortSignal): Promise<IndexStatus> {
  return apiFetch<IndexStatus>("/knowledge/index/status", { signal });
}

export function getModelStatus(signal?: AbortSignal): Promise<RuntimeModelStatus> {
  return apiFetch<RuntimeModelStatus>("/runtime/models", { signal });
}

export function getDiagnostics(signal?: AbortSignal): Promise<Diagnostics> { return apiFetch<Diagnostics>("/system/diagnostics", { signal }); }
export function getSafeMode(signal?: AbortSignal): Promise<{ enabled: boolean }> { return apiFetch("/system/safe-mode", { signal }); }
export function setSafeMode(enabled: boolean, reason: string): Promise<{ enabled: boolean }> { return apiFetch("/system/safe-mode", { method: "POST", body: { enabled, reason } }); }
export function listRecoveryPoints(signal?: AbortSignal): Promise<{ items: RecoveryPoint[] }> { return apiFetch("/system/recovery-points", { signal }); }
export function createRecoveryPoint(label: string): Promise<RecoveryPoint> { return apiFetch("/system/recovery-points", { method: "POST", body: { label } }); }
export function previewRestore(id: string): Promise<{ recovery_point_id: string; label: string; campaigns: number; tables: number; confirm_token: string; warning: string }> { return apiFetch(`/system/recovery-points/${id}/preview-restore`, { method: "POST" }); }
export function restorePoint(id: string, confirmToken: string): Promise<unknown> { return apiFetch(`/system/recovery-points/${id}/restore`, { method: "POST", body: { confirm_token: confirmToken, confirmation: "RESTORE" } }); }
export function listAudit(campaignId: string | null, signal?: AbortSignal): Promise<{ items: AuditEntry[] }> { return apiFetch(`/system/audit${campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : ""}`, { signal }); }
export function listHouseRules(campaignId: string, signal?: AbortSignal): Promise<{ items: HouseRuleOverride[] }> { return apiFetch(`/system/campaigns/${campaignId}/house-rules`, { signal }); }
export function saveHouseRule(campaignId: string, value: { rule_key: string; core_value: unknown; override_value: unknown; source: string; reason: string; enabled: boolean }): Promise<HouseRuleOverride> { return apiFetch(`/system/campaigns/${campaignId}/house-rules`, { method: "PUT", body: value }); }
