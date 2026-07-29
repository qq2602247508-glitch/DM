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

export type CompendiumCatalog = {
  items: CompendiumEntry[];
  total: number;
  page: number;
  page_size: number;
  counts: Record<string, number>;
  official_total: number;
  facets: Record<string, string[]>;
};

export async function listCompendium(
  campaignId: string,
  filters: {
    entry_type?: string;
    source_kind?: string;
    text?: string;
    page?: number;
    page_size?: number;
    class_name?: string;
    spell_level?: string;
    monster_type?: string;
    challenge_rating?: string;
    slot?: string;
    rarity?: string;
    category?: string;
    attunement?: string;
    edition?: string;
    content_type?: string;
  },
  signal?: AbortSignal,
): Promise<CompendiumCatalog> {
  const query = new URLSearchParams();
  if (filters.entry_type) query.set("entry_type", filters.entry_type);
  if (filters.source_kind) query.set("source_kind", filters.source_kind);
  if (filters.text) query.set("text", filters.text);
  if (filters.page) query.set("page", String(filters.page));
  if (filters.page_size) query.set("page_size", String(filters.page_size));
  for (const key of [
    "class_name", "spell_level", "monster_type", "challenge_rating",
    "slot", "rarity", "category", "attunement", "edition", "content_type",
  ] as const) {
    if (filters[key]) query.set(key, filters[key]);
  }
  const suffix = query.size ? `?${query.toString()}` : "";
  return apiFetch<CompendiumCatalog>(
    `/campaigns/${campaignId}/compendium${suffix}`,
    { signal },
  );
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
