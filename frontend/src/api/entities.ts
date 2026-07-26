import { apiFetch } from "./client";
import type {
  CampaignEvent,
  CharacterCompanion,
  CharacterOptionsCatalog,
  AdvancementPreview,
  AdvancementRequest,
  Character,
  CharacterCondition,
  Clue,
  Combat,
  CombatAction,
  CombatActionConfirmation,
  CombatActionPreview,
  Combatant,
  CombatEffect,
  CombatEffectConfirmation,
  CombatSettlementPreview,
  CombatSettlementResult,
  ConcentrationCheckResult,
  DeathSave,
  DeathSaveConfirmation,
  EncounterAdjustment,
  EncounterOperation,
  ListEnvelope,
  Location,
  Npc,
  ProposalEntityType,
  Quest,
  ResourcePool,
  RestConfirmRequest,
  RestPreview,
  RestPreviewRequest,
  TurnAdvanceResult,
} from "./types";

/**
 * Typed wrappers over the nested campaign-state CRUD routes. All mutations
 * send the entity `version` in the request body (backend accepts body version
 * in place of If-Match).
 */

async function listEntities<T>(path: string, signal?: AbortSignal): Promise<T[]> {
  const separator = path.includes("?") ? "&" : "?";
  const envelope = await apiFetch<ListEnvelope<T>>(`${path}${separator}limit=200`, { signal });
  return envelope.items;
}

/** Resource path segments for proposal-targeted entity types. */
const PROPOSAL_RESOURCE_PATHS: Record<ProposalEntityType, string> = {
  character: "characters",
  npc: "npcs",
  quest: "quests",
  event: "events",
};

/** Fetch a single proposal-targeted entity (for before/after diffs). */
export function getProposalEntity(
  campaignId: string,
  entityType: ProposalEntityType,
  entityId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(
    `/campaigns/${campaignId}/${PROPOSAL_RESOURCE_PATHS[entityType]}/${entityId}`,
    { signal },
  );
}

function createEntity<T, TInput>(path: string, input: TInput): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: input });
}

function patchEntity<T, TInput extends object>(
  path: string,
  input: TInput,
  version: number,
): Promise<T> {
  return apiFetch<T>(path, {
    method: "PATCH",
    body: { ...input, version },
  });
}

function deleteEntity(path: string, version: number): Promise<void> {
  const separator = path.includes("?") ? "&" : "?";
  return apiFetch<void>(`${path}${separator}version=${version}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Characters
// ---------------------------------------------------------------------------

export type CharacterInput = {
  name?: string;
  race?: string | null;
  background?: string | null;
  class_name?: string | null;
  level?: number;
  experience?: number;
  armor_class?: number;
  speed?: number;
  ability_scores?: Record<string, number>;
  hp?: number;
  max_hp?: number;
  max_hp_reduction?: number;
  ability_score_reductions?: Record<string, number>;
  death_saves?: { successes: number; failures: number };
  inventory?: unknown[];
  equipment?: unknown[];
  proficiencies?: unknown[];
  skills?: Record<string, unknown>;
  features?: unknown[];
  actions?: unknown[];
  resources?: Record<string, unknown>;
  spells?: unknown[];
  spellcasting?: Record<string, unknown>;
  class_levels?: Record<string, number>;
  subclass_choices?: Record<string, string>;
  notes?: string | null;
};

export const listCharacters = (cid: string, signal?: AbortSignal) =>
  listEntities<Character>(`/campaigns/${cid}/characters`, signal);

export const createCharacter = (cid: string, input: CharacterInput) =>
  createEntity<Character, CharacterInput>(`/campaigns/${cid}/characters`, input);

export const updateCharacter = (cid: string, id: string, input: CharacterInput, version: number) =>
  patchEntity<Character, CharacterInput>(`/campaigns/${cid}/characters/${id}`, input, version);

export const deleteCharacter = (cid: string, id: string, version: number) =>
  deleteEntity(`/campaigns/${cid}/characters/${id}`, version);

export const getCharacterOptions = (signal?: AbortSignal) =>
  apiFetch<CharacterOptionsCatalog>("/rules/character-options", { signal });

export const previewAdvancement = (
  cid: string,
  characterId: string,
  input: AdvancementRequest,
) =>
  apiFetch<AdvancementPreview>(
    `/campaigns/${cid}/characters/${characterId}/advancement/preview`,
    { method: "POST", body: input },
  );

export const confirmAdvancement = (
  cid: string,
  characterId: string,
  input: AdvancementRequest & { preview_token: string; idempotency_key: string },
) =>
  apiFetch<AdvancementPreview & { advancement_record_id: string }>(
    `/campaigns/${cid}/characters/${characterId}/advancement/confirm`,
    { method: "POST", body: input },
  );

export const listCompanions = (
  cid: string,
  ownerCharacterId?: string,
  signal?: AbortSignal,
) =>
  apiFetch<ListEnvelope<CharacterCompanion>>(
    `/campaigns/${cid}/companions${ownerCharacterId ? `?owner_character_id=${encodeURIComponent(ownerCharacterId)}` : ""}`,
    { signal },
  ).then((result) => result.items);

export type CompanionInput = Omit<
  CharacterCompanion,
  keyof import("./types").Versioned | "campaign_id"
>;

export const createCompanion = (cid: string, input: CompanionInput) =>
  createEntity<CharacterCompanion, CompanionInput>(`/campaigns/${cid}/companions`, input);

export const updateCompanion = (
  cid: string,
  id: string,
  input: Partial<CompanionInput>,
  version: number,
) => patchEntity<CharacterCompanion, Partial<CompanionInput>>(
  `/campaigns/${cid}/companions/${id}`,
  input,
  version,
);

export const listResourcePools = (cid: string, characterId?: string, signal?: AbortSignal) =>
  apiFetch<{ items: ResourcePool[] }>(`/campaigns/${cid}/resources${characterId ? `?character_id=${encodeURIComponent(characterId)}` : ""}`, { signal })
    .then((result) => result.items);

export const previewRest = (cid: string, input: RestPreviewRequest) =>
  apiFetch<RestPreview>(`/campaigns/${cid}/rests/preview`, { method: "POST", body: input });

export const confirmRest = (cid: string, input: RestConfirmRequest) =>
  apiFetch<RestPreview>(`/campaigns/${cid}/rests/confirm`, { method: "POST", body: input });

// Character conditions -------------------------------------------------------

export type ConditionInput = {
  condition_name?: string;
  source?: string | null;
  duration?: string | null;
  notes?: string | null;
  details?: Record<string, unknown>;
};

export const listConditions = (cid: string, characterId: string, signal?: AbortSignal) =>
  listEntities<CharacterCondition>(
    `/campaigns/${cid}/characters/${characterId}/conditions`,
    signal,
  );

export const createCondition = (cid: string, characterId: string, input: ConditionInput) =>
  createEntity<CharacterCondition, ConditionInput>(
    `/campaigns/${cid}/characters/${characterId}/conditions`,
    input,
  );

export const deleteCondition = (cid: string, characterId: string, id: string, version: number) =>
  deleteEntity(`/campaigns/${cid}/characters/${characterId}/conditions/${id}`, version);

// ---------------------------------------------------------------------------
// NPCs
// ---------------------------------------------------------------------------

export type NpcInput = {
  name?: string;
  description?: string | null;
  alignment?: string | null;
  attitude?: string | null;
  personality?: string | null;
  goal?: string | null;
  fear?: string | null;
  armor_class?: number;
  hp?: number;
  max_hp?: number;
  speed?: number;
  ability_scores?: Record<string, number>;
  challenge_rating?: string | null;
  actions?: unknown[];
  equipment?: unknown[];
  relationship?: string | null;
  secrets?: string | null;
  known_information?: string | null;
  location_id?: string | null;
  status?: string;
};

export const listNpcs = (cid: string, signal?: AbortSignal) =>
  listEntities<Npc>(`/campaigns/${cid}/npcs`, signal);

export const createNpc = (cid: string, input: NpcInput) =>
  createEntity<Npc, NpcInput>(`/campaigns/${cid}/npcs`, input);

export const updateNpc = (cid: string, id: string, input: NpcInput, version: number) =>
  patchEntity<Npc, NpcInput>(`/campaigns/${cid}/npcs/${id}`, input, version);

export const deleteNpc = (cid: string, id: string, version: number) =>
  deleteEntity(`/campaigns/${cid}/npcs/${id}`, version);

// ---------------------------------------------------------------------------
// Locations
// ---------------------------------------------------------------------------

export type LocationInput = {
  name?: string;
  parent_location_id?: string | null;
  depth?: number;
  description?: string | null;
  interactive_objects?: unknown[];
  secrets?: string | null;
  discovered?: boolean;
  notes?: string | null;
};

export const listLocations = (cid: string, signal?: AbortSignal) =>
  listEntities<Location>(`/campaigns/${cid}/locations`, signal);

export const createLocation = (cid: string, input: LocationInput) =>
  createEntity<Location, LocationInput>(`/campaigns/${cid}/locations`, input);

export const updateLocation = (cid: string, id: string, input: LocationInput, version: number) =>
  patchEntity<Location, LocationInput>(`/campaigns/${cid}/locations/${id}`, input, version);

export const deleteLocation = (cid: string, id: string, version: number) =>
  deleteEntity(`/campaigns/${cid}/locations/${id}`, version);

// ---------------------------------------------------------------------------
// Quests
// ---------------------------------------------------------------------------

export type QuestInput = {
  name?: string;
  description?: string | null;
  quest_type?: "main" | "side" | "personal" | "faction";
  giver?: string | null;
  reward?: string | null;
  xp_reward?: number;
  xp_awarded?: boolean;
  status?: string;
  notes?: string | null;
};

export const listQuests = (cid: string, signal?: AbortSignal) =>
  listEntities<Quest>(`/campaigns/${cid}/quests`, signal);

export const createQuest = (cid: string, input: QuestInput) =>
  createEntity<Quest, QuestInput>(`/campaigns/${cid}/quests`, input);

export const updateQuest = (cid: string, id: string, input: QuestInput, version: number) =>
  patchEntity<Quest, QuestInput>(`/campaigns/${cid}/quests/${id}`, input, version);

export const deleteQuest = (cid: string, id: string, version: number) =>
  deleteEntity(`/campaigns/${cid}/quests/${id}`, version);

// ---------------------------------------------------------------------------
// Clues
// ---------------------------------------------------------------------------

export type ClueInput = {
  name?: string;
  description?: string | null;
  player_text?: string | null;
  dm_truth?: string | null;
  verified?: boolean;
  quest_id?: string | null;
  discovered?: boolean;
  discovered_at?: string | null;
  source_event_id?: string | null;
};

export const listClues = (cid: string, signal?: AbortSignal) =>
  listEntities<Clue>(`/campaigns/${cid}/clues`, signal);

export const createClue = (cid: string, input: ClueInput) =>
  createEntity<Clue, ClueInput>(`/campaigns/${cid}/clues`, input);

export const updateClue = (cid: string, id: string, input: ClueInput, version: number) =>
  patchEntity<Clue, ClueInput>(`/campaigns/${cid}/clues/${id}`, input, version);

export const deleteClue = (cid: string, id: string, version: number) =>
  deleteEntity(`/campaigns/${cid}/clues/${id}`, version);

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

export type EventInput = {
  title?: string;
  event_type?: string;
  description?: string | null;
  occurred_at?: string | null;
  location_id?: string | null;
  visibility?: "dm" | "players" | "public";
  metadata_json?: Record<string, unknown>;
};

export const listEvents = (cid: string, signal?: AbortSignal) =>
  listEntities<CampaignEvent>(`/campaigns/${cid}/events`, signal);

export const createEvent = (cid: string, input: EventInput) =>
  createEntity<CampaignEvent, EventInput>(`/campaigns/${cid}/events`, input);

export const updateEvent = (cid: string, id: string, input: EventInput, version: number) =>
  patchEntity<CampaignEvent, EventInput>(`/campaigns/${cid}/events/${id}`, input, version);

export const deleteEvent = (cid: string, id: string, version: number) =>
  deleteEntity(`/campaigns/${cid}/events/${id}`, version);

// Encounter adjustment proposals --------------------------------------------

export type EncounterAdjustmentInput = {
  scene_id: string;
  combat_id?: string | null;
  source_event_id?: string | null;
  title: string;
  reason: string;
  difficulty_shift: -1 | 0 | 1;
  operations: EncounterOperation[];
};

export const listEncounterAdjustments = (
  cid: string,
  sceneId?: string,
  signal?: AbortSignal,
) =>
  listEntities<EncounterAdjustment>(
    `/campaigns/${cid}/encounter-adjustments${sceneId ? `?scene_id=${encodeURIComponent(sceneId)}` : ""}`,
    signal,
  );

export const createEncounterAdjustment = (cid: string, input: EncounterAdjustmentInput) =>
  createEntity<EncounterAdjustment, EncounterAdjustmentInput>(
    `/campaigns/${cid}/encounter-adjustments`,
    input,
  );

export const rejectEncounterAdjustment = (cid: string, id: string, version: number) =>
  apiFetch<EncounterAdjustment>(`/campaigns/${cid}/encounter-adjustments/${id}/reject`, {
    method: "POST",
    headers: { "If-Match": `"${version}"`, "X-Request-ID": crypto.randomUUID() },
  });

export const applyEncounterAdjustment = (cid: string, id: string, version: number) =>
  apiFetch<EncounterAdjustment>(`/campaigns/${cid}/encounter-adjustments/${id}/apply`, {
    method: "POST",
    headers: { "If-Match": `"${version}"`, "X-Request-ID": crypto.randomUUID() },
  });

export const revertEncounterAdjustment = (cid: string, id: string, version: number) =>
  apiFetch<EncounterAdjustment>(`/campaigns/${cid}/encounter-adjustments/${id}/revert`, {
    method: "POST",
    headers: { "If-Match": `"${version}"`, "X-Request-ID": crypto.randomUUID() },
  });

// ---------------------------------------------------------------------------
// Combats & combatants
// ---------------------------------------------------------------------------

export type CombatInput = {
  name?: string;
  scene_id?: string | null;
  status?: string;
  round_number?: number;
  current_turn_index?: number;
  difficulty?: "trivial" | "low" | "moderate" | "high" | null;
  base_xp?: number;
  difficulty_adjustments?: unknown[];
  xp_awarded?: boolean;
};

export const listCombats = (cid: string, signal?: AbortSignal) =>
  listEntities<Combat>(`/campaigns/${cid}/combats`, signal);

export const createCombat = (cid: string, input: CombatInput) =>
  createEntity<Combat, CombatInput>(`/campaigns/${cid}/combats`, input);

export const updateCombat = (cid: string, id: string, input: CombatInput, version: number) =>
  patchEntity<Combat, CombatInput>(`/campaigns/${cid}/combats/${id}`, input, version);

export const deleteCombat = (cid: string, id: string, version: number) =>
  deleteEntity(`/campaigns/${cid}/combats/${id}`, version);

export type CombatantInput = {
  display_name?: string;
  entity_type?: string;
  entity_id?: string | null;
  initiative?: number;
  armor_class?: number;
  hp?: number;
  max_hp?: number;
  temporary_hp?: number;
  max_hp_reduction?: number;
  damage_resistances?: string[];
  damage_vulnerabilities?: string[];
  damage_immunities?: string[];
  condition_immunities?: string[];
  conditions?: unknown[];
  concentration?: Record<string, unknown>;
  speed_ft?: number;
  movement_remaining_ft?: number;
  action_available?: boolean;
  bonus_action_available?: boolean;
  reaction_available?: boolean;
  snapshot_json?: Record<string, unknown>;
  is_active?: boolean;
};

export const listCombatants = (cid: string, combatId: string, signal?: AbortSignal) =>
  listEntities<Combatant>(`/campaigns/${cid}/combats/${combatId}/combatants`, signal);

export const createCombatant = (cid: string, combatId: string, input: CombatantInput) =>
  createEntity<Combatant, CombatantInput>(
    `/campaigns/${cid}/combats/${combatId}/combatants`,
    input,
  );

export const updateCombatant = (
  cid: string,
  combatId: string,
  id: string,
  input: CombatantInput,
  version: number,
) =>
  patchEntity<Combatant, CombatantInput>(
    `/campaigns/${cid}/combats/${combatId}/combatants/${id}`,
    input,
    version,
  );

export const deleteCombatant = (cid: string, combatId: string, id: string, version: number) =>
  deleteEntity(`/campaigns/${cid}/combats/${combatId}/combatants/${id}`, version);

export type CombatActionCommand = {
  action_type: "damage" | "heal";
  target_combatant_id: string;
  target_version: number;
  actor_combatant_id?: string | null;
  amount: number;
  damage_type?: string | null;
  dm_override?: boolean;
  override_reason?: string | null;
};

export const previewCombatAction = (
  cid: string,
  combatId: string,
  input: CombatActionCommand,
) =>
  apiFetch<CombatActionPreview>(
    `/campaigns/${cid}/combats/${combatId}/actions/preview`,
    { method: "POST", body: input },
  );

export const confirmCombatAction = (
  cid: string,
  combatId: string,
  input: CombatActionCommand,
) =>
  apiFetch<CombatActionConfirmation>(
    `/campaigns/${cid}/combats/${combatId}/actions/confirm`,
    {
      method: "POST",
      body: input,
      headers: { "X-Request-ID": crypto.randomUUID() },
    },
  );

export const listCombatActions = (
  cid: string,
  combatId: string,
  signal?: AbortSignal,
) =>
  apiFetch<ListEnvelope<CombatAction>>(
    `/campaigns/${cid}/combats/${combatId}/actions`,
    { signal },
  ).then((envelope) => envelope.items);

export const getDeathSave = (
  cid: string,
  combatId: string,
  combatantId: string,
  signal?: AbortSignal,
) =>
  apiFetch<DeathSave>(
    `/campaigns/${cid}/combats/${combatId}/combatants/${combatantId}/death-save`,
    { signal },
  );

export const confirmDeathSave = (
  cid: string,
  combatId: string,
  combatantId: string,
  targetVersion: number,
  roll: number,
) =>
  apiFetch<DeathSaveConfirmation>(
    `/campaigns/${cid}/combats/${combatId}/combatants/${combatantId}/death-save/confirm`,
    {
      method: "POST",
      body: { target_version: targetVersion, roll },
      headers: { "X-Request-ID": crypto.randomUUID() },
    },
  );

export const confirmCombatantDeath = (
  cid: string,
  combatId: string,
  combatantId: string,
  targetVersion: number,
  reason: string,
) =>
  apiFetch<DeathSaveConfirmation>(
    `/campaigns/${cid}/combats/${combatId}/combatants/${combatantId}/death-save/confirm-death`,
    {
      method: "POST",
      body: { target_version: targetVersion, reason },
      headers: { "X-Request-ID": crypto.randomUUID() },
    },
  );

export const advanceCombatTurn = (
  cid: string,
  combatId: string,
  combatVersion: number,
) =>
  apiFetch<TurnAdvanceResult>(
    `/campaigns/${cid}/combats/${combatId}/turns/advance`,
    {
      method: "POST",
      body: { combat_version: combatVersion },
      headers: { "X-Request-ID": crypto.randomUUID() },
    },
  );

export type CombatEffectCommand = {
  target_combatant_id: string;
  target_version: number;
  source_combatant_id?: string | null;
  source_version?: number | null;
  name: string;
  effect_type: "condition" | "buff" | "debuff" | "aura" | "damage_over_time";
  details_json?: Record<string, unknown>;
  duration_unit: "rounds" | "minutes" | "concentration" | "until_save" | "until_removed";
  duration_value?: number | null;
  requires_concentration?: boolean;
  save_dc?: number | null;
  save_ability?: string | null;
  trigger_timing?: "turn_start" | "turn_end" | "round_start" | "round_end" | null;
};

export const listCombatEffects = (
  cid: string,
  combatId: string,
  signal?: AbortSignal,
) =>
  apiFetch<ListEnvelope<CombatEffect>>(
    `/campaigns/${cid}/combats/${combatId}/effects`,
    { signal },
  ).then((envelope) => envelope.items);

export const confirmCombatEffect = (
  cid: string,
  combatId: string,
  input: CombatEffectCommand,
) =>
  apiFetch<CombatEffectConfirmation>(
    `/campaigns/${cid}/combats/${combatId}/effects/confirm`,
    {
      method: "POST",
      body: input,
      headers: { "X-Request-ID": crypto.randomUUID() },
    },
  );

export const endCombatEffect = (
  cid: string,
  combatId: string,
  effectId: string,
  targetVersion: number,
  sourceVersion: number | null,
  reason: string,
) =>
  apiFetch<CombatEffectConfirmation>(
    `/campaigns/${cid}/combats/${combatId}/effects/${effectId}/end`,
    {
      method: "POST",
      body: {
        target_version: targetVersion,
        source_version: sourceVersion,
        reason,
      },
      headers: { "X-Request-ID": crypto.randomUUID() },
    },
  );

export const confirmConcentrationCheck = (
  cid: string,
  combatId: string,
  input: {
    combatant_id: string;
    target_version: number;
    damage_action_id: string;
    roll_total: number;
  },
) =>
  apiFetch<ConcentrationCheckResult>(
    `/campaigns/${cid}/combats/${combatId}/concentration/confirm`,
    {
      method: "POST",
      body: input,
      headers: { "X-Request-ID": crypto.randomUUID() },
    },
  );

export type CombatSettlementCommand = {
  combat_version: number;
  resolution_type: "victory" | "defeat" | "retreat" | "negotiated" | "bypassed" | "other";
  xp_awards: { character_id: string; xp: number }[];
  writebacks: {
    combatant_id: string;
    character_id: string;
    write_hp: boolean;
    write_conditions: boolean;
  }[];
  notes?: string | null;
};

export const previewCombatSettlement = (
  cid: string,
  combatId: string,
  input: CombatSettlementCommand,
) =>
  apiFetch<CombatSettlementPreview>(
    `/campaigns/${cid}/combats/${combatId}/settlement/preview`,
    { method: "POST", body: input },
  );

export const confirmCombatSettlement = (
  cid: string,
  combatId: string,
  input: CombatSettlementCommand,
) =>
  apiFetch<CombatSettlementResult>(
    `/campaigns/${cid}/combats/${combatId}/settlement/confirm`,
    {
      method: "POST",
      body: input,
      headers: { "X-Request-ID": crypto.randomUUID() },
    },
  );
