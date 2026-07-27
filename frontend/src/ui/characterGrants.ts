import type {
  Character,
  CharacterOptionsCatalog,
  RuleDocument,
  SpellOption,
} from "../api/types";
import { BACKGROUNDS_2024, classSkillSelection } from "./characterRules";

export type CharacterGrantKind =
  | "equipment"
  | "item"
  | "spell"
  | "class_feature"
  | "skill_proficiency"
  | "skill_expertise";

export type CharacterGrantIntent = {
  characterId: string;
  characterName: string;
  kind: CharacterGrantKind;
  prompt: string;
  requestedName: string;
  quantity: number;
};

export type CharacterGrantDraft = CharacterGrantIntent & {
  candidateName: string;
  eligible: boolean;
  blockingReason: string | null;
  ruleReason: string;
  sourceRecordId: string | null;
  sourceLabel: string;
  sourcePath: string | null;
  canonicalUrl: string | null;
  edition: string;
  officiality: string;
  description: string;
  metadata: Record<string, unknown>;
};

const CLASS_ALIASES: Record<string, string> = {
  邪术师: "魔契师",
  术士: "术士",
};

function canonicalClassName(value: string | null): string {
  const name = (value ?? "").trim();
  return CLASS_ALIASES[name] ?? name;
}

function characterClassLevel(character: Character, className: string): number {
  const canonical = canonicalClassName(className);
  const entry = Object.entries(character.class_levels).find(
    ([name]) => canonicalClassName(name) === canonical,
  );
  if (entry) return entry[1];
  return canonicalClassName(character.class_name) === canonical ? character.level : 0;
}

function objectName(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && "name" in value) {
    const name = (value as { name?: unknown }).name;
    return typeof name === "string" || typeof name === "number" ? String(name) : "";
  }
  return "";
}

function parseQuantity(text: string): number {
  const arabic = text.match(/(?:给|奖励|添加|授予|获得)[^，。]{0,30}?(\d+)\s*(?:个|件|把|瓶|枚|本|套|支|张)/u);
  if (arabic) return Math.max(1, Number(arabic[1]));
  const chinese = text.match(/([一二三四五六七八九十两])\s*(?:个|件|把|瓶|枚|本|套|支|张)/u)?.[1];
  const values: Record<string, number> = {
    一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5,
    六: 6, 七: 7, 八: 8, 九: 9, 十: 10,
  };
  return chinese ? values[chinese] ?? 1 : 1;
}

function requestedName(text: string, characterName: string): string {
  let value = text.replace(characterName, " ");
  const noise = [
    /^(?:请|现在|然后|这时|DM)?\s*(?:给|奖励|授予|让|使)\s*/u,
    /(?:添加到|加入到|放进|装进).*(?:背包|角色卡|法术书).*$/u,
    /(?:抄入|写入).*(?:法术书).*$/u,
    /(?:给|奖励|授予|让|使|添加|加入|获得|学会|学习|装备|拥有|把|将|补齐|解锁)/gu,
    /(?:当前等级|应有的|合法的|一个|一件|一把|一瓶|一枚|一本|一套|一支|一张|\d+\s*(?:个|件|把|瓶|枚|本|套|支|张))/gu,
    /(?:法术|技能熟练|技能|职业特性|职业能力|特性|装备|道具)\s*[:：]?/gu,
  ];
  for (const pattern of noise) value = value.replace(pattern, " ");
  return value
    .replace(/[“”"'，。；;！!]/g, " ")
    .replace(/^\s*[一二三四五六七八九十两]\s+/u, "")
    .replace(/\s+/g, " ")
    .trim();
}

function detectKind(text: string): CharacterGrantKind {
  if (/专精/u.test(text)) return "skill_expertise";
  if (/熟练|技能熟练/u.test(text)) return "skill_proficiency";
  if (/抄入|法术书|(?:学会|学习|添加|获得).*(?:术|咒|法术)|戏法|法术/u.test(text)) return "spell";
  if (/职业特性|职业能力|技能|特性|能力/u.test(text)) return "class_feature";
  if (/道具|药水|毒药|卷轴|消耗品|材料包/u.test(text)) return "item";
  return "equipment";
}

const SKILL_ALIASES: Record<string, string> = {
  潜行: "隐匿",
};

function canonicalSkillName(value: string): string {
  const name = value.trim();
  return SKILL_ALIASES[name] ?? name;
}

function primaryClassName(character: Character): string {
  const explicit = (character.class_name ?? "")
    .split("/")[0]
    ?.replace(/\d+/g, "")
    .trim();
  if (explicit) return canonicalClassName(explicit);
  return canonicalClassName(Object.keys(character.class_levels)[0] ?? "");
}

function skillSetting(character: Character, skillName: string): Record<string, unknown> {
  const canonical = canonicalSkillName(skillName);
  const entry = Object.entries(character.skills).find(
    ([name]) => canonicalSkillName(name) === canonical,
  );
  return entry && entry[1] && typeof entry[1] === "object"
    ? entry[1] as Record<string, unknown>
    : {};
}

function proficientSkillNames(character: Character): string[] {
  return Object.entries(character.skills)
    .filter(([, value]) => (
      value === true
      || (value && typeof value === "object" && (value as { proficient?: unknown }).proficient === true)
    ))
    .map(([name]) => canonicalSkillName(name));
}

function expertiseEntitlement(character: Character, catalog: CharacterOptionsCatalog): number {
  return catalog.classes.reduce((total, rule) => {
    const level = characterClassLevel(character, rule.name);
    if (level < 1) return total;
    const grants = rule.levels
      .filter((entry) => entry.level <= level)
      .flatMap((entry) => entry.features)
      .filter((name) => name.includes("专精")).length;
    return total + grants * 2;
  }, 0);
}

export function buildSkillGrantDraft(
  intent: CharacterGrantIntent,
  character: Character,
  catalog: CharacterOptionsCatalog,
): CharacterGrantDraft {
  const requested = canonicalSkillName(intent.requestedName.replace(/专精|熟练|技能/g, "").trim());
  const officialSkill = catalog.skills.find((name) => canonicalSkillName(name) === requested);
  const setting = skillSetting(character, requested);
  const alreadyProficient = setting.proficient === true || setting.expertise === true;
  const alreadyExpert = setting.expertise === true;
  const primaryClass = primaryClassName(character);
  const background = BACKGROUNDS_2024.find((item) => item.name === character.background);
  const backgroundSkills = (background?.skills ?? []).map(canonicalSkillName);
  const skillRuleClass = primaryClass === "魔契师" ? "邪术师" : primaryClass;
  const classSelection = classSkillSelection(skillRuleClass, backgroundSkills);
  const proficient = proficientSkillNames(character);
  const usedClassChoices = proficient.filter(
    (name) => classSelection.choices.map(canonicalSkillName).includes(name)
      && !backgroundSkills.includes(name),
  ).length;
  const classRule = catalog.classes.find(
    (item) => canonicalClassName(item.name) === primaryClass,
  );
  let eligible = false;
  let blockingReason: string | null = null;
  let ruleReason = "";
  let sourceLabel = "玩家手册 2024 · 技能规则";
  let sourceRecordId: string | null = null;
  let sourcePath: string | null = null;
  if (!officialSkill) {
    blockingReason = `“${intent.requestedName}”不是 D&D 5e 2024 的标准技能。`;
  } else if (intent.kind === "skill_expertise") {
    const entitlement = expertiseEntitlement(character, catalog);
    const usedExpertise = Object.values(character.skills).filter(
      (value) => value && typeof value === "object"
        && (value as { expertise?: unknown }).expertise === true,
    ).length;
    if (!alreadyProficient) {
      blockingReason = `${requested}尚未熟练，不能直接获得专精。`;
    } else if (alreadyExpert) {
      blockingReason = `${character.name}已经拥有${requested}专精。`;
    } else if (usedExpertise >= entitlement) {
      blockingReason = `角色职业等级只提供${entitlement}个专精选择，当前已经全部使用。`;
    } else {
      eligible = true;
      ruleReason = `角色职业成长共提供${entitlement}个专精选择，当前已用${usedExpertise}个；本次补齐剩余选择。`;
      sourceLabel = "玩家手册 2024 · 职业专精";
    }
  } else if (alreadyProficient) {
    blockingReason = `${character.name}已经拥有${requested}熟练。`;
  } else if (backgroundSkills.includes(requested)) {
    eligible = true;
    ruleReason = `${character.background}背景固定授予${requested}熟练；本次只补齐角色卡缺失数据。`;
    const backgroundRule = catalog.backgrounds.find((item) => item.name === character.background);
    sourceLabel = `玩家手册 2024 · ${character.background}背景`;
    sourceRecordId = backgroundRule?.source_record_id ?? null;
    sourcePath = backgroundRule?.source_path ?? null;
  } else if (
    classSelection.choices.map(canonicalSkillName).includes(requested)
    && usedClassChoices < classSelection.count
  ) {
    eligible = true;
    ruleReason = `${primaryClass}应选择${classSelection.count}项职业技能熟练，当前仅记录${usedClassChoices}项；本次补齐一个合法空缺。`;
    sourceLabel = `玩家手册 2024 · ${primaryClass}职业技能`;
    sourceRecordId = classRule?.source_record_id ?? null;
    sourcePath = classRule?.source_path ?? null;
  } else if (!classSelection.choices.map(canonicalSkillName).includes(requested)) {
    blockingReason = `${requested}不在${primaryClass}的职业技能选择列表中，且不是${character.background ?? "当前"}背景固定技能。`;
  } else {
    blockingReason = `${primaryClass}的${classSelection.count}个职业技能选择已经全部使用；额外熟练必须来自明确的专长或升级选择。`;
  }
  return {
    ...intent,
    requestedName: requested,
    candidateName: requested,
    eligible,
    blockingReason,
    ruleReason: ruleReason || "没有可用于本次技能变化的合法规则额度。",
    sourceRecordId,
    sourceLabel,
    sourcePath,
    canonicalUrl: null,
    edition: "2024",
    officiality: officialSkill ? "official" : "unknown",
    description: eligible
      ? `${requested}检定使用对应属性调整值；熟练时加入熟练加值，专精时熟练加值翻倍。`
      : "",
    metadata: {
      skill_name: requested,
      expertise: intent.kind === "skill_expertise",
      primary_class: primaryClass,
      used_class_choices: usedClassChoices,
      class_choice_limit: classSelection.count,
    },
  };
}

export function detectCharacterGrantIntent(
  text: string,
  characters: Character[],
): CharacterGrantIntent | null {
  if (!/(?:给|奖励|授予|让|使|添加|加入|获得|学会|学习|装备|拥有|补齐|解锁)/u.test(text)) {
    return null;
  }
  const character = [...characters]
    .sort((left, right) => right.name.length - left.name.length)
    .find((item) => text.includes(item.name))
    ?? (characters.length === 1 && /玩家|角色/u.test(text) ? characters[0] : undefined);
  if (!character) return null;
  const name = requestedName(text, character.name);
  if (!name) return null;
  return {
    characterId: character.id,
    characterName: character.name,
    kind: detectKind(text),
    prompt: text,
    requestedName: name,
    quantity: parseQuantity(text),
  };
}

function wizardMaximumSpellLevel(level: number): number {
  if (level < 1) return 0;
  if (level < 3) return 1;
  if (level < 5) return 2;
  if (level < 7) return 3;
  if (level < 9) return 4;
  if (level < 11) return 5;
  if (level < 13) return 6;
  if (level < 15) return 7;
  if (level < 17) return 8;
  return 9;
}

function sameLooseName(left: string, right: string): boolean {
  const compact = (value: string) => value.toLowerCase().replace(/[^\p{Script=Han}a-z0-9]/gu, "");
  const a = compact(left);
  const b = compact(right);
  return Boolean(a && b && (a === b || a.includes(b) || b.includes(a)));
}

function findSpell(intent: CharacterGrantIntent, catalog: CharacterOptionsCatalog): SpellOption | null {
  return catalog.spells.find((spell) => sameLooseName(spell.name, intent.requestedName)) ?? null;
}

export function buildSpellGrantDraft(
  intent: CharacterGrantIntent,
  character: Character,
  catalog: CharacterOptionsCatalog,
): CharacterGrantDraft {
  const spell = findSpell(intent, catalog);
  const className = "法师";
  const classLevel = characterClassLevel(character, className);
  const existing = character.spells.map(objectName);
  let blockingReason: string | null = null;
  if (!spell) blockingReason = `“${intent.requestedName}”不在本地 D&D 5e 2024 官方法术目录中。`;
  else if (classLevel < 1) {
    blockingReason = "DM 不能绕过职业成长直接增加已知/准备法术；目前仅允许法师抄写合法的有环法师法术。";
  } else if (!spell.classes.map(canonicalClassName).includes("法师")) {
    blockingReason = `${spell.name}不属于法师法术表。`;
  } else if (spell.level === 0) {
    blockingReason = "戏法数量由职业等级与升级选择决定，不能通过 DM 执行指令额外添加。";
  } else if (spell.level > wizardMaximumSpellLevel(classLevel)) {
    blockingReason = `法师${classLevel}级最高可用${wizardMaximumSpellLevel(classLevel)}环法术，不能抄写${spell.level}环的${spell.name}。`;
  } else if (existing.some((name) => sameLooseName(name, spell.name))) {
    blockingReason = `${character.name}已经拥有${spell.name}。`;
  }
  return {
    ...intent,
    candidateName: spell?.name ?? intent.requestedName,
    eligible: !blockingReason,
    blockingReason,
    ruleReason: spell
      ? `官方 2024 ${spell.level}环${spell.school ?? ""}法术；法师抄写后进入法术书，默认不准备，也不会绕过准备数量限制。`
      : "未找到可验证的官方法术条目。",
    sourceRecordId: spell?.source_record_id ?? null,
    sourceLabel: spell ? "玩家手册 2024 · 官方法术目录" : "无可靠来源",
    sourcePath: spell?.source_path ?? null,
    canonicalUrl: null,
    edition: "2024",
    officiality: spell ? "official" : "unknown",
    description: spell?.description ?? "",
    metadata: spell ? {
      character_spell: { ...spell, spell_level: spell.level, class_name: "法师", prepared: false },
      spell_level: spell.level,
      prepared: false,
      classes: spell.classes,
    } : {},
  };
}

export function buildFeatureGrantDraft(
  intent: CharacterGrantIntent,
  character: Character,
  catalog: CharacterOptionsCatalog,
): CharacterGrantDraft {
  const classCandidates = catalog.classes
    .map((rule) => ({
      rule,
      level: characterClassLevel(character, rule.name),
    }))
    .filter((item) => item.level > 0);
  const matched = classCandidates
    .flatMap(({ rule, level }) => rule.levels
      .filter((entry) => entry.level <= level)
      .flatMap((entry) => entry.features.map((name) => ({
        name,
        level: entry.level,
        classLevel: level,
        rule,
      }))))
    .find((item) => sameLooseName(item.name, intent.requestedName));
  const fallback = classCandidates[0];
  const classRule = matched?.rule ?? fallback?.rule;
  const className = classRule?.name ?? canonicalClassName(character.class_name);
  const classLevel = matched?.classLevel ?? fallback?.level ?? character.level;
  const feature = matched;
  const existing = character.features.map(objectName);
  let blockingReason: string | null = null;
  if (!classRule) blockingReason = "角色职业不在本地 2024 官方职业成长库中。";
  else if (!feature) blockingReason = `“${intent.requestedName}”不是${className}${classLevel}级以内应获得的职业特性。`;
  else if (existing.some((name) => sameLooseName(name, feature.name))) {
    blockingReason = `${character.name}已经拥有${feature.name}。`;
  }
  return {
    ...intent,
    candidateName: feature?.name ?? intent.requestedName,
    eligible: !blockingReason,
    blockingReason,
    ruleReason: feature
      ? `${className}${feature.level}级官方职业特性；仅补齐角色当前等级本应拥有但数据中缺失的条目。`
      : "没有符合当前职业与等级的官方特性。",
    sourceRecordId: classRule?.source_record_id ?? null,
    sourceLabel: classRule ? `玩家手册 2024 · ${className}` : "无可靠来源",
    sourcePath: classRule?.source_path ?? null,
    canonicalUrl: null,
    edition: "2024",
    officiality: classRule ? "official" : "unknown",
    description: "",
    metadata: feature ? { class_name: className, class_level: feature.level } : {},
  };
}

function parsePriceCopper(text: string): number | null {
  const match = text.match(/(\d+(?:\.\d+)?)\s*(CP|SP|EP|GP|PP|铜币|银币|金币|铂金币)/iu);
  if (!match) return null;
  const multipliers: Record<string, number> = {
    cp: 1, 铜币: 1, sp: 10, 银币: 10, ep: 50, gp: 100, 金币: 100, pp: 1000, 铂金币: 1000,
  };
  const amount = match[1] ?? "0";
  const unit = match[2] ?? "cp";
  return Math.round(Number(amount) * (multipliers[unit.toLowerCase()] ?? multipliers[unit] ?? 1));
}

function parseWeight(text: string): number | null {
  if (/半磅/u.test(text)) return 0.5;
  const fraction = text.match(/(\d+)\s*\/\s*(\d+)\s*磅/u);
  if (fraction) return Number(fraction[1]) / Number(fraction[2]);
  const match = text.match(/(\d+(?:\.\d+)?)\s*磅/u);
  return match ? Number(match[1]) : null;
}

function relevantExcerpt(text: string, name: string): string {
  const lines = text.split(/\r?\n/);
  const matchingLine = lines.findIndex((line) => line.includes(name));
  if (matchingLine >= 0) {
    const line = lines[matchingLine]?.trim() ?? "";
    if (line.startsWith("|")) return line;
    return lines.slice(matchingLine, matchingLine + 10).join("\n").slice(0, 900).trim();
  }
  const index = text.indexOf(name);
  if (index < 0) return text.slice(0, 700);
  return text.slice(Math.max(0, index - 80), Math.min(text.length, index + name.length + 620)).trim();
}

export function buildItemGrantDraft(
  intent: CharacterGrantIntent,
  document: RuleDocument | null,
): CharacterGrantDraft {
  const excerpt = document
    ? relevantExcerpt(document.content_markdown || document.content_plain_text, intent.requestedName)
    : "";
  const exact = Boolean(document && sameLooseName(excerpt, intent.requestedName));
  const official2024 = document?.officiality === "official" && document.edition === "2024";
  const blockingReason = !document
    ? `没有找到“${intent.requestedName}”的本地规则条目。`
    : !official2024
      ? "匹配条目不是 D&D 5e 2024 官方内容，已阻止写入。"
      : !exact
        ? `规则文档没有明确列出“${intent.requestedName}”，不能用相似页面代替具体物品。`
        : null;
  const requestedIndex = excerpt.indexOf(intent.requestedName);
  const mechanicsText = requestedIndex >= 0 ? excerpt.slice(requestedIndex) : excerpt;
  const priceCp = parsePriceCopper(mechanicsText);
  const weightLb = parseWeight(mechanicsText);
  const documentContext = `${document?.name ?? ""} ${document?.source_relative_path ?? ""} ${excerpt}`;
  const category = intent.kind === "item"
    ? "item"
    : /护甲|盾牌/u.test(documentContext) ? "armor"
      : /武器|伤害|近战|远程/u.test(documentContext) ? "weapon" : "gear";
  return {
    ...intent,
    candidateName: intent.requestedName,
    eligible: !blockingReason,
    blockingReason,
    ruleReason: blockingReason
      ? "只有本地 2024 官方规则库中可明确定位的物品才能授予。"
      : "已从本地 D&D 5e 2024 官方装备/物品文档中定位；规则字段不可由模型改写。",
    sourceRecordId: document?.stable_id ?? null,
    sourceLabel: document ? `${document.source_book ?? document.name} · ${document.name}` : "无可靠来源",
    sourcePath: document?.source_relative_path ?? null,
    canonicalUrl: document?.canonical_url ?? null,
    edition: document?.edition ?? "unknown",
    officiality: document?.officiality ?? "unknown",
    description: excerpt,
    metadata: {
      category,
      unit_weight_lb: weightLb,
      price_cp: priceCp,
      attunement_required: /需同调/u.test(excerpt),
      source_record_id: document?.stable_id ?? null,
      canonical_url: document?.canonical_url ?? null,
      edition: document?.edition ?? "unknown",
      officiality: document?.officiality ?? "unknown",
      description: excerpt,
    },
  };
}
