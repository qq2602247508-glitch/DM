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

type SceneNotesDocument = {
  scene_grid?: SceneGrid;
  story_outline?: Partial<SceneStoryOutline>;
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
