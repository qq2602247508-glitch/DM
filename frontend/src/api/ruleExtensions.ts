import { apiFetch } from "./client";

export type RuleExtension = {
  key: string;
  label: string;
  category: string;
  summary: string;
  source_record_name: string;
  source_edition: string;
  automation_status: "full" | "partial" | "dm_only";
  tags: string[];
  conflicts_with: string[];
  requires_legacy: boolean;
};

export type RuleExtensionCatalog = {
  items: RuleExtension[];
  default_enabled: string[];
  policy: Record<string, string>;
};

export function listRuleExtensions(signal?: AbortSignal): Promise<RuleExtensionCatalog> {
  return apiFetch<RuleExtensionCatalog>("/rules/extensions", { signal });
}
