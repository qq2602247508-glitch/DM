import { apiFetch } from "./client";

export type PrepDraft = {
  schema_version: "1.0";
  title?: string;
  locations: Array<Record<string, unknown>>;
  scenes: Array<Record<string, unknown>>;
  npcs: Array<Record<string, unknown>>;
  monsters: Array<Record<string, unknown>>;
  quests: Array<Record<string, unknown>>;
  clues: Array<Record<string, unknown>>;
  items: Array<Record<string, unknown>>;
};

export type PrepImportPreview = {
  valid: boolean;
  preview_token: string;
  expires_at: string;
  summary: Record<string, number>;
  warnings: Array<{ code: string; path: string; message: string }>;
  errors: Array<{ code: string; path: string; message: string }>;
  operations: Array<Record<string, unknown>>;
  reference_plan: Record<string, Record<string, string>>;
};

export function previewPrepImport(
  campaignId: string,
  draft: PrepDraft,
  duplicateStrategy: "error" | "reuse" | "create" = "reuse",
): Promise<PrepImportPreview> {
  return apiFetch(`/campaigns/${campaignId}/prep-imports/preview`, {
    method: "POST",
    body: { draft, duplicate_strategy: duplicateStrategy },
  });
}

export function confirmPrepImport(
  campaignId: string,
  input: {
    draft: PrepDraft;
    duplicate_strategy: "error" | "reuse" | "create";
    preview_token: string;
    idempotency_key: string;
  },
): Promise<{
  import_id: string;
  idempotent_replay: boolean;
  created: Record<string, number>;
  reused: Record<string, number>;
  reference_map: Record<string, Record<string, string>>;
}> {
  return apiFetch(`/campaigns/${campaignId}/prep-imports/confirm`, {
    method: "POST",
    body: input,
  });
}
