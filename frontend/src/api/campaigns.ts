import { apiFetch } from "./client";
import type { Campaign, CampaignBackup, ListEnvelope, StateSnapshot } from "./types";

export type CampaignCreateInput = {
  name: string;
  description?: string | null;
  world_setting?: string | null;
  current_time?: string | null;
  current_location_id?: string | null;
  status?: string;
  allow_legacy?: boolean;
  encumbrance_mode?: "standard" | "variant" | "none";
  enabled_rule_extensions?: string[];
  enabled_content_packs?: string[];
};

export type CampaignPatchInput = Partial<Omit<CampaignCreateInput, "name">> & {
  name?: string;
};

export async function listCampaigns(signal?: AbortSignal): Promise<Campaign[]> {
  const envelope = await apiFetch<ListEnvelope<Campaign>>("/campaigns?limit=200", {
    signal,
  });
  return envelope.items;
}

export function getCampaign(id: string, signal?: AbortSignal): Promise<Campaign> {
  return apiFetch<Campaign>(`/campaigns/${id}`, { signal });
}

export function getCampaignState(
  id: string,
  limit = 100,
  signal?: AbortSignal,
): Promise<StateSnapshot> {
  return apiFetch<StateSnapshot>(`/campaigns/${id}/state?limit=${limit}`, { signal });
}

export function createCampaign(input: CampaignCreateInput): Promise<Campaign> {
  return apiFetch<Campaign>("/campaigns", { method: "POST", body: input });
}

export function updateCampaign(
  id: string,
  input: CampaignPatchInput,
  version: number,
): Promise<Campaign> {
  return apiFetch<Campaign>(`/campaigns/${id}`, {
    method: "PATCH",
    body: { ...input, version },
  });
}

export function deleteCampaign(id: string, version: number): Promise<void> {
  return apiFetch<void>(`/campaigns/${id}?version=${version}`, { method: "DELETE" });
}

export function exportCampaign(id: string, signal?: AbortSignal): Promise<CampaignBackup> {
  return apiFetch<CampaignBackup>(`/campaigns/${id}/export`, { signal });
}

export function importCampaign(backup: CampaignBackup, name?: string): Promise<Campaign> {
  return apiFetch<Campaign>("/campaigns/import-backup", {
    method: "POST",
    body: { backup, ...(name ? { name } : {}) },
  });
}
