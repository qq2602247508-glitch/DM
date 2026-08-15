import { apiFetch } from "./client";

export type PlayerView = {
  campaign: { id: string; name: string; current_time: string | null };
  scene: null | { id: string; name: string; description: string | null; grid: null | { width: number; height: number; cell_size_ft: number; mode: string; public_description: string | null }; tokens: Array<{ id: string; label: string; row: number; col: number; size_cells: number; elevation_ft: number }>; objects: Array<{ id: string; object_type: string; label: string; row: number; col: number; width_cells: number; height_cells: number; state: string }> };
  initiative: Array<{ id: string; name: string; initiative: number; hp: number; max_hp: number; conditions: unknown }>;
  handouts: Array<{ id: string; title: string; body: string; sort_order: number }>;
  shared_log: Array<{ id: string; event_type: string; title: string; description: string | null; occurred_at: string }>;
};

export type PlayerCharacter = Record<string, unknown> & { id: string; name: string; version: number; hp: number; max_hp: number; actions: unknown[]; spells: unknown[]; resources: Record<string, unknown>; equipment: unknown[]; inventory: unknown[] };

export function getPlayerView(campaignId: string, signal?: AbortSignal): Promise<PlayerView> {
  return apiFetch<PlayerView>(`/player/campaigns/${campaignId}/view`, { signal });
}
export function getPlayerCharacter(campaignId: string, characterId: string, signal?: AbortSignal): Promise<PlayerCharacter> {
  return apiFetch<PlayerCharacter>(`/player/campaigns/${campaignId}/characters/${characterId}`, { signal });
}
export function listHandouts(campaignId: string, signal?: AbortSignal): Promise<{ items: Array<{ id: string; campaign_id: string; title: string; body: string; published: boolean; sort_order: number; version: number }> }> {
  return apiFetch(`/campaigns/${campaignId}/handouts`, { signal });
}

export function createHandout(campaignId: string, data: { title: string; body: string; published?: boolean; sort_order?: number }): Promise<Record<string, unknown>> {
  return apiFetch(`/campaigns/${campaignId}/handouts`, { method: "POST", body: data });
}

export function updateHandout(campaignId: string, handoutId: string, data: { title?: string; body?: string; published?: boolean; sort_order?: number; version: number }): Promise<Record<string, unknown>> {
  return apiFetch(`/campaigns/${campaignId}/handouts/${handoutId}`, { method: "PATCH", body: data });
}

export function publishHandout(campaignId: string, title: string, body: string): Promise<Record<string, unknown>> {
  return createHandout(campaignId, { title, body, published: true });
}
