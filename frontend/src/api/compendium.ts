import { apiFetch } from "./client";

export type CompendiumEntryType =
  | "spell" | "feature" | "monster" | "equipment" | "item" | "npc" | "location" | "scene";
export type CompendiumSourceKind =
  | "official" | "original" | "ai_generated" | "dm_modified" | "third_party";

export type CompendiumEntry = {
  id: string;
  version: number;
  campaign_id: string;
  entry_type: CompendiumEntryType;
  name: string;
  description: string | null;
  source_kind: CompendiumSourceKind;
  source_record_id: string | null;
  source_name: string | null;
  family_key: string | null;
  tags: string[];
  filters_json: Record<string, unknown>;
  rules_json: Record<string, unknown>;
};

export type CompendiumGenerationPreview = {
  schema_version: "1.0";
  mode: "single" | "equipment_set" | "monster_family";
  prompt: string;
  applicable_level: number;
  entries: Array<Omit<CompendiumEntry, "id" | "version" | "campaign_id" | "source_record_id" | "source_name">>;
  warnings: string[];
};

export async function listCompendium(
  campaignId: string,
  filters: { entry_type?: string; source_kind?: string; text?: string },
  signal?: AbortSignal,
): Promise<CompendiumEntry[]> {
  const query = new URLSearchParams();
  if (filters.entry_type) query.set("entry_type", filters.entry_type);
  if (filters.source_kind) query.set("source_kind", filters.source_kind);
  if (filters.text) query.set("text", filters.text);
  const suffix = query.size ? `?${query.toString()}` : "";
  return (await apiFetch<{ items: CompendiumEntry[] }>(
    `/campaigns/${campaignId}/compendium${suffix}`,
    { signal },
  )).items;
}

export function generateCompendium(
  campaignId: string,
  input: {
    mode: "single" | "equipment_set" | "monster_family";
    entry_type: CompendiumEntryType;
    prompt: string;
    applicable_level: number;
  },
): Promise<CompendiumGenerationPreview> {
  return apiFetch(`/campaigns/${campaignId}/compendium/generate/preview`, {
    method: "POST",
    body: input,
  });
}

export function createCompendiumEntry(
  campaignId: string,
  input: {
    entry_type: CompendiumEntryType;
    name: string;
    description?: string | null;
    source_kind: CompendiumSourceKind;
    source_record_id?: string | null;
    source_name?: string | null;
    tags?: string[];
    filters_json?: Record<string, unknown>;
    rules_json?: Record<string, unknown>;
  },
): Promise<CompendiumEntry> {
  return apiFetch(`/campaigns/${campaignId}/compendium`, {
    method: "POST",
    body: input,
  });
}

export async function confirmCompendiumGeneration(
  campaignId: string,
  preview: CompendiumGenerationPreview,
): Promise<CompendiumEntry[]> {
  return (await apiFetch<{ items: CompendiumEntry[] }>(
    `/campaigns/${campaignId}/compendium/generate/confirm`,
    { method: "POST", body: { preview } },
  )).items;
}

export function instantiateCompendiumEntry(
  campaignId: string,
  entryId: string,
  targetType: "character" | "scene",
  targetId: string,
): Promise<Record<string, unknown>> {
  return apiFetch(`/campaigns/${campaignId}/compendium/${entryId}/instantiate`, {
    method: "POST",
    body: { target_type: targetType, target_id: targetId },
  });
}
