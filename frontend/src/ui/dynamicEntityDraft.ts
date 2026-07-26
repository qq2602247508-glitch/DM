import type { Monster, SearchHit } from "../api/types";

export type ArrivalKind = "monster" | "npc";

export type MonsterReferenceCandidate =
  | {
      key: string;
      origin: "campaign";
      label: string;
      sourceLabel: string;
      matchReason: string;
      monster: Monster;
    }
  | {
      key: string;
      origin: "compendium";
      label: string;
      sourceLabel: string;
      matchReason: string;
      hit: SearchHit;
      stats: ParsedMonsterStats;
    };

export type ParsedMonsterStats = {
  name: string;
  armorClass: number;
  hp: number;
  speed: number;
  challengeRating: string;
  abilityScores: Record<string, number>;
  description: string;
};

export type ArrivalDraft = {
  kind: ArrivalKind;
  prompt: string;
  name: string;
  description: string;
  armorClass: number;
  hp: number;
  speed: number;
  challengeRating: string;
  sourceKey: string;
};

const ARRIVAL_PATTERN = /(?:来(?:了|到|袭)|出现|进入|闯入|突袭|袭击|赶到|现身|冒出|召唤|增援)/i;
const MONSTER_PATTERN = /(?:怪物|魔物|敌人|野兽|亡灵|恶魔|魔鬼|巨龙|地精|哥布林|兽人|妖精|异怪|构装|元素|邪魔)/i;
const NPC_PATTERN = /(?:NPC|人物|有人|一个人|陌生人|商人|守卫|村民|牧师|旅人|访客|盟友|使者|雇主)/i;

export function detectArrivalKind(text: string): ArrivalKind | null {
  if (!ARRIVAL_PATTERN.test(text)) return null;
  if (MONSTER_PATTERN.test(text)) return "monster";
  if (NPC_PATTERN.test(text)) return "npc";
  return null;
}

export function suggestedNpcName(text: string): string {
  const quoted = text.match(/[“「『"]([^”」』"]{2,24})[”」』"]/u)?.[1]?.trim();
  if (quoted) return quoted;
  const named = text.match(/(?:名叫|叫作|叫做)\s*([\p{L}\p{N}·' -]{2,24})/u)?.[1]?.trim();
  return named || "突然出现的陌生人";
}

function numberAfter(text: string, pattern: RegExp, fallback: number): number {
  const value = Number(text.match(pattern)?.[1]);
  return Number.isFinite(value) ? value : fallback;
}

export function parseMonsterStats(hit: SearchHit): ParsedMonsterStats {
  const text = hit.chunk.text.replace(/\s+/g, " ").trim();
  const abilityScores: Record<string, number> = {};
  const abilities = [
    ["strength", "力量"], ["dexterity", "敏捷"], ["constitution", "体质"],
    ["intelligence", "智力"], ["wisdom", "感知"], ["charisma", "魅力"],
  ] as const;
  for (const [key, label] of abilities) {
    abilityScores[key] = numberAfter(text, new RegExp(`${label}\\s*(\\d{1,2})(?:\\s|（|\\()`), 10);
  }
  const challengeRating = text.match(/(?:\bCR|挑战等级)[：:]?\s*([0-9]+(?:\/[0-9]+)?)/i)?.[1] ?? "1/4";
  return {
    name: hit.chunk.name,
    armorClass: numberAfter(text, /(?:\bAC|护甲等级)[：:]?\s*(\d+)/i, 12),
    hp: numberAfter(text, /(?:\bHP|生命值)[：:]?\s*(\d+)/i, 8),
    speed: numberAfter(text, /速度[：:]?\s*(\d+)\s*尺?/i, 30),
    challengeRating,
    abilityScores,
    description: text.slice(0, 900),
  };
}

function terms(text: string): string[] {
  return [...new Set(
    text.toLowerCase().match(/[\p{Script=Han}]{2,}|[a-z]{3,}/gu) ?? [],
  )];
}

function lexicalScore(query: string, candidate: string): number {
  const queryTerms = terms(query);
  if (queryTerms.length === 0) return 0;
  const normalized = candidate.toLowerCase();
  return queryTerms.filter((term) => normalized.includes(term)).length / queryTerms.length;
}

export function campaignMonsterCandidates(
  monsters: Monster[],
  query: string,
): MonsterReferenceCandidate[] {
  return monsters
    .map((monster) => ({
      monster,
      score: lexicalScore(query, `${monster.name} ${monster.source_name ?? ""} ${monster.notes ?? ""}`),
    }))
    .filter(({ score }) => score > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, 3)
    .map(({ monster, score }) => ({
      key: `campaign:${monster.id}`,
      origin: "campaign" as const,
      label: monster.name,
      sourceLabel: monster.source_name || "战役怪物原子",
      matchReason: `已有原子 · 场景关键词匹配 ${Math.round(score * 100)}%`,
      monster,
    }));
}

export function compendiumMonsterCandidates(hits: SearchHit[]): MonsterReferenceCandidate[] {
  const seen = new Set<string>();
  return hits.flatMap((hit) => {
    if (seen.has(hit.chunk.record_id)) return [];
    seen.add(hit.chunk.record_id);
    const stats = parseMonsterStats(hit);
    return [{
      key: `compendium:${hit.chunk.record_id}`,
      origin: "compendium" as const,
      label: hit.chunk.name,
      sourceLabel: `${hit.chunk.source_book ?? hit.chunk.source_title} · ${hit.chunk.edition} · ${hit.chunk.officiality === "official" ? "官方" : "来源待复核"}`,
      matchReason: `本地图鉴语义匹配 ${Math.round(hit.score * 100)}% · CR ${stats.challengeRating}`,
      hit,
      stats,
    }];
  });
}

export function monsterDraftFromCandidate(
  candidate: MonsterReferenceCandidate,
  prompt: string,
): ArrivalDraft {
  if (candidate.origin === "campaign") {
    return {
      kind: "monster", prompt, sourceKey: candidate.key,
      name: candidate.monster.name,
      description: candidate.monster.notes ?? `复用已有怪物原子：${candidate.monster.name}`,
      armorClass: candidate.monster.armor_class,
      hp: candidate.monster.max_hp,
      speed: candidate.monster.speed,
      challengeRating: candidate.monster.challenge_rating ?? "1/4",
    };
  }
  return {
    kind: "monster", prompt, sourceKey: candidate.key,
    name: candidate.stats.name,
    description: candidate.stats.description,
    armorClass: candidate.stats.armorClass,
    hp: candidate.stats.hp,
    speed: candidate.stats.speed,
    challengeRating: candidate.stats.challengeRating,
  };
}

export function customMonsterDraft(prompt: string): ArrivalDraft {
  return {
    kind: "monster", prompt, sourceKey: "custom",
    name: "待命名的自制怪物",
    description: prompt,
    armorClass: 12,
    hp: 8,
    speed: 30,
    challengeRating: "1/4",
  };
}

