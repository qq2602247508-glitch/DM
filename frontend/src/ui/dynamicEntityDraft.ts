import type { GeneratedAction, Monster, SearchHit } from "../api/types";

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
  actions: GeneratedAction[];
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
  templateSourceKey: string | null;
  abilityScores: Record<string, number>;
  actions: GeneratedAction[];
};

const ARRIVAL_PATTERN = /(?:来(?:了|到|袭)|出现|进入|闯入|突袭|袭击|赶到|现身|冒出|涌出|召唤|增援)/i;
const MONSTER_PATTERN = /(?:怪物|魔物|敌人|野兽|亡灵|恶魔|魔鬼|巨龙|地精|哥布林|兽人|妖精|异怪|构装|元素|邪魔|鼠群|鼠集群|老鼠|[\p{Script=Han}]{1,8}(?:魔|兽|怪|龙|蛛|鬼|妖|灵))/iu;
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

export function requestedMonsterName(text: string): string {
  const quoted = text.match(/[“「『"]([^”」』"]{2,24})[”」』"]/u)?.[1]?.trim();
  if (quoted) return quoted;
  const leading = text.match(
    /^\s*([\p{Script=Han}]{2,10}(?:魔|兽|怪|龙|蛛|鬼|妖|灵))(?=\s|$)/u,
  )?.[1];
  if (leading && !ARRIVAL_PATTERN.test(leading)) return leading;
  const afterArrival = text.match(
    /(?:出现|来了|来了一只|来了一个|现身|闯入|突袭|召唤|冒出|涌出)(?:了|一只|一个|一名|一头|一群|一些)?\s*([\p{Script=Han}A-Za-z· -]{2,20})/u,
  )?.[1]?.trim();
  const cleaned = afterArrival
    ?.replace(/(?:并|然后|而且|开始|正在|向|对|袭击|攻击|突袭).*$/u, "")
    .trim();
  if (cleaned) return cleaned;
  return text.match(/(鼠集群|鼠群|老鼠|[\p{Script=Han}]{2,10}(?:魔|兽|怪|龙|蛛|鬼|妖|灵))/u)?.[1]
    ?? "待命名的自制怪物";
}

function numberAfter(text: string, pattern: RegExp, fallback: number): number {
  const value = Number(text.match(pattern)?.[1]);
  return Number.isFinite(value) ? value : fallback;
}

const ABILITY_KEYS: Record<string, string> = {
  力量: "strength",
  敏捷: "dexterity",
  体质: "constitution",
  智力: "intelligence",
  感知: "wisdom",
  魅力: "charisma",
};

function actionName(line: string): string {
  const beforePeriod = line.split(/[。.]/, 1)[0]?.trim() ?? "";
  const chinese = beforePeriod.match(/^([\p{Script=Han}·：:（）()0-9~～-]{2,30})/u)?.[1];
  return chinese?.replace(/[（(].*$/u, "").trim() || beforePeriod.slice(0, 30) || "未命名动作";
}

function actionDamage(line: string): string | undefined {
  return line.match(/[（(]\s*(\d+d\d+(?:\s*[+-]\s*\d+)?)\s*[）)]\s*(?:点)?[^。]*?伤害/i)?.[1]
    ?.replace(/\s+/g, "")
    ?? line.match(/(\d+d\d+(?:\s*[+-]\s*\d+)?)\s*点[^。]*?伤害/i)?.[1]
      ?.replace(/\s+/g, "");
}

function actionDamageType(line: string): string | undefined {
  return ["挥砍", "穿刺", "钝击", "火焰", "寒冷", "闪电", "毒素", "强酸", "黯蚀", "光耀", "心灵", "力场", "雷鸣"]
    .find((type) => line.includes(`${type}伤害`));
}

export function parseMonsterActions(text: string): GeneratedAction[] {
  const normalized = text
    .replace(/\r/g, "")
    .replace(/[ \t]+/g, " ")
    .replace(/\n(?=[A-Za-z])/g, " ");
  const actionSection = normalized.match(/(?:^|\n)动作(?:Actions)?\s*\n([\s\S]*?)(?=\n(?:附赠动作|反应|传奇动作|巢穴动作|施法|EndFragment)\b|$)/u)?.[1]
    ?? normalized;
  const lines = actionSection.split("\n").map((line) => line.trim()).filter(Boolean);
  return lines
    .filter((line) => (
      /(?:武器攻击|法术攻击|命中\s*\+|豁免|伤害|多重攻击|充能)/u.test(line)
      && !/^(?:护甲等级|生命值|速度|力量|敏捷|体质|智力|感知|魅力|挑战等级)/u.test(line)
    ))
    .slice(0, 12)
    .map((line): GeneratedAction => {
      const save = line.match(/DC\s*(\d+)\s*的?\s*(力量|敏捷|体质|智力|感知|魅力)\s*豁免/iu);
      const leadingSave = line.match(/(力量|敏捷|体质|智力|感知|魅力)\s*豁免(?:检定)?[：:]?\s*DC\s*(\d+)/iu);
      const range = line.match(/触及\s*(\d+)\s*尺/iu)?.[1]
        ?? line.match(/(?:覆盖(?:一处)?|长)\s*(\d+)\s*尺(?:的)?\s*(?:锥状|线状|范围)?/iu)?.[1]
        ?? line.match(/(\d+)\s*尺(?:锥形|锥状|直线|线状)/iu)?.[1]
        ?? line.match(/射程\s*(\d+)\s*尺/iu)?.[1];
      const shape = /锥状|锥形/u.test(line) ? "锥形" : /线状|直线/u.test(line) ? "直线" : "";
      return {
        name: actionName(line),
        description: line.slice(0, 900),
        damage: actionDamage(line),
        damage_type: actionDamageType(line),
        range: range ? `${range}尺${shape}` : "5尺",
        cost: "动作",
        attack_bonus: Number(
          line.match(/(?:命中|攻击检定[：:]?)\s*\+\s*(\d+)/iu)?.[1],
        ) || undefined,
        save_dc: save ? Number(save[1]) : leadingSave ? Number(leadingSave[2]) : undefined,
        save_ability: save?.[2]
          ? ABILITY_KEYS[save[2]]
          : leadingSave?.[1]
            ? ABILITY_KEYS[leadingSave[1]]
            : undefined,
        half_damage_on_save: /豁免成功.*(?:减半|一半)|成功则伤害减半|成功[：:].*(?:半伤|减半)/u.test(line),
        auto_eligible: !/(?:正受擒|被[^。]{0,20}擒抱|陷入失能)/u.test(line),
        recharge: line.match(/充能\s*([0-9~～\-–—]+)/u)?.[1],
      };
    });
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
    actions: parseMonsterActions(hit.chunk.text),
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

function compactName(text: string): string {
  return text.toLowerCase().replace(/[^\p{Script=Han}a-z0-9]/gu, "");
}

function editDistance(left: string, right: string): number {
  const a = [...left];
  const b = [...right];
  const row = Array.from({ length: b.length + 1 }, (_, index) => index);
  for (let i = 1; i <= a.length; i += 1) {
    let previous = row[0] ?? 0;
    row[0] = i;
    for (let j = 1; j <= b.length; j += 1) {
      const old = row[j] ?? 0;
      row[j] = Math.min(
        (row[j] ?? 0) + 1,
        (row[j - 1] ?? 0) + 1,
        previous + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
      previous = old;
    }
  }
  return row[b.length] ?? Math.max(a.length, b.length);
}

function fuzzyNameScore(query: string, names: string[]): number {
  const compactQuery = compactName(requestedMonsterName(query));
  if (!compactQuery) return 0;
  return Math.max(...names.map((name) => {
    const compactCandidate = compactName(name);
    if (!compactCandidate) return 0;
    if (compactCandidate.includes(compactQuery) || compactQuery.includes(compactCandidate)) return 1;
    const distance = editDistance(compactQuery, compactCandidate);
    return Math.max(0, 1 - distance / Math.max(compactQuery.length, compactCandidate.length));
  }));
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

export function compendiumMonsterCandidates(
  hits: SearchHit[],
  query = "",
): MonsterReferenceCandidate[] {
  const seen = new Set<string>();
  return hits.flatMap((hit) => {
    if (seen.has(hit.chunk.record_id)) return [];
    seen.add(hit.chunk.record_id);
    const stats = parseMonsterStats(hit);
    const fuzzyScore = fuzzyNameScore(query, [hit.chunk.name, ...hit.chunk.aliases]);
    return [{
      key: `compendium:${hit.chunk.record_id}`,
      origin: "compendium" as const,
      label: hit.chunk.name,
      sourceLabel: `${hit.chunk.source_book ?? hit.chunk.source_title} · ${hit.chunk.edition} · ${hit.chunk.officiality === "official" ? "官方" : "来源待复核"}`,
      matchReason: `${fuzzyScore >= 0.5 ? `名称模糊匹配 ${Math.round(fuzzyScore * 100)}% · ` : ""}本地图鉴语义匹配 ${Math.round(hit.score * 100)}% · CR ${stats.challengeRating}`,
      hit,
      stats,
      fuzzyScore,
    }];
  }).sort((left, right) => (
    right.fuzzyScore - left.fuzzyScore
    || Number(right.stats.actions.length > 0) - Number(left.stats.actions.length > 0)
    || right.hit.score - left.hit.score
  )).map((ranked) => {
    const candidate = { ...ranked };
    delete (candidate as Partial<typeof candidate>).fuzzyScore;
    return candidate;
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
      templateSourceKey: candidate.key,
      abilityScores: candidate.monster.ability_scores,
      actions: candidate.monster.actions,
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
    templateSourceKey: candidate.key,
    abilityScores: candidate.stats.abilityScores,
    actions: candidate.stats.actions,
  };
}

export function customMonsterDraft(
  prompt: string,
  template?: MonsterReferenceCandidate,
): ArrivalDraft {
  const templateDraft = template ? monsterDraftFromCandidate(template, prompt) : null;
  return {
    kind: "monster", prompt, sourceKey: "custom",
    name: requestedMonsterName(prompt),
    description: templateDraft
      ? `${prompt}\n规则模板绑定：${template?.label ?? "已选怪物"}。外观、名称与叙事保持自定义，战斗数值和动作参考该模板。`
      : prompt,
    armorClass: templateDraft?.armorClass ?? 12,
    hp: templateDraft?.hp ?? 8,
    speed: templateDraft?.speed ?? 30,
    challengeRating: templateDraft?.challengeRating ?? "1/4",
    templateSourceKey: template?.key ?? null,
    abilityScores: templateDraft?.abilityScores ?? {
      strength: 10, dexterity: 10, constitution: 10,
      intelligence: 8, wisdom: 10, charisma: 8,
    },
    actions: templateDraft?.actions ?? [{
      name: "基础攻击",
      description: "自定义怪物的临时近战攻击；DM确认模板后应替换为对应动作。",
      damage: "1d6",
      range: "5尺",
      cost: "动作",
    }],
  };
}
