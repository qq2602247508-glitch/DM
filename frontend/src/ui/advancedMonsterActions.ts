import type { Combatant, MonsterAIPhase } from "../api/types";
import type { CombatActionLike } from "./combatAutomation";
import { explicitElevationFt } from "./gridTargeting";

export const BACKEND_THREE_DIMENSIONAL_REVIEW_LABEL = "后端权威三维复核";

export type AdvancedActionAvailability = {
  phase: Exclude<MonsterAIPhase, "turn">;
  available: boolean;
  blockingReasons: string[];
  windowLabel: string;
  resourceLabel: string;
  triggerLabel: string | null;
};

export type AdvancedActionPendingRollInput = {
  actorName?: unknown;
  actionName?: unknown;
  actionCost?: unknown;
  legendaryCost?: unknown;
  legendaryPoolMax?: unknown;
  reactionTrigger?: unknown;
};

export type AdvancedAreaTargetingInput = {
  anchorPoint?: { row: number; col: number } | null;
  horizontalTargetIds?: ReadonlySet<string>;
  validTargetIds?: ReadonlySet<string>;
  missingElevationTargetIds?: ReadonlySet<string>;
};

export type AdvancedAreaTargeting = {
  isAreaAction: boolean;
  ready: boolean;
  eligibleTargetIds: ReadonlySet<string>;
  excludedTargetIds: ReadonlySet<string>;
  blockingReasons: string[];
  verticalSummary: string | null;
};

function positiveInt(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function nonNegativeInt(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function positiveNumber(value: unknown): number | null {
  const parsed = finiteNumber(value);
  return parsed !== null && parsed > 0 ? parsed : null;
}

function nonEmptyText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

type VerticalBand = {
  lowerFt: number;
  upperFt: number;
  summary: string;
};

function advancedVerticalBand(
  action: CombatActionLike,
  actor: Combatant,
): { band: VerticalBand | null; reason: string | null } {
  const shape = action.area_shape;
  if (!shape || shape === "single") {
    return { band: null, reason: "高级区域动作缺少明确区域形状，不能把二维目标当作三维目标" };
  }
  const anchorHeightFt = finiteNumber(action.area_anchor_height_ft);
  const sizeFt = positiveNumber(action.area_size_ft);
  const actorElevationFt = explicitElevationFt(actor.snapshot_json.grid_position);

  if (shape === "cylinder") {
    const heightFt = positiveNumber(action.area_height_ft);
    if (heightFt === null) return { band: null, reason: "圆柱区域缺少明确 height，不能自动选择上下层目标" };
    if (anchorHeightFt === null) return { band: null, reason: "圆柱区域缺少明确 anchorHeight，不能自动选择上下层目标" };
    return {
      band: {
        lowerFt: anchorHeightFt,
        upperFt: anchorHeightFt + heightFt,
        summary: `${anchorHeightFt}–${anchorHeightFt + heightFt}尺`,
      },
      reason: null,
    };
  }

  if (shape === "cube") {
    if (sizeFt === null) return { band: null, reason: "立方区域缺少明确边长，不能自动选择上下层目标" };
    if (anchorHeightFt === null) return { band: null, reason: "立方区域缺少明确 anchorHeight，不能自动选择上下层目标" };
    return {
      band: {
        lowerFt: anchorHeightFt,
        upperFt: anchorHeightFt + sizeFt,
        summary: `${anchorHeightFt}–${anchorHeightFt + sizeFt}尺`,
      },
      reason: null,
    };
  }

  if (shape === "circle" || shape === "sphere") {
    if (sizeFt === null) return { band: null, reason: "球形区域缺少明确半径，不能自动选择上下层目标" };
    if (anchorHeightFt === null) return { band: null, reason: "球形区域缺少明确 anchorHeight，不能自动选择上下层目标" };
    return {
      band: {
        lowerFt: anchorHeightFt - sizeFt,
        upperFt: anchorHeightFt + sizeFt,
        summary: `${anchorHeightFt - sizeFt}–${anchorHeightFt + sizeFt}尺（球形外包高度）`,
      },
      reason: null,
    };
  }

  if (actorElevationFt === null) {
    return { band: null, reason: "区域来源单位没有 grid_position.elevation_ft，不能自动选择上下层目标" };
  }
  if (shape === "line") {
    const widthFt = positiveNumber(action.area_width_ft);
    if (widthFt === null) return { band: null, reason: "直线区域缺少明确宽度，不能自动选择上下层目标" };
    const halfWidthFt = widthFt / 2;
    return {
      band: {
        lowerFt: actorElevationFt - halfWidthFt,
        upperFt: actorElevationFt + halfWidthFt,
        summary: `${actorElevationFt - halfWidthFt}–${actorElevationFt + halfWidthFt}尺（直线宽度）`,
      },
      reason: null,
    };
  }
  if (sizeFt === null) return { band: null, reason: "锥形区域缺少明确长度，不能自动选择上下层目标" };
  return {
    band: {
      lowerFt: actorElevationFt - sizeFt,
      upperFt: actorElevationFt + sizeFt,
      summary: `${actorElevationFt - sizeFt}–${actorElevationFt + sizeFt}尺（锥形最大高度）`,
    },
    reason: null,
  };
}

export function isAdvancedAreaAction(action: CombatActionLike): boolean {
  return Boolean(
    action.save_dc
    && action.save_ability
    && (action.affects_multiple_targets || (action.area_shape && action.area_shape !== "single")),
  );
}

/**
 * Keeps the advanced-action picker from treating a 2-D map highlight as a
 * complete target list.  The server still rechecks geometry when it receives
 * an authoritative area command; this client gate only prevents an obviously
 * unmeasured or vertically impossible selection from being proposed.
 */
export function evaluateAdvancedAreaTargeting(
  action: CombatActionLike,
  actor: Combatant,
  candidates: Combatant[],
  input: AdvancedAreaTargetingInput = {},
): AdvancedAreaTargeting {
  if (!isAdvancedAreaAction(action)) {
    return {
      isAreaAction: false,
      ready: true,
      eligibleTargetIds: new Set(candidates.map((candidate) => candidate.id)),
      excludedTargetIds: new Set(),
      blockingReasons: [],
      verticalSummary: null,
    };
  }

  const blockingReasons: string[] = [];
  const horizontalTargetIds = input.horizontalTargetIds;
  const hasMeasuredAnchor = Boolean(input.anchorPoint && horizontalTargetIds && horizontalTargetIds.size > 0);
  if (!hasMeasuredAnchor) {
    blockingReasons.push("请先在战斗地图定位该高级区域，再选择目标");
  }
  const horizontalCandidates = candidates.filter((candidate) => horizontalTargetIds?.has(candidate.id));
  const { band, reason } = advancedVerticalBand(action, actor);
  if (reason) blockingReasons.push(reason);

  const missingElevationCandidates = horizontalCandidates.filter((candidate) => (
    input.missingElevationTargetIds?.has(candidate.id)
    || explicitElevationFt(candidate.snapshot_json.grid_position) === null
  ));
  if (missingElevationCandidates.length > 0) {
    blockingReasons.push(
      `目标缺少 grid_position.elevation_ft：${missingElevationCandidates.map((candidate) => candidate.display_name).join("、")}`,
    );
  }

  const verticallyEligible = band
    ? horizontalCandidates.filter((candidate) => {
        const elevationFt = explicitElevationFt(candidate.snapshot_json.grid_position);
        return elevationFt !== null
          && elevationFt >= band.lowerFt
          && elevationFt < band.upperFt;
      })
    : [];
  const eligibleTargetIds = new Set(
    (hasMeasuredAnchor ? verticallyEligible : [])
      .filter((candidate) => input.validTargetIds?.has(candidate.id))
      .map((candidate) => candidate.id),
  );
  const excludedTargetIds = new Set(
    horizontalCandidates
      .filter((candidate) => !eligibleTargetIds.has(candidate.id))
      .map((candidate) => candidate.id),
  );
  if (band && horizontalCandidates.length > 0 && eligibleTargetIds.size === 0 && missingElevationCandidates.length === 0) {
    blockingReasons.push("当前二维区域没有位于该动作垂直范围内的可选目标");
  }
  if (input.validTargetIds && input.validTargetIds.size > 0 && verticallyEligible.length > 0 && eligibleTargetIds.size === 0) {
    blockingReasons.push("当前地图预览没有确认任何同时满足水平和垂直几何的目标");
  }

  return {
    isAreaAction: true,
    ready: blockingReasons.length === 0 && eligibleTargetIds.size > 0,
    eligibleTargetIds,
    excludedTargetIds,
    blockingReasons,
    verticalSummary: band?.summary ?? null,
  };
}

export function advancedActionPhase(
  action: CombatActionLike,
): Exclude<MonsterAIPhase, "turn"> | null {
  if (action.action_type === "reaction") return "reaction";
  if (action.action_type === "legendary_action") return "legendary";
  if (action.action_type === "lair_action") return "lair";
  return null;
}

/**
 * Pending player-roll snapshots expose the action request, rather than the
 * monster stat block.  Keep the action-cost mapping here so both the DM
 * waiting state and the request text use the same, conservative labels.
 */
export function advancedActionPhaseFromCost(
  actionCost: unknown,
): Exclude<MonsterAIPhase, "turn"> | null {
  if (actionCost === "reaction") return "reaction";
  if (actionCost === "legendary_action") return "legendary";
  if (actionCost === "lair_action") return "lair";
  return null;
}

/**
 * This text is deliberately about a pending request, not a completed action.
 * The server has accepted the action cost before publishing this request, but
 * damage, conditions, and turn progression still wait for the player's roll.
 */
export function advancedActionPendingRollSummary(
  input: AdvancedActionPendingRollInput,
): string | null {
  const phase = advancedActionPhaseFromCost(input.actionCost);
  if (!phase) return null;

  const actorName = nonEmptyText(input.actorName);
  const actionName = nonEmptyText(input.actionName) ?? "怪物高级动作";
  const actionLabel = `${actorName ? `${actorName}的` : ""}${advancedPhaseLabel(phase)}「${actionName}」`;
  const resource = phase === "legendary"
    ? (() => {
        const cost = positiveInt(input.legendaryCost, 1);
        const poolMax = positiveInt(input.legendaryPoolMax);
        return poolMax > 0
          ? `资源：本次消耗 ${cost} 点（动作池上限 ${poolMax} 点）。`
          : `资源：本次消耗 ${cost} 点；动作池上限未随请求同步。`;
      })()
    : phase === "lair"
      ? "窗口：先攻20的巢穴动作窗口，本轮一次。"
      : `资源：反应本轮一次；实际触发事件：${nonEmptyText(input.reactionTrigger) ?? "DM记录未随请求同步"}。`;

  return `DM 已确认${actionLabel}并创建你的待掷骰请求。${resource} 你的骰子提交前，此动作尚未完成结算；伤害、状态和后续回合不会视为完成。`;
}

/**
 * Describes the same action-window gates enforced by combat_service. This is
 * intentionally presentation-only: the backend remains authoritative when
 * the DM confirms the action.
 */
export function evaluateAdvancedActionAvailability(
  actor: Combatant,
  action: CombatActionLike,
  active: Combatant,
  roundNumber: number,
  turnIndex: number,
  lairWindow: boolean,
  reactionTrigger?: string | null,
): AdvancedActionAvailability | null {
  const phase = advancedActionPhase(action);
  if (!phase) return null;

  const blockingReasons: string[] = [];
  const declaredTrigger = phase === "reaction"
    ? nonEmptyText(action.reaction_trigger)
    : null;
  const confirmedTrigger = phase === "reaction"
    ? nonEmptyText(reactionTrigger)
    : null;
  const triggerLabel = confirmedTrigger ?? declaredTrigger;

  if (phase === "reaction") {
    if (!actor.reaction_available) blockingReasons.push("该单位的反应已经使用");
    if (!confirmedTrigger) {
      blockingReasons.push(declaredTrigger
        ? `请 DM 填写本次实际触发事件（规则条件：${declaredTrigger}）`
        : "资料没有结构化触发条件，执行前必须由 DM 填写实际事件");
    }
    return {
      phase,
      available: blockingReasons.length === 0,
      blockingReasons,
      windowLabel: "事件发生后；DM 记录实际触发事件后，每个单位本轮只能使用一次反应",
      resourceLabel: actor.reaction_available ? "反应：可用" : "反应：已用",
      triggerLabel,
    };
  }

  if (phase === "legendary") {
    const poolMax = positiveInt(action.legendary_pool_max);
    const cost = positiveInt(action.legendary_cost, 1);
    const remaining = nonNegativeInt(
      actor.snapshot_json.legendary_actions_remaining,
      poolMax,
    );
    if (actor.id === active.id) {
      blockingReasons.push("当前是该怪物自己的回合；传奇动作只能在其他单位回合结束后使用");
    }
    if (poolMax < 1) blockingReasons.push("资料没有明确传奇动作池上限");
    if (remaining < cost) blockingReasons.push(`传奇动作点不足：需要 ${cost} 点，剩余 ${remaining} 点`);
    const windowKey = `${roundNumber}:${turnIndex}`;
    if (actor.snapshot_json.legendary_action_window_used === windowKey) {
      blockingReasons.push("当前先攻窗口已经使用过传奇动作");
    }
    return {
      phase,
      available: blockingReasons.length === 0,
      blockingReasons,
      windowLabel: "其他单位回合结束后；每个先攻窗口最多一次（DM 仍需确认已到回合结束）",
      resourceLabel: poolMax > 0
        ? `传奇动作：${remaining}/${poolMax} 点 · 本次消耗 ${cost} 点`
        : "传奇动作：点数未明确",
      triggerLabel: null,
    };
  }

  if (!lairWindow) blockingReasons.push("当前不在先攻20的巢穴动作窗口");
  if (positiveInt(actor.snapshot_json.lair_action_round) === roundNumber) {
    blockingReasons.push("该单位本轮已经使用过巢穴动作");
  }
  return {
    phase,
    available: blockingReasons.length === 0,
    blockingReasons,
    windowLabel: "先攻20窗口；每个巢穴每轮一次",
    resourceLabel: lairWindow ? "巢穴动作：本轮可用" : "巢穴动作：当前窗口不可用",
    triggerLabel: null,
  };
}

export function advancedPhaseLabel(phase: Exclude<MonsterAIPhase, "turn">): string {
  return phase === "reaction" ? "反应" : phase === "legendary" ? "传奇动作" : "巢穴动作";
}
