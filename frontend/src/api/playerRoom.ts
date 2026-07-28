import { apiFetch, ApiError } from "./client";
import { createClientId } from "../ui/id";

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
  equipment_assets: PlayerEquipmentAsset[];
  active_attunements: number;
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

export type PlayerEquipmentSlot = "armor" | "main_hand" | "off_hand" | "focus" | "worn";

export type PlayerEquipmentAsset = {
  id: string;
  name: string;
  category: string;
  quantity: number;
  armor_class: number | null;
  equipped: boolean;
  attunement_required: boolean;
  attuned: boolean;
  charges: number | null;
  max_charges: number | null;
  slot: PlayerEquipmentSlot | null;
  metadata_json: Record<string, unknown>;
  profile: {
    kind: "armor" | "shield" | "weapon" | "focus" | "worn";
    allowed_slots: PlayerEquipmentSlot[];
    default_slot: PlayerEquipmentSlot;
    hand_usage: number;
    two_handed: boolean;
    armor_type: "light" | "medium" | "heavy" | null;
    base_armor_class: number | null;
    rule_reference: string;
  };
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
  entity_type: "character" | "npc" | "monster" | "marker";
  entity_id: string | null;
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
  interaction?: Record<string, unknown>;
};

export type NoncombatActionOption = {
  id: string;
  kind: "skill" | "tool" | "spell";
  name: string;
  description: string;
  ability?: string;
  ability_label?: string;
  suggested_dc?: number;
  range?: string | null;
  duration?: string | null;
  concentration?: boolean;
  resource_key?: string | null;
  resource_cost?: number;
  target_types: Array<"self" | "npc" | "monster" | "object" | "area">;
};

export type NoncombatPendingAction = {
  id: string;
  version: number;
  message: string | null;
  payload: {
    phase?: "awaiting_player_roll" | "resolved" | "dm_confirmed";
    action?: NoncombatActionOption;
    target?: { type?: string; id?: string; name?: string };
    resolution?: {
      kind?: string;
      instruction?: string;
      modifier?: number;
      dc?: number;
      raw_roll?: number;
      total?: number;
      success?: boolean;
      save?: Record<string, unknown>;
    };
    proposal?: { kind?: string; summary?: string };
    cost?: Record<string, unknown>;
    narrative_suggestions?: string[];
  };
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
  speed_ft: number;
  ability_scores: Record<string, number>;
  actions: Array<string | Record<string, unknown>>;
  damage_resistances: string[];
  damage_immunities: string[];
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
  actor_combatant_id: string | null;
  actor_name: string | null;
  target_combatant_id: string | null;
  target_name: string | null;
  damage_on_success: number;
  damage_on_failure: number;
  damage_type: string | null;
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
  log: Array<{
    id: string;
    summary: string;
    round_number: number;
    turn_index: number;
    status: string;
    action_type?: string;
    actor_combatant_id?: string | null;
    actor_name?: string | null;
    target_combatant_ids?: string[];
    target_names?: string[];
    action_name?: string | null;
    from_position?: { row: number; col: number } | null;
    to_position?: { row: number; col: number } | null;
    movement_spent_ft?: number | null;
    resolution_type?: string | null;
    dc?: number | null;
    roll_formula?: string | null;
    damage?: number | null;
    created_at?: string;
  }>;
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
    noncombat: {
      available_actions: NoncombatActionOption[];
      pending_actions: NoncombatPendingAction[];
    };
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
  skill_proficiencies: string[];
  spells?: Array<Record<string, unknown>>;
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

export class PlayerRoomApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, {
      code: `http_${status}`,
      message,
      details: null,
      request_id: "player-gateway",
    });
    this.name = "PlayerRoomApiError";
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

export const getDmNoncombatActions = (
  campaignId: string,
  characterId: string,
  signal?: AbortSignal,
) => apiFetch<{
  available_actions: NoncombatActionOption[];
  pending_actions: NoncombatPendingAction[];
}>(
  `/campaigns/${campaignId}/player-room/dm/noncombat-actions/${characterId}`,
  { signal },
);

export const planDmNoncombatAction = (
  campaignId: string,
  input: {
    character_id: string;
    action_id: string;
    target_type: "self" | "npc" | "monster" | "object" | "area";
    target_id: string | null;
    message: string;
  },
) => apiFetch<Record<string, unknown>>(
  `/campaigns/${campaignId}/player-room/dm/noncombat-actions/plan`,
  {
    method: "POST",
    body: {
      ...input,
      idempotency_key: createClientId("dm-noncombat-plan"),
    },
  },
);

export const rollDmNoncombatAction = (
  campaignId: string,
  characterId: string,
  requestId: string,
  version: number,
  rawRoll: number,
) => apiFetch<Record<string, unknown>>(
  `/campaigns/${campaignId}/player-room/dm/noncombat-actions/${requestId}/roll`,
  {
    method: "POST",
    body: {
      character_id: characterId,
      version,
      raw_roll: rawRoll,
    },
  },
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

export type PlayerEquipmentOperation = {
  equipment_id: string;
  operation: "equip" | "unequip" | "attune" | "unattune";
  slot?: PlayerEquipmentSlot | null;
  preview_token?: string;
  idempotency_key?: string;
};

export const previewMyEquipment = (input: PlayerEquipmentOperation) =>
  playerFetch<Record<string, unknown>>("/player-room/me/equipment/preview", {
    method: "POST",
    body: JSON.stringify(input),
  });

export const confirmMyEquipment = (input: PlayerEquipmentOperation) =>
  playerFetch<Record<string, unknown>>("/player-room/me/equipment/confirm", {
    method: "POST",
    body: JSON.stringify(input),
  });

export const submitMyActionRequest = (actionType: string, message: string) =>
  playerFetch<Record<string, unknown>>("/player-room/me/action-requests", {
    method: "POST",
    body: JSON.stringify({
      action_type: actionType,
      message,
      payload_json: {},
      idempotency_key: createClientId("player-action"),
    }),
  });

export const planMyNoncombatAction = (
  actionId: string,
  targetType: "self" | "npc" | "monster" | "object" | "area",
  targetId: string | null,
  message: string,
) => playerFetch<Record<string, unknown>>("/player-room/me/noncombat-actions/plan", {
  method: "POST",
  body: JSON.stringify({
    action_id: actionId,
    target_type: targetType,
    target_id: targetId,
    message,
    idempotency_key: createClientId("noncombat-plan"),
  }),
});

export const rollMyNoncombatAction = (
  requestId: string,
  version: number,
  rawRoll: number,
) => playerFetch<Record<string, unknown>>(`/player-room/me/noncombat-actions/${requestId}/roll`, {
  method: "POST",
  body: JSON.stringify({ version, raw_roll: rawRoll }),
});

export const moveMyCombatant = (row: number, col: number, combatantVersion: number) =>
  playerFetch<Record<string, unknown>>("/player-room/me/combat/move", {
    method: "POST",
    body: JSON.stringify({ row, col, combatant_version: combatantVersion }),
  });

export const attackWithMyCombatant = (
  targetId: string,
  targetIds: string[],
  actionName: string,
  attackTotal: number,
  damageTotal: number,
  endTurnAfter = false,
) => playerFetch<Record<string, unknown>>("/player-room/me/combat/attack", {
  method: "POST",
  body: JSON.stringify({
    target_combatant_id: targetId,
    target_combatant_ids: targetIds,
    action_name: actionName,
    attack_total: attackTotal,
    damage_total: damageTotal,
    end_turn_after: endTurnAfter,
    idempotency_key: createClientId("player-attack"),
  }),
});

export const submitMyPlayerRoll = (actionId: string, actionVersion: number, rollTotal: number) =>
  playerFetch<Record<string, unknown>>(`/player-room/me/combat/player-rolls/${actionId}`, {
    method: "POST",
    body: JSON.stringify({
      action_version: actionVersion,
      roll_total: rollTotal,
      idempotency_key: createClientId("player-roll"),
    }),
  });

export const endMyTurn = (combatVersion: number) =>
  playerFetch<Record<string, unknown>>("/player-room/me/combat/end-turn", {
    method: "POST",
    body: JSON.stringify({
      combat_version: combatVersion,
      idempotency_key: createClientId("player-end-turn"),
    }),
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
