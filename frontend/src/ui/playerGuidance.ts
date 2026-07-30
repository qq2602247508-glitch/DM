import type { ScenePhase } from "./contextualQuickActions";

export type PlayerGuidanceReason = "dm_advanced" | "flow_advanced" | "scene_entered";

const PHASE_SUGGESTIONS: Record<ScenePhase, [string, string, string]> = {
  opening: [
    "描述角色此刻在做什么，并说明你最先关注的人、声音或物件。",
    "主动向一名在场人物提问，或与一名队友交换目前掌握的信息。",
    "如果想调查环境，请说清楚调查位置和方法，DM 会判断是否需要检定。",
  ],
  development: [
    "根据刚刚公开的新情况，选择调查、交涉、利用环境或直接行动。",
    "说清楚你的目标、做法和希望队友如何协助，方便 DM 一次完成裁定。",
    "回看公开日志与讲义，找出仍未验证的线索或尚未回应的人物。",
  ],
  twist: [
    "先确认局势发生了什么变化，再决定应对威胁、保护目标还是改变原计划。",
    "可以提出一个利用地形、物件、技能或法术的新方案。",
    "与队友快速分工，并说明谁先行动、其他人如何配合。",
  ],
  climax: [
    "选择最能决定当前 Scene 结果的行动，并明确你愿意承担的风险。",
    "确认队伍是迎战、谈判、绕过、撤退，还是采用另一种具体方案。",
    "行动后检查角色资源、状态与仍未解决的目标。",
  ],
  transition: [
    "确认离开前是否还要交谈、搜索、休息或处理角色资源。",
    "整理已经公开的线索、获得的物品以及仍未解决的问题。",
    "准备好后告诉 DM 队伍如何前往下一地点，以及采用什么行进方式。",
  ],
};

export function buildPlayerGuidance(input: {
  sceneName: string;
  phase: ScenePhase;
  reason: PlayerGuidanceReason;
}): { title: string; suggestions: string[] } {
  const prefix = input.reason === "scene_entered"
    ? `已进入「${input.sceneName}」`
    : input.reason === "flow_advanced"
    ? "场景进入了新的推进节点"
    : "DM 刚刚推进了当前局势";
  return {
    title: `${prefix} · 轮到你们回应`,
    suggestions: [...PHASE_SUGGESTIONS[input.phase]],
  };
}
