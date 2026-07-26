export type DraftKind = "scene" | "npc" | "monster" | "quest" | "clue" | "item";
export type DraftAtom = { id: string; kind: DraftKind; name: string; description: string };

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
    const [rawName, ...rest] = item.split(/[｜|]/);
    const name = rawName?.replace(/\*\*/g, "").replace(/[：:]$/, "").trim();
    if (!name) continue;
    atoms.push({
      id: crypto.randomUUID(), kind: currentKind, name,
      description: rest.join("｜").trim() || `${name}（来自备团草稿）`,
    });
  }
  return atoms;
}
