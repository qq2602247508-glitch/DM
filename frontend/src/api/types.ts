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

export type RecoveryPoint = { id: string; label: string; kind: string; file_name: string; sha256: string; size_bytes: number; created_at: string };
export type AuditEntry = { id: string; campaign_id: string | null; actor: string; action: string; entity_type: string; entity_id: string | null; before_json: unknown; after_json: unknown; request_id: string; created_at: string };
export type HouseRuleOverride = { id: string; rule_key: string; core_value_json: unknown; override_value_json: unknown; source: string; reason: string; enabled: boolean; version?: number };
export type Diagnostics = { database: { available: boolean; reason: string | null; migration_revision: string | null }; read_only_safe_mode: boolean; backups_directory: string; index: unknown; models: unknown };

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
  enabled_rule_extensions: string[];
  enabled_content_packs: string[];
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
  max_hp_reduction: number;
  ability_score_reductions: Record<string, number>;
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
  notes: string | null;
};

export type CharacterOptionSummary = {
  name: string;
  source_record_id: string;
  source_path: string;
};

export type SpellOption = CharacterOptionSummary & {
  level: number;
  classes: string[];
  school: string | null;
  casting_time: string | null;
  range: string | null;
  components: string | null;
  duration: string | null;
  concentration: boolean;
  ritual: boolean;
  damage_expression: string | null;
  damage_type: string | null;
  save_ability: string | null;
  half_damage_on_save: boolean;
  description: string;
  cost: string;
  resource_key: string | null;
  resource_cost: number;
  resolution_kind: "damage" | "narrative";
  rule_plan?: Record<string, unknown>;
};

export type AdvancementChoiceRequirement = {
  key: string;
  kind: string;
  minimum: number;
  maximum: number;
  strict: boolean;
  options_source: string;
  reason: string;
  target_total: number | null;
  maximum_spell_level: number | null;
};

export type ClassLevelOption = {
  level: number;
  proficiency_bonus: number;
  features: string[];
  progression: Record<string, string>;
  choice_requirements?: AdvancementChoiceRequirement[];
  resource_updates?: Record<string, Record<string, unknown>>;
  scaling_updates?: Record<string, Record<string, unknown>>;
  feature_grants?: SheetFeatureGrant[];
};

export type ClassOption = CharacterOptionSummary & {
  hit_die: number;
  levels: ClassLevelOption[];
  subclasses: CharacterOptionSummary[];
};

export type CharacterOptionsCatalog = {
  edition: 2024;
  officiality: "official";
  classes: ClassOption[];
  species: CharacterOptionSummary[];
  backgrounds: CharacterOptionSummary[];
  feats: CharacterOptionSummary[];
  spells: SpellOption[];
  skills: string[];
  languages: string[];
  tools: string[];
  enabled_content_packs?: string[];
  content_packs?: Array<Record<string, unknown>>;
  extension_character_options?: Array<CharacterOptionSummary & {
    content_pack_key: string;
    content_pack_label: string;
    kind: "class" | "subclass" | "feat";
    parent_class: string | null;
    normalization_status: "needs_normalization";
    automation_status: "dm_only";
    selectable_for_automatic_advancement: false;
    requires_dm_adjudication: true;
    reason: string;
  }>;
  enabled_rule_extensions: string[];
  rule_extensions: Array<{
    key: string;
    label: string;
    category: string;
    summary: string;
    automation_status: "full" | "partial" | "dm_only";
  }>;
};

export type AdvancementRequest = {
  character_version: number;
  class_name: string;
  subclass_name?: string | null;
  hp_mode: "fixed" | "roll";
  hp_roll?: number | null;
  ability_increases: Record<string, number>;
  feat_choice?: string | null;
  feature_choices: string[];
  spell_additions: Array<Record<string, unknown>>;
  spell_removals: string[];
  dm_override_reason?: string | null;
};

export type AdvancementStepRequest = Omit<AdvancementRequest, "character_version">;

export type AdvancementBatchRequest = {
  character_version: number;
  steps: AdvancementStepRequest[];
};

export type SheetFeatureGrant = {
  name: string;
  kind?: string;
  class_name?: string;
  class_level?: number;
  source_record_id?: string;
  source_path?: string;
  rule_year?: 2024;
  runtime?: {
    automation_status?: "full" | "partial" | "dm_only";
    requires_dm_adjudication?: boolean;
    tracked_resource_keys?: string[];
    tracked_scaling_keys?: string[];
    note?: string;
  };
};

export type AdvancementPreview = {
  preview_token: string;
  character_id: string;
  character_name: string;
  from_level: number;
  to_level: number;
  class_name: string;
  class_level: number;
  subclass_name: string | null;
  hit_die: number;
  hp_mode: "fixed" | "roll";
  hp_gain: number;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  features_gained: SheetFeatureGrant[];
  feat_choice: string | null;
  warnings: string[];
  choice_requirements?: AdvancementChoiceRequirement[];
  resource_updates?: Record<string, Record<string, unknown>>;
  scaling_updates?: Record<string, Record<string, unknown>>;
  rule_reference: {
    year: 2024;
    source_record_id?: string;
    source_path: string;
  };
};

export type AdvancementBatchPreview = {
  kind: "batch";
  preview_token: string;
  character_id: string;
  character_name: string;
  from_level: number;
  to_level: number;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  steps: Array<Omit<AdvancementPreview, "preview_token"> & { batch_index: number }>;
  features_gained: SheetFeatureGrant[];
  resource_updates: Record<string, Record<string, unknown>>;
  scaling_updates: Record<string, Record<string, unknown>>;
  warnings: string[];
  rule_reference: {
    year: 2024;
    source_path: string;
  };
};

export type CharacterCompanion = Versioned & {
  campaign_id: string;
  owner_character_id: string;
  name: string;
  companion_type: "familiar" | "animal_companion" | "summon" | "wild_shape" | "form";
  source_record_id: string | null;
  template_json: Record<string, unknown>;
  hp: number;
  max_hp: number;
  armor_class: number;
  speed: number;
  active: boolean;
  notes: string | null;
};

export type RestType = "short" | "long";

export type ResourcePool = {
  id: string;
  character_id: string;
  key: string;
  label: string;
  category: string;
  current: number;
  maximum: number;
  recovery_timing: string;
  die_size: number | null;
  version: number;
};

export type RestHitDieUse = { resource_pool_id: string; roll: number };

export type RestParticipantRequest = {
  character_id: string;
  character_version: number;
  hit_dice: RestHitDieUse[];
  excluded_resource_keys: string[];
};

export type RestPreviewRequest = {
  rest_type: RestType;
  duration_minutes: number;
  interrupted: boolean;
  interruption_reason?: string | null;
  fallback_to_short_rest: boolean;
  participants: RestParticipantRequest[];
  notes?: string | null;
  dm_override_reason?: string | null;
};

export type RestChange = {
  type: string;
  key?: string | null;
  label?: string | null;
  before: number;
  after: number;
  amount: number;
  explanation?: string | null;
};

export type RestParticipantPreview = {
  character_id: string;
  character_name: string;
  character_version: number;
  before: {
    hp: number;
    fatigue: number;
    max_hp_reduction: number;
    ability_score_reductions: Record<string, number>;
    death_saves: { successes: number; failures: number };
  };
  after: {
    hp: number;
    fatigue: number;
    max_hp_reduction: number;
    ability_score_reductions: Record<string, number>;
    death_saves: { successes: number; failures: number };
  };
  changes: RestChange[];
  hit_dice: RestHitDieUse[];
};

export type RestPreview = {
  preview_token: string;
  rest_type: RestType;
  effective_rest_type: RestType;
  duration_minutes: number;
  interrupted: boolean;
  world_time_before: string | null;
  world_time_after: string | null;
  warnings: string[];
  rule_reference: string | null;
  participants: RestParticipantPreview[];
};

export type RestConfirmRequest = RestPreviewRequest & {
  preview_token: string;
  idempotency_key: string;
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

export type NarrativeRecord = Versioned & Record<string, unknown> & { campaign_id: string; status?: string; title?: string; description?: string | null };

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
  damage?: string;
  damage_type?: string;
  range?: string;
  cost?: string;
  attack_bonus?: number;
  save_dc?: number;
  save_ability?: string;
  half_damage_on_save?: boolean;
  recharge?: string;
  resource_key?: string;
  resource_cost?: number;
  auto_eligible?: boolean;
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
  cell_size_ft: number;
  theme: string;
  cells: {
    row: number;
    col: number;
    kind: "floor" | "wall" | "cover" | "door" | "object" | "water" | "difficult" | "terrain" | "light" | "trap" | "treasure" | "furniture" | "portal";
    label: string;
    blocks_sight?: boolean;
    sight_transparency?: string;
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

export type MonsterAIPhase = "turn" | "reaction" | "legendary" | "lair";

export type MonsterAITactics = "instinctive" | "standard" | "smart" | "tactical";

export type MonsterReactionEvent =
  | "leaves_reach"
  | "enters_reach"
  | "takes_damage"
  | "hit_by_attack"
  | "casts_spell"
  | "turn_end";

export type MonsterAIPlan = {
  actor_id: string;
  action_name: string;
  action_type: string;
  target_ids: string[];
  reason: string;
  steps: {
    action_name: string;
    action_index: number;
    action_type: string;
    target_ids: string[];
    requires_player_roll: boolean;
    auto_eligible: boolean;
    reason: string;
  }[];
  legendary_cost: number;
  requires_player_roll: boolean;
  requires_dm_confirmation: boolean;
  confirmation_reasons: string[];
  tactical_intent?: string;
  movement_mode?: string;
  focus_target_id?: string | null;
};

export type MonsterAIPreview = {
  combat: Combat;
  actor: Combatant;
  actor_policy?: string;
  plan: MonsterAIPlan | null;
  requires_confirmation: boolean;
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
  actor: Combatant | null;
  target: Combatant;
  phase?: string;
  pending_reaction?: Record<string, unknown> | null;
};

export type PlayerRollResolutionType =
  | "armor_class"
  | "saving_throw"
  | "ability_check"
  | "skill_check";

export type PlayerRollPromptCommand = {
  actor_combatant_id: string;
  actor_version: number;
  action_cost?: "action" | "bonus_action" | "reaction" | "legendary_action" | "lair_action" | "none";
  target_combatant_id: string;
  target_version: number;
  effect_target_combatant_id?: string | null;
  effect_target_version?: number | null;
  action_name: string;
  resolution_type: PlayerRollResolutionType;
  dc: number;
  ability?: string | null;
  skill?: string | null;
  roll_formula?: string;
  damage_on_success?: number;
  damage_on_failure?: number;
  damage_components_on_success?: Array<{ amount: number; damage_type: string; damage_tags?: string[] }>;
  damage_components_on_failure?: Array<{ amount: number; damage_type: string; damage_tags?: string[] }>;
  damage_type?: string | null;
  damage_tags?: string[];
  description?: string | null;
  recharge_key?: string | null;
  recharge_consume?: boolean;
  legendary_cost?: number | null;
  legendary_pool_max?: number | null;
  reaction_trigger?: string | null;
  reaction_event?: MonsterReactionEvent | null;
  sequence_id?: string | null;
  sequence_step?: number | null;
  sequence_size?: number | null;
  conditions_on_success?: string[];
  conditions_on_failure?: string[];
  condition_duration?: "actor_turn_start" | "actor_turn_end" | "target_turn_start" | "target_turn_end" | "rounds" | "minutes" | "until_save" | "until_removed" | null;
  condition_duration_value?: number | null;
  condition_save_dc?: number | null;
  condition_save_ability?: string | null;
  movement_on_success_ft?: number | null;
  movement_on_failure_ft?: number | null;
  movement_direction?: "away" | "toward" | null;
  area_shape?: "cone" | "line" | "cube" | "sphere" | "cylinder" | null;
  area_size_ft?: number | null;
  area_width_ft?: number | null;
  area_height_ft?: number | null;
  area_anchor_height_ft?: number | null;
  area_anchor_row?: number | null;
  area_anchor_col?: number | null;
  area_include_actor?: boolean;
  requires_explicit_elevation?: boolean;
};

export type PlayerRollPromptBatchTarget = {
  target_combatant_id: string;
  target_version: number;
  effect_target_combatant_id?: string | null;
  effect_target_version?: number | null;
};

export type PlayerRollPromptBatchCommand = Omit<
  PlayerRollPromptCommand,
  "target_combatant_id" | "target_version" | "effect_target_combatant_id" | "effect_target_version"
> & {
  targets: PlayerRollPromptBatchTarget[];
};

export type PlayerRollPromptBatchResult = {
  actions: CombatAction[];
  actor: Combatant;
  targets: Combatant[];
  transaction: Record<string, unknown>;
  already_applied: boolean;
};

export type PlayerRollResolutionCommand = {
  action_version: number;
  roll_total: number;
  roll_totals?: number[];
  use_legendary_resistance?: boolean;
  use_feature_reroll?: boolean;
  dm_note?: string | null;
};

export type PlayerRollResolution = {
  phase: "awaiting_player_roll" | "resolved";
  roll_owner: "player";
  roll_total?: number;
  dc?: number;
  success?: boolean;
  outcome?: "success" | "failure";
  damage?: number;
  damage_type?: string | null;
  damage_components?: Array<{ amount: number; damage_type: string; damage_tags?: string[] }>;
  dm_note?: string | null;
  follow_up_damage?: {
    action_type: "damage";
    actor_combatant_id: string;
    target_combatant_id: string;
    target_version: number;
    amount: number;
    damage_type: string;
    damage_components?: Array<{ amount: number; damage_type: string; damage_tags?: string[] }>;
  } | null;
};

export type PlayerRollPromptResult = {
  action: CombatAction;
  actor: Combatant;
};

export type PlayerRollResolutionResult = {
  action: CombatAction;
  actor: Combatant;
  target: Combatant;
  resolution: PlayerRollResolution;
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
  effect_prompts: Array<{
    effect_id: string;
    target_combatant_id: string;
    save_dc: number;
    save_ability: string;
    summary?: string;
    requires_save?: boolean;
  }>;
  effect_ticks?: unknown[];
  status_prompts?: unknown[];
};

export type CombatResetResult = {
  combat: Combat;
  combatants: Combatant[];
  cleared_log: boolean;
};

export type CombatEffect = Versioned & {
  campaign_id: string;
  combat_id: string;
  target_combatant_id: string;
  source_combatant_id: string | null;
  source_action_id: string | null;
  name: string;
  effect_type: "condition" | "buff" | "debuff" | "aura" | "damage_over_time";
  details_json: Record<string, unknown>;
  started_round: number;
  duration_unit: string;
  duration_value: number | null;
  ends_round: number | null;
  requires_concentration: boolean;
  save_dc: number | null;
  save_ability: string | null;
  trigger_timing: string | null;
  status: "active" | "ended";
  ended_at: string | null;
  end_reason: string | null;
};

export type CombatEffectConfirmation = {
  action: CombatAction;
  effect: CombatEffect;
  ended_effects: CombatEffect[];
  target: Combatant;
  source: Combatant | null;
};

export type ConcentrationCheckResult = {
  action: CombatAction;
  target: Combatant;
  dc: number;
  roll_total: number;
  success: boolean;
  ended_effects: CombatEffect[];
};

export type CombatSettlement = Versioned & {
  campaign_id: string;
  combat_id: string;
  transaction_id: string | null;
  status: "confirmed" | "reverted" | "conflict";
  resolution_type: string;
  xp_allocations: unknown[];
  writebacks: unknown[];
  result_json: Record<string, unknown>;
  idempotency_key: string;
  notes: string | null;
  confirmed_at: string;
};

export type CombatSettlementPreview = {
  combat: Combat;
  resolution_type: string;
  character_changes: {
    character_id: string;
    name: string;
    before: { hp: number; experience: number; version: number };
    after: { hp: number; experience: number; version: number };
    conditions_to_add: string[];
    xp_award: number;
  }[];
  currency_changes: {
    character_id: string;
    name: string;
    before_copper: number;
    award_copper: number;
    after_copper: number;
  }[];
  loot_changes: {
    character_id: string;
    character_name: string;
    name: string;
    quantity: number;
    unit_weight_lb: number;
    price_cp: number;
  }[];
  total_xp: number;
  total_copper: number;
  notes: string | null;
};

export type CombatSettlementResult = {
  settlement: CombatSettlement;
  combat: Combat;
  characters: Character[];
  conditions: CharacterCondition[];
  wallets: unknown[];
  loot_items: WorldItem[];
};

export type CombatEndCondition = {
  can_end: boolean;
  suggested_resolution_type: "victory" | null;
  reason: "all_hostile_monsters_defeated" | "hostile_monsters_remain" | "no_hostile_monsters";
  hostile_count: number;
  defeated_count: number;
  remaining_hostiles: { combatant_id: string; display_name: string; hp: number }[];
  requires_dm_confirmation: boolean;
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
  schema_version: "1.0" | "2.0";
  exported_at: string;
  campaign: Record<string, unknown> & Partial<Campaign>;
  manifest?: {
    format: "dnd-dm-campaign-backup";
    source_campaign_id: string;
    table_names: string[];
    excluded_tables: string[];
    record_count: number;
    sha256: string;
  } | null;
  counts?: Record<string, number>;
  tables?: Record<string, Record<string, unknown>[]>;
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
  request_understanding: string;
  response_plan: string;
  delivery_mode: "read_aloud" | "spoken_line" | "dm_guidance" | "explanation" | "revision" | "other";
  audience_handoff: string;
  text: string;
  assumptions: string[];
  uncertainties: string[];
  citations: Citation[];
  proposed_changes: string[];
};

export type AssistantConversationMessage = {
  role: "dm" | "assistant";
  content: string;
  message_kind: "question" | "answer" | "confirmed_progress";
  authoritative: boolean;
  created_at: string;
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
