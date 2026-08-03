export function damageModifierLabel(modifier: unknown): string {
  if (modifier === "resistance") return "抗性减半";
  if (modifier === "vulnerability") return "易伤翻倍";
  if (modifier === "immunity") return "免疫归零";
  return "正常伤害";
}

const DAMAGE_TYPE_LABELS: Record<string, string> = {
  acid: "强酸",
  bludgeoning: "钝击",
  cold: "寒冷",
  fire: "火焰",
  force: "力场",
  lightning: "闪电",
  necrotic: "黯蚀",
  piercing: "穿刺",
  poison: "毒素",
  psychic: "心灵",
  radiant: "光耀",
  slashing: "挥砍",
  thunder: "雷鸣",
  mixed: "混合",
};

function damageTypeLabel(value: unknown): string {
  if (typeof value !== "string") return "未知伤害";
  return DAMAGE_TYPE_LABELS[value.trim().toLowerCase()] ?? (value.trim() || "未知伤害");
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Format the authoritative per-type damage result without collapsing defenses. */
export function damageComponentsSummary(raw: unknown): string | null {
  if (!Array.isArray(raw)) return null;
  const parts: string[] = [];
  let adjustedTotal = 0;
  let hasAdjustedTotal = false;
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const component = item as Record<string, unknown>;
    const original = finiteNumber(component.original_damage)
      ?? finiteNumber(component.reported_total)
      ?? finiteNumber(component.amount);
    const adjusted = finiteNumber(component.adjusted_damage)
      ?? finiteNumber(component.adjusted_total)
      ?? finiteNumber(component.damage_total)
      ?? finiteNumber(component.amount);
    if (original === null && adjusted === null) continue;
    const shownOriginal = original ?? adjusted ?? 0;
    const shownAdjusted = adjusted ?? shownOriginal;
    adjustedTotal += shownAdjusted;
    hasAdjustedTotal = true;
    const value = shownOriginal === shownAdjusted
      ? String(shownAdjusted)
      : `${shownOriginal}→${shownAdjusted}`;
    const modifier = typeof component.modifier === "string" && component.modifier !== "normal"
      ? `（${damageModifierLabel(component.modifier)}）`
      : "";
    const tags = Array.isArray(component.damage_tags) && component.damage_tags.length
      ? ` [${component.damage_tags.join("、")}]`
      : "";
    parts.push(`${damageTypeLabel(component.damage_type)} ${value}${modifier}${tags}`);
  }
  if (!parts.length) return null;
  return `${parts.join("；")}${hasAdjustedTotal ? `；合计 ${adjustedTotal}` : ""}`;
}

export function damageComponentsByTargetSummary(raw: unknown): string | null {
  if (!Array.isArray(raw)) return null;
  const parts = raw.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const target = item as Record<string, unknown>;
    const name = typeof target.target_name === "string" ? target.target_name : "目标";
    const summary = damageComponentsSummary(target.damage_components);
    return summary ? [`${name}：${summary}`] : [];
  });
  return parts.length ? parts.join("；") : null;
}

export function actionEconomySummary(state: {
  action_available: boolean;
  bonus_action_available: boolean;
  reaction_available: boolean;
  movement_remaining_ft: number;
}): string {
  return [
    `动作 ${state.action_available ? "可用" : "已用"}`,
    `附赠 ${state.bonus_action_available ? "可用" : "已用"}`,
    `反应 ${state.reaction_available ? "可用" : "已用"}`,
    `移动 ${state.movement_remaining_ft}尺`,
  ].join(" · ");
}

export function deathSaveSummary(state: {
  successes: number;
  failures: number;
  stable: boolean;
  dead: boolean;
  pending_death_confirmation: boolean;
}): string {
  let status = "濒死";
  if (state.dead) status = "已死亡";
  else if (state.pending_death_confirmation) status = "等待 DM 确认死亡";
  else if (state.stable) status = "已稳定";
  return `成功 ${state.successes}/3 · 失败 ${state.failures}/3 · ${status}`;
}
