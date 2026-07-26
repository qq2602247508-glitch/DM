import { apiFetch } from "./client";
import type {
  InventorySummary,
  LocationGenerationPreview,
  Monster,
  NpcGenerationPreview,
  Scene,
  SceneCombatResult,
  SceneParticipant,
  WorldItem,
} from "./types";

type Items<T> = { items: T[] };

export function generateNpc(
  campaignId: string,
  input: {
    mode: "quick" | "guided";
    brief: string;
    answers: Record<string, string>;
  },
): Promise<NpcGenerationPreview> {
  return apiFetch(`/campaigns/${campaignId}/generate/npc`, {
    method: "POST",
    body: input,
  });
}

export function generateLocation(
  campaignId: string,
  input: { brief: string; maximum_depth: number; scale: "small" | "medium" | "large" },
): Promise<LocationGenerationPreview> {
  return apiFetch(`/campaigns/${campaignId}/generate/location`, {
    method: "POST",
    body: input,
  });
}

export function confirmLocation(
  campaignId: string,
  preview: LocationGenerationPreview,
): Promise<{ locations: unknown[]; items: WorldItem[] }> {
  return apiFetch(`/campaigns/${campaignId}/generate/location/confirm`, {
    method: "POST",
    body: { preview },
  });
}

export async function listWorldItems(
  campaignId: string,
  filters: { location_id?: string; owner_character_id?: string } = {},
  signal?: AbortSignal,
): Promise<WorldItem[]> {
  const query = new URLSearchParams(filters);
  return (
    await apiFetch<Items<WorldItem>>(
      `/campaigns/${campaignId}/items${query.size ? `?${query}` : ""}`,
      { signal },
    )
  ).items;
}

export function createWorldItem(
  campaignId: string,
  input: Partial<WorldItem> & Pick<WorldItem, "name">,
): Promise<WorldItem> {
  return apiFetch(`/campaigns/${campaignId}/items`, { method: "POST", body: input });
}

export function pickupItem(
  campaignId: string,
  itemId: string,
  input: { character_id: string; quantity: number; version: number },
): Promise<{ item: WorldItem; inventory: InventorySummary }> {
  return apiFetch(`/campaigns/${campaignId}/items/${itemId}/pickup`, {
    method: "POST",
    body: input,
  });
}

export function getInventory(
  campaignId: string,
  characterId: string,
  signal?: AbortSignal,
): Promise<InventorySummary> {
  return apiFetch(`/campaigns/${campaignId}/characters/${characterId}/inventory`, { signal });
}

export async function listMonsters(
  campaignId: string,
  signal?: AbortSignal,
): Promise<Monster[]> {
  return (await apiFetch<Items<Monster>>(`/campaigns/${campaignId}/monsters`, { signal })).items;
}

export function createMonster(
  campaignId: string,
  input: Partial<Monster> & Pick<Monster, "name">,
): Promise<Monster> {
  return apiFetch(`/campaigns/${campaignId}/monsters`, { method: "POST", body: input });
}

export async function listScenes(
  campaignId: string,
  signal?: AbortSignal,
): Promise<Scene[]> {
  return (await apiFetch<Items<Scene>>(`/campaigns/${campaignId}/scenes`, { signal })).items;
}

export function createScene(
  campaignId: string,
  input: { name: string; location_id?: string | null; description?: string | null; notes?: string | null },
): Promise<Scene> {
  return apiFetch(`/campaigns/${campaignId}/scenes`, { method: "POST", body: input });
}

export async function listSceneParticipants(
  campaignId: string,
  sceneId: string,
  signal?: AbortSignal,
): Promise<SceneParticipant[]> {
  return (
    await apiFetch<Items<SceneParticipant>>(
      `/campaigns/${campaignId}/scenes/${sceneId}/participants`,
      { signal },
    )
  ).items;
}

export function addSceneParticipant(
  campaignId: string,
  sceneId: string,
  input: {
    entity_type: "character" | "npc" | "monster";
    entity_id: string;
    role?: string;
    visible?: boolean;
  },
): Promise<SceneParticipant> {
  return apiFetch(`/campaigns/${campaignId}/scenes/${sceneId}/participants`, {
    method: "POST",
    body: input,
  });
}

export function removeSceneParticipant(
  campaignId: string,
  sceneId: string,
  participantId: string,
  version: number,
): Promise<void> {
  return apiFetch(
    `/campaigns/${campaignId}/scenes/${sceneId}/participants/${participantId}?version=${version}`,
    { method: "DELETE" },
  );
}

export function startSceneCombat(
  campaignId: string,
  sceneId: string,
  name?: string,
): Promise<SceneCombatResult> {
  return apiFetch(`/campaigns/${campaignId}/scenes/${sceneId}/start-combat`, {
    method: "POST",
    body: { name: name || null },
  });
}
