export function damageModifierLabel(modifier: unknown): string {
  if (modifier === "resistance") return "抗性减半";
  if (modifier === "vulnerability") return "易伤翻倍";
  if (modifier === "immunity") return "免疫归零";
  return "正常伤害";
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
