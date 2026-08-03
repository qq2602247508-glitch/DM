export type RuleBlockKind =
  | "trigger"
  | "target"
  | "range"
  | "cost"
  | "roll"
  | "save"
  | "effect"
  | "defense"
  | "movement"
  | "condition"
  | "modifier"
  | "object_state"
  | "exploration_effect"
  | "duration"
  | "repeat"
  | "special";

export type RuleBlock = {
  kind: RuleBlockKind;
  label: string;
  value: string;
};

export type RuleBlockPlan = {
  blocks: RuleBlock[];
  automation: "automatic" | "partial" | "manual";
  automationLabel: string;
  reason: string;
};

export type RuleTargeting = {
  shape: "single" | "circle" | "cone" | "line" | "cube" | "cylinder";
  rangeFt: number;
  sizeFt?: number;
  widthFt?: number;
  heightFt?: number;
  anchorHeightFt?: number;
  requiresElevation?: boolean;
  originSelf?: boolean;
};

const LABELS: Record<RuleBlockKind, string> = {
  trigger: "触发 / 时机",
  target: "目标",
  range: "距离 / 范围",
  cost: "消耗",
  roll: "骰子 / 命中",
  save: "豁免 / DC",
  effect: "伤害 / 治疗",
  defense: "抗性 / 易伤 / 免疫",
  movement: "移动 / 位移",
  condition: "状态",
  modifier: "战斗修正",
  object_state: "物件状态",
  exploration_effect: "探索效果",
  duration: "持续时间",
  repeat: "重复 / 次数",
  special: "特殊规则",
};

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? value as Record<string, unknown>
    : {};
}

function scalar(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  return "";
}

function list(value: unknown): string {
  if (Array.isArray(value)) return value.map(scalar).filter(Boolean).join("、");
  return scalar(value);
}

function first(data: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = list(data[key]);
    if (value) return value;
  }
  return "";
}

function add(
  blocks: RuleBlock[],
  kind: RuleBlockKind,
  values: Array<string | undefined>,
): void {
  const value = values.filter((item): item is string => Boolean(item)).join(" · ");
  if (value) blocks.push({ kind, label: LABELS[kind], value });
}

function withUnit(value: string, unit: string): string {
  return value && /^\d+(?:\.\d+)?$/.test(value) ? `${value}${unit}` : value;
}

function damageEffect(expression: string, damageType: string): string {
  if (!damageType) return `${expression} 伤害`;
  const normalizedExpression = expression.toLowerCase().replace(/\s+/g, " ").trim();
  const normalizedType = damageType.toLowerCase().trim();
  return normalizedExpression.endsWith(` ${normalizedType}`)
    ? `${expression}伤害`
    : `${expression} ${damageType}伤害`;
}

const CONDITION_RULES: Record<string, string> = {
  "倒地": "攻击者近战攻击具有优势；目标攻击具有劣势；起身消耗一半速度",
  "失能": "不能进行动作或反应；不能维持专注",
  "受惊": "不能主动靠近恐惧源；攻击检定和相关能力检定具有劣势",
  "恐慌": "不能主动靠近恐惧源；攻击检定和相关能力检定具有劣势",
  "束缚": "速度为0；攻击检定具有劣势；针对目标的攻击具有优势",
  "擒抱": "速度为0；擒抱者移动时可携带目标",
  "隐形": "攻击检定具有优势；针对目标的攻击具有劣势",
  "发光": "目标可见；针对目标的攻击具有优势（以法术说明为准）",
  "中毒": "攻击检定和能力检定具有劣势",
};

function conditionEffect(value: string): string {
  const key = Object.keys(CONDITION_RULES).find((candidate) => value.includes(candidate));
  return key && value === key ? `${key} · ${CONDITION_RULES[key]}` : value;
}

function embeddedPlan(source: unknown): Record<string, unknown> | null {
  const raw = record(source);
  const plan = record(raw.rule_plan);
  return Array.isArray(plan.blocks) ? plan : null;
}

function canonicalBlockPlan(plan: Record<string, unknown>): RuleBlockPlan {
  const blocks: RuleBlock[] = [];
  for (const rawBlock of Array.isArray(plan.blocks) ? plan.blocks : []) {
    const block = record(rawBlock);
    const kind = scalar(block.kind);
    if (kind === "target") {
      const mode = scalar(block.mode);
      const shape = scalar(block.shape);
      add(blocks, "target", [
        mode === "self" ? "自身" : mode === "area" ? "区域内目标" : scalar(block.disposition) || "目标",
        scalar(block.max_targets) ? `最多${scalar(block.max_targets)}个` : undefined,
      ]);
      add(blocks, "range", [
        scalar(block.range_ft) ? `${scalar(block.range_ft)}尺` : undefined,
        shape ? `${scalar(block.size_ft)}尺${shape}` : undefined,
        scalar(block.height_ft) ? `高${scalar(block.height_ft)}尺` : undefined,
      ]);
    } else if (kind === "resource") {
      add(blocks, "cost", [
        `${scalar(block.operation) || "spend"} ${scalar(block.resource_key)} × ${scalar(block.amount) || "0"}`,
      ]);
    } else if (kind === "roll") {
      add(blocks, "roll", [
        `${scalar(block.die) || "d20"} · ${scalar(block.roll_type)}${scalar(block.skill) ? ` · ${scalar(block.skill)}` : ""}`
          + ` · 对比${scalar(block.target_defense).toUpperCase()}`
          + (scalar(block.modifier) ? ` · 加值 ${scalar(block.modifier)}` : ""),
      ]);
    } else if (kind === "save") {
      add(blocks, "save", [
        `${scalar(block.ability)}豁免 · ${
          scalar(block.dc) ? `DC ${scalar(block.dc)}` : scalar(block.dc_source) || "动态DC"
        } · 成功${scalar(block.on_success) || "按规则"}`,
      ]);
    } else if (kind === "damage") {
      add(blocks, "effect", [
        `${damageEffect(scalar(block.expression), scalar(block.damage_type))} · ${
          block.shared_roll === false ? "逐目标分别掷伤害" : "整次效果共用伤害骰"
        }`,
      ]);
    } else if (kind === "defense") {
      const operation = scalar(block.operation);
      const label = operation === "resistance"
        ? "抗性（伤害减半）"
        : operation === "vulnerability"
          ? "易伤（伤害翻倍）"
          : "免疫（伤害归零）";
      add(blocks, "defense", [
        `${label} · ${list(block.damage_types)}`,
      ]);
    } else if (kind === "heal") {
      add(blocks, "effect", [
        `${scalar(block.expression)} ${block.temporary_hp === true ? "临时生命值" : "治疗"}`,
      ]);
    } else if (kind === "condition") {
      add(blocks, "condition", [
        `${scalar(block.operation)} · ${conditionEffect(scalar(block.condition))}`,
      ]);
    } else if (kind === "modifier") {
      const operation = scalar(block.operation);
      const value = scalar(block.value);
      const expression = scalar(block.expression);
      const source = scalar(block.source);
      const scope = scalar(block.scope);
      add(blocks, "modifier", [
        `${scalar(block.stat)} · ${operation}`,
        value ? `${value}` : undefined,
        expression,
        scope !== "all" ? scope : undefined,
        scalar(block.skill) ? `技能：${scalar(block.skill)}` : undefined,
        source,
      ]);
    } else if (kind === "object_state") {
      add(blocks, "object_state", [
        `${scalar(block.operation)} → ${scalar(block.state)}`,
        list(block.object_types),
        block.requires_dm_adjudication === true ? "需DM确认" : "可执行",
      ]);
    } else if (kind === "exploration_effect") {
      add(blocks, "exploration_effect", [
        scalar(block.operation),
        scalar(block.radius_ft) ? `${scalar(block.radius_ft)}尺` : undefined,
        scalar(block.details),
        block.requires_dm_adjudication === true ? "需DM确认" : "可执行",
      ]);
    } else if (kind === "move") {
      add(blocks, "movement", [
        `${scalar(block.movement_type)} ${scalar(block.distance_ft)}尺 · ${scalar(block.direction)}`,
      ]);
    } else if (kind === "teleport") {
      add(blocks, "movement", [
        `传送 · ${scalar(block.destination_kind) || "需选择目的地"}`,
        scalar(block.max_distance_ft) ? `最大${scalar(block.max_distance_ft)}尺` : "距离由法术原文/DM确认",
        block.requires_destination_choice !== false ? "施法时选择目的地" : undefined,
        block.can_take_creatures === true ? "可携带生物" : undefined,
      ]);
    } else if (kind === "transformation") {
      add(blocks, "special", [
        `${scalar(block.mode) || "变形"} · ${scalar(block.form_ref) || "需选择形态"}`,
        block.reversible !== false ? "可恢复/可结束" : undefined,
        block.requires_form_choice !== false ? "施法时选择形态" : undefined,
      ]);
    } else if (kind === "creation") {
      add(blocks, "special", [
        `创造${scalar(block.creation_kind) || "物件"} · ${scalar(block.template_ref) || "需选择模板"}`,
        scalar(block.count) ? `数量${scalar(block.count)}` : scalar(block.count_expression),
        block.requires_template_choice !== false ? "施法时选择模板" : undefined,
      ]);
    } else if (kind === "dispel") {
      add(blocks, "special", [
        `${scalar(block.mode) === "counterspell" ? "反制法术" : "驱散效果"}`,
        list(block.effect_types),
        block.check_required === true ? `需要检定${scalar(block.check_dc_source) ? ` · ${scalar(block.check_dc_source)}` : ""}` : "无需额外检定",
      ]);
    } else if (kind === "duration") {
      add(blocks, "duration", [
        `${scalar(block.value)}${scalar(block.unit)}`.replace(/^0/, ""),
        block.concentration === true ? "需要专注" : undefined,
      ]);
    } else if (kind === "repeat") {
      add(blocks, "repeat", [
        scalar(block.count) ? `重复${scalar(block.count)}次` : scalar(block.count_expression),
        scalar(block.timing),
      ]);
    } else if (kind === "choice") {
      const options = Array.isArray(block.options)
        ? block.options.map((item) => scalar(record(item).label)).filter(Boolean).join(" / ")
        : "";
      add(blocks, "special", [`${scalar(block.prompt)}：${options}`]);
    } else if (kind === "summon") {
      const entersCombat = block.enters_combat !== false;
      const initiativeMode = scalar(block.initiative_mode);
      const initiative = !entersCombat
        ? "不进入独立先攻"
        : initiativeMode === "shared_with_source"
          ? "共用来源单位先攻"
          : "自行掷先攻";
      add(blocks, "effect", [
        `召唤 ${scalar(block.creature_ref)} × ${scalar(block.count_expression) || scalar(block.count) || "1"} · ${scalar(block.controller)} · ${initiative}`,
      ]);
    } else if (kind === "trigger") {
      add(blocks, "trigger", [`${scalar(block.timing)} · ${scalar(block.event)}`]);
    } else if (kind === "narrative") {
      add(blocks, "special", [scalar(block.text)]);
    }
  }
  const confidence = scalar(plan.automation_confidence);
  const automation = confidence === "exact"
    ? "automatic"
    : confidence === "partial"
      ? "partial"
      : "manual";
  const reasons = Array.isArray(plan.unresolved_reasons)
    ? plan.unresolved_reasons.map(scalar).filter(Boolean).join("；")
    : "";
  return {
    blocks,
    automation,
    automationLabel: automation === "automatic"
      ? "可进入自动结算"
      : automation === "partial"
        ? "仅可部分自动结算"
        : "不可自动结算 · 需 DM 裁定",
    reason: reasons || (
      automation === "automatic"
        ? "规则已经编译为可验证的执行积木。"
        : automation === "partial"
          ? "部分规则已结构化，其余步骤需要玩家报骰或 DM 确认。"
          : "规则未安全结构化；系统不会根据名称或说明猜测数值。"
    ),
  };
}

export function targetingFromRulePlan(source: unknown): RuleTargeting | null {
  const plan = embeddedPlan(source);
  if (!plan) return null;
  const planBlocks = (Array.isArray(plan.blocks) ? plan.blocks : []).map(record);
  const target = planBlocks
    .map(record)
    .find((block) => block.kind === "target");
  if (!target) return null;
  const rawShape = scalar(target.shape);
  const area = planBlocks.find((block) => block.kind === "area_effect");
  const areaShape = scalar(area?.shape);
  const rawShapeValue = rawShape || areaShape;
  const originSelf = scalar(target.mode) === "self"
    || scalar(area?.origin) === "self"
    || (target.range_ft != null && Number(target.range_ft) === 0);
  // Older persisted plans sometimes retained only "self + 0尺" after the
  // area block was flattened. That is not enough to decide that the action is
  // a single-target effect: let the caller's explicit range/description
  // fallback recover a cube, cone, or other shape instead of suppressing it
  // behind a false single-target template.
  if (!rawShapeValue && originSelf) return null;
  const shape = rawShapeValue === "sphere"
    ? "circle"
    : rawShapeValue === "cylinder"
      ? "cylinder"
    : rawShapeValue === "cone"
      ? "cone"
      : rawShapeValue === "line"
        ? "line"
        : rawShapeValue === "cube"
          ? "cube"
        : rawShapeValue
          ? null
          : "single";
  if (!shape) return null;
  // Missing range is unresolved data, not a touch/self spell. Returning a
  // zero-foot template would silently make the map treat it as point-blank.
  if (!originSelf && target.range_ft == null) return null;
  const heightFt = target.height_ft == null
    ? area?.height_ft == null ? undefined : Number(area.height_ft)
    : Number(target.height_ft);
  const widthFt = target.width_ft == null
    ? area?.width_ft == null ? undefined : Number(area.width_ft)
    : Number(target.width_ft);
  const anchorHeightFt = target.anchor_height_ft == null
    ? area?.anchor_height_ft == null ? undefined : Number(area.anchor_height_ft)
    : Number(target.anchor_height_ft);
  const requiresElevation = target.requires_explicit_elevation === true
    || area?.requires_explicit_elevation === true;
  return {
    shape,
    rangeFt: Number(target.range_ft ?? 0),
    sizeFt: target.size_ft == null
      ? area?.size_ft == null ? undefined : Number(area.size_ft)
      : Number(target.size_ft),
    ...(widthFt === undefined ? {} : { widthFt }),
    ...(heightFt === undefined ? {} : { heightFt }),
    ...(anchorHeightFt === undefined ? {} : { anchorHeightFt }),
    ...(requiresElevation ? { requiresElevation: true } : {}),
    ...(originSelf ? { originSelf: true } : {}),
  };
}

/**
 * Turns explicitly structured action/spell data into UI steps.
 *
 * This deliberately does not infer mechanics from a name or prose description.
 * Missing execution fields must stay visible as a DM decision instead of being
 * silently invented by the client.
 */
export function buildRuleBlockPlan(source: unknown): RuleBlockPlan {
  const raw = record(source);
  const canonical = embeddedPlan(raw);
  if (canonical) return canonicalBlockPlan(canonical);
  const metadata = record(raw.metadata_json ?? raw.metadata);
  const data = { ...metadata, ...raw };
  const blocks: RuleBlock[] = [];

  const trigger = first(data, "trigger", "reaction_trigger", "when");
  const timing = first(data, "casting_time", "castingTime", "action", "activation");
  add(blocks, "trigger", [trigger, timing]);

  const target = first(data, "target", "targets", "target_type", "target_description");
  const targetCount = first(data, "target_count", "number_of_targets");
  add(blocks, "target", [
    target,
    targetCount ? `${targetCount}个目标` : undefined,
  ]);

  const range = first(data, "range", "reach");
  const area = first(data, "area", "area_of_effect", "shape", "template");
  const radius = withUnit(first(data, "radius", "radius_ft"), "尺半径");
  const cone = withUnit(first(data, "cone", "cone_ft"), "尺锥形");
  const line = withUnit(first(data, "line", "line_ft"), "尺直线");
  add(blocks, "range", [range, area, radius, cone, line]);

  const cost = first(data, "cost", "action_cost");
  const resourceKey = first(data, "resource_label", "resource_key", "resource");
  const resourceCost = first(data, "resource_cost", "slot_cost");
  add(blocks, "cost", [
    cost,
    resourceKey
      ? `${resourceKey}${resourceCost ? ` × ${resourceCost}` : ""}`
      : resourceCost
        ? `资源 × ${resourceCost}`
        : undefined,
  ]);

  const roll = first(data, "attack_roll", "roll", "check", "dice");
  const attackBonus = first(data, "attack_bonus", "to_hit");
  add(blocks, "roll", [
    roll,
    attackBonus ? `d20 ${Number(attackBonus) >= 0 ? "+" : ""}${attackBonus} 对比目标 AC` : undefined,
  ]);

  const saveAbility = first(data, "save_ability", "saving_throw");
  const saveDc = first(data, "save_dc", "dc");
  const saveResult = data.half_damage_on_save === true
    ? "成功半伤"
    : data.no_damage_on_save === true
      ? "成功无伤"
      : first(data, "save_success", "on_save");
  add(blocks, "save", [
    saveAbility
      ? `${saveAbility}豁免 · ${saveDc ? `DC ${saveDc}` : "DC 未记录"}`
      : undefined,
    saveResult,
  ]);

  const damage = first(data, "damage_expression", "damage");
  const damageType = first(data, "damage_type");
  const healing = first(data, "healing_expression", "healing", "heal");
  add(blocks, "effect", [
    damage ? damageEffect(damage, damageType) : undefined,
    healing ? `${healing} 治疗` : undefined,
  ]);

  const conditions = first(data, "conditions", "condition", "status", "applies_condition");
  add(blocks, "condition", [conditions ? conditionEffect(conditions) : undefined]);

  const movement = record(data.movement);
  if (Object.keys(movement).length) {
    add(blocks, "movement", [
      `${first(movement, "type", "movement_type") || "forced"} ${first(movement, "distance_ft")}尺 · ${first(movement, "direction") || "chosen"}`,
    ]);
  }

  const reaction = record(data.reaction);
  if (Object.keys(reaction).length) {
    add(blocks, "trigger", [
      `反应 · ${first(reaction, "event", "trigger")}`,
      first(reaction, "effect", "description"),
    ]);
  }

  const duration = first(data, "duration");
  const concentration = data.concentration === true ? "需要专注" : "";
  add(blocks, "duration", [duration, concentration]);

  const repeat = first(data, "repeat", "repeat_save", "frequency");
  const uses = first(data, "uses", "use_limit", "limit");
  const recharge = first(data, "recharge");
  add(blocks, "repeat", [
    repeat,
    uses ? `使用限制：${uses}` : undefined,
    recharge ? `充能：${recharge}` : undefined,
  ]);

  const special = first(data, "special", "special_rule", "rules_note");
  const description = first(data, "description", "effect", "rules_text", "summary");
  add(blocks, "special", [special, description]);

  const resolutionKind = first(data, "resolution_kind", "resolution");
  const explicitlyNarrative = resolutionKind === "narrative"
    || data.auto_eligible === false;
  const hasEffect = Boolean(damage || healing || conditions);
  const hasResolutionGate = Boolean(
    roll || attackBonus || saveAbility || saveDc || data.auto_eligible === true,
  );

  if (!explicitlyNarrative && hasEffect && hasResolutionGate) {
    return {
      blocks,
      automation: "automatic",
      automationLabel: "可进入自动结算",
      reason: "已记录效果骰与命中、豁免或明确的自动执行条件。",
    };
  }
  if (!explicitlyNarrative && hasEffect) {
    return {
      blocks,
      automation: "partial",
      automationLabel: "仅可部分自动结算",
      reason: "已记录效果，但缺少命中、豁免或其他执行条件；由 DM 确认后结算。",
    };
  }
  return {
    blocks,
    automation: "manual",
    automationLabel: "不可自动结算 · 需 DM 裁定",
    reason: explicitlyNarrative
      ? "这是叙事或特殊效果。系统只展示已记录规则文字，不会虚构伤害、范围或 DC。"
      : "缺少结构化伤害、治疗或状态效果。系统不会根据名称或说明猜测规则。",
  };
}
