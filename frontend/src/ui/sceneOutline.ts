import type { Scene, SceneGrid } from "../api/types";

export type SceneStoryOutline = {
  chapterTitle: string;
  chapterOrder: number;
  sceneOrder: number;
  objective: string;
  opening: string;
  development: string;
  twist: string;
  climax: string;
  transition: string;
};

export type SceneFlowStepKind =
  | "setup"
  | "hook"
  | "interaction"
  | "challenge"
  | "choice"
  | "complication"
  | "resolution"
  | "transition";

export type SceneFlowStep = {
  id: string;
  order: number;
  kind: SceneFlowStepKind;
  title: string;
  instruction: string;
  dmNote: string;
  sourcePhase: "opening" | "development" | "twist" | "climax" | "transition";
};

type SceneNotesDocument = {
  scene_grid?: SceneGrid;
  story_outline?: Partial<SceneStoryOutline>;
  story_flow?: string[];
};

const FALLBACK_CHAPTER = "未编排章节";

export function chapterOrderFromTitle(title: string): number {
  const arabic = title.match(/\d+/)?.[0];
  if (arabic) return Math.max(1, Number(arabic));
  const chinese: Record<string, number> = {
    一: 1, 二: 2, 三: 3, 四: 4, 五: 5,
    六: 6, 七: 7, 八: 8, 九: 9, 十: 10,
  };
  const match = title.match(/第?([一二三四五六七八九十])章?/);
  return match?.[1] ? chinese[match[1]] ?? 999 : 999;
}

export function readSceneStoryOutline(
  scene: Scene,
  fallbackOrder: number,
): SceneStoryOutline {
  let parsed: SceneNotesDocument = {};
  try {
    const value = JSON.parse(scene.notes ?? "{}") as unknown;
    if (value && typeof value === "object") parsed = value;
  } catch {
    // Older scenes may contain plain-text notes. They remain usable and are
    // shown under a clearly labeled fallback chapter.
  }
  const outline = parsed.story_outline ?? {};
  const chapterTitle = String(outline.chapterTitle || FALLBACK_CHAPTER);
  return {
    chapterTitle,
    chapterOrder: Number(outline.chapterOrder) || chapterOrderFromTitle(chapterTitle),
    sceneOrder: Number(outline.sceneOrder) || fallbackOrder,
    objective: String(outline.objective || scene.description || "由 DM 自由推进。"),
    opening: String(outline.opening || scene.description || "介绍当前环境与在场人物。"),
    development: String(outline.development || "根据玩家行动推进冲突、探索或对话。"),
    twist: String(outline.twist || "视玩家选择加入变化；没有必要时可以跳过。"),
    climax: String(outline.climax || "确认本 Scene 的目标是否完成。"),
    transition: String(outline.transition || "完成后由 DM 决定是否进入下一个 Scene。"),
  };
}

export function buildSceneNotes(
  grid: SceneGrid,
  outline: SceneStoryOutline,
): string {
  return JSON.stringify({
    scene_grid: grid,
    story_outline: outline,
  });
}

export function sortScenesByOutline(scenes: Scene[]): Scene[] {
  return [...scenes].sort((left, right) => {
    const leftIndex = scenes.indexOf(left) + 1;
    const rightIndex = scenes.indexOf(right) + 1;
    const a = readSceneStoryOutline(left, leftIndex);
    const b = readSceneStoryOutline(right, rightIndex);
    return a.chapterOrder - b.chapterOrder
      || a.chapterTitle.localeCompare(b.chapterTitle, "zh-CN")
      || a.sceneOrder - b.sceneOrder
      || left.created_at.localeCompare(right.created_at);
  });
}

function conciseTitle(text: string, fallback: string): string {
  const clean = text.replace(/[。；;，,：:！!？?\n]/g, " ").replace(/\s+/g, " ").trim();
  if (!clean) return fallback;
  return clean.length > 18 ? `${clean.slice(0, 18)}…` : clean;
}

/**
 * Compile old five-field outlines into a practical DM run sheet. The five
 * fields remain an import/storage compatibility format; they are not the UI
 * structure and they do not force the table into a fixed dramatic formula.
 */
export function buildSceneFlow(scene: Scene, fallbackOrder: number): SceneFlowStep[] {
  const outline = readSceneStoryOutline(scene, fallbackOrder);
  let storedFlow: string[] = [];
  try {
    const parsed = JSON.parse(scene.notes ?? "{}") as SceneNotesDocument;
    if (Array.isArray(parsed.story_flow)) {
      storedFlow = parsed.story_flow.filter(
        (item): item is string => typeof item === "string" && item.trim().length > 0,
      ).slice(0, 16);
    }
  } catch {
    // Old plain-text notes use the deterministic compatibility flow below.
  }
  if (storedFlow.length >= 3) {
    const lastIndex = storedFlow.length - 1;
    return storedFlow.map((instruction, index) => {
      const kind: SceneFlowStepKind = index === 0 ? "setup"
        : index === lastIndex ? "transition"
        : /结算|奖励|记录|收束|确认结果/.test(instruction) ? "resolution"
        : /检定|豁免|裁定|难度|代价/.test(instruction) ? "challenge"
        : /选择|决定|询问玩家/.test(instruction) ? "choice"
        : /突发|变化|揭示|危险|伏击/.test(instruction) ? "complication"
        : /交涉|询问|调查|搜索|互动/.test(instruction) ? "interaction"
        : "hook";
      const sourcePhase: SceneFlowStep["sourcePhase"] = index === 0 ? "opening"
        : index === lastIndex ? "transition"
        : index / lastIndex < 0.45 ? "development"
        : index / lastIndex < 0.72 ? "twist"
        : "climax";
      return {
        id: `${scene.id}:flow:${index + 1}`,
        order: index + 1,
        kind,
        sourcePhase,
        title: conciseTitle(instruction, `流程 ${index + 1}`),
        instruction,
        dmNote: kind === "challenge"
          ? "只有结果不确定且失败有意义时才要求检定；规则数值由规则引擎或规则搜索确认。"
          : kind === "transition"
            ? "先确认玩家是否还有行动；只有 DM 明确确认后才进入下一 Scene。"
            : "这是可调整的导航步骤；优先承接玩家已经提出的合理方案。",
      };
    });
  }
  const drafts: Omit<SceneFlowStep, "id" | "order">[] = [];
  drafts.push({
      kind: "setup", sourcePhase: "opening",
      title: conciseTitle(outline.opening, "建立现场"),
      instruction: outline.opening,
      dmNote: "只陈述玩家能够立刻感知的事实，再逐一询问角色此刻在做什么。",
  });
  if (outline.objective.trim() && !outline.opening.includes(outline.objective.trim())) {
    drafts.push({
      kind: "hook", sourcePhase: "opening",
      title: `明确本场目标：${conciseTitle(outline.objective, "建立行动方向")}`,
      instruction: `让玩家自然理解当前可处理的问题或机会：${outline.objective}`,
      dmNote: "不要替玩家做决定；至少留下调查、交涉、绕行或直接行动中的两种入口。",
    });
  }
  if (outline.development.trim() && !/^(根据玩家行动推进|由 DM 自由推进)[。.]?$/.test(outline.development.trim())) {
    drafts.push({
      kind: "interaction", sourcePhase: "development",
      title: conciseTitle(outline.development, "展开人物与环境互动"),
      instruction: outline.development,
      dmNote: "先让已在场人物和可互动物响应玩家；只有结果存在不确定且失败有意义时才要求检定。",
    });
  }
  drafts.push({
      kind: "choice", sourcePhase: "development",
      title: "停下来接收玩家方案",
      instruction: "概括玩家目前知道的事实，询问他们具体怎么做、由谁行动，以及其他角色如何协助。",
      dmNote: "接受大纲外的合理方案。流程是导航，不是必须逐字执行的剧本。",
  });
  if (outline.twist.trim() && !/^(可选转折|视玩家选择加入变化|没有必要时可以跳过)[。；;]?$/.test(outline.twist.trim())) {
    drafts.push({
      kind: "complication", sourcePhase: "twist",
      title: conciseTitle(outline.twist, "按需引入局势变化"),
      instruction: outline.twist,
      dmNote: "仅在节奏停滞、玩家触发条件或前序行动确实导致变化时使用；不需要时可以跳过。",
    });
  }
  const mayNeedAdjudication = /调查|搜索|潜入|追逐|交涉|说服|欺瞒|撬锁|陷阱|危险|战斗|攻击|检定|豁免|机关/.test(
    `${scene.name} ${scene.description ?? ""} ${outline.objective} ${outline.development} ${outline.twist}`,
  );
  if (mayNeedAdjudication) {
    drafts.push({
      kind: "challenge", sourcePhase: "twist",
      title: "裁定行动与即时后果",
      instruction: "根据玩家采用的方法，决定直接成功、需要检定、消耗资源，或引发新的选择；随后明确描述世界反应。",
      dmNote: "规则数值交给规则搜索或规则引擎；失败应推动局势并带来代价，而不是让故事原地停止。",
    });
  }
  if (outline.climax.trim()) {
    drafts.push({
      kind: "resolution", sourcePhase: "climax",
      title: conciseTitle(outline.climax, "确认本场结果"),
      instruction: outline.climax,
      dmNote: `对照目标“${outline.objective}”记录已完成、被绕过及仍未解决的事项。`,
    });
  }
  if (/奖励|战斗|伤势|资源|线索|任务|物品|金币|经验|关系|态度/.test(
    `${scene.description ?? ""} ${outline.objective} ${outline.development} ${outline.twist} ${outline.climax}`,
  )) {
    drafts.push({
      kind: "resolution", sourcePhase: "climax",
      title: "结算状态、线索与回报",
      instruction: "同步角色状态、获得或失去的资源、NPC态度、公开线索和后续风险。",
      dmNote: "只有 DM 确认的事实才写入；战斗奖励仍走独立结算确认。",
    });
  }
  if (outline.transition.trim()) {
    drafts.push({
      kind: "transition", sourcePhase: "transition",
      title: conciseTitle(outline.transition, "决定下一去向"),
      instruction: outline.transition,
      dmNote: "先询问玩家离场前是否还有行动，再由 DM 明确进入下一个 Scene；AI 只能提示，不能自动切换。",
    });
  }
  return drafts.map((step, index) => ({
    ...step,
    id: `${scene.id}:flow:${index + 1}`,
    order: index + 1,
  }));
}
