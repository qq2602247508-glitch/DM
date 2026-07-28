export type DraftKind = "location" | "building" | "dungeon" | "scene" | "npc" | "monster" | "quest" | "clue" | "item";
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
  siteConfig?: { regionPath: string; maximumLevels: number };
  sceneOutline?: DraftSceneOutline;
};

const DRAFT_HEADINGS: Record<string, DraftKind> = {
  "地点": "location", "地点与场景": "location", "场景": "scene", "npc": "npc", "NPC": "npc",
  "怪物": "monster", "敌人与怪物": "monster", "任务": "quest",
  "线索": "clue", "物品": "item", "奖励与物品": "item",
  "建筑": "building", "地下城": "dungeon",
};

function includesAny(text: string, words: string[]): boolean {
  return words.some((word) => text.includes(word));
}

/**
 * A deterministic D&D-only fallback for short briefs or temporarily
 * unavailable local models. It deliberately produces the same reviewable
 * Markdown contract as the model, so no campaign state is written until the
 * DM imports the selected atoms.
 */
export function buildFallbackPrepDraft(brief: string): string {
  const normalized = brief.trim() || "1级玩家在新手村酒馆集结，并遭遇地精袭击";
  const isTavern = /酒馆|旅店|客栈|tavern|inn/i.test(normalized);
  const isBaldursGate = /博德之门|baldur/i.test(normalized);
  const isGoblin = /地精|goblin/i.test(normalized);
  const locationName = isTavern
    ? `${isBaldursGate ? "博德之门" : "新手村"}的集结酒馆`
    : "冒险起始地点";
  const monsterName = isGoblin ? "地精" : includesAny(normalized, ["鼠群", "鼠集群", "老鼠"])
    ? "鼠群"
    : "符合场景的低等级敌人";
  const firstScene = isTavern ? "酒馆集结" : "冒险集结";
  return `## 地点
- ${locationName}｜${normalized}。这里包含入口、主要活动区、掩体与可互动物，并生成对应的5尺战斗网格。
## 场景
- 第一章｜1｜${firstScene}｜让玩家认识彼此并了解眼前局势｜描述${locationName}与在场人物，请每名玩家介绍角色｜通过店主、旅客或现场细节给出行动切入点｜异动打断集结，${monsterName}威胁现场｜玩家决定交涉、保护平民或迎战｜威胁出现时进入下一Scene
- 第一章｜2｜${monsterName}突袭｜处理突袭并保护现场｜从入口、暗处或混乱人群中展示敌人出现｜让玩家利用环境、交涉或准备战斗｜敌人改变位置或威胁无辜者｜击退、制服或迫使敌人撤退｜战斗结算后调查敌人的来意
## 建筑
- ${locationName}｜${isBaldursGate ? "博德之门/下城区" : "新手村/中心区"}｜2｜包含集结大厅、后厨、客房、储藏室与门廊；楼层和房间以门连接。
## NPC
- 酒馆老板｜熟悉本地消息，会优先保护客人与财物，可向玩家提供目击线索。
## 怪物
- ${monsterName}｜优先从本地D&D 5e图鉴匹配；若进入战斗，应按1级队伍人数复核遭遇难度。
## 任务
- 处理突发威胁｜保护现场并查明${monsterName}为何在此出现。
## 线索
- 袭击者留下的痕迹｜指向附近藏身处或幕后指使者，由DM决定具体方向。
## 物品
- 现场可互动物｜桌椅、门窗、酒桶或其他符合地点的掩体与临时工具。
## DM建议
这是依据简短描述生成的D&D 5e确定性备团草案。请审核名称、怪物数量与难度后再导入。`;
}

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
        id: createClientId("prep"),
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
    if ((currentKind === "building" || currentKind === "dungeon") && parts.length >= 4) {
      const [, regionPath, rawLevels, ...description] = parts;
      atoms.push({
        id: createClientId("prep"), kind: currentKind, name,
        description: description.join("｜").trim() || `${name}（来自备团草稿）`,
        siteConfig: {
          regionPath: regionPath || "未归类区域",
          maximumLevels: Math.max(1, Math.min(20, Number(rawLevels) || 1)),
        },
      });
    } else {
      atoms.push({
        id: createClientId("prep"), kind: currentKind, name,
        description: rest.join("｜").trim() || `${name}（来自备团草稿）`,
      });
    }
  }
  if (!atoms.some((atom) => atom.kind === "building" || atom.kind === "dungeon")) {
    const candidate = atoms.find((atom) => atom.kind === "location" && (
      /地下城|地牢|矿坑|洞穴|遗迹|宅邸|酒馆|旅店|教堂|塔楼|城堡/.test(`${atom.name}${atom.description}`)
    ));
    if (candidate) {
      const dungeon = /地下城|地牢|矿坑|洞穴|遗迹/.test(`${candidate.name}${candidate.description}`);
      atoms.push({
        id: createClientId("prep"),
        kind: dungeon ? "dungeon" : "building",
        name: candidate.name,
        description: candidate.description,
        siteConfig: {
          regionPath: "未归类区域",
          maximumLevels: dungeon ? 3 : 2,
        },
      });
    }
  }
  return atoms;
}
import { createClientId } from "./id";
