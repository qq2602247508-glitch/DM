export type DraftKind = "scene" | "npc" | "monster" | "quest" | "clue" | "item";
export type DraftSceneOutline = {
  chapterTitle: string;
  sceneOrder: number;
  objective: string;
  opening: string;
  development: string;
  twist: string;
  climax: string;
  transition: string;
};
export type DraftAtom = {
  id: string;
  kind: DraftKind;
  name: string;
  description: string;
  sceneOutline?: DraftSceneOutline;
};

const DRAFT_HEADINGS: Record<string, DraftKind> = {
  "场景": "scene", "地点与场景": "scene", "npc": "npc", "NPC": "npc",
  "怪物": "monster", "敌人与怪物": "monster", "任务": "quest",
  "线索": "clue", "物品": "item", "奖励与物品": "item",
};

export function parsePrepDraft(text: string): DraftAtom[] {
  let currentKind: DraftKind | null = null;
  const atoms: DraftAtom[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    const heading = line.replace(/^#+\s*/, "").replace(/[：:]$/, "").trim();
    const matchedHeading = Object.entries(DRAFT_HEADINGS).find(([label]) => heading.toLowerCase() === label.toLowerCase());
    if (matchedHeading) {
      currentKind = matchedHeading[1];
      continue;
    }
    // Any other Markdown heading ends the previous import section. Without
    // this reset, bullets under “DM建议” inherit the preceding “物品” kind.
    if (/^#{1,6}(?:\s|$)/.test(line)) {
      currentKind = null;
      continue;
    }
    const item = line.match(/^(?:[-*•]|\d+[.)、])\s*(.+)$/)?.[1]?.trim();
    if (!item || !currentKind) continue;
    const parts = item.split(/[｜|]/).map((part) => part.trim());
    if (currentKind === "scene" && parts.length >= 4 && /^\d+$/.test(parts[1] ?? "")) {
      const [
        chapterTitle, rawOrder, name, objective = "", opening = "",
        development = "", twist = "", climax = "", transition = "",
      ] = parts;
      if (!chapterTitle || !name) continue;
      atoms.push({
        id: crypto.randomUUID(),
        kind: "scene",
        name,
        description: objective || `${name}（来自备团草稿）`,
        sceneOutline: {
          chapterTitle,
          sceneOrder: Math.max(1, Number(rawOrder)),
          objective: objective || "由 DM 自由推进。",
          opening: opening || objective,
          development: development || "根据玩家行动推进。",
          twist: twist || "可选转折。",
          climax: climax || "确认场景目标。",
          transition: transition || "由 DM 决定是否转场。",
        },
      });
      continue;
    }
    const [rawName, ...rest] = parts;
    const name = rawName?.replace(/\*\*/g, "").replace(/[：:]$/, "").trim();
    if (!name) continue;
    atoms.push({
      id: crypto.randomUUID(), kind: currentKind, name,
      description: rest.join("｜").trim() || `${name}（来自备团草稿）`,
    });
  }
  return atoms;
}
