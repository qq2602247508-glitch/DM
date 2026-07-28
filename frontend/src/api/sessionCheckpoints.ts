import { apiFetch } from "./client";

export type SessionCheckpointSummary = {
  id: string;
  name: string;
  schema_version: number;
  status: "active" | "archived";
  scene_id: string | null;
  active_combat_id: string | null;
  entry_count: number;
  entity_count: number;
  base_campaign_version: number;
  version: number;
  created_at: string;
  notes?: string | null;
};

export type SessionCheckpointDetail = SessionCheckpointSummary & {
  entries: Array<Record<string, unknown>>;
  snapshot?: Record<string, unknown>;
};

export type SessionCheckpointRestorePreview = {
  checkpoint_id: string;
  can_restore: boolean;
  conflicts: Array<Record<string, unknown>>;
  warnings: string[];
  change_summary: Record<string, unknown>;
};

export function listSessionCheckpoints(
  campaignId: string,
  signal?: AbortSignal,
): Promise<SessionCheckpointSummary[]> {
  return apiFetch<{ checkpoints: SessionCheckpointSummary[] }>(
    `/campaigns/${campaignId}/session-checkpoints`,
    { signal },
  ).then((result) => result.checkpoints);
}

export function getSessionCheckpoint(
  campaignId: string,
  checkpointId: string,
): Promise<SessionCheckpointDetail> {
  return apiFetch<SessionCheckpointDetail>(
    `/campaigns/${campaignId}/session-checkpoints/${checkpointId}`,
  );
}

export function createSessionCheckpoint(
  campaignId: string,
  input: {
    name: string;
    scene_id?: string | null;
    active_combat_id?: string | null;
    entries?: Array<Record<string, unknown>>;
    expected_campaign_version?: number;
    notes?: string | null;
  },
): Promise<SessionCheckpointSummary> {
  return apiFetch<SessionCheckpointSummary>(
    `/campaigns/${campaignId}/session-checkpoints`,
    { method: "POST", body: input },
  );
}

export function previewSessionCheckpointRestore(
  campaignId: string,
  checkpointId: string,
  input: { expected_campaign_version?: number; force?: boolean } = {},
): Promise<SessionCheckpointRestorePreview> {
  return apiFetch<SessionCheckpointRestorePreview>(
    `/campaigns/${campaignId}/session-checkpoints/${checkpointId}/restore-preview`,
    { method: "POST", body: input },
  );
}

export function restoreSessionCheckpoint(
  campaignId: string,
  checkpointId: string,
  input: {
    expected_campaign_version?: number;
    force?: boolean;
    idempotency_key: string;
  },
): Promise<{
  restored: boolean;
  checkpoint_id: string;
  campaign_id: string;
  restored_at: string;
  entries: Array<Record<string, unknown>>;
  change_summary: Record<string, unknown>;
}> {
  return apiFetch(
    `/campaigns/${campaignId}/session-checkpoints/${checkpointId}/restore`,
    { method: "POST", body: input },
  );
}

export function archiveSessionCheckpoint(
  campaignId: string,
  checkpointId: string,
  version: number,
): Promise<SessionCheckpointSummary> {
  return apiFetch(
    `/campaigns/${campaignId}/session-checkpoints/${checkpointId}/archive`,
    { method: "POST", body: { version } },
  );
}
