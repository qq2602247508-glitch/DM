import type { SceneStoryOutline } from "./sceneOutline";

type ParticipantSummary = {
  entity_type: "character" | "npc" | "monster";
  name: string;
  defeated?: boolean;
};

export type ScenePhase = "opening" | "development" | "twist" | "climax" | "transition";

export const SCENE_PHASE_LABELS: Record<ScenePhase, string> = {
  opening: "起",
  development: "承",
  twist: "转",
  climax: "合",
  transition: "转场",
};

export function scenePhaseText(outline: SceneStoryOutline, phase: ScenePhase): string {
  return {
    opening: outline.opening,
    development: outline.development,
    twist: outline.twist,
    climax: outline.climax,
    transition: outline.transition,
  }[phase];
}

export function buildContextualQuickActions(input: {
  sceneName: string;
  outline: SceneStoryOutline | null;
  phase: ScenePhase;
  participants: ParticipantSummary[];
  recentText?: string;
}): string[] {
  const npc = input.participants.find((item) => item.entity_type === "npc");
  const monster = input.participants.find(
    (item) => item.entity_type === "monster" && !item.defeated,
  );
  const phaseText = input.outline ? scenePhaseText(input.outline, input.phase) : "";
  const actions: string[] = [];

  if (input.phase === "opening") {
    actions.push(`朗读“${input.sceneName}”的开场环境，并请玩家说明各自行动`);
    actions.push(npc
      ? `让 ${npc.name} 依照目标和态度主动开口，给出玩家可回应的话题`
      : "从当前地点的声音、人物或可互动物中给出一个自然切入点");
  } else if (input.phase === "development") {
    actions.push(`围绕“${phaseText || input.sceneName}”推进调查、交涉或环境互动`);
    actions.push(npc
      ? `继续与 ${npc.name} 的交涉，并根据玩家态度改变其反应`
      : "揭示一条可通过观察、询问或行动获得的场景信息");
  } else if (input.phase === "twist") {
    actions.push(`落实当前转折：“${phaseText || "局势发生变化"}”`);
    actions.push(monster
      ? `让 ${monster.name} 的存在产生明确压力，并判断交涉、追逐或战斗`
      : "让已知线索、人物关系或环境危险产生新的具体后果");
  } else if (input.phase === "climax") {
    actions.push(`检查 Scene 目标是否完成，并描述玩家行动造成的结果`);
    actions.push(monster
      ? `处理 ${monster.name} 带来的最终选择：迎战、逼退、绕过或谈判`
      : "让玩家做出决定当前 Scene 结局的最后选择");
  } else {
    actions.push(`依据“${phaseText || "当前结果"}”生成转场描述`);
    actions.push("结算当前 Scene 的线索、状态与未解决事项，再提示下一个 Scene");
  }

  if (monster) {
    actions.push(`评估 ${monster.name} 是否立即敌对；若开战，提示 DM 发起当前场景战斗`);
  } else if (input.recentText?.trim()) {
    actions.push("根据最近一次玩家行动，给出最直接的世界反应与两种后续选择");
  } else {
    actions.push("询问玩家接下来做什么，并准备两个符合当前局势的回应方向");
  }
  return [...new Set(actions)].slice(0, 4);
}
