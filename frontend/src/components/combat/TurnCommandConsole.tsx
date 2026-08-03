import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import {
  confirmCombatAction,
  confirmCombatActionBatch,
  createPlayerRollPrompt,
  createPlayerRollPromptBatch,
  previewMonsterAI,
  previewCombatAction,
  updateCharacter,
  updateCombatant,
  type CombatActionBatchCommand,
  type CombatActionCommand,
} from "../../api/entities";
import type {
  Character,
  CombatActionPreview,
  Combatant,
  MonsterAIPreview,
  MonsterAIPhase,
  MonsterReactionEvent,
} from "../../api/types";
import { useToast } from "../../hooks/toastContext";
import {
  ENEMY_TACTICS_LABELS,
  abilityModifier,
  actionRangeSummary,
  chooseEnemyTarget,
  chooseEnemyActionIndex,
  executableTargetIds,
  forcedMovementFromAction,
  expandMonsterAction,
  hasGridPosition,
  isPlayerControlledCombatant,
  isRechargeAvailable,
  isMonsterTurnAction,
  monsterActionCost,
  parseRechargeRange,
  parseRangeFeet,
  proficiencyBonus,
  rechargeActionKey,
  rollStructuredDamage,
  proposeFreeformCheck,
  upcastExpression,
  type CombatActionLike,
  type EnemyTactics,
} from "../../ui/combatAutomation";
import { isPreparedCombatSpell } from "../../ui/characterRules";
import { targetingFromRulePlan } from "../../ui/ruleBlocks";
import {
  resolveAreaSavingThrows,
  type AreaSpellResolution,
} from "../../ui/areaSpellResolution";
import { Badge, Button } from "../../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../../ui/styles";
import { gridDistanceFt, type TargetingTemplate } from "../../ui/gridTargeting";
import { monsterActionsForRules } from "../../ui/monsterRuleProfiles";
import {
  BACKEND_THREE_DIMENSIONAL_REVIEW_LABEL,
  advancedActionPhase,
  advancedActionPhaseFromCost,
  advancedActionPendingRollSummary,
  advancedPhaseLabel,
  evaluateAdvancedAreaTargeting,
  evaluateAdvancedActionAvailability,
  isAdvancedAreaAction,
  type AdvancedActionAvailability,
} from "../../ui/advancedMonsterActions";
import { RuleBlockPlan } from "../RuleBlockPlan";

export type CombatTargeting = TargetingTemplate & { label: string };

export type CombatTargetingValidity = {
  /** The map point/direction the DM selected for the active template. */
  anchorPoint: { row: number; col: number } | null;
  /** All targets covered by the current horizontal map template. */
  horizontalTargetIds: ReadonlySet<string>;
  /** Targets that also satisfy the currently selected vertical volume. */
  validTargetIds: ReadonlySet<string>;
  /** Horizontally covered targets whose elevation was not recorded. */
  missingElevationTargetIds: ReadonlySet<string>;
};

type PendingResolution = {
  command: CombatActionCommand;
  preview: CombatActionPreview;
  explanation: string;
};

type PendingAreaResolution = {
  resolution: AreaSpellResolution;
  actionName: string;
  actionCost: ActionCost;
  damageType: string;
  forcedMovement: ReturnType<typeof forcedMovementFromAction>;
  areaFields: Partial<Pick<CombatActionCommand,
    "area_shape" | "area_size_ft" | "area_width_ft" | "area_height_ft"
    | "area_anchor_height_ft" | "area_anchor_row" | "area_anchor_col"
    | "area_include_actor" | "requires_explicit_elevation"
  >>;
};

function normalizeAction(raw: unknown, index: number): CombatActionLike {
  if (typeof raw === "string") return { name: raw, description: "角色卡记录", cost: "动作" };
  if (raw && typeof raw === "object") {
    const action = { ...(raw as Record<string, unknown>) } as CombatActionLike;
    const plan = action.rule_plan;
    const blocks = plan && typeof plan === "object" && Array.isArray(plan.blocks)
      ? plan.blocks.filter((item): item is Record<string, unknown> => (
          item !== null && typeof item === "object" && !Array.isArray(item)
        ))
      : [];
    const target = blocks.find((block) => block.kind === "target");
    const save = blocks.find((block) => block.kind === "save");
    const damageBlocks = blocks.filter((block) => block.kind === "damage");
    const movement = blocks.find((block) => block.kind === "move");
    const setIfMissing = (key: keyof CombatActionLike, value: unknown): void => {
      if (action[key] == null && value != null) {
        (action as Record<string, unknown>)[key] = value;
      }
    };

    // A compiled plan is the canonical source of truth.  Older API snapshots
    // did not project its target/save fields onto the action object, which
    // meant the targeting map worked but the console could still choose the
    // ordinary attack branch (notably for Fireball).  Project only explicit
    // values; never invent a distance, DC, or effect from prose here.
    if (target) {
      setIfMissing("range_ft", target.range_ft);
      setIfMissing("area_shape", target.shape);
      setIfMissing("area_size_ft", target.size_ft);
      setIfMissing("area_width_ft", target.width_ft);
      setIfMissing("area_height_ft", target.height_ft);
      setIfMissing("area_anchor_height_ft", target.anchor_height_ft);
      if (action.area_origin_self == null && target.mode === "self") action.area_origin_self = true;
      if (
        action.affects_multiple_targets == null
        && (target.mode === "area" || target.mode === "multiple" || target.shape)
      ) {
        action.affects_multiple_targets = true;
      }
    }
    if (save) {
      setIfMissing("save_ability", save.ability);
      setIfMissing("save_dc", save.dc);
      if (action.half_damage_on_save == null && save.on_success === "half") {
        action.half_damage_on_save = true;
      }
    }
    if (damageBlocks.length > 0) {
      const firstDamage = damageBlocks[0];
      if (firstDamage) {
        setIfMissing("damage", firstDamage.expression ?? firstDamage.damage);
        setIfMissing("damage_type", firstDamage.damage_type);
        if ((!Array.isArray(action.damage_components) || action.damage_components.length === 0) && damageBlocks.length > 1) {
          action.damage_components = damageBlocks.map((block) => ({
            expression: typeof block.expression === "string" ? block.expression : undefined,
            damage_type: typeof block.damage_type === "string" ? block.damage_type : undefined,
          }));
        }
      }
    }
    if (movement) {
      setIfMissing("movement", {
        distance_ft: movement.distance_ft,
        type: movement.movement_type,
        direction: movement.direction,
      });
    }
    return action;
  }
  return { name: `动作 ${index + 1}` };
}

function actionModifier(character: Character, action: CombatActionLike): number {
  const text = `${action.name ?? ""} ${action.description ?? ""}`;
  const rawSpellAbility = character.spellcasting.ability;
  const spellAbility = typeof rawSpellAbility === "string"
    ? ({ 力量: "strength", 敏捷: "dexterity", 体质: "constitution", 智力: "intelligence", 感知: "wisdom", 魅力: "charisma" }[rawSpellAbility] ?? rawSpellAbility)
    : "intelligence";
  const ability = /法术|魔能|火焰|奥术/.test(text)
    ? spellAbility
    : /远程|弓|弩|灵巧/.test(text)
      ? "dexterity"
      : "strength";
  return abilityModifier(character.ability_scores[ability])
    + proficiencyBonus(character.level);
}

type ActionCost = "action" | "bonus_action" | "reaction" | "legendary_action" | "lair_action" | "none";

type AdvancedActionChoice = {
  key: string;
  actor: Combatant;
  action: CombatActionLike;
  actionIndex: number;
  availability: AdvancedActionAvailability;
};

function actionCost(action: CombatActionLike): ActionCost {
  return monsterActionCost(action);
}

function hasActionEconomy(active: Combatant, cost: ActionCost): boolean {
  if (cost === "none") return true;
  if (cost === "bonus_action") return active.bonus_action_available;
  if (cost === "reaction") return active.reaction_available;
  if (cost === "legendary_action") {
    return Number(active.snapshot_json.legendary_actions_remaining ?? 0) > 0;
  }
  if (cost === "lair_action") return false;
  return active.action_available;
}

function targetingForAction(
  action: CombatActionLike,
  options: { requiresElevation?: boolean } = {},
): CombatTargeting {
  const compiled = targetingFromRulePlan(action);
  if (compiled) {
    return {
      ...compiled,
      shape: action.area_shape && action.area_shape !== "single"
        ? action.area_shape === "sphere" ? "circle" : action.area_shape
        : compiled.shape,
      sizeFt: action.area_size_ft ?? compiled.sizeFt,
      widthFt: action.area_width_ft ?? compiled.widthFt,
      heightFt: action.area_height_ft ?? compiled.heightFt,
      anchorHeightFt: action.area_anchor_height_ft ?? undefined,
      ...(options.requiresElevation ? { requiresElevation: true } : {}),
      label: `${action.name ?? "动作"} · 已编译规则范围`,
    };
  }
  const summary = actionRangeSummary(action);
  const targetingText = `${action.range ?? ""} ${action.description ?? ""}`;
  const radiusMatch = targetingText.match(/(\d+)\s*尺(?:半径|范围|球形|爆发|立方|圆柱)/);
  const lengthMatch = targetingText.match(/(\d+)\s*尺(?:长|锥形|直线)/);
  const widthMatch = targetingText.match(/(\d+)\s*尺(?:宽|宽度)/);
  const shape = action.area_shape && action.area_shape !== "single"
    ? action.area_shape === "sphere" ? "circle" : action.area_shape
    : /锥形/.test(summary)
      ? "cone"
      : /直线/.test(summary)
        ? "line"
        : /立方/.test(`${summary} ${targetingText}`)
          ? "cube"
          : /圆柱|柱状|cylinder/i.test(`${summary} ${targetingText}`)
            ? "cylinder"
          : /圆形|球形|半径|爆炸|爆发/.test(`${summary} ${targetingText}`)
            ? "circle"
          : "single";
  return {
    rangeFt: action.range_ft ?? parseRangeFeet(action.range) ?? 0,
    sizeFt: action.area_size_ft ?? (
      shape === "circle" || shape === "cube" || shape === "cylinder"
        ? (radiusMatch ? Number(radiusMatch[1]) : undefined)
        : (lengthMatch ? Number(lengthMatch[1]) : undefined)
    ),
    heightFt: action.area_height_ft ?? undefined,
    anchorHeightFt: action.area_anchor_height_ft ?? undefined,
    widthFt: action.area_width_ft ?? (widthMatch ? Number(widthMatch[1]) : undefined),
    ...(options.requiresElevation ? { requiresElevation: true } : {}),
    originSelf: action.area_origin_self ?? /自身|self/i.test(targetingText),
    shape,
    label: `${action.name ?? "动作"} · ${action.range_ft == null && parseRangeFeet(action.range) == null && !/自身|self/i.test(targetingText) ? "距离未明确 · 需要 DM 裁定" : summary}`,
  };
}

function areaPromptFields(
  action: CombatActionLike,
  actor: Combatant,
  target: Combatant,
  mapAnchor: { row: number; col: number } | null = null,
): Record<string, unknown> {
  const shape = action.area_shape;
  if (!shape || shape === "single") return {};
  const actorPosition = actor.snapshot_json.grid_position;
  const targetPosition = target.snapshot_json.grid_position;
  // The map anchor is the DM's actual selected centre/direction.  Falling
  // back to the action source keeps legacy self-origin areas usable, while a
  // remote advanced area never silently substitutes its selected target for a
  // separately chosen map point.
  const source = mapAnchor ?? (action.area_origin_self ? actorPosition : targetPosition);
  if (!source || typeof source !== "object" || Array.isArray(source)) return {};
  const row = Number((source as Record<string, unknown>).row);
  const col = Number((source as Record<string, unknown>).col);
  const size = Number(action.area_size_ft);
  if (!Number.isInteger(row) || !Number.isInteger(col) || row < 1 || col < 1 || !Number.isInteger(size) || size < 5) {
    return {};
  }
  const backendShape = shape === "circle" ? "sphere" : shape;
  return {
    area_shape: backendShape,
    area_size_ft: size,
    area_width_ft: action.area_width_ft ?? null,
    area_height_ft: action.area_height_ft ?? null,
    // A missing elevation is meaningful: the area gate must reject it rather
    // than silently turning an unmeasured action into a ground-level one.
    area_anchor_height_ft: action.area_anchor_height_ft ?? 0,
    area_anchor_row: row,
    area_anchor_col: col,
    area_include_actor: false,
  };
}

export function TurnCommandConsole({
  active,
  activeCharacter,
  campaignId,
  combatId,
  fighters,
  autoEnemies,
  automationReady,
  onAutoEnemiesChange,
  onEnemyTurnComplete,
  onRangeChange,
  onTargetChange,
  selectedTargetId,
  targetingValidity,
  turnKey,
}: {
  active: Combatant;
  activeCharacter?: Character;
  campaignId: string;
  combatId: string;
  fighters: Combatant[];
  autoEnemies: boolean;
  automationReady: boolean;
  onAutoEnemiesChange: (enabled: boolean) => void;
  onEnemyTurnComplete: () => void;
  onRangeChange: (range: CombatTargeting | null, actorId?: string | null) => void;
  onTargetChange?: (targetId: string) => void;
  selectedTargetId?: string;
  targetingValidity?: CombatTargetingValidity;
  turnKey: string;
}): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const validTargetIds = targetingValidity?.validTargetIds;
  const [mode, setMode] = useState<"auto" | "assisted">("assisted");
  const [actionIndex, setActionIndex] = useState("0");
  const [selectedSlotLevel, setSelectedSlotLevel] = useState(1);
  const [targetId, setTargetId] = useState("");
  const [attackTotal, setAttackTotal] = useState("");
  const [saveTotal, setSaveTotal] = useState("");
  const [damageTotal, setDamageTotal] = useState("");
  const [damageComponentTotals, setDamageComponentTotals] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<PendingResolution | null>(null);
  const [pendingArea, setPendingArea] = useState<PendingAreaResolution | null>(null);
  const [freeform, setFreeform] = useState("");
  const [tactics, setTactics] = useState<EnemyTactics>("standard");
  const [advancedChoiceKey, setAdvancedChoiceKey] = useState("");
  const [advancedTargetId, setAdvancedTargetId] = useState("");
  const [advancedAreaTargetingKey, setAdvancedAreaTargetingKey] = useState<string | null>(null);
  const [reactionTrigger, setReactionTrigger] = useState("");
  const [reactionEvent, setReactionEvent] = useState<MonsterReactionEvent | "">("");
  const [advancedAttackTotal, setAdvancedAttackTotal] = useState("");
  const processedAutomaticTurn = useRef<string | null>(null);
  // A monster action changes action_available before the query has moved to
  // the next initiative slot.  Keep the current sequence marked in-flight so
  // that the effect below cannot interpret that transient state as a second
  // request to advance the same turn.
  const monsterSequenceInFlight = useRef<string | null>(null);
  const activeIsPlayerControlled = isPlayerControlledCombatant(active.entity_type, active.snapshot_json);

  const actions = useMemo(
    () => activeIsPlayerControlled
      ? (
          Array.isArray(active.snapshot_json.actions)
            ? active.snapshot_json.actions
            : activeCharacter ? [
                ...activeCharacter.actions,
                ...activeCharacter.spells.filter(isPreparedCombatSpell),
              ] : []
        ).map(normalizeAction)
      : monsterActionsForRules(
          active.display_name,
          ((active.snapshot_json.actions as unknown[] | undefined) ?? [])
            .map(normalizeAction),
        ).filter(isMonsterTurnAction),
    [active.display_name, active.snapshot_json.actions, activeCharacter, activeIsPlayerControlled],
  );
  const selectedActionBase = useMemo(
    () => actions[Number(actionIndex)] ?? actions[0] ?? {
      name: "未结构化动作",
      cost: "动作",
    },
    [actionIndex, actions],
  );
  const selectedAction = useMemo(() => {
    const spellLevel = Number(selectedActionBase.spell_level ?? 0);
    if (spellLevel <= 0) return selectedActionBase;
    const slotLevel = Math.max(spellLevel, selectedSlotLevel);
    const damage = upcastExpression(
      selectedActionBase.damage,
      slotLevel,
      spellLevel,
      Number(selectedActionBase.upcast_damage_dice ?? 0),
    );
    const healing = upcastExpression(
      selectedActionBase.healing,
      slotLevel,
      spellLevel,
      Number(selectedActionBase.upcast_healing_dice ?? 0),
    );
    return {
      ...selectedActionBase,
      damage,
      healing,
      damage_components: Array.isArray(selectedActionBase.damage_components)
        ? selectedActionBase.damage_components.map((component) => {
            const expression = typeof component.expression === "string"
              ? component.expression
              : typeof component.damage === "string"
                ? component.damage
                : undefined;
            const upcast = upcastExpression(
              expression,
              slotLevel,
              spellLevel,
              Number(selectedActionBase.upcast_damage_dice ?? 0),
            );
            return {
              ...component,
              ...(upcast ? { expression: upcast, damage: upcast } : {}),
            };
          })
        : selectedActionBase.damage_components,
      resource_key: `spell_slots_${slotLevel}`,
      resource_cost: 1,
      spell_level: spellLevel,
      selected_slot_level: slotLevel,
    };
  }, [selectedActionBase, selectedSlotLevel]);
  const selectedDamageComponents = useMemo(
    () => (Array.isArray(selectedAction.damage_components) ? selectedAction.damage_components : [])
      .filter((component) => (
        typeof component === "object"
        && typeof component.damage_type === "string"
        && component.damage_type.trim().length > 0
      )),
    [selectedAction.damage_components],
  );
  const selectedAreaDamageComponents = selectedDamageComponents.length > 1
    ? selectedDamageComponents
    : null;
  const hasAllDamageComponentTotals = selectedDamageComponents.length <= 1
    || selectedDamageComponents.every((_, index) => {
      const value = damageComponentTotals[String(index)];
      return value !== undefined && value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0;
    });
  useEffect(() => {
    setDamageComponentTotals({});
  }, [actionIndex, selectedSlotLevel, turnKey]);
  const selectedActionCost = actionCost(selectedAction);
  const rechargeAvailable = useMemo(() => {
    const raw = active.snapshot_json.recharge_available;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
    return Object.fromEntries(
      Object.entries(raw).filter(([, value]) => typeof value === "boolean"),
    );
  }, [active.snapshot_json.recharge_available]);
  const selectedRechargeRange = parseRechargeRange(selectedAction.recharge);
  const selectedRechargeKey = selectedRechargeRange
    ? rechargeActionKey(selectedAction, Number(actionIndex))
    : null;
  const selectedRechargeAvailable = isRechargeAvailable(
    selectedAction,
    rechargeAvailable,
    Number(actionIndex),
  );
  const selectedResourceKey = selectedAction.resource_key;
  const selectedResource = selectedResourceKey && activeCharacter
    ? activeCharacter.resources[selectedResourceKey] as {
        label?: string;
        current?: number;
        max?: number;
      } | undefined
    : undefined;
  const selectedResourceCost = Math.max(1, Number(selectedAction.resource_cost ?? 1));
  const selectedResourceAvailable = !selectedResourceKey
    || Number(selectedResource?.current ?? 0) >= selectedResourceCost;
  const selectedSpellLevel = Number(selectedActionBase.spell_level ?? 0);
  const availableSlotLevels = activeCharacter && selectedSpellLevel > 0
    ? Array.from({ length: 10 - selectedSpellLevel }, (_, index) => selectedSpellLevel + index)
      .filter((level) => activeCharacter.resources[`spell_slots_${level}`] != null)
    : [];
  const selectedActionAvailable = hasActionEconomy(active, selectedActionCost)
    && selectedResourceAvailable
    && selectedRechargeAvailable;
  const selectedMonsterSteps = activeIsPlayerControlled
    ? null
    : expandMonsterAction(actions, Number(actionIndex));
  const targetingAction = selectedAction.multiattack
    ? selectedMonsterSteps?.[0]?.action ?? selectedAction
    : selectedAction;
  const selectedTargeting = targetingForAction(targetingAction);
  const targetIdsForExecution = executableTargetIds(
    validTargetIds,
    targetingValidity?.horizontalTargetIds,
    selectedTargeting.requiresElevation === true,
  );
  const targetingRangeKnown = Boolean(
    selectedTargeting.originSelf
    || targetingAction.range_ft != null
    || parseRangeFeet(targetingAction.range) != null,
  );
  const isAreaSaveAction = Boolean(
    activeIsPlayerControlled
    && selectedAction.save_dc
    && selectedAction.save_ability
    && selectedTargeting.shape !== "single",
  );
  const isSingleSaveAction = Boolean(
    activeIsPlayerControlled
    && selectedAction.save_dc
    && selectedAction.save_ability
    && !isAreaSaveAction,
  );
  const saveAbilityLabel = ({ wisdom: "感知", dexterity: "敏捷", constitution: "体质", strength: "力量", intelligence: "智力", charisma: "魅力" } as Record<string, string>)[selectedAction.save_ability ?? ""] ?? selectedAction.save_ability;
  const isNarrativeAction = selectedAction.resolution_kind === "narrative";
  const possibleTargets = fighters.filter((fighter) => {
    const fighterIsPlayerControlled = isPlayerControlledCombatant(fighter.entity_type, fighter.snapshot_json);
    // When the current combat is map-backed, an unplaced summon/NPC is not a
    // legal automatic target.  Leaving it in this list lets the AI choose it,
    // then areaPromptFields cannot build an authoritative anchor and the
    // mutation error leaves the initiative cursor waiting forever.
    const mapTargetRequired = hasGridPosition(active.snapshot_json);
    return fighter.id !== active.id
      && fighter.hp > 0
      && (!mapTargetRequired || hasGridPosition(fighter.snapshot_json))
      && fighterIsPlayerControlled !== activeIsPlayerControlled;
  });
  const roundNumber = Number(turnKey.split(":")[0] ?? 1);
  const turnIndex = Number(turnKey.split(":")[1] ?? 0);
  const orderedFighters = [...fighters]
    .filter((fighter) => fighter.is_active)
    .sort((left, right) => right.initiative - left.initiative || left.display_name.localeCompare(right.display_name));
  const currentInitiative = orderedFighters[turnIndex]?.initiative;
  const previousInitiative = turnIndex > 0 ? orderedFighters[turnIndex - 1]?.initiative : undefined;
  const lairWindow = currentInitiative !== undefined
    && currentInitiative <= 20
    && (previousInitiative === undefined || previousInitiative > 20);
  const advancedChoices: AdvancedActionChoice[] = fighters.flatMap((fighter) => {
    if (fighter.entity_type !== "monster" || fighter.hp <= 0 || !fighter.is_active) return [];
    const rawActions = monsterActionsForRules(
      fighter.display_name,
      ((fighter.snapshot_json.actions as unknown[] | undefined) ?? []).map(normalizeAction),
    );
    return rawActions.flatMap((action, index) => {
      const phase = advancedActionPhase(action);
      if (!phase) return [];
      const availability = evaluateAdvancedActionAvailability(
        fighter,
        action,
        active,
        roundNumber,
        turnIndex,
        lairWindow,
        reactionTrigger,
      );
      if (!availability) return [];
      return [{
        key: `${fighter.id}:${index}`,
        actor: fighter,
        action,
        actionIndex: index,
        availability,
      }];
    });
  });
  const selectedAdvancedChoice = advancedChoices.find((choice) => choice.key === advancedChoiceKey)
    ?? advancedChoices.find((choice) => choice.availability.available)
    ?? advancedChoices[0];
  const selectedAdvancedIsAreaAction = selectedAdvancedChoice
    ? isAdvancedAreaAction(selectedAdvancedChoice.action)
    : false;
  const advancedCandidateTargets = selectedAdvancedChoice
    ? fighters.filter((fighter) => {
        const targetControlled = fighter.entity_type === "character"
          || fighter.snapshot_json.controller === "player";
        return fighter.id !== selectedAdvancedChoice.actor.id
          && fighter.hp > 0
          && fighter.is_active
          && targetControlled;
      })
    : [];
  const advancedAreaTargeting = selectedAdvancedChoice && selectedAdvancedIsAreaAction
    ? evaluateAdvancedAreaTargeting(
        selectedAdvancedChoice.action,
        selectedAdvancedChoice.actor,
        advancedCandidateTargets,
        advancedAreaTargetingKey === selectedAdvancedChoice.key
          ? targetingValidity
          : undefined,
      )
    : null;
  const advancedMapAnchor = advancedAreaTargetingKey === selectedAdvancedChoice?.key
    ? targetingValidity?.anchorPoint ?? null
    : null;
  const advancedTargets = selectedAdvancedIsAreaAction
    ? advancedCandidateTargets.filter((fighter) => advancedAreaTargeting?.eligibleTargetIds.has(fighter.id))
    : advancedCandidateTargets;
  // Keep target choice explicit. A candidate list is not permission to
  // invent the first target, especially for a reaction or DM-directed action.
  const selectedAdvancedTarget = advancedTargets.find((fighter) => fighter.id === advancedTargetId);
  const [advancedPreview, setAdvancedPreview] = useState<MonsterAIPreview | null>(null);
  const previewAdvancedAction = useMutation({
    mutationFn: () => {
      if (!selectedAdvancedChoice) throw new Error("没有可预览的高级动作");
      const raw = selectedAdvancedChoice.actor.snapshot_json.recharge_available;
      const rechargeAvailable = raw && typeof raw === "object" && !Array.isArray(raw)
        ? Object.fromEntries(
            Object.entries(raw).filter(([, value]) => typeof value === "boolean"),
          ) as Record<string, boolean>
        : undefined;
      return previewMonsterAI(
        campaignId,
        combatId,
        selectedAdvancedChoice.actor.id,
        {
          actorVersion: selectedAdvancedChoice.actor.version,
          phase: selectedAdvancedChoice.availability.phase as MonsterAIPhase,
          tactics,
          rechargeAvailable,
          reactionEvent: reactionEvent || undefined,
        },
      );
    },
    onSuccess: (result) => {
      setAdvancedPreview(result);
      showToast(result.plan ? "后端高级动作计划已返回，仍需 DM 确认" : "后端没有返回当前窗口可用计划", result.plan ? "success" : "error");
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "高级动作计划预览失败", "error"),
  });
  const target = fighters.find((fighter) => fighter.id === targetId);
  const skills = activeCharacter
    ? Object.keys(activeCharacter.skills).filter((name) => Boolean(activeCharacter.skills[name]))
    : [];
  const check = activeCharacter && freeform.trim()
    ? proposeFreeformCheck(
        freeform,
        activeCharacter.ability_scores,
        activeCharacter.level,
        skills,
      )
    : null;
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
    void client.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
    void client.invalidateQueries({ queryKey: ["combat-end-condition", campaignId, combatId] });
  };
  const preview = useMutation({
    mutationFn: ({ command, explanation }: { command: CombatActionCommand; explanation: string }) =>
      previewCombatAction(campaignId, combatId, command)
        .then((result) => ({ command, explanation, preview: result })),
    onSuccess: setPending,
    onError: () => showToast("无法生成动作结算预览", "error"),
  });
  const confirm = useMutation({
    mutationFn: () => {
      if (!pending) throw new Error("没有待确认动作");
      return confirmCombatAction(campaignId, combatId, pending.command);
    },
    onSuccess: () => {
      setPending(null);
      invalidate();
      showToast("动作已由 DM 确认并写入战斗日志");
    },
    onError: () => showToast("动作确认失败，目标状态可能已改变", "error"),
  });
  const confirmArea = useMutation({
    mutationFn: async () => {
      if (!pendingArea) throw new Error("没有待确认的区域法术");
      const forcedMovement = pendingArea.forcedMovement;
      const items: CombatActionBatchCommand["items"] = pendingArea.resolution.targets.map((result, index) => {
        const currentTarget = fighters.find((fighter) => fighter.id === result.targetId);
        if (!currentTarget) throw new Error(`${result.targetName}已不在本场战斗`);
        return {
          idempotency_key: `area:${combatId}:${pendingArea.actionName}:${result.targetId}:${result.d20}:${index}`,
          command: {
            action_type: "damage",
            // Keep the origin actor on every target command so the backend can
            // re-check the same authoritative 3-D volume for every target.
            // Only the first command spends the action; later commands are
            // target resolutions in the same already-approved spell. The
            // first action flips the actor CAS version once, so later
            // action_cost=none commands use the post-spend version during the
            // batch preflight while still retaining the source for push-away.
            actor_combatant_id: active.id,
            actor_version: active.version + (index === 0 ? 0 : 1),
            action_cost: index === 0 ? pendingArea.actionCost : "none",
            action_name: pendingArea.actionName,
            resolution_note: `${result.targetName}：${pendingArea.resolution.saveAbility}豁免 d20(${result.d20}) ${result.modifier >= 0 ? "+" : ""}${result.modifier} = ${result.saveTotal}，对 DC ${pendingArea.resolution.saveDc} ${result.success ? "成功" : "失败"}；承受 ${result.damage} 点${pendingArea.damageType}伤害`,
            target_combatant_id: result.targetId,
            target_version: currentTarget.version,
            amount: result.damage,
            damage_type: pendingArea.resolution.damageType,
            damage_components: result.damageComponents.map((component) => ({
              amount: component.amount,
              damage_type: component.damageType,
              damage_tags: component.damageTags,
            })),
            forced_movement_distance_ft: !result.success ? forcedMovement?.distance_ft ?? null : null,
            forced_movement_direction: !result.success ? forcedMovement?.direction ?? null : null,
            ...pendingArea.areaFields,
          },
        };
      });
      await confirmCombatActionBatch(campaignId, combatId, { items });
      if (selectedResourceKey && activeCharacter && selectedResource) {
        await updateCharacter(
          campaignId,
          activeCharacter.id,
          {
            resources: {
              ...activeCharacter.resources,
              [selectedResourceKey]: {
                ...selectedResource,
                current: Math.max(
                  0,
                  Number(selectedResource.current ?? 0) - selectedResourceCost,
                ),
              },
            },
          },
          activeCharacter.version,
        );
      }
    },
    onSuccess: () => {
      setPendingArea(null);
      invalidate();
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      showToast(
        selectedResourceKey
          ? `区域法术已对全部目标结算；只消耗一次动作和 ${selectedResourceCost} 点${selectedResource?.label ?? selectedResourceKey}`
          : "区域法术已对范围内全部目标结算；动作只消耗一次",
      );
    },
    onError: (error) => showToast(
      error instanceof Error ? error.message : "区域法术结算失败，目标状态可能已改变",
      "error",
    ),
  });
  const freeformConditions = /滑倒|摔倒|绊倒|失去平衡|推倒/.test(freeform)
    ? ["prone"]
    : [];
  const executeFreeform = useMutation({
    mutationFn: () => {
      if (!activeCharacter || !check || !target || !freeform.trim()) {
        throw new Error("请填写自由行动、选择目标，并确认当前行动单位是玩家角色");
      }
      const resolutionType = check.skill === "临场判断" ? "ability_check" : "skill_check";
      return createPlayerRollPrompt(campaignId, combatId, {
        actor_combatant_id: active.id,
        actor_version: active.version,
        action_cost: "action",
        // The player rolls their own check.  The optional effect target is
        // resolved only after that roll succeeds, so an enemy never receives
        // a player-facing dice prompt by mistake.
        target_combatant_id: active.id,
        target_version: active.version,
        effect_target_combatant_id: target.id,
        effect_target_version: target.version,
        action_name: `自由行动：${freeform.trim().slice(0, 160)}`,
        resolution_type: resolutionType,
        dc: check.dc,
        ability: check.ability,
        skill: resolutionType === "skill_check" ? check.skill : null,
        roll_formula: "1d20",
        conditions_on_success: freeformConditions,
        condition_duration: freeformConditions.length ? "target_turn_end" : null,
        description: `规则助手建议：${check.skill}（${check.abilityLabel}）d20 + ${check.modifier >= 0 ? "+" : ""}${check.modifier}，对抗 DC ${check.dc}。${check.explanation}。${freeformConditions.length ? "成功后目标获得倒地状态，持续到目标回合结束。" : "成功后的叙事效果由 DM 根据输入确认。"}`,
      });
    },
    onSuccess: () => {
      setFreeform("");
      invalidate();
      showToast("已执行规则建议；玩家端现在会收到骰子输入");
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "自由行动执行失败", "error"),
  });
  const requestPlayerSave = useMutation({
    mutationFn: ({
      chosenTarget,
      failureDamage,
      successDamage,
      failureComponents,
      successComponents,
    }: {
      chosenTarget: Combatant;
      failureDamage: number;
      successDamage: number;
      failureComponents?: Array<{ amount: number; damage_type: string; damage_tags?: string[] }>;
      successComponents?: Array<{ amount: number; damage_type: string; damage_tags?: string[] }>;
    }) => createPlayerRollPrompt(campaignId, combatId, {
      actor_combatant_id: active.id,
      actor_version: active.version,
      target_combatant_id: chosenTarget.id,
      target_version: chosenTarget.version,
      action_name: selectedAction.name ?? "怪物能力",
      action_cost: selectedActionCost,
      resolution_type: "saving_throw",
      dc: selectedAction.save_dc ?? 10,
      ability: selectedAction.save_ability ?? "dexterity",
      skill: null,
      damage_on_success: successDamage,
      damage_on_failure: failureDamage,
      damage_components_on_success: successComponents ?? [],
      damage_components_on_failure: failureComponents ?? [],
      damage_type: typeof selectedAction.damage_type === "string"
        ? selectedAction.damage_type.trim()
        : null,
      recharge_key: selectedRechargeKey,
      recharge_consume: Boolean(selectedRechargeKey),
      description: `${active.display_name} 对 ${chosenTarget.display_name} 使用「${selectedAction.name ?? "怪物能力"}」，等待玩家进行${selectedAction.save_ability ?? "敏捷"}豁免。`,
    }),
    onSuccess: () => {
      invalidate();
      showToast("已在右侧战斗面板生成玩家豁免请求");
    },
    onError: () => {
      processedAutomaticTurn.current = null;
      showToast("无法生成玩家豁免请求", "error");
    },
  });
  const executeMonsterSequence = useMutation({
    mutationFn: async ({ chosenTarget }: { chosenTarget: Combatant }) => {
      const steps = expandMonsterAction(actions, Number(actionIndex));
      if (!steps?.length) {
        throw new Error("多重攻击的子动作与次数没有可靠解析，请由 DM 裁定");
      }
      if (steps.some((step) => step.action.auto_eligible === false)) {
        throw new Error("动作序列包含条件、持续时间或数值未明确的子动作，请由 DM 裁定");
      }
      type RecordToExecute = {
        kind: "attack" | "save";
        action: CombatActionLike;
        target: Combatant;
        damage: number;
        damageComponents: Array<{ amount: number; damage_type: string; damage_tags?: string[] }>;
        hit?: boolean;
        note: string;
      };
      const records: RecordToExecute[] = [];
      let currentTarget = chosenTarget;
      for (const step of steps) {
        const action = step.action;
        const rolledDamage = rollStructuredDamage(action);
        const damageType = rolledDamage?.damageType ?? String(action.damage_type ?? "").trim();
        const rangeKnown = action.range_ft != null || parseRangeFeet(action.range) != null;
        if (!rolledDamage || !damageType || (!rangeKnown && !action.area_origin_self)) {
          throw new Error(`「${action.name ?? "怪物动作"}」缺少可靠伤害骰、伤害类型或距离`);
        }
        if (action.save_dc && action.save_ability) {
          const isArea = Boolean(action.area_shape && action.area_shape !== "single")
            || Boolean(action.affects_multiple_targets);
          const affected = isArea
            ? possibleTargets.filter((fighter) => targetIdsForExecution?.has(fighter.id))
            : [currentTarget];
          if (affected.length === 0) {
            throw new Error(`「${action.name ?? "区域能力"}」尚未在地图上覆盖任何玩家目标`);
          }
          for (const affectedTarget of affected) {
            records.push({
              kind: "save",
              action,
              target: affectedTarget,
              damage: rolledDamage.total,
              damageComponents: rolledDamage.components,
              note: `${affectedTarget.display_name}需要进行${action.save_ability}豁免`,
            });
          }
          continue;
        }
        if (action.attack_bonus === undefined) {
          throw new Error(`「${action.name ?? "怪物攻击"}」没有明确攻击加值`);
        }
        const d20 = Math.floor(Math.random() * 20) + 1;
        const attackTotalValue = d20 + action.attack_bonus;
        const hit = attackTotalValue >= currentTarget.armor_class;
        const damage = hit ? rolledDamage.total : 0;
        records.push({
          kind: "attack",
          action,
          target: currentTarget,
          damage,
          damageComponents: hit ? rolledDamage.components : [],
          hit,
          note: `d20(${d20}) + ${action.attack_bonus} = ${attackTotalValue}，${hit ? `命中 AC ${currentTarget.armor_class}` : `未达到 AC ${currentTarget.armor_class}`}`,
        });
      }
      if (records.length === 0) throw new Error("怪物动作序列为空");
      // Combat reset clears the visible action log but intentionally keeps
      // operation transactions for audit/idempotency.  Include the current
      // combatant version so the same initiative slot in a fresh reset is a
      // new execution window, while duplicate requests in one window still
      // share the same idempotency key.
      const sequenceId = `monster:${combatId.slice(0, 8)}:${turnKey}:${active.id.slice(0, 8)}:${active.version}:${actionIndex}`;
      let actorVersion = active.version;
      const targetVersions = new Map(fighters.map((fighter) => [fighter.id, fighter.version]));
      let pendingRollCount = 0;
      if (records.length > 1 && records.every((record) => record.kind === "save")) {
        const first = records[0];
        if (!first) throw new Error("怪物区域豁免动作缺少首个目标");
        const firstAreaFields = areaPromptFields(first.action, active, first.target);
        const batchBase = {
          actor_combatant_id: active.id,
          actor_version: actorVersion,
          action_cost: selectedActionCost,
          action_name: selectedAction.multiattack
            ? `${selectedAction.name ?? "多重攻击"} · 区域豁免`
            : first.action.name ?? "怪物区域动作",
          ...firstAreaFields,
          resolution_type: "saving_throw" as const,
          dc: Number(first.action.save_dc),
          ability: String(first.action.save_ability),
          damage_on_success: first.action.half_damage_on_save
            ? Math.floor(first.damage / 2)
            : 0,
          damage_on_failure: first.damage,
          damage_components_on_failure: first.damageComponents,
          damage_components_on_success: first.action.half_damage_on_save
            ? first.damageComponents.map((component) => ({
                ...component,
                amount: Math.floor(component.amount / 2),
              }))
            : [],
          damage_type: first.damageComponents.length === 1
            ? first.damageComponents[0]?.damage_type ?? null
            : "mixed",
          recharge_key: selectedRechargeKey,
          recharge_consume: Boolean(selectedRechargeKey),
          sequence_id: sequenceId,
          sequence_step: 0,
          sequence_size: records.length,
          description: `${active.display_name}使用「${first.action.name ?? "怪物区域动作"}」；向 ${records.length} 名玩家发出豁免请求。`,
        };
        const batchResponse = await createPlayerRollPromptBatch(
          campaignId,
          combatId,
          {
            ...batchBase,
            targets: records.map((record) => ({
              target_combatant_id: record.target.id,
              target_version: targetVersions.get(record.target.id) ?? record.target.version,
            })),
          },
          `${sequenceId}:batch`,
        );
        pendingRollCount = batchResponse.actions.length;
        actorVersion = batchResponse.actor.version;
        return { pendingRollCount, recordCount: records.length };
      }
      for (const [index, record] of records.entries()) {
        const cost = index === 0 ? selectedActionCost : "none";
        const common = {
          actor_combatant_id: active.id,
          actor_version: actorVersion,
          action_cost: cost,
          action_name: selectedAction.multiattack
            ? `${selectedAction.name ?? "多重攻击"} · ${record.action.name ?? `第${index + 1}击`}`
            : record.action.name ?? "怪物动作",
          target_combatant_id: record.target.id,
          target_version: targetVersions.get(record.target.id) ?? record.target.version,
          recharge_key: index === 0 ? selectedRechargeKey : null,
          recharge_consume: index === 0 && Boolean(selectedRechargeKey),
          sequence_id: sequenceId,
          sequence_step: index,
          sequence_size: records.length,
        } as const;
        const requestId = `${sequenceId}:${index}`;
        if (record.kind === "save") {
          const areaFields = areaPromptFields(record.action, active, record.target);
          if (record.action.area_shape && record.action.area_shape !== "single" && Object.keys(areaFields).length === 0) {
            throw new Error(`「${record.action.name ?? "区域能力"}」缺少可验证的三维锚点或高度，已暂停给 DM 裁定`);
          }
          const successDamage = record.action.half_damage_on_save
            ? Math.floor(record.damage / 2)
            : 0;
          const response = await createPlayerRollPrompt(campaignId, combatId, {
            ...common,
            ...areaFields,
            resolution_type: "saving_throw",
            dc: Number(record.action.save_dc),
            ability: String(record.action.save_ability),
            skill: null,
            damage_on_success: successDamage,
            damage_on_failure: record.damage,
            damage_components_on_failure: record.damageComponents,
            damage_components_on_success: record.action.half_damage_on_save
              ? record.damageComponents.map((component) => ({
                  ...component,
                  amount: Math.floor(component.amount / 2),
                }))
              : [],
            damage_type: record.damageComponents.length === 1
              ? record.damageComponents[0]?.damage_type ?? null
              : "mixed",
            conditions_on_failure: record.action.conditions_on_failure ?? [],
            conditions_on_success: record.action.conditions_on_success ?? [],
            condition_duration: record.action.condition_duration ?? null,
            condition_duration_value: record.action.condition_duration_value ?? null,
            condition_save_dc: record.action.condition_save_dc ?? null,
            condition_save_ability: record.action.condition_save_ability ?? null,
            movement_on_failure_ft: record.action.movement?.distance_ft ?? null,
            movement_direction: record.action.movement?.direction ?? null,
            description: `${active.display_name}使用「${record.action.name ?? "怪物能力"}」；${record.note}。`,
          }, requestId);
          actorVersion = response.actor.version;
          pendingRollCount += 1;
        } else {
          const response = await confirmCombatAction(campaignId, combatId, {
            ...common,
            action_type: "damage",
            amount: record.damage,
            damage_type: record.damageComponents.length === 1
              ? record.damageComponents[0]?.damage_type ?? null
              : "mixed",
            damage_components: record.damageComponents,
            is_attack: true,
            attack_roll_mode: "normal",
            attack_adjudication_note: record.note,
            resolution_note: `${record.note}；${record.hit ? `造成 ${record.damage} 点${record.action.damage_type}伤害` : "攻击未命中"}`,
            conditions_to_apply: record.hit ? record.action.conditions_on_hit ?? [] : [],
            condition_duration: record.hit ? record.action.condition_duration ?? null : null,
            condition_duration_value: record.hit ? record.action.condition_duration_value ?? null : null,
            condition_save_dc: record.hit ? record.action.condition_save_dc ?? null : null,
            condition_save_ability: record.hit ? record.action.condition_save_ability ?? null : null,
            forced_movement_distance_ft: record.hit ? record.action.movement?.distance_ft ?? null : null,
            forced_movement_direction: record.hit ? record.action.movement?.direction ?? null : null,
          }, requestId);
          actorVersion = response.actor?.version ?? actorVersion;
          targetVersions.set(record.target.id, response.target.version);
          if (response.target.hp <= 0) {
            currentTarget = chooseEnemyTarget(
              possibleTargets.filter((fighter) => fighter.id !== record.target.id),
              tactics,
            ) ?? currentTarget;
          }
        }
      }
      return { pendingRollCount, recordCount: records.length };
    },
    onSuccess: async ({ pendingRollCount, recordCount }) => {
      invalidate();
      if (pendingRollCount > 0) {
        showToast(`怪物动作序列已记录 ${recordCount} 步；等待 ${pendingRollCount} 个玩家豁免后恢复`);
        return;
      }
      showToast(`怪物已完成 ${recordCount} 步动作序列`);
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      onEnemyTurnComplete();
    },
    onError: async (error) => {
      monsterSequenceInFlight.current = null;
      processedAutomaticTurn.current = null;
      // A turn boundary or another DM/player write can legitimately make the
      // optimistic snapshot stale.  Refresh before retrying; otherwise the
      // effect keeps the cursor on an AI unit with no way to recover.
      await Promise.all([
        client.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] }),
        client.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] }),
      ]);
      showToast(error instanceof Error ? error.message : "怪物动作序列失败，已暂停供 DM 检查", "error");
    },
  });
  const executeAdvancedMonsterAction = useMutation({
    mutationFn: async () => {
      if (!selectedAdvancedChoice || (!selectedAdvancedIsAreaAction && !selectedAdvancedTarget)) {
        throw new Error("没有可执行的怪物高级动作或目标");
      }
      const { actor, action } = selectedAdvancedChoice;
      const cost = monsterActionCost(action);
      if (!selectedAdvancedChoice.availability.available) {
        throw new Error(selectedAdvancedChoice.availability.blockingReasons.join("；"));
      }
      if (!(["legendary_action", "lair_action", "reaction"] as ActionCost[]).includes(cost)) {
        throw new Error("该动作不属于传奇、巢穴或反应窗口");
      }
      if (cost === "reaction" && !reactionTrigger.trim()) {
        throw new Error("怪物反应必须由 DM 写明本次触发事件");
      }
      if ((action.conditions_on_failure?.length || action.conditions_on_hit?.length) && !action.condition_duration) {
        throw new Error("该动作的状态持续时间未可靠解析，请由 DM 在高级编辑中裁定");
      }
      if (selectedAdvancedIsAreaAction && (
        advancedAreaTargetingKey !== selectedAdvancedChoice.key
        || !advancedAreaTargeting?.ready
      )) {
        throw new Error(
          advancedAreaTargeting?.blockingReasons.join("；")
            || "请先在地图定位高级区域，并完成后端权威三维复核前的高度数据检查",
        );
      }
      const rolledDamage = rollStructuredDamage(action);
      const damageType = rolledDamage?.damageType ?? String(action.damage_type ?? "").trim();
      const hasStructuredDamage = Boolean(rolledDamage);
      if (!hasStructuredDamage && !action.save_dc && action.attack_bonus === undefined) {
        throw new Error("该高级动作既没有可靠伤害，也没有豁免或攻击加值，保留给 DM 裁定");
      }
      const affectedTargets = selectedAdvancedIsAreaAction
        ? advancedTargets
        : selectedAdvancedTarget ? [selectedAdvancedTarget] : [];
      if (affectedTargets.length === 0) {
        throw new Error("当前高级区域没有通过水平与垂直几何检查的目标");
      }
      const sharedDamage = rolledDamage?.total ?? 0;
      const sharedDamageComponents = rolledDamage?.components ?? [];
      const sequenceId = `advanced:${combatId.slice(0, 8)}:${turnKey}:${actor.id.slice(0, 8)}:${selectedAdvancedChoice.actionIndex}`;
      const advancedPendingRollDescription = advancedActionPendingRollSummary({
        actorName: actor.display_name,
        actionName: action.name,
        actionCost: cost,
        legendaryCost: action.legendary_cost,
        legendaryPoolMax: action.legendary_pool_max,
        reactionTrigger,
      }) ?? "DM 已创建玩家待掷骰请求；提交骰子前，此动作尚未完成结算。";
      let actorVersion = actor.version;
      let pendingRollCount = 0;
      let batchedSave = false;
      if (action.save_dc && action.save_ability && affectedTargets.length > 1) {
        const firstTarget = affectedTargets[0];
        if (!firstTarget) throw new Error("区域动作缺少第一个有效目标");
        const areaFields = areaPromptFields(action, actor, firstTarget, advancedMapAnchor);
        if (action.area_shape && action.area_shape !== "single" && Object.keys(areaFields).length === 0) {
          throw new Error(`「${action.name ?? "区域能力"}」缺少可验证的三维锚点或高度，不能创建玩家豁免请求`);
        }
        const promptBase = {
          actor_combatant_id: actor.id,
          actor_version: actorVersion,
          action_cost: cost,
          action_name: action.name ?? "怪物高级动作",
          target_combatant_id: firstTarget.id,
          target_version: firstTarget.version,
          legendary_cost: cost === "legendary_action" ? Number(action.legendary_cost ?? 1) : null,
          legendary_pool_max: cost === "legendary_action" ? Number(action.legendary_pool_max) : null,
          reaction_trigger: cost === "reaction" ? reactionTrigger.trim() : null,
          reaction_event: cost === "reaction" ? reactionEvent || null : null,
          sequence_id: sequenceId,
          sequence_step: 0,
          sequence_size: affectedTargets.length,
          requires_explicit_elevation: true,
          ...areaFields,
          resolution_type: "saving_throw" as const,
          dc: action.save_dc,
          ability: action.save_ability,
          damage_on_failure: sharedDamage,
          damage_on_success: action.half_damage_on_save ? Math.floor(sharedDamage / 2) : 0,
          damage_components_on_failure: sharedDamageComponents,
          damage_components_on_success: action.half_damage_on_save
            ? sharedDamageComponents.map((component) => ({
                amount: Math.floor(component.amount / 2),
                damage_type: component.damage_type,
              }))
            : [],
          damage_type: hasStructuredDamage ? damageType : null,
          conditions_on_failure: action.conditions_on_failure ?? [],
          condition_duration: action.condition_duration ?? null,
          condition_duration_value: action.condition_duration_value ?? null,
          condition_save_dc: action.condition_save_dc ?? null,
          condition_save_ability: action.condition_save_ability ?? null,
          movement_on_failure_ft: action.movement?.distance_ft ?? null,
          movement_direction: action.movement?.direction ?? null,
          description: advancedPendingRollDescription,
        };
        const batchBase = Object.fromEntries(
          Object.entries(promptBase).filter(([key]) => (
            key !== "target_combatant_id" && key !== "target_version"
          )),
        ) as Omit<typeof promptBase, "target_combatant_id" | "target_version">;
        const response = await createPlayerRollPromptBatch(campaignId, combatId, {
          ...batchBase,
          targets: affectedTargets.map((candidate) => ({
            target_combatant_id: candidate.id,
            target_version: candidate.version,
          })),
        }, `${sequenceId}:batch`);
        actorVersion = response.actor.version;
        pendingRollCount = response.actions.length;
        batchedSave = true;
      }
      if (!batchedSave) {
        for (const [index, affectedTarget] of affectedTargets.entries()) {
        const actionCostValue = index === 0 ? cost : "none";
        const areaFields = areaPromptFields(action, actor, affectedTarget, advancedMapAnchor);
        if (action.area_shape && action.area_shape !== "single" && Object.keys(areaFields).length === 0) {
          throw new Error(`「${action.name ?? "区域能力"}」缺少可验证的三维锚点或高度，不能创建玩家豁免请求`);
        }
        const common = {
          actor_combatant_id: actor.id,
          actor_version: actorVersion,
          action_cost: actionCostValue,
          action_name: action.name ?? "怪物高级动作",
          target_combatant_id: affectedTarget.id,
          target_version: affectedTarget.version,
          legendary_cost: actionCostValue === "legendary_action" ? Number(action.legendary_cost ?? 1) : null,
          legendary_pool_max: actionCostValue === "legendary_action" ? Number(action.legendary_pool_max) : null,
          reaction_trigger: actionCostValue === "reaction" ? reactionTrigger.trim() : null,
          reaction_event: actionCostValue === "reaction" ? reactionEvent || null : null,
          sequence_id: sequenceId,
          sequence_step: index,
          sequence_size: affectedTargets.length,
          requires_explicit_elevation: selectedAdvancedIsAreaAction,
        } as const;
        const requestId = `${sequenceId}:${index}`;
        if (action.save_dc && action.save_ability) {
          const promptBase = {
            ...common,
            ...areaFields,
            resolution_type: "saving_throw" as const,
            dc: action.save_dc,
            ability: action.save_ability,
            damage_on_failure: sharedDamage,
            damage_on_success: action.half_damage_on_save ? Math.floor(sharedDamage / 2) : 0,
            damage_components_on_failure: sharedDamageComponents,
            damage_components_on_success: action.half_damage_on_save
              ? sharedDamageComponents.map((component) => ({
                  amount: Math.floor(component.amount / 2),
                  damage_type: component.damage_type,
                }))
              : [],
            damage_type: hasStructuredDamage ? damageType : null,
            conditions_on_failure: action.conditions_on_failure ?? [],
            condition_duration: action.condition_duration ?? null,
            condition_duration_value: action.condition_duration_value ?? null,
            condition_save_dc: action.condition_save_dc ?? null,
            condition_save_ability: action.condition_save_ability ?? null,
            movement_on_failure_ft: action.movement?.distance_ft ?? null,
            movement_direction: action.movement?.direction ?? null,
            description: advancedPendingRollDescription,
          };
          if (affectedTargets.length > 1) {
            const batchBase = Object.fromEntries(
              Object.entries(promptBase).filter(([key]) => (
                key !== "target_combatant_id" && key !== "target_version"
              )),
            ) as Omit<typeof promptBase, "target_combatant_id" | "target_version">;
            const response = await createPlayerRollPromptBatch(campaignId, combatId, {
              ...batchBase,
              targets: affectedTargets.map((candidate) => ({
                target_combatant_id: candidate.id,
                target_version: candidate.version,
              })),
            }, requestId);
            actorVersion = response.actor.version;
            pendingRollCount += response.actions.length;
          } else {
            const response = await createPlayerRollPrompt(campaignId, combatId, promptBase, requestId);
            actorVersion = response.actor.version;
            pendingRollCount += 1;
          }
        } else {
          if (action.attack_bonus === undefined) {
            throw new Error("该高级动作没有明确攻击加值，保留给 DM 裁定");
          }
          const attackTotalValue = Number(advancedAttackTotal);
          if (!Number.isInteger(attackTotalValue) || attackTotalValue < -100 || attackTotalValue > 1000) {
            throw new Error("请先填写 DM 实际掷出的攻击总值");
          }
          const hit = attackTotalValue >= affectedTarget.armor_class;
          const response = await confirmCombatAction(campaignId, combatId, {
            ...common,
            action_type: "damage",
            amount: hit ? sharedDamage : 0,
            damage_type: hasStructuredDamage ? damageType : null,
            damage_components: hit ? sharedDamageComponents : [],
            is_attack: true,
            attack_roll_mode: "normal",
            attack_roll_total: attackTotalValue,
            attack_adjudication_note: `DM确认高级动作窗口；报告攻击总值 ${attackTotalValue}（动作加值 ${action.attack_bonus}）`,
            resolution_note: hit
              ? `命中并造成 ${sharedDamage} 点${damageType}伤害`
              : `未达到 AC ${affectedTarget.armor_class}，攻击未命中`,
            conditions_to_apply: hit ? action.conditions_on_hit ?? [] : [],
            condition_duration: hit ? action.condition_duration ?? null : null,
            condition_duration_value: hit ? action.condition_duration_value ?? null : null,
            condition_save_dc: hit ? action.condition_save_dc ?? null : null,
            condition_save_ability: hit ? action.condition_save_ability ?? null : null,
            forced_movement_distance_ft: hit ? action.movement?.distance_ft ?? null : null,
            forced_movement_direction: hit ? action.movement?.direction ?? null : null,
          }, requestId);
          actorVersion = response.actor?.version ?? actorVersion;
        }
        }
      }
      return { pendingRollCount, targetCount: affectedTargets.length, cost };
    },
    onSuccess: ({ pendingRollCount, targetCount, cost }) => {
      invalidate();
      setReactionTrigger("");
      setReactionEvent("");
      setAdvancedAttackTotal("");
      setAdvancedAreaTargetingKey(null);
      onRangeChange(targetingForAction(targetingAction), active.id);
      const phase = advancedActionPhaseFromCost(cost);
      const phaseLabel = phase ? advancedPhaseLabel(phase) : "高级动作";
      showToast(
        pendingRollCount > 0
          ? `${phaseLabel}已创建 ${targetCount} 个待玩家豁免请求；骰子提交前不会视为结算完成。`
          : `${phaseLabel}已按 DM 确认结算`,
      );
    },
    onError: (error) => showToast(
      error instanceof Error ? error.message : "怪物高级动作结算失败",
      "error",
    ),
  });
  const autoResolve = useMutation({
    mutationFn: (command: CombatActionCommand) =>
      confirmCombatAction(campaignId, combatId, command),
    onSuccess: async () => {
      invalidate();
      showToast(`${active.display_name}已完成攻击；正在展示命中与伤害效果`);
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      onEnemyTurnComplete();
    },
    onError: () => {
      processedAutomaticTurn.current = null;
      showToast("怪物自动动作失败，已暂停在当前回合供 DM 检查", "error");
    },
  });
  const rechargeRoll = useMutation({
    mutationFn: () => {
      if (!selectedRechargeRange || !selectedRechargeKey) {
        throw new Error("当前动作不是充能动作");
      }
      const roll = Math.floor(Math.random() * 6) + 1;
      return updateCombatant(
        campaignId,
        combatId,
        active.id,
        {
          snapshot_json: {
            ...active.snapshot_json,
            recharge_available: {
              ...(rechargeAvailable ?? {}),
              [selectedRechargeKey]: roll >= selectedRechargeRange.minimum,
            },
            recharge_rolls: {
              ...(
                active.snapshot_json.recharge_rolls
                && typeof active.snapshot_json.recharge_rolls === "object"
                && !Array.isArray(active.snapshot_json.recharge_rolls)
                  ? active.snapshot_json.recharge_rolls
                  : {}
              ),
              [selectedRechargeKey]: roll,
            },
          },
        },
        active.version,
      ).then((result) => ({ result, roll }));
    },
    onSuccess: ({ roll }) => {
      invalidate();
      showToast(
        `${selectedRechargeKey} 充能骰为 ${roll}：${roll >= (selectedRechargeRange?.minimum ?? 7) ? "可用" : "仍在充能"}`,
        roll >= (selectedRechargeRange?.minimum ?? 7) ? "success" : "info",
      );
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "充能状态写入失败", "error"),
  });

  const selectAction = (value: string) => {
    setActionIndex(value);
    setAttackTotal("");
    setSaveTotal("");
    setDamageTotal("");
    const action = actions[Number(value)] ?? selectedAction;
    setSelectedSlotLevel(Math.max(1, Number(action.spell_level ?? 1)));
    setPending(null);
    setPendingArea(null);
    const steps = activeIsPlayerControlled ? null : expandMonsterAction(actions, Number(value));
    setAdvancedAreaTargetingKey(null);
    onRangeChange(
      targetingForAction(action.multiattack ? steps?.[0]?.action ?? action : action),
      active.id,
    );
  };
  useEffect(() => {
    if (selectedTargetId === undefined) return;
    if (advancedAreaTargetingKey) {
      if (advancedTargets.some((fighter) => fighter.id === selectedTargetId)) {
        setAdvancedTargetId((current) => current === selectedTargetId ? current : selectedTargetId);
      }
      return;
    }
    if (selectedTargetId !== targetId) {
      setTargetId(selectedTargetId);
    }
  }, [advancedAreaTargetingKey, advancedTargets, selectedTargetId, targetId]);
  useEffect(() => {
    const nextIndex = activeIsPlayerControlled
      ? 0
      : chooseEnemyActionIndex(
          actions,
          tactics,
          Number(turnKey.split(":")[0] ?? 0),
          rechargeAvailable,
        );
    selectAction(String(nextIndex));
    // The active fighter/action list changed; initialize the map indicator.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active.id, rechargeAvailable, tactics, turnKey]);
  const prepareAttack = (
    automatic: boolean,
    forcedTarget?: Combatant,
    fullyAutomaticEnemy = false,
  ): boolean => {
    if (!targetingRangeKnown) {
      showToast("该动作没有明确施法/触及距离，不能按默认距离自动结算；请由 DM 裁定", "error");
      return false;
    }
    const chosenTarget = forcedTarget ?? target;
    if (!selectedActionAvailable) {
      showToast(
        selectedActionCost === "bonus_action"
          ? "本回合附赠动作已经使用"
          : selectedActionCost === "reaction"
            ? "本轮反应已经使用"
            : "本回合动作已经使用，请结束回合",
        "error",
      );
      return false;
    }
    if (!chosenTarget) {
      showToast("请先选择目标", "error");
      return false;
    }
    if (targetIdsForExecution && !targetIdsForExecution.has(chosenTarget.id)) {
      showToast("目标不在当前技能的合法距离或范围内，请先在战斗地图上选择有效目标", "error");
      return false;
    }
    if (!activeIsPlayerControlled && fullyAutomaticEnemy) {
      executeMonsterSequence.mutate({ chosenTarget });
      return true;
    }
    const damagePreview = rollStructuredDamage(selectedAction);
    const damageType = damagePreview?.damageType
      ?? (typeof selectedAction.damage_type === "string" ? selectedAction.damage_type.trim() : "");
    if (!damagePreview || !damageType) {
      showToast("该动作没有明确伤害类型，不能默认当作未分类伤害；请由 DM 裁定", "error");
      return false;
    }
    if (
      !activeIsPlayerControlled
      && selectedAction.save_dc
      && selectedAction.save_ability
    ) {
      const successComponents = selectedAction.half_damage_on_save
        ? damagePreview.components.map((component) => ({
            ...component,
            amount: Math.floor(component.amount / 2),
          }))
        : [];
      const successDamage = selectedAction.half_damage_on_save
        ? successComponents.reduce((sum, component) => sum + component.amount, 0)
        : 0;
      requestPlayerSave.mutate({
        chosenTarget,
        failureDamage: damagePreview.total,
        successDamage,
        failureComponents: damagePreview.components,
        successComponents,
      });
      return true;
    }
    if (automatic && selectedAction.attack_bonus === undefined) {
      showToast("该动作没有明确攻击加值，不能自动猜测；请切换 DM 手动并按规则裁定", "error");
      return false;
    }
    const modifier = activeCharacter
      ? actionModifier(activeCharacter, selectedAction)
      : selectedAction.attack_bonus ?? 0;
    const forcedMovement = forcedMovementFromAction(selectedAction);
    const d20 = Math.floor(Math.random() * 20) + 1;
    const finalAttack = automatic ? d20 + modifier : Number(attackTotal);
    const hit = finalAttack >= chosenTarget.armor_class;
    const manualComponents = selectedDamageComponents.length > 1
      ? selectedDamageComponents.map((component, index) => ({
          amount: Number(damageComponentTotals[String(index)]),
          damage_type: String(component.damage_type),
          ...(Array.isArray(component.damage_tags) ? { damage_tags: component.damage_tags } : {}),
        }))
      : null;
    if (!automatic && manualComponents?.some((component) => !Number.isFinite(component.amount) || component.amount < 0)) {
      showToast("请分别填写每一段伤害骰的最终结果；系统会分别应用抗性、易伤和免疫", "error");
      return false;
    }
    const finalComponents = automatic
      ? damagePreview.components
      : manualComponents ?? [{ amount: Number(damageTotal), damage_type: damageType }];
    const finalDamage = finalComponents.reduce((sum, component) => sum + component.amount, 0);
    if (!Number.isFinite(finalDamage) || finalDamage < 0) {
      showToast("请输入玩家掷出的最终伤害", "error");
      return false;
    }
    const explanation = hit
      ? automatic
        ? `${active.display_name} → ${chosenTarget.display_name}，使用「${selectedAction.name ?? "攻击"}」：d20(${d20}) + ${modifier} = ${finalAttack}，命中 AC ${chosenTarget.armor_class}；分段伤害 ${finalComponents.map((component) => `${component.amount}${component.damage_type}`).join("+")} = ${finalDamage}`
        : `${active.display_name} → ${chosenTarget.display_name}，使用「${selectedAction.name ?? "攻击"}」：玩家报告命中总值 ${finalAttack}，达到 AC ${chosenTarget.armor_class}；玩家报告分段伤害 ${finalComponents.map((component) => `${component.amount}${component.damage_type}`).join("+")} = ${finalDamage}`
      : `${active.display_name} → ${chosenTarget.display_name}，使用「${selectedAction.name ?? "攻击"}」：命中总值 ${finalAttack}，未达到 AC ${chosenTarget.armor_class}；攻击落空但仍消耗${selectedAction.cost ?? "动作"}`;
    const command: CombatActionCommand = {
      action_type: "damage",
      actor_combatant_id: active.id,
      actor_version: active.version,
      action_cost: selectedActionCost,
      action_name: selectedAction.name ?? "攻击",
      resolution_note: hit
        ? `命中并造成 ${finalDamage} 点${selectedAction.damage_type ?? "未分类"}伤害`
        : `命中总值 ${finalAttack} 未达到 AC ${chosenTarget.armor_class}，攻击未命中`,
      target_combatant_id: chosenTarget.id,
      target_version: chosenTarget.version,
      amount: hit ? finalDamage : 0,
      damage_type: damageType,
      damage_components: hit ? finalComponents : [],
      forced_movement_distance_ft: hit ? forcedMovement?.distance_ft ?? null : null,
      forced_movement_direction: hit ? forcedMovement?.direction ?? null : null,
      recharge_key: selectedRechargeKey,
      recharge_consume: Boolean(selectedRechargeKey),
    };
    if (fullyAutomaticEnemy) {
      autoResolve.mutate(command);
    } else {
      preview.mutate({ command, explanation });
    }
    return true;
  };
  const prepareAreaSpell = () => {
    if (!selectedActionAvailable) {
      showToast(
        selectedResourceAvailable
          ? "本回合动作已经使用，请结束回合"
          : `${selectedResource?.label ?? "所需资源"}不足，无法施放`,
        "error",
      );
      return;
    }
    const damageType = selectedAreaDamageComponents
      ? "mixed"
      : typeof selectedAction.damage_type === "string"
        ? selectedAction.damage_type.trim()
        : "";
    if (!damageType) {
      showToast("区域法术没有明确伤害类型，不能默认当作未分类伤害；请由 DM 裁定", "error");
      return;
    }
    const affectedTargets = possibleTargets.filter((fighter) => targetIdsForExecution?.has(fighter.id));
    if (affectedTargets.length === 0) {
      showToast("请先在战斗地图上选择范围中心或直线方向，并确保至少覆盖一个敌人", "error");
      return;
    }
    const firstAffectedTarget = affectedTargets[0];
    const areaFields = firstAffectedTarget
      ? areaPromptFields(
          selectedAction,
          active,
          firstAffectedTarget,
          targetingValidity?.anchorPoint,
        ) as PendingAreaResolution["areaFields"]
      : {};
    if (selectedTargeting.shape !== "single" && Object.keys(areaFields).length === 0) {
      showToast("区域法术缺少可验证的地图锚点，不能绕过后端三维范围复核", "error");
      return;
    }
    const componentInputs = selectedAreaDamageComponents?.map((component, index) => ({
      amount: Number(damageComponentTotals[String(index)]),
      damage_type: component.damage_type!.trim(),
      damage_tags: component.damage_tags,
      expression: typeof component.expression === "string" ? component.expression : component.damage,
    }));
    if (componentInputs) {
      if (componentInputs.some((component) => !Number.isFinite(component.amount) || component.amount < 0)) {
        showToast("请分别填写每一段伤害骰的最终结果；系统会分别应用抗性、易伤和免疫", "error");
        return;
      }
    } else {
      const reportedDamage = Number(damageTotal);
      if (!damageTotal || !Number.isFinite(reportedDamage) || reportedDamage < 0) {
        showToast(`请先让玩家掷 ${selectedAction.damage ?? "伤害骰"}，并输入最终伤害总值`, "error");
        return;
      }
    }
    try {
      const resolution = resolveAreaSavingThrows({
        targets: affectedTargets.map((fighter) => ({
          id: fighter.id,
          name: fighter.display_name,
          abilityScores: fighter.snapshot_json.ability_scores as Record<string, number> | undefined,
          savingThrows: fighter.snapshot_json.saving_throws as Record<string, number> | undefined,
        })),
        damageExpression: selectedAction.damage ?? "",
        saveDc: Number(selectedAction.save_dc),
        saveAbility: String(selectedAction.save_ability),
        halfDamageOnSave: Boolean(selectedAction.half_damage_on_save),
        sharedDamage: componentInputs ? undefined : Number(damageTotal),
        damageComponents: componentInputs,
        damageType,
      });
      setPending(null);
      setPendingArea({
        resolution,
        actionName: selectedAction.name ?? "区域法术",
        actionCost: selectedActionCost,
        damageType,
        forcedMovement: forcedMovementFromAction(selectedAction),
        areaFields: {
          ...areaFields,
          requires_explicit_elevation: Boolean(selectedTargeting.requiresElevation),
        },
      });
    } catch (error) {
      showToast(error instanceof Error ? error.message : "无法计算区域法术", "error");
    }
  };
  const prepareSingleSaveSpell = () => {
    if (!selectedActionAvailable || !target) {
      showToast("请先选择合法目标，并确认动作与法术位可用", "error");
      return;
    }
    const structuredDamage = selectedDamageComponents.length > 1;
    const damageType = structuredDamage
      ? "mixed"
      : typeof selectedAction.damage_type === "string"
        ? selectedAction.damage_type.trim()
        : "";
    if (!damageType) {
      showToast("豁免法术没有明确伤害类型，不能默认当作未分类伤害；请由 DM 裁定", "error");
      return;
    }
    if (targetIdsForExecution && !targetIdsForExecution.has(target.id)) {
      showToast("目标不在当前法术的合法距离内", "error");
      return;
    }
    const reportedSave = Number(saveTotal);
    const componentInputs = structuredDamage
      ? selectedDamageComponents.map((component, index) => ({
          amount: Number(damageComponentTotals[String(index)]),
          damage_type: String(component.damage_type),
          ...(Array.isArray(component.damage_tags) ? { damage_tags: component.damage_tags } : {}),
        }))
      : null;
    const reportedDamage = componentInputs
      ? componentInputs.reduce((sum, component) => sum + component.amount, 0)
      : Number(damageTotal);
    if (!saveTotal || !Number.isFinite(reportedSave) || (!componentInputs && !damageTotal) || !Number.isFinite(reportedDamage) || reportedDamage < 0 || componentInputs?.some((component) => !Number.isFinite(component.amount) || component.amount < 0)) {
      showToast(`请填写目标${saveAbilityLabel}豁免总值和玩家掷出的${selectedAction.damage ?? "伤害骰"}总值`, "error");
      return;
    }
    const dc = Number(selectedAction.save_dc ?? 10);
    const success = reportedSave >= dc;
    const finalComponents = componentInputs
      ? (success && selectedAction.half_damage_on_save
          ? componentInputs.map((component) => ({ ...component, amount: Math.floor(component.amount / 2) }))
          : success ? [] : componentInputs)
      : [];
    const finalDamage = componentInputs
      ? finalComponents.reduce((sum, component) => sum + component.amount, 0)
      : success && selectedAction.half_damage_on_save
        ? Math.floor(reportedDamage / 2)
        : success ? 0 : reportedDamage;
    const command: CombatActionCommand = {
      action_type: "damage",
      actor_combatant_id: active.id,
      actor_version: active.version,
      action_cost: selectedActionCost,
      action_name: selectedAction.name ?? "豁免法术",
      resolution_note: `目标${saveAbilityLabel}豁免 ${reportedSave} 对 DC ${dc}${success ? "成功" : "失败"}；${success ? (selectedAction.half_damage_on_save ? "伤害减半" : "不受伤害") : `受到 ${finalDamage} 点伤害`}`,
      target_combatant_id: target.id,
      target_version: target.version,
      amount: finalDamage,
      damage_type: damageType,
      damage_components: finalComponents,
      forced_movement_distance_ft: !success
        ? forcedMovementFromAction(selectedAction)?.distance_ft ?? null
        : null,
      forced_movement_direction: !success
        ? forcedMovementFromAction(selectedAction)?.direction ?? null
        : null,
    };
    preview.mutate({
      command,
      explanation: `${active.display_name} 使用「${selectedAction.name ?? "豁免法术"}」；目标${saveAbilityLabel}豁免 ${reportedSave} 对 DC ${dc}${success ? "成功" : "失败"}，最终受到 ${finalDamage} 点${selectedAction.damage_type ?? "未分类"}伤害。`,
    });
  };
  const enemyTarget = chooseEnemyTarget(possibleTargets, tactics);
  const automaticAreaFallbackTarget = useMemo(() => {
    if (activeIsPlayerControlled || selectedTargeting.shape === "single" || !enemyTarget) return false;
    const source = active.snapshot_json.grid_position;
    const targetPosition = enemyTarget.snapshot_json.grid_position;
    if (!source || typeof source !== "object" || Array.isArray(source)
      || !targetPosition || typeof targetPosition !== "object" || Array.isArray(targetPosition)) {
      return false;
    }
    const sourceRecord = source as Record<string, unknown>;
    const targetRecord = targetPosition as Record<string, unknown>;
    if (!Number.isInteger(sourceRecord.row) || !Number.isInteger(sourceRecord.col)
      || !Number.isInteger(targetRecord.row) || !Number.isInteger(targetRecord.col)) {
      return false;
    }
    // The grid-validity effect publishes its sets one render after the AI
    // action template.  During that short window, an already adjacent,
    // position-backed area target is safe to submit; the backend remains the
    // final geometry authority.  This prevents an AI cone from waiting
    // forever on an empty initial Set.
    return gridDistanceFt(
      { row: Number(sourceRecord.row), col: Number(sourceRecord.col) },
      { row: Number(targetRecord.row), col: Number(targetRecord.col) },
    ) <= selectedTargeting.rangeFt;
  }, [active.snapshot_json.grid_position, activeIsPlayerControlled, enemyTarget, selectedTargeting.rangeFt, selectedTargeting.shape]);
  const enemyReason = tactics === "instinctive"
    ? "本能型会扑向最先发现的目标。"
    : tactics === "standard"
      ? "普通敌人优先攻击当前生命最低的目标。"
      : tactics === "smart"
        ? "聪明敌人会集中攻击最虚弱的目标并利用自身动作。"
      : "战术敌人优先寻找低 AC、低生命目标，并保留撤退与控制空间。";
  useEffect(() => {
    if (!autoEnemies || !automationReady || activeIsPlayerControlled) return;
    // Friendly/neutral NPC movement and turn completion are handled by the
    // shared battle grid. They must never enter the monster attack selector.
    if (active.entity_type === "npc") return;
    // Advanced actions (legendary/lair/reaction) are intentionally excluded
    // from the ordinary monster turn. If a monster has no structured normal
    // action, do not fall back to a fake zero-range action and let the map
    // planner run until it appears stuck. The advanced-action window remains
    // available to the DM for an explicit confirmation.
    if (actions.length === 0) {
      const noActionKey = `${turnKey}:no-structured-normal-action`;
      if (processedAutomaticTurn.current === noActionKey) return;
      processedAutomaticTurn.current = noActionKey;
      showToast(`${active.display_name}没有可自动执行的普通动作；高级动作仍需 DM 确认，已结束本回合。`, "info");
      onEnemyTurnComplete();
      return;
    }
    // The targeting grid and the action selector settle in separate renders.
    // A turn-only guard could therefore mark the turn as processed while the
    // previous player's targeting state was still mounted; when the monster's
    // cone/range became available later, the attack was never started. Include
    // the selected action and its targeting shape in the guard so a newly
    // settled action gets one execution attempt of its own.
    const automaticActionKey = [
      turnKey,
      actionIndex,
      selectedAction.name ?? "未命名动作",
      selectedAction.save_dc ?? "",
      selectedAction.save_ability ?? "",
      selectedTargeting.shape,
      selectedTargeting.rangeFt,
      selectedActionAvailable ? "available" : "unavailable",
      targetingRangeKnown ? "range-known" : "range-unknown",
    ].join(":");
    if (processedAutomaticTurn.current === automaticActionKey) return;
    if (!selectedActionAvailable) {
      // The action economy is also updated immediately after an automatic
      // sequence is submitted.  Do not end the turn from this intermediate
      // render; the sequence's onSuccess owns the single advance call.
      if (monsterSequenceInFlight.current === turnKey || executeMonsterSequence.isPending) return;
      // A genuinely unavailable action (for example a spent action at the
      // start of a turn) has no executable queue.  It is safe to pass the
      // turn, but never mark a just-consumed sequence as a new turn.
      if (!active.action_available && !active.bonus_action_available && !active.reaction_available) {
        processedAutomaticTurn.current = automaticActionKey;
        onEnemyTurnComplete();
      }
      return;
    }
    if (!targetingRangeKnown) {
      processedAutomaticTurn.current = automaticActionKey;
      showToast(`${active.display_name}的普通动作缺少可靠范围，已结束回合并保留给 DM 裁定。`, "info");
      onEnemyTurnComplete();
      return;
    }
    if (!enemyTarget) {
      // Wait for the initiative snapshot to expose a legal player target.
      // Advancing here can consume an enemy turn during the short render where
      // the player/companion list is still being refreshed.
      if (possibleTargets.length === 0) {
        // All player-controlled units are at 0 HP or have left the initiative.
        // There is no valid target to wait for; end this AI turn explicitly so
        // the character death-save/end-condition flow can take over.
        processedAutomaticTurn.current = automaticActionKey;
        onEnemyTurnComplete();
      }
      return;
    }
    if (targetIdsForExecution && targetIdsForExecution.size === 0 && !automaticAreaFallbackTarget) {
      // A geometry check can legitimately produce no legal target after the
      // movement planner has exhausted the monster's movement (for example a
      // cone direction blocked by a wall). Do not leave the initiative cursor
      // forever on an AI unit in this state.
      if (active.movement_remaining_ft === 0) {
        processedAutomaticTurn.current = automaticActionKey;
        showToast(`${active.display_name}无法在当前移动与几何范围内覆盖合法目标，结束本回合。`, "info");
        onEnemyTurnComplete();
      }
      return;
    }
    if (targetIdsForExecution?.has(enemyTarget.id) || automaticAreaFallbackTarget) {
      setTargetId(enemyTarget.id);
      monsterSequenceInFlight.current = turnKey;
      const started = prepareAttack(true, enemyTarget, true);
      processedAutomaticTurn.current = started ? automaticActionKey : null;
      if (!started) monsterSequenceInFlight.current = null;
      return;
    }
    if (active.movement_remaining_ft === 0) {
      processedAutomaticTurn.current = automaticActionKey;
      onEnemyTurnComplete();
    }
    // React when pathfinding updates the combatant position/range.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    active.movement_remaining_ft,
    autoEnemies,
    automationReady,
    actionIndex,
    enemyTarget?.id,
    selectedActionAvailable,
    selectedAction.name,
    selectedAction.save_ability,
    selectedAction.save_dc,
    selectedTargeting.rangeFt,
    selectedTargeting.shape,
    turnKey,
    targetIdsForExecution,
    automaticAreaFallbackTarget,
    activeIsPlayerControlled,
  ]);

  return (
    <div className="mt-3 rounded-lg border-2 border-ember-500/50 bg-ember-950/10 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={activeIsPlayerControlled ? "ok" : "danger"}>当前回合</Badge>
        <strong className="text-base text-parchment-100">{active.display_name}</strong>
        <span className="text-xs text-stone-400">{activeIsPlayerControlled ? (active.entity_type === "companion" ? "玩家召唤物，等待主人声明行动" : "等待玩家声明行动") : active.entity_type === "npc" ? "NPC 正在撤离危险区域" : "敌人 AI 正在评估行动"}</span>
        <Badge tone={active.action_available ? "ok" : "neutral"}>动作：{active.action_available ? "可用" : "已用"}</Badge>
        <Badge tone={active.bonus_action_available ? "ok" : "neutral"}>附赠：{active.bonus_action_available ? "可用" : "已用"}</Badge>
        <Badge tone={active.reaction_available ? "ok" : "neutral"}>反应：{active.reaction_available ? "可用" : "已用"}</Badge>
        {activeIsPlayerControlled ? (
          <div className="ml-auto">
            <span className="mb-1 block text-right text-2xs text-stone-500">玩家攻击结算</span>
            <div className="flex rounded border border-ink-600 p-0.5">
              <button className={`rounded px-2 py-1 text-2xs ${mode === "assisted" ? "bg-ember-600 text-white" : "text-stone-400"}`} onClick={() => setMode("assisted")} type="button">玩家报骰</button>
              <button className={`rounded px-2 py-1 text-2xs ${mode === "auto" ? "bg-ember-600 text-white" : "text-stone-400"}`} onClick={() => setMode("auto")} type="button">系统掷骰</button>
            </div>
          </div>
        ) : (
          <div className="ml-auto">
            <span className="mb-1 block text-right text-2xs text-stone-500">怪物回合控制</span>
            <div className="flex rounded border border-ink-600 p-0.5">
              <button className={`rounded px-2 py-1 text-2xs ${!autoEnemies ? "bg-stone-700 text-white" : "text-stone-400"}`} onClick={() => onAutoEnemiesChange(false)} type="button">DM手动</button>
              <button className={`rounded px-2 py-1 text-2xs ${autoEnemies ? "bg-ember-600 text-white" : "text-stone-400"}`} onClick={() => onAutoEnemiesChange(true)} type="button">怪物全自动</button>
            </div>
          </div>
        )}
      </div>

      {advancedChoices.length > 0 ? (
        <div className="mt-3 rounded border border-fuchsia-800/60 bg-fuchsia-950/15 p-3">
          <strong className="text-xs text-fuchsia-100">怪物高级动作窗口 · 需要 DM 确认</strong>
          <p className="mb-2 mt-1 text-2xs text-stone-400">
            高级动作不会混入普通怪物回合。这里按当前快照展示窗口与资源；后端确认时仍会复核。不可用项可查看失败原因，DM 仍必须确认真实触发、目标和未结构化效果。
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <select aria-label="怪物高级动作" className={selectCls} onChange={(event) => {
              setAdvancedChoiceKey(event.target.value);
              setAdvancedPreview(null);
              setAdvancedTargetId("");
              setReactionTrigger("");
              setReactionEvent(
                advancedChoices.find((choice) => choice.key === event.target.value)?.action.reaction_event
                  ?? "",
              );
              setAdvancedAttackTotal("");
              if (advancedAreaTargetingKey) {
                setAdvancedAreaTargetingKey(null);
                onRangeChange(targetingForAction(targetingAction), active.id);
              }
            }} value={selectedAdvancedChoice?.key ?? ""}>
              {advancedChoices.map((choice) => (
                <option key={choice.key} value={choice.key}>
                  {choice.actor.display_name} · {choice.action.name ?? "高级动作"} · {advancedPhaseLabel(choice.availability.phase)} · {choice.availability.available ? "可用" : "不可用"}
                </option>
              ))}
            </select>
            <select aria-label="怪物高级动作目标" className={selectCls} disabled={selectedAdvancedIsAreaAction && !advancedAreaTargeting?.ready} onChange={(event) => setAdvancedTargetId(event.target.value)} value={selectedAdvancedTarget?.id ?? ""}>
              <option value="">{selectedAdvancedIsAreaAction ? "地图已覆盖目标（可选查看）" : "选择明确目标"}</option>
              {advancedTargets.map((fighter) => <option key={fighter.id} value={fighter.id}>{fighter.display_name} · AC {fighter.armor_class} · HP {fighter.hp}/{fighter.max_hp}</option>)}
            </select>
          </div>
          {selectedAdvancedChoice?.action.action_type === "reaction" ? (
            <label className="mt-2 block text-2xs text-stone-400">
              资料库触发事件（只匹配明确结构化事件）
              <select
                aria-label="怪物反应结构化触发事件"
                className={`${selectCls} mt-1 w-full`}
                onChange={(event) => setReactionEvent(event.target.value as MonsterReactionEvent | "")}
                value={reactionEvent}
              >
                <option value="">未结构化事件（仅保留 DM 确认）</option>
                <option value="leaves_reach">离开近战威胁范围</option>
                <option value="enters_reach">进入近战威胁范围</option>
                <option value="takes_damage">受到伤害</option>
                <option value="casts_spell">施法</option>
                <option value="turn_end">回合结束</option>
              </select>
              本次反应的实际触发事件
              <input
                aria-label="怪物反应触发事件"
                className={`${inputCls} mt-1 w-full`}
                onChange={(event) => setReactionTrigger(event.target.value)}
                placeholder={selectedAdvancedChoice.action.reaction_trigger || "DM填写：哪一个可见事件触发了本次反应"}
                value={reactionTrigger}
              />
            </label>
          ) : null}
          {selectedAdvancedChoice && !selectedAdvancedChoice.action.save_dc ? (
            <label className="mt-2 block text-2xs text-stone-400">
              DM 报告攻击总值（d20 + 加值）
              <input
                aria-label="怪物高级动作攻击总值"
                className={`${inputCls} mt-1 w-full sm:max-w-xs`}
                inputMode="numeric"
                onChange={(event) => setAdvancedAttackTotal(event.target.value)}
                placeholder={`例如 ${Number(selectedAdvancedChoice.action.attack_bonus ?? 0) + 12}`}
                type="number"
                value={advancedAttackTotal}
              />
            </label>
          ) : null}
          {selectedAdvancedChoice ? (
            <div className="mb-2 mt-2 grid gap-1 rounded border border-fuchsia-900/60 bg-ink-950/40 p-2 text-2xs text-stone-300 sm:grid-cols-2">
              <p className="m-0 sm:col-span-2">{selectedAdvancedChoice.action.description ?? "以资料库规则原文为准"}</p>
              <p className="m-0">窗口：{selectedAdvancedChoice.availability.windowLabel}</p>
              <p className="m-0">资源：{selectedAdvancedChoice.availability.resourceLabel}</p>
              <p className="m-0">触发：{selectedAdvancedChoice.availability.triggerLabel ?? (selectedAdvancedChoice.availability.phase === "reaction" ? "需 DM 明示事件" : "按窗口触发")}</p>
              <p className="m-0">范围：{actionRangeSummary(selectedAdvancedChoice.action)}</p>
              {selectedAdvancedIsAreaAction ? (
                <>
                  <p className="m-0 sm:col-span-2 text-sky-100"><strong>{BACKEND_THREE_DIMENSIONAL_REVIEW_LABEL}</strong>：前端候选必须同时通过当前地图的水平模板、动作的 height/anchorHeight 与已记录的 grid_position.elevation_ft；确认提交时仍由后端几何作最终判定。</p>
                  <p className="m-0 sm:col-span-2">前端垂直范围：{advancedAreaTargeting?.verticalSummary ?? "高度数据未完整，已阻止自动选择"} · 当前可选 {advancedTargets.length} 名。</p>
                  {advancedAreaTargeting?.blockingReasons.length ? <p className="m-0 text-amber-200 sm:col-span-2">三维目标限制：{advancedAreaTargeting.blockingReasons.join("；")}</p> : null}
                </>
              ) : null}
              {selectedAdvancedChoice.action.save_dc && selectedAdvancedChoice.action.save_ability ? <p className="m-0">豁免：{selectedAdvancedChoice.action.save_ability} DC {selectedAdvancedChoice.action.save_dc}</p> : null}
              {selectedAdvancedChoice.action.damage ? <p className="m-0">伤害：{selectedAdvancedChoice.action.damage} {selectedAdvancedChoice.action.damage_type ?? "类型未明确"}</p> : null}
              {selectedAdvancedChoice.action.conditions_on_failure?.length ? <p className="m-0">失败状态：{selectedAdvancedChoice.action.conditions_on_failure.join("、")}</p> : null}
              {selectedAdvancedChoice.availability.blockingReasons.length > 0 ? (
                <p className="m-0 text-amber-200 sm:col-span-2">当前限制：{selectedAdvancedChoice.availability.blockingReasons.join("；")}</p>
              ) : null}
              {selectedAdvancedIsAreaAction ? <p className="m-0 sm:col-span-2">确认后会向 {advancedTargets.length} 名通过三维候选检查的玩家分别发出豁免请求；玩家提交前不视为伤害、状态或回合已结算。</p> : null}
            </div>
          ) : null}
          {advancedPreview ? (
            <div className="mb-2 rounded border border-sky-800/60 bg-sky-950/15 p-2 text-2xs text-sky-100">
              <strong>后端 phase 预览：{advancedPreview.plan ? `${advancedPreview.plan.action_name} · ${advancedPreview.plan.action_type}` : "当前窗口没有可用计划"}</strong>
              <p className="mb-1 mt-1 text-stone-300">这是只读预览：不会创建玩家掷骰请求，也不代表动作已经执行。</p>
              {advancedPreview.plan ? (
                <>
                  <p className="mb-1 mt-1">{advancedPreview.plan.reason}</p>
                  {advancedPreview.plan.confirmation_reasons.length > 0 ? <p className="mb-0 text-amber-200">仍需确认：{advancedPreview.plan.confirmation_reasons.join("；")}</p> : null}
                </>
              ) : <p className="mb-0 mt-1">后端没有为当前 actor/phase 返回可执行动作；这不是前端猜测失败，保留 DM 裁定。</p>}
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {selectedAdvancedIsAreaAction ? (
              <Button
                disabled={!selectedAdvancedChoice}
                onClick={() => {
                  if (!selectedAdvancedChoice) return;
                  setAdvancedAreaTargetingKey(selectedAdvancedChoice.key);
                  setAdvancedTargetId("");
                  onTargetChange?.("");
                  onRangeChange(
                    targetingForAction(selectedAdvancedChoice.action, { requiresElevation: true }),
                    selectedAdvancedChoice.actor.id,
                  );
                }}
                size="sm"
                variant="primary"
              >
                在地图定位三维区域
              </Button>
            ) : null}
            <Button
              disabled={!selectedAdvancedChoice || previewAdvancedAction.isPending}
              loading={previewAdvancedAction.isPending}
              onClick={() => previewAdvancedAction.mutate()}
              size="sm"
            >
              读取后端窗口预览
            </Button>
          <Button
            disabled={!selectedAdvancedChoice?.availability.available || (selectedAdvancedIsAreaAction ? !advancedTargets.length : !selectedAdvancedTarget) || (selectedAdvancedChoice?.availability.phase === "reaction" && !reactionTrigger.trim()) || (selectedAdvancedIsAreaAction && (!advancedAreaTargeting?.ready || advancedAreaTargetingKey !== selectedAdvancedChoice?.key)) || executeAdvancedMonsterAction.isPending}
            loading={executeAdvancedMonsterAction.isPending}
            onClick={() => executeAdvancedMonsterAction.mutate()}
            size="sm"
            variant="danger"
          >
            DM确认并执行高级动作
          </Button>
          </div>
        </div>
      ) : null}

      {activeIsPlayerControlled ? (
        <div className="mt-3 grid gap-3">
          <div className="rounded border border-ink-700 bg-ink-950/60 p-3">
            <strong className="text-xs text-parchment-100">角色卡动作与施法指示</strong>
            {activeCharacter && Object.keys(activeCharacter.skills).length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1">
                {Object.keys(activeCharacter.skills).map((skill) => (
                  <span className="rounded border border-sky-800/60 bg-sky-950/20 px-2 py-1 text-2xs text-sky-200" key={skill} title={`${skill}已熟练：相关检定使用 d20 + 对应属性调整值 + 熟练加值。`}>
                    {skill} · 熟练
                  </span>
                ))}
              </div>
            ) : null}
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <select className={selectCls} onChange={(event) => selectAction(event.target.value)} value={actionIndex}>
                {actions.length === 0 ? <option value="0">未结构化动作 · 伤害骰未明确 · 范围未明确</option> : null}
                {actions.map((action, index) => <option disabled={!hasActionEconomy(active, actionCost(action))} key={`${action.name}-${index}`} value={index}>{action.name ?? `动作${index + 1}`} · {action.damage ?? "伤害骰未明确"} · {action.range ?? "范围未明确"}{!hasActionEconomy(active, actionCost(action)) ? " · 本回合已用" : ""}</option>)}
              </select>
              {selectedSpellLevel > 0 ? (
                <label className="text-2xs text-stone-400">
                  使用法术环阶
                  <select aria-label="使用法术环阶" className={`${selectCls} mt-1`} onChange={(event) => setSelectedSlotLevel(Number(event.target.value))} value={Math.max(selectedSpellLevel, selectedSlotLevel)}>
                    {(availableSlotLevels.length ? availableSlotLevels : [selectedSpellLevel]).map((level) => {
                      const slot = activeCharacter?.resources[`spell_slots_${level}`] as { label?: string; current?: number; max?: number } | undefined;
                      return <option disabled={Number(slot?.current ?? 0) < 1} key={level} value={level}>{level}环 · {slot?.label ?? `法术位${level}`} · 可用 {Number(slot?.current ?? 0)}/{Number(slot?.max ?? 0)}</option>;
                    })}
                  </select>
                </label>
              ) : null}
              <select className={selectCls} onChange={(event) => { setTargetId(event.target.value); onTargetChange?.(event.target.value); }} value={targetId}>
                <option value="">选择目标</option>
                {possibleTargets.map((fighter) => <option disabled={Boolean(validTargetIds && !validTargetIds.has(fighter.id))} key={fighter.id} value={fighter.id}>{fighter.display_name} · AC {fighter.armor_class} · HP {fighter.hp}/{fighter.max_hp}{validTargetIds && !validTargetIds.has(fighter.id) ? " · 超出范围" : ""}</option>)}
              </select>
            </div>
            {selectedSpellLevel > 0 ? <p className="mb-2 mt-1 text-2xs text-amber-200">当前施法：{Math.max(selectedSpellLevel, selectedSlotLevel)}环 · 消耗 1 个对应法术位；伤害/治疗会按升环规则计算。{selectedResource ? ` 当前剩余 ${Number(selectedResource.current ?? 0)}/${Number(selectedResource.max ?? 0)}。` : " 当前角色没有可用对应法术位。"}</p> : null}
            <p className="mb-2 mt-2 text-2xs text-stone-400">{selectedAction.cost ?? "动作"} · {actionRangeSummary(selectedAction)} · {selectedAction.description ?? "以角色卡和规则条目为准"}</p>
            <RuleBlockPlan source={selectedAction} title="当前动作执行积木" />
            {isNarrativeAction ? (
              <div className="rounded border border-violet-800/50 bg-violet-950/20 p-2">
                <p className="m-0 text-xs leading-5 text-violet-100">
                  这是叙事、辅助或持续效果法术，没有可直接套用的即时伤害公式。系统会显示规则描述、距离、持续时间与资源消耗，但不会虚构伤害；请在下方“自由行动裁定”记录具体目标和效果。
                </p>
                {selectedResourceKey ? <p className="mb-0 mt-1 text-2xs text-stone-400">施放时消耗 {selectedResourceCost} 点{selectedResource?.label ?? selectedResourceKey}；当前剩余 {Number(selectedResource?.current ?? 0)}。</p> : null}
              </div>
            ) : isAreaSaveAction ? (
              <div className="rounded border border-fuchsia-800/60 bg-fuchsia-950/20 p-2">
                <p className="m-0 text-xs text-fuchsia-100">
                  这是区域豁免法术，不进行攻击检定。先在地图选择
                  {selectedTargeting.originSelf
                    ? "自身为区域起点"
                    : selectedTargeting.shape === "circle" ? "爆发中心" : "直线方向"}；
                  当前覆盖 <strong>{possibleTargets.filter((fighter) => validTargetIds?.has(fighter.id)).length}</strong> 个敌人。
                  按 D&D 5e 规则，本次施法{selectedAreaDamageComponents ? "共用各段独立伤害骰" : `共用一次 ${selectedAction.damage} 伤害骰`}；每个目标分别进行
                  {selectedAction.save_ability}豁免（DC {selectedAction.save_dc}），成功
                  {selectedAction.half_damage_on_save ? "伤害减半" : "不受伤害"}，再分别应用各自的抗性、易伤或免疫，因此最终扣血可以不同。
                </p>
                <p className="mb-2 mt-1 text-2xs text-stone-400">
                  范围内：{possibleTargets.filter((fighter) => validTargetIds?.has(fighter.id)).map((fighter) => fighter.display_name).join("、") || "尚未覆盖目标"}
                  {selectedResourceKey
                    ? ` · 消耗 ${selectedResourceCost} 点${selectedResource?.label ?? selectedResourceKey}（剩余 ${Number(selectedResource?.current ?? 0)}）`
                    : ""}
                </p>
                <div className="flex flex-wrap gap-2">
                  {selectedAreaDamageComponents ? selectedAreaDamageComponents.map((component, index) => (
                    <input
                      aria-label={`区域法术第${index + 1}段${component.damage_type}伤害总值`}
                      className={`${inputCls} w-40`}
                      key={`${selectedAction.name ?? "area"}-${index}-${component.damage_type}`}
                      min="0"
                      onChange={(event) => setDamageComponentTotals((current) => ({
                        ...current,
                        [String(index)]: event.target.value,
                      }))}
                      placeholder={`${component.damage_type} ${component.expression ?? component.damage ?? "伤害骰"}`}
                      type="number"
                      value={damageComponentTotals[String(index)] ?? ""}
                    />
                  )) : (
                    <input
                      aria-label="区域法术玩家伤害总值"
                      className={`${inputCls} w-36`}
                      min="0"
                      onChange={(event) => setDamageTotal(event.target.value)}
                      placeholder={`玩家掷 ${selectedAction.damage ?? "伤害骰"}`}
                      type="number"
                      value={damageTotal}
                    />
                  )}
                  <Button
                    disabled={!selectedActionAvailable || !validTargetIds?.size || confirmArea.isPending || (
                      selectedAreaDamageComponents
                        ? selectedAreaDamageComponents.some((_, index) => !damageComponentTotals[String(index)])
                        : !damageTotal
                    )}
                    onClick={prepareAreaSpell}
                    variant="primary"
                  >
                    {selectedAreaDamageComponents ? "分别录入伤害骰并预览豁免" : "使用玩家伤害骰并预览豁免"}
                  </Button>
                </div>
              </div>
            ) : isSingleSaveAction ? (
              <div className="rounded border border-fuchsia-800/50 bg-fuchsia-950/20 p-2">
                <p className="m-0 text-xs text-fuchsia-100">
                  这是单体豁免法术，不进行命中检定。目标进行<strong>{saveAbilityLabel}豁免（DC {selectedAction.save_dc}）</strong>；
                  {selectedAction.half_damage_on_save ? "成功伤害减半，失败承受全部伤害。" : "成功不受伤害，失败承受全部伤害。"}
                  请玩家掷出伤害骰，并由 DM 录入目标豁免总值与伤害总值。
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <input aria-label="目标豁免总值" className={`${inputCls} w-32`} onChange={(event) => setSaveTotal(event.target.value)} placeholder={`${saveAbilityLabel}豁免总值`} type="number" value={saveTotal} />
                  {selectedDamageComponents.length > 1 ? selectedDamageComponents.map((component, index) => (
                    <input
                      aria-label={`单体豁免第${index + 1}段${component.damage_type}伤害总值`}
                      className={`${inputCls} w-40`}
                      key={`single-save-${selectedAction.name ?? "spell"}-${index}-${component.damage_type}`}
                      min="0"
                      onChange={(event) => setDamageComponentTotals((current) => ({ ...current, [String(index)]: event.target.value }))}
                      placeholder={`${component.damage_type} ${component.expression ?? component.damage ?? "伤害骰"}`}
                      type="number"
                      value={damageComponentTotals[String(index)] ?? ""}
                    />
                  )) : (
                    <input aria-label="玩家伤害总值" className={`${inputCls} w-32`} onChange={(event) => setDamageTotal(event.target.value)} placeholder={`玩家掷 ${selectedAction.damage}`} type="number" value={damageTotal} />
                  )}
                  <Button disabled={!target || !selectedActionAvailable || preview.isPending || !hasAllDamageComponentTotals} onClick={prepareSingleSaveSpell} variant="primary">计算并预览豁免</Button>
                </div>
              </div>
            ) : mode === "assisted" ? (
              <div className="rounded border border-sky-800/50 bg-sky-950/20 p-2">
                <p className="m-0 text-xs text-sky-200">
                  请玩家掷 d20 并加入角色卡命中调整值。
                  {target
                    ? <>最终命中总值至少需要达到 <strong>AC {target.armor_class}</strong>（即 ≥ {target.armor_class}）</>
                    : <>选择目标后，这里会明确显示需要达到的 AC</>}。
                  命中后再掷 {selectedAction.damage ?? "角色卡所列伤害骰"}；请输入最终总值，系统负责对比 AC、抗性与 HP。
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <input aria-label="玩家命中总值" className={`${inputCls} w-28`} onChange={(event) => setAttackTotal(event.target.value)} placeholder="命中总值" type="number" value={attackTotal} />
                  {selectedDamageComponents.length > 1 ? selectedDamageComponents.map((component, index) => (
                    <input
                      aria-label={`攻击第${index + 1}段${component.damage_type}伤害总值`}
                      className={`${inputCls} w-36`}
                      key={`attack-${selectedAction.name ?? "action"}-${index}-${component.damage_type}`}
                      min="0"
                      onChange={(event) => setDamageComponentTotals((current) => ({ ...current, [String(index)]: event.target.value }))}
                      placeholder={`${component.damage_type} ${component.expression ?? component.damage ?? "伤害骰"}`}
                      type="number"
                      value={damageComponentTotals[String(index)] ?? ""}
                    />
                  )) : (
                    <input aria-label="玩家伤害总值" className={`${inputCls} w-28`} onChange={(event) => setDamageTotal(event.target.value)} placeholder="伤害总值" type="number" value={damageTotal} />
                  )}
                  <Button disabled={!target || !selectedActionAvailable || preview.isPending || !hasAllDamageComponentTotals} onClick={() => prepareAttack(false)} variant="primary">计算并预览</Button>
                </div>
              </div>
            ) : (
              <Button disabled={!target || !selectedActionAvailable || preview.isPending} onClick={() => prepareAttack(true)} variant="primary">自动掷命中与伤害</Button>
            )}
          </div>

          <div className="rounded border border-violet-800/50 bg-violet-950/10 p-3">
            <strong className="text-xs text-violet-200">DM 自由发挥 · 规则助手建议</strong>
            <textarea className={`${textareaCls} mt-2 min-h-20`} onChange={(event) => setFreeform(event.target.value)} placeholder="例如：我拿出怪物最害怕的圣徽，试图让它退缩。" value={freeform} />
            {check ? (
              <div className="mt-2 rounded border border-violet-800/50 p-2 text-xs text-stone-300">
                <p className="mb-2 mt-0">建议进行 <strong>{check.skill}（{check.abilityLabel}）</strong>检定：d20 {check.modifier >= 0 ? "+" : ""}{check.modifier}，目标 DC {check.dc}。{check.explanation}。</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <select className={selectCls} onChange={(event) => setTargetId(event.target.value)} value={targetId}><option value="">效果目标</option>{possibleTargets.map((fighter) => <option key={fighter.id} value={fighter.id}>{fighter.display_name}</option>)}</select>
                </div>
                <p className="mb-0 mt-2 text-amber-200">点击执行后，玩家端会弹出 d20 输入；玩家提交后系统自动计算加值、DC 和积木效果。{freeformConditions.length ? "本例成功会给目标写入倒地状态。" : "没有明确结构化状态时只记录检定结果，DM再做叙事描述。"}</p>
                <Button className="mt-2" disabled={!target || executeFreeform.isPending} loading={executeFreeform.isPending} onClick={() => executeFreeform.mutate()} size="sm" variant="primary">执行建议并请求玩家掷骰</Button>
              </div>
            ) : null}
          </div>
        </div>
      ) : active.entity_type === "npc" ? (
        <div className="mt-3 rounded border border-violet-800/50 bg-violet-950/15 p-3">
          <strong className="text-xs text-violet-200">NPC 撤退回合</strong>
          <p className="mb-0 mt-1 text-xs leading-5 text-stone-300">
            {active.display_name}不会被当成敌对怪物操作。系统会让其远离最近怪物或冲突中心；
            无路可走时原地防守，然后自动结束回合。
          </p>
        </div>
      ) : (
        <div className="mt-3 rounded border border-red-900/60 bg-red-950/10 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-auto text-xs text-red-200">敌人战斗 AI</strong>
            <select className={selectCls} onChange={(event) => setTactics(event.target.value as EnemyTactics)} value={tactics}>
              {Object.entries(ENEMY_TACTICS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}智商</option>)}
            </select>
          </div>
          <p className="mb-2 mt-2 text-xs text-stone-300">建议目标：<strong>{enemyTarget?.display_name ?? "无有效玩家目标"}</strong>。{enemyReason}</p>
          <label className="mb-2 block text-2xs text-stone-400">
            本回合怪物动作
            <select className={`${selectCls} mt-1`} onChange={(event) => selectAction(event.target.value)} value={actionIndex}>
              {actions.length === 0 ? <option value="0">未结构化动作 · 伤害骰未明确 · 范围未明确</option> : null}
              {actions.map((action, index) => (
                <option
                  disabled={
                    !hasActionEconomy(active, actionCost(action))
                    || !isRechargeAvailable(action, rechargeAvailable, index)
                  }
                  key={`${action.name}-${index}`}
                  value={index}
                >
                  {action.name ?? `动作${index + 1}`} · {action.damage ?? "按规则描述"} · {actionRangeSummary(action)}
                </option>
              ))}
            </select>
          </label>
          <p className="mb-2 mt-0 text-2xs text-stone-500">建议动作：{selectedAction.name ?? "未结构化动作"} · {selectedAction.damage ?? "伤害骰未明确"} · {actionRangeSummary(selectedAction)}。地图会先按剩余速度寻路；攻击检定由怪物自动掷，怪物能力要求豁免时会在右侧等待玩家输入骰值。</p>
          {selectedRechargeRange ? (
            <div className="mb-2 rounded border border-cyan-800/60 bg-cyan-950/15 p-2 text-2xs text-cyan-100">
              <strong>充能 {selectedRechargeRange.minimum}–{selectedRechargeRange.maximum}</strong>
              {selectedRechargeAvailable ? (
                <span className="ml-2 text-emerald-300">当前可用；使用后会记录为已消耗。</span>
              ) : (
                <span className="ml-2 text-amber-200">当前未充能，不能自动重复使用。</span>
              )}
              {selectedRechargeKey && rechargeAvailable && !selectedRechargeAvailable ? (
                <Button
                  className="ml-2"
                  disabled={rechargeRoll.isPending}
                  loading={rechargeRoll.isPending}
                  onClick={() => rechargeRoll.mutate()}
                  size="sm"
                >
                  DM掷 d6 充能
                </Button>
              ) : null}
            </div>
          ) : null}
          {autoEnemies ? (
            <div className="rounded border border-red-900/60 bg-red-950/20 p-2 text-xs text-red-100">
              全自动处理中：{active.display_name}会先移动到合法位置，再使用
              「{selectedAction.name ?? "基础攻击"}」攻击{enemyTarget?.display_name ?? "有效目标"}。
              若无需玩家掷骰，结算后会自动结束回合。
            </div>
          ) : (
            <div className="rounded border border-amber-800/60 bg-amber-950/15 p-2">
              <p className="mb-2 mt-0 text-xs text-amber-200">
                当前是 DM 手动模式，所以系统不会自行攻击。切换右上角“怪物全自动”后，怪物会立即自行选目标、移动、攻击并结束回合。
              </p>
              <Button
                disabled={!enemyTarget || !selectedActionAvailable || preview.isPending || requestPlayerSave.isPending || autoResolve.isPending || executeMonsterSequence.isPending}
                onClick={() => {
                  if (!enemyTarget) return;
                  setTargetId(enemyTarget.id);
                  if (selectedAction.multiattack || selectedAction.affects_multiple_targets || (selectedAction.area_shape && selectedAction.area_shape !== "single")) {
                    executeMonsterSequence.mutate({ chosenTarget: enemyTarget });
                  } else {
                    prepareAttack(true, enemyTarget);
                  }
                }}
                variant="danger"
              >
                手动执行怪物动作
              </Button>
            </div>
          )}
        </div>
      )}

      {pending ? (
        <div className="mt-3 rounded border border-amber-600/60 bg-amber-950/20 p-3">
          <strong className="text-xs text-amber-200">待 DM 确认的战斗结果</strong>
          <p className="mb-1 mt-1 text-xs text-stone-300">{pending.explanation}</p>
          <p className="mb-2 mt-0 text-2xs text-stone-500">HP {String(pending.preview.before.hp)} → {String(pending.preview.after.hp)}；尚未写入。</p>
          <div className="flex gap-2"><Button loading={confirm.isPending} onClick={() => confirm.mutate()} variant="primary">DM确认写入</Button><Button onClick={() => setPending(null)}>取消</Button></div>
        </div>
      ) : null}
      {pendingArea ? (
        <div className="mt-3 rounded border-2 border-fuchsia-600/60 bg-fuchsia-950/20 p-3">
          <strong className="text-xs text-fuchsia-100">
            {pendingArea.actionName} · 区域结算预览（尚未写入）
          </strong>
          <p className="mb-2 mt-1 text-xs text-stone-300">
            {pendingArea.resolution.damageComponents.length > 1
              ? <>各段伤害独立记录：</>
              : <>共用伤害骰 {pendingArea.resolution.damageExpression}：</>}
            {pendingArea.resolution.damageRolls.length
              ? <>[{pendingArea.resolution.damageRolls.join(" + ")}] = </>
              : <>玩家报告最终总值 = </>}
            <strong>{pendingArea.resolution.sharedDamage}</strong>。
            {pendingArea.resolution.damageComponents.length > 1
              ? <>（{pendingArea.resolution.damageComponents.map((component) => `${component.amount}${component.damageType}`).join(" + ")}）</>
              : null}
            下列每个目标独立豁免。
          </p>
          <ul className="m-0 space-y-1 pl-4 text-xs text-stone-300">
            {pendingArea.resolution.targets.map((result) => (
              <li key={result.targetId}>
                <strong>{result.targetName}</strong>：d20({result.d20}) {result.modifier >= 0 ? "+" : ""}{result.modifier}
                {" = "}{result.saveTotal} vs DC {pendingArea.resolution.saveDc}，
                <span className={result.success ? "text-emerald-300" : "text-red-300"}>
                  {result.success ? "成功" : "失败"}
                </span>
                ，预计 {result.damage} 点{pendingArea.damageType}伤害
                {result.damageComponents.length > 1
                  ? <>（{result.damageComponents.map((component) => `${component.amount}${component.damageType}`).join(" + ")}）</>
                  : null}
              </li>
            ))}
          </ul>
          <div className="mt-3 flex gap-2">
            <Button loading={confirmArea.isPending} onClick={() => confirmArea.mutate()} variant="primary">
              DM确认对全部目标结算
            </Button>
            <Button disabled={confirmArea.isPending} onClick={() => setPendingArea(null)}>取消</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
