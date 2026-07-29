import { apiFetch } from "./client";

export type MerchantStock = {
  id?: string;
  name: string;
  quantity: number;
  price_copper: number;
  source_kind?: "official" | "original";
  category?: string;
  filters_json?: Record<string, unknown>;
  rules_json?: Record<string, unknown>;
  metadata_json?: Record<string, unknown>;
};

export type MerchantPreview = {
  schema_version: "1.0";
  merchant: {
    name: string;
    brief: string;
    location_id: string | null;
    location_name: string | null;
    scene_id: string | null;
    scene_name: string | null;
    categories: string[];
    item_tier: string;
    character_ids: string[];
    character_names: string[];
    price_modifier_bps: number;
  };
  stock: MerchantStock[];
  summary: {
    official_atoms: number;
    original_atoms: number;
    party_level: number | null;
    seed?: number | string;
    categories?: Record<string, number>;
  };
};

export type MerchantGroup = {
  merchant_id: string;
  name: string;
  npc_id: string;
  location_id: string | null;
  scene_id: string | null;
  item_tier: string;
  stock: MerchantStock[];
};

export type MerchantGenerateInput = {
  name?: string;
  brief: string;
  location_id?: string;
  scene_id?: string;
  categories: string[];
  item_tier: string;
  character_ids: string[];
  stock_size: number;
  price_modifier_bps: number;
  allow_original: boolean;
  seed?: number;
};

export async function listMerchants(
  campaignId: string,
  signal?: AbortSignal,
): Promise<MerchantGroup[]> {
  const result = await apiFetch<{ items: MerchantGroup[] }>(
    `/campaigns/${campaignId}/merchants`,
    { signal },
  );
  return result.items;
}

export function previewMerchant(
  campaignId: string,
  input: MerchantGenerateInput,
): Promise<MerchantPreview> {
  return apiFetch(`/campaigns/${campaignId}/merchants/generate/preview`, {
    method: "POST",
    body: input,
  });
}

export function confirmMerchant(
  campaignId: string,
  preview: MerchantPreview,
): Promise<{ merchant_id: string; stock: MerchantStock[] }> {
  return apiFetch(`/campaigns/${campaignId}/merchants/generate/confirm`, {
    method: "POST",
    body: { preview },
  });
}
