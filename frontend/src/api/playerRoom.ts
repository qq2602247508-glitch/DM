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
  wallet: { id?: string; name: string; copper: number; gp: number; version?: number } | null;
  conditions?: Array<{ id: string; name: string; source: string | null; duration: string | null; status: string; details: Record<string, unknown>; version: number }>;
  hit_dice?: PlayerHitDieResource[];
  version: number;
  companions?: PlayerCompanion[];
};

export type PlayerCompanion = {
  id: string;
  name: string;
  companion_type: "familiar" | "animal_companion" | "summon" | "wild_shape" | "form";
  source_record_id: string | null;
  template_json: Record<string, unknown>;
  hp: number;
  max_hp: number;
  armor_class: number;
  speed: number;
  active: boolean;
};

export type PlayerHitDieResource = {
  id: string;
  key: string;
  label: string;
  category: "hit_die";
  current: number;
  maximum: number;
  die_size: number | null;
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
    kind: "armor" | "shield" | "weapon" | "focus" | "worn" | "consumable";
    allowed_slots: PlayerEquipmentSlot[];
    default_slot: PlayerEquipmentSlot | null;
    hand_usage: number;
    two_handed: boolean;
    armor_type: "light" | "medium" | "heavy" | null;
    base_armor_class: number | null;
    rule_reference: string;
  };
};

export type PlayerShopStock = {
  id: string;
  name: string;
  quantity: number;
  price_copper: number;
  version: number;
  category: string | null;
  item_tier: string | null;
};

export type PlayerShop = {
  merchant_id: string;
  name: string;
  description: string | null;
  stock: PlayerShopStock[];
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
  theme?: string | null;
  visual_theme?: Record<string, unknown>;
  fog_of_war?: boolean;
  explored_cells?: Array<{ row: number; col: number }>;
  visible_cells?: Array<{ row: number; col: number }>;
  cells?: Array<{
    row: number;
    col: number;
    kind: string;
    label?: string;
    blocks_sight?: boolean;
    sight_transparency?: string;
  }>;
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
  version?: number;
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
  rule_plan?: Record<string, unknown>;
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
  position: { row: number; col: number; elevation_ft?: number } | null;
  health_status: string;
  is_own: boolean;
  controller?: "player" | "dm" | null;
  owner_character_id?: string | null;
  disposition?: "ally" | "enemy" | null;
  version?: number;
  hp?: number;
  max_hp?: number;
  temporary_hp?: number;
  armor_class?: number;
  conditions?: unknown[];
  movement_remaining_ft?: number;
  action_available?: boolean;
  bonus_action_available?: boolean;
  reaction_available?: boolean;
  extra_action_budget?: number;
  attack_roll_budget?: number;
  bardic_inspiration_die?: { value?: string | null; source?: string | null } | null;
  speed_ft: number;
  ability_scores: Record<string, number>;
  actions: Array<string | Record<string, unknown>>;
  active_action?: Record<string, unknown> | null;
  damage_resistances: string[];
  damage_vulnerabilities: string[];
  damage_immunities: string[];
  active_effects?: Array<{
    id: string;
    name: string;
    effect_type: string;
    duration_unit: string;
    duration_value: number | null;
    ends_round: number | null;
    trigger_timing: string | null;
    rule_block: Record<string, unknown> | null;
  }>;
  summon?: {
    source_combatant_id?: string | null;
    lifecycle_effect_id?: string | null;
    duration?: { unit?: string; value?: number | null; requires_concentration?: boolean } | null;
    enemy_ai_mode?: "dm_only" | "basic" | "not_applicable" | null;
  };
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
  effect_target_combatant_id?: string | null;
  effect_target_name?: string | null;
  damage_on_success: number;
  damage_on_failure: number;
  damage_type: string | null;
  damage_components_on_success?: Array<{ amount: number; damage_type: string; damage_tags?: string[] }>;
  damage_components_on_failure?: Array<{ amount: number; damage_type: string; damage_tags?: string[] }>;
  damage_tags?: string[];
  action_cost?: "action" | "bonus_action" | "reaction" | "legendary_action" | "lair_action" | "none";
  legendary_cost?: number | null;
  legendary_pool_max?: number | null;
  reaction_trigger?: string | null;
  sequence_step?: number | null;
  sequence_size?: number | null;
  bardic_inspiration_die?: { value?: string | null; source?: string | null } | null;
};

export type PlayerPendingReaction = {
  id: string;
  version: number;
  kind?: "opportunity" | "pre_damage" | "deflect_redirect";
  feature_id?: string | null;
  feature_name?: string | null;
  requires_reduction_roll?: boolean;
  damage_reduction_formula?: string | null;
  damage_reduction_bonus?: number | null;
  eligible_damage_types?: string[] | "all" | null;
  source_name: string | null;
  source_action_name: string | null;
  damage_expression: string | null;
  damage_type: string | null;
  target_name: string | null;
  reaction_trigger: string | null;
  message: string | null;
  candidate_target_ids?: string[];
  candidate_target_names?: Record<string, string>;
  save_ability?: string | null;
  save_dc?: number | null;
  damage_die_expression?: string | null;
  damage_die_sides?: number | null;
  damage_dice_count?: number | null;
  damage_modifier?: number | null;
  resource_key?: string | null;
  resource_cost?: number | null;
};

export type PlayerDeathSave = {
  combatant_id: string;
  successes: number;
  failures: number;
  stable: boolean;
  dead: boolean;
  pending_death_confirmation: boolean;
  last_roll: number | null;
  version: number;
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
  own_combatant_ids?: string[];
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
    damage_type?: string | null;
    damage_components?: Array<Record<string, unknown>>;
    damage_components_by_target?: Array<{
      target_combatant_id: string;
      target_name: string;
      damage_components: Array<Record<string, unknown>>;
    }>;
    created_at?: string;
  }>;
  pending_rolls: PlayerPendingRoll[];
  pending_reactions: PlayerPendingReaction[];
  death_save: PlayerDeathSave | null;
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
      available_transitions: Array<{
        connector_id: string;
        direction: "stairs_up" | "stairs_down";
        label: string;
        row: number;
        col: number;
        from_scene_id: string;
        target_scene_id: string;
        target_level_index: number;
        target_level_name: string;
      }>;
    };
    handouts: Array<{ id: string; title: string; body: string; sort_order: number }>;
    shared_log: Array<{ id: string; event_type: string; title: string; description: string | null; occurred_at: string }>;
    shops?: PlayerShop[];
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
  ability_generation_method: "standard_array" | "point_buy" | "rolled_4d6_drop_lowest";
  ability_rolls?: Record<string, number[]>;
  origin_ability_increases: Record<string, number>;
  background_tool_proficiency: string;
  languages: string[];
  starter_equipment_option: "fixed_package";
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
  expectedVersion?: number,
) => apiFetch<PlayerRoom>(`/campaigns/${campaignId}/player-room/live-state`, {
  method: "POST",
  body: {
    scene_id: sceneId,
    combat_id: combatId,
    ...(expectedVersion === undefined ? {} : { expected_version: expectedVersion }),
  },
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
  input: { attack_total?: number; damage_total?: number; critical_hit?: boolean } = {},
) => apiFetch<PlayerActionRequest>(
  `/campaigns/${campaignId}/player-action-requests/${requestId}/${decision}`,
  { method: "POST", body: { version, dm_note: null, ...input } },
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

export const switchPlayerRoom = (joinCode: string, displayName: string) =>
  playerFetch<{ campaign: { id: string; name: string }; player: { id: string; display_name: string }; expires_at: string }>(
    "/player-room/switch",
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
  operation: "equip" | "unequip" | "consume" | "use_charge" | "attune" | "unattune";
  slot?: PlayerEquipmentSlot | null;
  amount?: number;
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

export type PlayerCommerceOperation = {
  wallet_id: string;
  wallet_version: number;
  shop_inventory_id: string;
  shop_version: number;
  quantity: number;
  preview_token?: string;
  idempotency_key?: string;
};

export const previewMyCommerce = (input: PlayerCommerceOperation) =>
  playerFetch<Record<string, unknown>>("/player-room/me/commerce/preview", {
    method: "POST",
    body: JSON.stringify(input),
  });

export const confirmMyCommerce = (input: PlayerCommerceOperation) =>
  playerFetch<Record<string, unknown>>("/player-room/me/commerce/confirm", {
    method: "POST",
    body: JSON.stringify(input),
  });

export const submitMyActionRequest = (
  actionType: string,
  message: string,
  payloadJson: Record<string, unknown> = {},
) =>
  playerFetch<Record<string, unknown>>("/player-room/me/action-requests", {
    method: "POST",
    body: JSON.stringify({
      action_type: actionType,
      message,
      payload_json: payloadJson,
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

export const moveMyCombatant = (row: number, col: number, combatantVersion: number, disengage = false) =>
  playerFetch<Record<string, unknown>>("/player-room/me/combat/move", {
    method: "POST",
    body: JSON.stringify({ row, col, combatant_version: combatantVersion, disengage }),
  });

export const moveMonsterCombatant = (
  campaignId: string,
  combatId: string,
  combatantId: string,
  row: number,
  col: number,
  combatantVersion: number,
  movementRemainingFt: number,
) => apiFetch<Record<string, unknown>>(
  `/campaigns/${campaignId}/player-room/combat/${combatId}/monster-move/${combatantId}`,
  {
    method: "POST",
    body: {
      row,
      col,
      combatant_version: combatantVersion,
      movement_remaining_ft: movementRemainingFt,
    },
  },
);

export type PlayerCombatManeuver = {
  action_type:
    | "dash"
    | "stand_up"
    | "grapple"
    | "shove"
    | "dodge"
    | "help"
    | "ready"
    | "search"
    | "hide"
    | "disengage"
    | "use_item"
    | "object_interaction";
  actor_version: number;
  target_combatant_id?: string;
  target_version?: number;
  outcome?: "success" | "failure";
  shove_mode?: "prone" | "push";
  push_distance_ft?: number;
  adjudication_note?: string;
  help_trigger?: string;
  ready_phase?: "prepare" | "trigger";
  ready_trigger?: string;
  ready_response?: string;
  ready_effect_id?: string;
  ready_effect_version?: number;
  item_id?: string;
  item_version?: number;
  object_id?: string;
  object_version?: number;
  object_state?: "active" | "open" | "closed" | "destroyed" | "disarmed" | "picked_up";
};

export const performMyCombatManeuver = (input: PlayerCombatManeuver) =>
  playerFetch<Record<string, unknown>>("/player-room/me/combat/maneuver", {
    method: "POST",
    body: JSON.stringify({
      ...input,
      idempotency_key: createClientId(`player-maneuver-${input.action_type}`),
    }),
  });

export const attackWithMyCombatant = (
  targetId: string,
  targetIds: string[],
  actionName: string,
  slotLevel: number | null,
  attackTotal: number,
  damageTotal: number,
  criticalHit = false,
  endTurnAfter = false,
  execution: {
    damageComponentTotals?: Record<string, number>;
    targetDamageComponentTotals?: Record<string, Record<string, number>>;
    reactionTrigger?: string;
    specialInputs?: Record<string, unknown>;
  } = {},
) => playerFetch<Record<string, unknown>>("/player-room/me/combat/attack", {
  method: "POST",
  body: JSON.stringify({
    target_combatant_id: targetId,
    target_combatant_ids: targetIds,
    action_name: actionName,
    slot_level: slotLevel,
    attack_total: attackTotal,
    damage_total: damageTotal,
    damage_component_totals: execution.damageComponentTotals ?? {},
    target_damage_component_totals: execution.targetDamageComponentTotals ?? {},
    reaction_trigger: execution.reactionTrigger ?? null,
    special_inputs: execution.specialInputs ?? {},
    critical_hit: criticalHit,
    end_turn_after: endTurnAfter,
    idempotency_key: createClientId("player-attack"),
  }),
});

export const castMyCombatAction = (
  targetId: string,
  targetIds: string[],
  actionName: string,
  slotLevel: number | null,
  healingTotal: number,
  endTurnAfter = false,
  specialInputs: Record<string, unknown> = {},
) => playerFetch<Record<string, unknown>>("/player-room/me/combat/cast", {
  method: "POST",
  body: JSON.stringify({
    target_combatant_id: targetId,
    target_combatant_ids: targetIds,
    action_name: actionName,
    slot_level: slotLevel,
    healing_total: healingTotal,
    special_inputs: specialInputs,
    end_turn_after: endTurnAfter,
    idempotency_key: createClientId("player-cast"),
  }),
});

export const submitMyFeatureAction = (
  featureId: string,
  targetCombatantId: string | null,
  healingTotal: number | null,
  selectedAction?: "dash" | "disengage" | "hide",
  outcome?: "success" | "failure",
  adjudicationNote?: string,
  conditionToCure?: "poisoned" | "diseased",
) => playerFetch<Record<string, unknown>>("/player-room/me/combat/feature-action", {
  method: "POST",
  body: JSON.stringify({
    feature_id: featureId,
    target_combatant_id: targetCombatantId,
    selected_action: selectedAction ?? null,
    outcome: outcome ?? null,
    adjudication_note: adjudicationNote ?? null,
    healing_total: healingTotal,
    condition_to_cure: conditionToCure ?? null,
    idempotency_key: createClientId("player-feature-action"),
  }),
});

export const summonMyCompanion = (
  companionId: string,
  actionName: string,
  count = 1,
  position?: { row: number; col: number },
) =>
  playerFetch<Record<string, unknown>>("/player-room/me/combat/summon", {
    method: "POST",
    body: JSON.stringify({
      companion_id: companionId,
      action_name: actionName,
      count,
      position: position ?? null,
      idempotency_key: createClientId("player-summon"),
    }),
  });

export const dismissMySummon = (
  summonCombatantId: string,
  summonVersion: number,
  reason = "玩家主动结束召唤",
) => playerFetch<Record<string, unknown>>(`/player-room/me/combat/summons/${summonCombatantId}/dismiss`, {
  method: "POST",
  body: JSON.stringify({
    summon_version: summonVersion,
    reason,
    idempotency_key: createClientId("player-dismiss-summon"),
  }),
});

export const submitMyPlayerRoll = (
  actionId: string,
  actionVersion: number,
  rollTotal: number,
  bardicInspirationTotal?: number,
) =>
  playerFetch<Record<string, unknown>>(`/player-room/me/combat/player-rolls/${actionId}`, {
    method: "POST",
    body: JSON.stringify({
      action_version: actionVersion,
      roll_total: rollTotal,
      ...(bardicInspirationTotal !== undefined
        ? { bardic_inspiration_total: bardicInspirationTotal }
        : {}),
      idempotency_key: createClientId("player-roll"),
    }),
  });

export const resolveMyOpportunityReaction = (
  requestId: string,
  version: number,
  decision: "accept" | "reject",
) => playerFetch<Record<string, unknown>>(`/player-room/me/combat/reactions/${requestId}`, {
  method: "POST",
  body: JSON.stringify({ version, decision }),
});

export const resolveMyPreDamageReaction = (
  windowId: string,
  version: number,
  decision: "accept" | "reject",
  featureId?: string,
  reductionRoll?: number,
) => playerFetch<Record<string, unknown>>(`/player-room/me/combat/pre-damage-reactions/${windowId}`, {
  method: "POST",
  body: JSON.stringify({ version, decision, feature_id: featureId ?? null, reduction_roll: reductionRoll ?? null }),
});

export const resolveMyDeflectRedirect = (
  windowId: string,
  version: number,
  input: {
    decision: "accept" | "reject";
    target_combatant_id?: string | null;
    target_version?: number | null;
    saving_throw_roll?: number | null;
    damage_rolls?: number[];
  },
) => playerFetch<Record<string, unknown>>(`/player-room/me/combat/deflect-redirect/${windowId}`, {
  method: "POST",
  body: JSON.stringify({ version, ...input }),
  headers: { "X-Request-ID": createClientId("player-deflect-redirect") },
});

export const submitMyDeathSave = (targetVersion: number, roll: number) =>
  playerFetch<Record<string, unknown>>("/player-room/me/combat/death-save", {
    method: "POST",
    body: JSON.stringify({
      target_version: targetVersion,
      roll,
      idempotency_key: createClientId("player-death-save"),
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
