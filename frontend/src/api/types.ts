/**
 * API types mirroring the FastAPI schemas. These are the contract of record;
 * see docs/frontend-api.md. Do not invent fields the backend does not return.
 */

// ---------------------------------------------------------------------------
// Enums (domain/content.py, domain/agent.py)
// ---------------------------------------------------------------------------

export type ContentType =
  | "rules"
  | "classes"
  | "subclasses"
  | "spells"
  | "monsters"
  | "items"
  | "feats"
  | "backgrounds"
  | "conditions"
  | "actions"
  | "equipment"
  | "unknown";

export type Edition = "2014" | "2024" | "2025" | "legacy" | "mixed" | "unknown";

export type Officiality = "official" | "third_party" | "unknown";

export type ProposalStatus = "pending" | "confirmed" | "rejected" | "conflict";

export type StateOperationKind = "create" | "update" | "delete";

export type ProposalEntityType = "character" | "npc" | "quest" | "event";

export type ToolName =
  | "search_rules"
  | "get_campaign_state"
  | "update_campaign_state"
  | "generate_dm_hint";

export type EventVisibility = "dm" | "players" | "public";

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------

export type HealthResponse = {
  status: "ok";
  database: "ok";
  environment: string;
};

export type ConfiguredModelStatus = {
  role: "intent" | "reasoning" | "embedding";
  model: string | null;
  configured: boolean;
  installed: boolean;
};

export type RuntimeModelStatus = {
  ollama_available: boolean;
  think_enabled: boolean;
  models: ConfiguredModelStatus[];
  installed_models: string[];
  reason: string | null;
};

export type IndexStatus = {
  collection_name: string;
  available: boolean;
  state: "ready" | "missing" | "building" | "inconsistent";
  reason: string | null;
  points_count: number;
  vector_size: number | null;
  indexed_records: number;
  embedding_model: string | null;
  chunking_fingerprint: string | null;
  updated_at: string | null;
};

// ---------------------------------------------------------------------------
// Knowledge (domain/rag.py)
// ---------------------------------------------------------------------------

export type Chunk = {
  chunk_id: string;
  record_id: string;
  chunk_index: number;
  text: string;
  name: string;
  aliases: string[];
  content_type: ContentType;
  edition: Edition;
  officiality: Officiality;
  source_title: string;
  source_book: string | null;
  canonical_url: string;
  source_url: string;
  repository_url: string | null;
  source_relative_path: string | null;
  source_ref: string | null;
  source_revision: string | null;
  source_license: string;
  heading_path: string[];
  section: string;
  fragment: string | null;
  record_checksum: string;
  chunk_checksum: string;
};

export type SearchHit = {
  chunk: Chunk;
  score: number;
};

export type RuleDocument = {
  stable_id: string;
  name: string;
  aliases: string[];
  content_type: ContentType;
  source_url: string;
  canonical_url: string;
  repository_url: string | null;
  source_revision: string | null;
  source_ref: string | null;
  source_relative_path: string | null;
  source_license: string;
  source_book: string | null;
  edition: Edition;
  officiality: Officiality;
  heading_path: string[];
  fragment: string | null;
  content_markdown: string;
  content_plain_text: string;
  checksum: string;
  fetched_at: string;
  spell: Record<string, unknown> | null;
  warnings: string[];
};

export type SearchQuery = {
  text: string;
  top_k?: number;
  candidate_k?: number;
  min_score?: number;
  content_types?: ContentType[];
  editions?: Edition[];
  source_books?: string[];
  current_official?: boolean;
  allow_unknown?: boolean;
  allow_third_party?: boolean;
};

export type Citation = {
  citation_id: number;
  chunk_id: string;
  record_id: string;
  rule_name: string;
  source_title: string;
  canonical_url: string;
  section: string;
  heading_path: string[];
  content_type: ContentType;
  edition: Edition;
  officiality: Officiality;
  source_book: string | null;
  repository_url: string | null;
  source_relative_path: string | null;
  source_ref: string | null;
  source_revision: string | null;
  score: number;
};

export type GroundedAnswer = {
  answer: string;
  abstained: boolean;
  reason: string | null;
  citations: Citation[];
};

// ---------------------------------------------------------------------------
// Campaign state entities
// ---------------------------------------------------------------------------

export type Versioned = {
  id: string;
  created_at: string;
  updated_at: string;
  version: number;
};

export type Campaign = Versioned & {
  name: string;
  description: string | null;
  world_setting: string | null;
  current_time: string | null;
  current_location_id: string | null;
  status: string;
  ruleset: "dnd5e";
  primary_rules_year: 2024;
  allow_legacy: boolean;
  encumbrance_mode: "standard" | "variant" | "none";
};

export type Character = Versioned & {
  campaign_id: string;
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
  inventory: unknown[];
  equipment: unknown[];
  proficiencies: unknown[];
  skills: Record<string, unknown>;
  features: unknown[];
  actions: unknown[];
  resources: Record<string, unknown>;
  spells: unknown[];
  spellcasting: Record<string, unknown>;
  notes: string | null;
};

export type CharacterCondition = Versioned & {
  campaign_id: string;
  character_id: string;
  condition_name: string;
  source: string | null;
  duration: string | null;
  notes: string | null;
  details: Record<string, unknown>;
};

export type Npc = Versioned & {
  campaign_id: string;
  name: string;
  description: string | null;
  alignment: string | null;
  attitude: string | null;
  personality: string | null;
  goal: string | null;
  fear: string | null;
  armor_class: number;
  hp: number;
  max_hp: number;
  speed: number;
  ability_scores: Record<string, number>;
  challenge_rating: string | null;
  actions: GeneratedAction[];
  equipment: GeneratedItem[];
  relationship: string | null;
  secrets: string | null;
  known_information: string | null;
  location_id: string | null;
  status: string;
};

export type Location = Versioned & {
  campaign_id: string;
  parent_location_id: string | null;
  depth: number;
  name: string;
  description: string | null;
  interactive_objects: unknown[];
  secrets: string | null;
  discovered: boolean;
  notes: string | null;
};

export type GeneratedAction = {
  name: string;
  description: string;
};

export type GeneratedItem = {
  name: string;
  description: string | null;
  category: string;
  quantity: number;
  unit_weight_lb: number;
  price_cp: number;
  interactive_note: string | null;
  hidden: boolean;
};

export type GeneratedNpc = {
  name: string;
  description: string;
  alignment: string | null;
  attitude: string | null;
  personality: string | null;
  goal: string | null;
  fear: string | null;
  secret: string | null;
  known_information: string | null;
  armor_class: number;
  hp: number;
  max_hp: number;
  speed: number;
  ability_scores: Record<string, number>;
  challenge_rating: string | null;
  actions: GeneratedAction[];
  equipment: GeneratedItem[];
};

export type GeneratedLocationNode = {
  temp_id: string;
  name: string;
  description: string;
  interactive_objects: string[];
  secrets: string | null;
  discovered: boolean;
  items: GeneratedItem[];
  suggested_npcs: string[];
  suggested_monsters: string[];
  children: GeneratedLocationNode[];
};

export type NpcGenerationPreview = {
  ruleset: "dnd5e";
  primary_rules_year: 2024;
  npc: GeneratedNpc;
  citations: Citation[];
  warnings: string[];
};

export type LocationGenerationPreview = {
  ruleset: "dnd5e";
  primary_rules_year: 2024;
  maximum_depth: number;
  root: GeneratedLocationNode;
  citations: Citation[];
  warnings: string[];
};

export type WorldItem = Versioned & {
  campaign_id: string;
  name: string;
  description: string | null;
  category: string;
  quantity: number;
  unit_weight_lb: number;
  price_cp: number;
  source_record_id: string | null;
  source_label: "official" | "legacy" | "custom" | "ai_generated";
  location_id: string | null;
  owner_character_id: string | null;
  is_equipped: boolean;
  is_hidden: boolean;
  metadata_json: Record<string, unknown>;
};

export type InventorySummary = {
  character_id: string;
  strength: number;
  encumbrance_mode: "standard" | "variant" | "none";
  total_weight_lb: number;
  maximum_weight_lb: number | null;
  state: "normal" | "encumbered" | "heavily_encumbered" | "over_capacity" | "ignored";
  items: WorldItem[];
};

export type Monster = Versioned & {
  campaign_id: string;
  name: string;
  source_record_id: string | null;
  source_name: string | null;
  armor_class: number;
  hp: number;
  max_hp: number;
  speed: number;
  ability_scores: Record<string, number>;
  challenge_rating: string | null;
  actions: GeneratedAction[];
  notes: string | null;
};

export type Scene = Versioned & {
  campaign_id: string;
  location_id: string | null;
  name: string;
  description: string | null;
  status: "draft" | "active" | "closed";
  notes: string | null;
};

export type SceneGrid = {
  width: number;
  height: number;
  cell_size_ft: 5;
  theme: string;
  cells: {
    row: number;
    col: number;
    kind: "floor" | "wall" | "cover" | "door" | "object";
    label: string;
  }[];
};

export type SceneParticipant = Versioned & {
  scene_id: string;
  entity_type: "character" | "npc" | "monster";
  entity_id: string;
  role: string;
  visible: boolean;
  notes: string | null;
  entity: Character | Npc | Monster;
};

export type SceneCombatResult = {
  combat: Combat;
  initiative_rolls: {
    entity_type: "character" | "npc" | "monster";
    entity_id: string;
    name: string;
    die: number;
    dexterity_modifier: number;
    total: number;
  }[];
};

export type Quest = Versioned & {
  campaign_id: string;
  name: string;
  description: string | null;
  quest_type: "main" | "side" | "personal" | "faction";
  giver: string | null;
  reward: string | null;
  xp_reward: number;
  xp_awarded: boolean;
  status: string;
  notes: string | null;
};

export type Clue = Versioned & {
  campaign_id: string;
  quest_id: string | null;
  name: string;
  description: string | null;
  player_text: string | null;
  dm_truth: string | null;
  verified: boolean;
  discovered: boolean;
  discovered_at: string | null;
  source_event_id: string | null;
};

export type CampaignEvent = Versioned & {
  campaign_id: string;
  event_type: string;
  title: string;
  description: string | null;
  occurred_at: string;
  location_id: string | null;
  visibility: EventVisibility;
  metadata_json: Record<string, unknown>;
};

export type EncounterEntityType = "character" | "npc" | "monster";

type EncounterOperationBase = {
  entity_type: EncounterEntityType;
  entity_id: string;
  reason: string;
};

export type EncounterOperation =
  | (EncounterOperationBase & { kind: "remove_entity" })
  | (EncounterOperationBase & { kind: "add_scene_entity" })
  | (EncounterOperationBase & { kind: "set_entity_hp"; hp: number })
  | (EncounterOperationBase & { kind: "add_entity_condition"; condition: string })
  | (EncounterOperationBase & {
      kind: "schedule_reinforcement";
      round: number;
      quantity: number;
    });

export type EncounterAdjustment = Versioned & {
  campaign_id: string;
  scene_id: string;
  combat_id: string | null;
  source_event_id: string | null;
  operation_transaction_id: string | null;
  title: string;
  reason: string;
  difficulty_shift: -1 | 0 | 1;
  operations_json: EncounterOperation[];
  inverse_operations_json: unknown[];
  status: "pending" | "applied" | "rejected" | "reverted" | "conflict";
  applied_at: string | null;
  reverted_at: string | null;
};

export type Combat = Versioned & {
  campaign_id: string;
  scene_id: string | null;
  name: string;
  status: string;
  round_number: number;
  current_turn_index: number;
  difficulty: "trivial" | "low" | "moderate" | "high" | null;
  base_xp: number;
  difficulty_adjustments: unknown[];
  xp_awarded: boolean;
  started_at: string;
  ended_at: string | null;
};

export type Combatant = Versioned & {
  campaign_id: string;
  combat_id: string;
  entity_type: string;
  entity_id: string | null;
  display_name: string;
  initiative: number;
  armor_class: number;
  hp: number;
  max_hp: number;
  temporary_hp: number;
  max_hp_reduction: number;
  damage_resistances: string[];
  damage_vulnerabilities: string[];
  damage_immunities: string[];
  condition_immunities: string[];
  conditions: unknown[];
  concentration: Record<string, unknown>;
  speed_ft: number;
  movement_remaining_ft: number;
  action_available: boolean;
  bonus_action_available: boolean;
  reaction_available: boolean;
  snapshot_json: Record<string, unknown>;
  is_active: boolean;
};

export type CombatAction = Versioned & {
  campaign_id: string;
  combat_id: string;
  actor_combatant_id: string | null;
  transaction_id: string | null;
  action_type: string;
  target_combatant_ids: string[];
  request_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  explanation: string | null;
  round_number: number;
  turn_index: number;
  summary: string;
  idempotency_key: string;
  dm_override: boolean;
  override_reason: string | null;
  status: string;
};

export type CombatActionPreview = {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  result: Record<string, unknown>;
  concentration_check_dc: number | null;
};

export type CombatActionConfirmation = {
  action: CombatAction;
  target: Combatant;
};

export type DeathSave = Versioned & {
  combatant_id: string;
  successes: number;
  failures: number;
  stable: boolean;
  dead: boolean;
  pending_death_confirmation: boolean;
  last_roll: number | null;
};

export type DeathSaveConfirmation = {
  action: CombatAction;
  target: Combatant;
  death_save: DeathSave;
};

export type TurnAdvanceResult = {
  action: CombatAction;
  combat: Combat;
  active_combatant: Combatant | null;
  expiration_prompts: unknown[];
};

export type StateSnapshot = {
  campaign: Record<string, unknown> & Partial<Campaign>;
  characters: Character[];
  npcs: Npc[];
  locations: Location[];
  quests: Quest[];
  open_clues: Clue[];
  active_combats: Combat[];
  as_of: string;
};

export type CampaignBackup = {
  schema_version: "1.0";
  exported_at: string;
  campaign: Record<string, unknown> & Partial<Campaign>;
  characters: Record<string, unknown>[];
  conditions: Record<string, unknown>[];
  npcs: Record<string, unknown>[];
  locations: Record<string, unknown>[];
  connections: Record<string, unknown>[];
  quests: Record<string, unknown>[];
  clues: Record<string, unknown>[];
  events: Record<string, unknown>[];
  combats: Record<string, unknown>[];
  combatants: Record<string, unknown>[];
  world_items: Record<string, unknown>[];
  monsters: Record<string, unknown>[];
  scenes: Record<string, unknown>[];
  scene_participants: Record<string, unknown>[];
};

export type ListEnvelope<T> = {
  items: T[];
  limit: number;
  offset?: number;
};

// ---------------------------------------------------------------------------
// Assistant (domain/agent.py)
// ---------------------------------------------------------------------------

export type ToolResult = {
  tool: ToolName;
  ok: boolean;
  data: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
};

export type StateChangeProposal = {
  id: string;
  campaign_id: string;
  tool_name: "update_campaign_state";
  operation: StateOperationKind;
  entity_type: ProposalEntityType;
  entity_id: string | null;
  payload: Record<string, unknown>;
  expected_version: number | null;
  reason: string;
  status: ProposalStatus;
  created_by_model: string;
  request_id: string;
  created_at: string;
  updated_at: string;
  decided_at: string | null;
  version: number;
};

export type ProposalDecision = {
  proposal: StateChangeProposal;
  applied_entity: Record<string, unknown> | null;
  already_decided: boolean;
};

export type DmHint = {
  visibility: "dm_private";
  text: string;
  assumptions: string[];
  uncertainties: string[];
  citations: Citation[];
  proposed_changes: string[];
};

export type AgentResponse = {
  request_id: string;
  campaign_id: string;
  dm_hint: DmHint | null;
  tool_results: ToolResult[];
  citations: Citation[];
  proposals: StateChangeProposal[];
  abstained: boolean;
  errors: string[];
};

// ---------------------------------------------------------------------------
// Error envelope (api/errors.py)
// ---------------------------------------------------------------------------

export type ErrorEnvelope = {
  code: string;
  message: string;
  details: unknown;
  request_id: string;
};
