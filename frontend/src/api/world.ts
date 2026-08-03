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

export type SiteGenerationInput = {
  site_type: "building" | "dungeon";
  name: string;
  brief: string;
  region_path: string;
  maximum_levels: number;
  rooms_min: number;
  rooms_max: number;
  party_level: number;
  party_size: number;
  character_ids: string[];
  starting_difficulty: "low" | "moderate" | "high";
  difficulty_growth: number;
  monster_density: number;
  reward_rate: number;
  overall_scale: "small" | "medium" | "large" | "huge";
  minimum_room_size: "small" | "medium" | "large" | "huge";
  maximum_room_size: "small" | "medium" | "large" | "huge";
  generate_npcs: boolean;
  generate_monsters: boolean;
  generate_loot: boolean;
  seed?: number;
};
export type SiteCell = { row: number; col: number; kind: string; label: string; blocks_sight?: boolean };
export type SiteRoomPlan = {
  room_index: number;
  name: string;
  room_type: string;
  description?: string | null;
  bounds?: Record<string, number>;
  bounds_json?: Record<string, number>;
  encounter_json?: {
    visibility?: "hidden" | "revealed";
    monsters?: Array<Record<string, unknown>>;
    npcs?: Array<Record<string, unknown>>;
  };
};
export type SiteLevelPreview = {
  level_index: number;
  name: string;
  description: string;
  difficulty: "low" | "moderate" | "high";
  encounter_budget_xp: number;
  reward_budget_gp: number;
  layout: { width: number; height: number; cell_size_ft: number; cells: SiteCell[] };
  visual_theme?: {
    theme?: string;
    label?: string;
    palette?: string;
    source_kind?: "preset" | "compiled";
    keywords?: string[];
    atmosphere?: string;
    hazard_motifs?: string[];
  };
  rooms: SiteRoomPlan[];
  connectors: Array<Record<string, unknown>>;
  monster_plan: Array<{ name: string; quantity: number; xp_each: number; source: string; room_index?: number }>;
  npc_plan?: Array<{ name: string; role: string; room_index: number }>;
  reward_plan: Array<{
    name: string;
    value_gp: number;
    category?: string;
    room_index?: number;
    source_kind?: string;
    rarity?: string | null;
  }>;
  quality?: {
    score: number;
    room_size_cv: number;
    largest_smallest_ratio: number;
    valid_connectors: number;
    algorithm: string;
  };
};
export type SiteGenerationPreview = {
  schema_version: string;
  site: SiteGenerationInput & { theme: string; seed: number; generation_parameters: Record<string, unknown> };
  region: { path: string[]; name: string };
  levels: SiteLevelPreview[];
  warnings: string[];
};
export type AdventureSite = SiteGenerationPreview["site"] & {
  id: string;
  version: number;
  region_map_id: string;
  location_id: string;
  map_position: { row: number; col: number };
  status: string;
  levels?: Array<SiteLevelPreview & { id: string }>;
};
export type RegionMap = {
  id: string; name: string; width: number; height: number;
  map_json: { pois?: Array<{ site_id: string; name: string; site_type: string; row: number; col: number }> };
};

export function previewSiteGeneration(
  campaignId: string,
  input: SiteGenerationInput,
): Promise<SiteGenerationPreview> {
  return apiFetch(`/campaigns/${campaignId}/sites/generate/preview`, {
    method: "POST",
    body: input,
  });
}

export function confirmSiteGeneration(
  campaignId: string,
  preview: SiteGenerationPreview,
  requestId: string,
): Promise<AdventureSite> {
  return apiFetch(`/campaigns/${campaignId}/sites/generate/confirm`, {
    method: "POST",
    body: { preview },
    headers: { "X-Request-ID": requestId },
  });
}

export async function listAdventureSites(campaignId: string, signal?: AbortSignal): Promise<AdventureSite[]> {
  return (await apiFetch<{ sites: AdventureSite[] }>(`/campaigns/${campaignId}/sites`, { signal })).sites;
}

export function getAdventureSite(campaignId: string, siteId: string, signal?: AbortSignal): Promise<AdventureSite> {
  return apiFetch(`/campaigns/${campaignId}/sites/${siteId}`, { signal });
}

export function setSiteRoomVisibility(
  campaignId: string,
  siteId: string,
  levelIndex: number,
  roomIndex: number,
  visible: boolean,
): Promise<{
  site_id: string;
  level_index: number;
  room_index: number;
  visibility: "hidden" | "revealed";
  tokens_updated: number;
}> {
  return apiFetch(
    `/campaigns/${campaignId}/sites/${siteId}/levels/${levelIndex}/rooms/${roomIndex}/visibility`,
    { method: "PUT", body: { visible } },
  );
}

export function deleteAdventureSite(
  campaignId: string,
  siteId: string,
  version: number,
): Promise<void> {
  return apiFetch(`/campaigns/${campaignId}/sites/${siteId}?version=${version}`, {
    method: "DELETE",
  });
}

export async function listRegionMaps(campaignId: string, signal?: AbortSignal): Promise<RegionMap[]> {
  return (await apiFetch<{ region_maps: RegionMap[] }>(`/campaigns/${campaignId}/region-maps`, { signal })).region_maps;
}

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

export type PersistentSceneGrid = { id: string; width: number; height: number; cell_size_ft: number; mode: "narrative" | "exploration" | "combat"; public_description: string | null; dm_description: string | null; layers_json: Record<string, unknown> };
export type SceneToken = { id: string; label: string; row: number; col: number; entity_type: string; entity_id?: string | null; visible: boolean };
export type PersistentSceneObject = { id: string; version: number; label: string; row: number; col: number; object_type: string; state: string; visibility: string };
export function getSceneGrid(campaignId: string, sceneId: string, signal?: AbortSignal): Promise<{ grid: PersistentSceneGrid; tokens: SceneToken[]; objects: PersistentSceneObject[] }> {
  return apiFetch(`/campaigns/${campaignId}/scenes/${sceneId}/grid`, { signal });
}
export function createPersistentGrid(campaignId: string, sceneId: string, input: Partial<PersistentSceneGrid> = {}): Promise<PersistentSceneGrid> {
  return apiFetch(`/campaigns/${campaignId}/scenes/${sceneId}/grid`, { method: "POST", body: input });
}
export function createSceneObject(campaignId: string, sceneId: string, input: { object_type: "wall" | "door" | "cover" | "terrain" | "light" | "trap" | "treasure" | "furniture" | "portal"; label: string; row: number; col: number; visibility?: "public" | "dm" | "hidden"; interaction_json?: Record<string, unknown>; metadata_json?: Record<string, unknown> }): Promise<PersistentSceneObject> {
  return apiFetch(`/campaigns/${campaignId}/scenes/${sceneId}/objects`, { method: "POST", body: input });
}
export type SceneTokenInput = { entity_type: "character" | "npc" | "monster" | "marker"; entity_id?: string | null; label: string; row: number; col: number; size_cells?: number; elevation_ft?: number; visible?: boolean; metadata_json?: Record<string, unknown> };
export function createSceneToken(campaignId: string, sceneId: string, input: SceneTokenInput): Promise<SceneToken> {
  return apiFetch(`/campaigns/${campaignId}/scenes/${sceneId}/tokens`, { method: "POST", body: input });
}
export type ExplorationInput = { action: "move" | "search" | "interact" | "explore"; minutes: number; token_id?: string | null; path?: Array<[number, number]>; object_id?: string | null; object_state?: string | null; notes?: string | null; preview_token?: string; idempotency_key?: string };
export function previewExploration(campaignId: string, sceneId: string, input: ExplorationInput): Promise<Record<string, unknown>> {
  return apiFetch(`/campaigns/${campaignId}/scenes/${sceneId}/exploration/preview`, { method: "POST", body: input });
}
export function confirmExploration(campaignId: string, sceneId: string, input: ExplorationInput): Promise<Record<string, unknown>> {
  return apiFetch(`/campaigns/${campaignId}/scenes/${sceneId}/exploration/confirm`, { method: "POST", body: input });
}
export type TravelInput = { to_location_id: string; distance_miles: number; pace: "fast" | "normal" | "slow"; encounter?: { title: string; outcome: "avoided" | "resolved" | "evaded"; summary: string; visibility: "dm" | "players" }; notes?: string | null; preview_token?: string; idempotency_key?: string };
export function previewTravel(campaignId: string, input: TravelInput): Promise<Record<string, unknown>> {
  return apiFetch(`/campaigns/${campaignId}/travel/preview`, { method: "POST", body: input });
}
export function confirmTravel(campaignId: string, input: TravelInput): Promise<Record<string, unknown>> {
  return apiFetch(`/campaigns/${campaignId}/travel/confirm`, { method: "POST", body: input });
}

export type ResolutionVisibility = "dm" | "players";
export type ExplorationCharacterEffect = {
  character_id: string;
  character_version: number;
  damage?: number;
  max_hp_reduction?: number;
  condition_name?: string | null;
  condition_duration?: string | null;
  condition_notes?: string | null;
};
type ConfirmationFields = { preview_token: string; idempotency_key: string };
type Confirmed<T> = T & ConfirmationFields;

export type ChaseInput = {
  chase_event_id?: string | null;
  chase_version?: number | null;
  title: string;
  outcome: "success" | "failure";
  target_successes?: number;
  target_failures?: number;
  minutes?: number;
  summary: string;
  visibility?: ResolutionVisibility;
  character_effects?: ExplorationCharacterEffect[];
};
export const listChases = (campaignId: string, signal?: AbortSignal) =>
  apiFetch<Items<Record<string, unknown>>>(`/campaigns/${campaignId}/chases`, { signal }).then((result) => result.items);
export const previewChase = (campaignId: string, input: ChaseInput) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/chases/preview`, { method: "POST", body: input });
export const confirmChase = (campaignId: string, input: Confirmed<ChaseInput>) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/chases/confirm`, { method: "POST", body: input });

export type TrapResolutionInput = {
  trap_version: number;
  outcome: "triggered" | "disarmed" | "bypassed" | "failed";
  result_state?: "active" | "disarmed" | "destroyed";
  minutes?: number;
  summary: string;
  visibility?: ResolutionVisibility;
  character_effects?: ExplorationCharacterEffect[];
};
export const previewTrapResolution = (campaignId: string, sceneId: string, trapId: string, input: TrapResolutionInput) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/scenes/${sceneId}/traps/${trapId}/preview`, { method: "POST", body: input });
export const confirmTrapResolution = (campaignId: string, sceneId: string, trapId: string, input: Confirmed<TrapResolutionInput>) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/scenes/${sceneId}/traps/${trapId}/confirm`, { method: "POST", body: input });

export type EnvironmentHazardInput = {
  name: string;
  object_id?: string | null;
  object_version?: number | null;
  object_state?: "active" | "open" | "closed" | "destroyed" | "disarmed" | "picked_up" | null;
  minutes?: number;
  summary: string;
  visibility?: ResolutionVisibility;
  character_effects?: ExplorationCharacterEffect[];
};
export const previewEnvironmentHazard = (campaignId: string, sceneId: string, input: EnvironmentHazardInput) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/scenes/${sceneId}/hazards/preview`, { method: "POST", body: input });
export const confirmEnvironmentHazard = (campaignId: string, sceneId: string, input: Confirmed<EnvironmentHazardInput>) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/scenes/${sceneId}/hazards/confirm`, { method: "POST", body: input });

export type AfflictionInput = {
  operation: "apply" | "progress" | "cure";
  character_id: string;
  character_version: number;
  condition_id?: string | null;
  condition_version?: number | null;
  affliction_type: "poison" | "disease" | "infection";
  condition_name: string;
  source?: string | null;
  duration?: string | null;
  summary: string;
  damage?: number;
  max_hp_reduction?: number;
  minutes?: number;
  visibility?: ResolutionVisibility;
};
export const previewAffliction = (campaignId: string, input: AfflictionInput) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/afflictions/preview`, { method: "POST", body: input });
export const confirmAffliction = (campaignId: string, input: Confirmed<AfflictionInput>) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/afflictions/confirm`, { method: "POST", body: input });

export type DowntimeResolutionInput = {
  activity_version: number;
  character_version: number;
  progress_days?: number;
  xp_award?: number;
  summary: string;
  visibility?: ResolutionVisibility;
};
export const previewDowntimeResolution = (campaignId: string, activityId: string, input: DowntimeResolutionInput) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/downtime/${activityId}/preview`, { method: "POST", body: input });
export const confirmDowntimeResolution = (campaignId: string, activityId: string, input: Confirmed<DowntimeResolutionInput>) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/downtime/${activityId}/confirm`, { method: "POST", body: input });

export type SocialInteractionInput = {
  npc_version: number;
  outcome: "improve" | "unchanged" | "worsen";
  minutes?: number;
  summary: string;
  memory_kind?: "conversation" | "bargain" | "deception" | "intimidation" | "favor" | "other";
  tags?: string[];
  secret?: boolean;
};
export const previewSocialInteraction = (campaignId: string, npcId: string, input: SocialInteractionInput) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/npcs/${npcId}/social/preview`, { method: "POST", body: input });
export const confirmSocialInteraction = (campaignId: string, npcId: string, input: Confirmed<SocialInteractionInput>) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/npcs/${npcId}/social/confirm`, { method: "POST", body: input });

export type NpcMoraleInput = {
  npc_version: number;
  outcome: "hold" | "retreat" | "surrender";
  combat_id?: string | null;
  combat_version?: number | null;
  leave_combat?: boolean;
  minutes?: number;
  summary: string;
  visibility?: ResolutionVisibility;
};
export const previewNpcMorale = (campaignId: string, npcId: string, input: NpcMoraleInput) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/npcs/${npcId}/morale/preview`, { method: "POST", body: input });
export const confirmNpcMorale = (campaignId: string, npcId: string, input: Confirmed<NpcMoraleInput>) =>
  apiFetch<Record<string, unknown>>(`/campaigns/${campaignId}/npcs/${npcId}/morale/confirm`, { method: "POST", body: input });

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
