import { apiFetch } from "./client";

export type ContentPack = {
  key: string;
  label: string;
  source_book: string;
  summary: string;
  source_edition: string;
  automation_status: "full" | "partial" | "dm_only";
  content_types: string[];
  default_enabled: boolean;
  available_entries: number;
  entry_counts: Record<string, number>;
  status_counts: {
    imported: number;
    needs_normalization: number;
  };
};

export type ContentPackCatalog = {
  items: ContentPack[];
  default_enabled: string[];
  policy: Record<string, string>;
};

export function listContentPacks(signal?: AbortSignal): Promise<ContentPackCatalog> {
  return apiFetch<ContentPackCatalog>("/rules/content-packs", { signal });
}
