import { apiFetch, ApiError } from "./client";

export type PlayerRoomMember = {
  id: string;
  display_name: string;
  character_id: string | null;
  status: string;
  last_seen_at: string;
  version: number;
};

export type PlayerRoom = {
  id: string;
  campaign_id: string;
  status: "active" | "closed" | "expired";
  active?: boolean;
  join_code?: string;
  join_code_hint: string;
  expires_at: string;
  current_scene_id: string | null;
  current_combat_id: string | null;
  version: number;
  urls: string[];
  members: PlayerRoomMember[];
};

export type PlayerActionRequest = {
  id: string;
  character_id: string;
  player_key: string;
  action_type: string;
  message: string | null;
  payload_json: Record<string, unknown>;
  status: "pending" | "accepted" | "rejected" | "stale";
  dm_note: string | null;
  created_at: string;
  version: number;
};

export type SafePlayerCharacter = {
  id: string;
  name: string;
  race: string | null;
  background: string | null;
  class_name: string | null;
  level: number;
  experience: number;
  armor_class: number;
  speed: number;
  ability_scores: Record<string, number>;
  hp: number;
  max_hp: number;
  max_hp_reduction: number;
  death_saves: { successes: number; failures: number };
  inventory: unknown[];
  equipment: unknown[];
  proficiencies: unknown[];
  skills: Record<string, unknown>;
  features: unknown[];
  actions: unknown[];
  resources: Record<string, unknown>;
  spells: unknown[];
  spellcasting: Record<string, unknown>;
  class_levels: Record<string, number>;
  subclass_choices: Record<string, string>;
  wallet: { name: string; copper: number; gp: number } | null;
  version: number;
};

export type AvailablePlayerCharacter = Pick<
  SafePlayerCharacter,
  "id" | "name" | "race" | "class_name" | "level"
>;

export type PlayerSceneGrid = {
  width: number;
  height: number;
  cell_size_ft: number;
  mode?: string;
  public_description?: string | null;
  cells?: Array<{ row: number; col: number; kind: string; label?: string }>;
};

export type PlayerSceneToken = {
  id: string;
  label: string;
  row: number;
  col: number;
  size_cells: number;
  elevation_ft: number;
};

export type PlayerSceneObject = {
  id: string;
  object_type: string;
  label: string;
  row: number;
  col: number;
  width_cells: number;
  height_cells: number;
  state: string;
};

export type PlayerCombatant = {
  id: string;
  name: string;
  entity_type: string;
  initiative: number;
  position: { row: number; col: number } | null;
  health_status: string;
  is_own: boolean;
  version?: number;
  hp?: number;
  max_hp?: number;
  armor_class?: number;
  conditions?: unknown[];
  movement_remaining_ft?: number;
  action_available?: boolean;
  bonus_action_available?: boolean;
  reaction_available?: boolean;
};

export type PlayerPendingRoll = {
  id: string;
  version: number;
  action_name: string;
  resolution_type: string;
  dc: number;
  ability: string | null;
  skill: string | null;
  roll_formula: string;
  description: string | null;
};

export type PlayerCombatSnapshot = {
  id: string;
  name: string;
  status: "active" | "ended";
  version: number;
  round_number: number;
  current_turn_index: number;
  active_combatant_id: string | null;
  is_my_turn: boolean;
  own_combatant_id: string | null;
  combatants: PlayerCombatant[];
  log: Array<{ id: string; summary: string; round_number: number; turn_index: number; status: string }>;
  pending_rolls: PlayerPendingRoll[];
};

export type PlayerRoomSnapshot = {
  room: { id: string; status: string; expires_at: string };
  campaign: { id: string; name: string; current_time: string | null };
  player: { id: string; display_name: string; character_id: string | null };
  available_characters?: AvailablePlayerCharacter[];
  character: SafePlayerCharacter | null;
  table: {
    scene: null | {
      id: string;
      name: string;
      description: string | null;
      grid: PlayerSceneGrid | null;
      tokens: PlayerSceneToken[];
      objects: PlayerSceneObject[];
    };
    handouts: Array<{ id: string; title: string; body: string; sort_order: number }>;
    shared_log: Array<{ id: string; event_type: string; title: string; description: string | null; occurred_at: string }>;
  };
  combat: PlayerCombatSnapshot | null;
};

export type PlayerCharacterDraft = {
  name: string;
  race: string;
  class_name: string;
  background: string;
  ability_scores: Record<string, number>;
  equipment: string[];
  spells?: Array<{ name: string; source_record_id: string; source_path: string }>;
};

export type PlayerRuleHit = {
  name: string;
  excerpt: string;
  content_type: string;
  canonical_url: string;
  edition: string;
  officiality: string;
};

const PUBLIC_API = "/api/v1";

export class PlayerRoomApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "PlayerRoomApiError";
    this.status = status;
  }
}

async function playerFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${PUBLIC_API}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    try {
      const body = await response.json() as { message?: string; detail?: string };
      message = body.message ?? body.detail ?? message;
    } catch { /* keep the safe fallback */ }
    throw new PlayerRoomApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const getPlayerRoom = (campaignId: string, signal?: AbortSignal) =>
  apiFetch<PlayerRoom>(`/campaigns/${campaignId}/player-room`, { signal });

export const openPlayerRoom = (campaignId: string, hours = 12) =>
  apiFetch<PlayerRoom>(`/campaigns/${campaignId}/player-room/open`, {
    method: "POST",
    body: { hours },
  });

export const closePlayerRoom = (campaignId: string) =>
  apiFetch<PlayerRoom>(`/campaigns/${campaignId}/player-room/close`, { method: "POST" });

export const setPlayerRoomLiveState = (
  campaignId: string,
  sceneId: string | null,
  combatId: string | null,
) => apiFetch<PlayerRoom>(`/campaigns/${campaignId}/player-room/live-state`, {
  method: "POST",
  body: { scene_id: sceneId, combat_id: combatId },
});

export const kickPlayerRoomMember = (campaignId: string, memberId: string) =>
  apiFetch<Record<string, unknown>>(
    `/campaigns/${campaignId}/player-room/members/${memberId}/kick`,
    { method: "POST" },
  );

export const assignPlayerRoomCharacter = (campaignId: string, memberId: string, characterId: string) =>
  apiFetch<Record<string, unknown>>(
    `/campaigns/${campaignId}/player-room/members/${memberId}/assign-character`,
    { method: "POST", body: { character_id: characterId } },
  );

export const listPlayerActionRequests = (campaignId: string, signal?: AbortSignal) =>
  apiFetch<{ items: PlayerActionRequest[] }>(
    `/campaigns/${campaignId}/player-action-requests?status=pending`,
    { signal },
  );

export const resolvePlayerActionRequest = (
  campaignId: string,
  requestId: string,
  version: number,
  decision: "accept" | "reject",
) => apiFetch<PlayerActionRequest>(
  `/campaigns/${campaignId}/player-action-requests/${requestId}/${decision}`,
  { method: "POST", body: { version, dm_note: null } },
);

export const isMissingPlayerRoom = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 404;

export const joinPlayerRoom = (joinCode: string, displayName: string) =>
  playerFetch<{ campaign: { id: string; name: string }; player: { id: string; display_name: string }; expires_at: string }>(
    "/player-room/join",
    { method: "POST", body: JSON.stringify({ join_code: joinCode, display_name: displayName }) },
  );

export const getMyPlayerRoom = (signal?: AbortSignal) =>
  playerFetch<PlayerRoomSnapshot>("/player-room/me", { signal });

export const createMyCharacter = (draft: PlayerCharacterDraft) =>
  playerFetch<SafePlayerCharacter>("/player-room/me/characters", {
    method: "POST",
    body: JSON.stringify(draft),
  });

export const bindMyCharacter = (characterId: string) =>
  playerFetch<SafePlayerCharacter>("/player-room/me/bind-character", {
    method: "POST",
    body: JSON.stringify({ character_id: characterId }),
  });

export const submitMyActionRequest = (actionType: string, message: string) =>
  playerFetch<Record<string, unknown>>("/player-room/me/action-requests", {
    method: "POST",
    body: JSON.stringify({
      action_type: actionType,
      message,
      payload_json: {},
      idempotency_key: crypto.randomUUID(),
    }),
  });

export const moveMyCombatant = (row: number, col: number, combatantVersion: number) =>
  playerFetch<Record<string, unknown>>("/player-room/me/combat/move", {
    method: "POST",
    body: JSON.stringify({ row, col, combatant_version: combatantVersion }),
  });

export const attackWithMyCombatant = (
  targetId: string,
  actionName: string,
  attackTotal: number,
  damageTotal: number,
) => playerFetch<Record<string, unknown>>("/player-room/me/combat/attack", {
  method: "POST",
  body: JSON.stringify({
    target_combatant_id: targetId,
    action_name: actionName,
    attack_total: attackTotal,
    damage_total: damageTotal,
    idempotency_key: crypto.randomUUID(),
  }),
});

export const submitMyPlayerRoll = (actionId: string, actionVersion: number, rollTotal: number) =>
  playerFetch<Record<string, unknown>>(`/player-room/me/combat/player-rolls/${actionId}`, {
    method: "POST",
    body: JSON.stringify({
      action_version: actionVersion,
      roll_total: rollTotal,
      idempotency_key: crypto.randomUUID(),
    }),
  });

export const endMyTurn = (combatVersion: number) =>
  playerFetch<Record<string, unknown>>("/player-room/me/combat/end-turn", {
    method: "POST",
    body: JSON.stringify({ combat_version: combatVersion, idempotency_key: crypto.randomUUID() }),
  });

export const searchPlayerRules = (text: string, signal?: AbortSignal) =>
  playerFetch<{ items: PlayerRuleHit[] }>("/player-room/me/rules/search", {
    method: "POST",
    body: JSON.stringify({ text, limit: 10 }),
    signal,
  }).then((result) => result.items);

export const logoutPlayerRoom = () =>
  playerFetch<void>("/player-room/logout", { method: "POST" });

export const isPlayerSessionMissing = (error: unknown): boolean =>
  error instanceof PlayerRoomApiError && error.status === 401;
