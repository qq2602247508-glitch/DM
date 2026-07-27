export type SpeciesRule = {
  name: string;
  speed: number;
  size: string;
  features: string[];
};

export type BackgroundRule = {
  name: string;
  skills: string[];
  feat: string;
  equipment: string[];
};

export type ClassRule = {
  name: string;
  hitDie: number;
  primary: string;
  saves: string[];
  proficiencies: string[];
  defaultSkills: string[];
  equipment: string[];
  actions: { name: string; description: string; damage?: string; range?: string; cost: string; resource?: string }[];
  resources: Record<string, { label: string; current: number; max: number; recovery: "short_rest" | "long_rest" }>;
  spellcasting?: { ability: string; mode: "slots"; level1Slots: number };
};

export type SpellSelectionRule = {
  cantrips: number;
  leveled: number;
  leveledLabel: string;
  preparedLeveled?: number;
};

export const SKILLS_2024 = [
  "杂技", "驯兽", "奥秘", "运动", "欺瞒", "历史", "洞悉", "威吓", "调查",
  "医药", "自然", "察觉", "表演", "游说", "宗教", "巧手", "隐匿", "生存",
] as const;

const CLASS_SKILL_SELECTION: Record<string, { count: number; choices: readonly string[] }> = {
  野蛮人: { count: 2, choices: ["驯兽", "运动", "威吓", "自然", "察觉", "生存"] },
  吟游诗人: { count: 3, choices: SKILLS_2024 },
  牧师: { count: 2, choices: ["历史", "洞悉", "医药", "游说", "宗教"] },
  德鲁伊: { count: 2, choices: ["驯兽", "奥秘", "洞悉", "医药", "自然", "察觉", "宗教", "生存"] },
  战士: { count: 2, choices: ["杂技", "驯兽", "运动", "历史", "洞悉", "威吓", "察觉", "游说", "生存"] },
  武僧: { count: 2, choices: ["杂技", "运动", "历史", "洞悉", "宗教", "隐匿"] },
  圣武士: { count: 2, choices: ["运动", "洞悉", "威吓", "医药", "游说", "宗教"] },
  游侠: { count: 3, choices: ["驯兽", "运动", "洞悉", "调查", "自然", "察觉", "隐匿", "生存"] },
  游荡者: { count: 4, choices: ["杂技", "运动", "欺瞒", "洞悉", "威吓", "调查", "察觉", "游说", "巧手", "隐匿"] },
  术士: { count: 2, choices: ["奥秘", "欺瞒", "洞悉", "威吓", "游说", "宗教"] },
  邪术师: { count: 2, choices: ["奥秘", "欺瞒", "历史", "威吓", "调查", "自然", "宗教"] },
  法师: { count: 2, choices: ["奥秘", "历史", "洞悉", "调查", "医药", "自然", "宗教"] },
};

const SPELL_SELECTION_2024: Record<string, SpellSelectionRule> = {
  吟游诗人: { cantrips: 2, leveled: 4, leveledLabel: "准备法术" },
  牧师: { cantrips: 3, leveled: 4, leveledLabel: "准备法术" },
  德鲁伊: { cantrips: 2, leveled: 4, leveledLabel: "准备法术" },
  圣武士: { cantrips: 0, leveled: 2, leveledLabel: "准备法术" },
  游侠: { cantrips: 0, leveled: 2, leveledLabel: "准备法术" },
  术士: { cantrips: 4, leveled: 2, leveledLabel: "准备法术" },
  邪术师: { cantrips: 2, leveled: 2, leveledLabel: "准备法术" },
  法师: { cantrips: 3, leveled: 6, leveledLabel: "法术书1环法术", preparedLeveled: 4 },
};

export function classSkillSelection(className: string, backgroundSkills: readonly string[] = []) {
  const rule = CLASS_SKILL_SELECTION[className] ?? { count: 0, choices: [] };
  return {
    count: rule.count,
    choices: rule.choices.filter((skill) => !backgroundSkills.includes(skill)),
  };
}

export function spellSelectionRule(className: string): SpellSelectionRule {
  return SPELL_SELECTION_2024[className] ?? { cantrips: 0, leveled: 0, leveledLabel: "1环法术" };
}

export function canonicalSpellClass(className: string): string {
  return className === "邪术师" ? "魔契师" : className;
}

export function spellIsAvailable(
  spell: { level: number; classes: string[] },
  className: string,
): boolean {
  return spell.level <= 1 && spell.classes.includes(canonicalSpellClass(className));
}

export function spellChoiceCounts(
  selectedIds: readonly string[],
  spells: readonly { source_record_id: string; level: number }[],
): { cantrips: number; leveled: number } {
  const selected = spells.filter((spell) => selectedIds.includes(spell.source_record_id));
  return {
    cantrips: selected.filter((spell) => spell.level === 0).length,
    leveled: selected.filter((spell) => spell.level === 1).length,
  };
}

export function spellChoicesComplete(
  className: string,
  selectedIds: readonly string[],
  spells: readonly { source_record_id: string; level: number }[],
): boolean {
  const limits = spellSelectionRule(className);
  const counts = spellChoiceCounts(selectedIds, spells);
  return counts.cantrips === limits.cantrips && counts.leveled === limits.leveled;
}

export function isPreparedCombatSpell(spell: unknown): boolean {
  if (typeof spell !== "object" || spell === null) return true;
  const record = spell as Record<string, unknown>;
  const level = Number(record.spell_level ?? 0);
  return level === 0 || record.prepared !== false;
}

export function spellToCharacterAction(
  spell: {
    name: string;
    source_record_id: string;
    source_path: string;
    level: number;
    classes: string[];
    school: string | null;
    casting_time: string | null;
    range: string | null;
    components: string | null;
    duration: string | null;
    concentration: boolean;
    ritual: boolean;
    damage_expression: string | null;
    damage_type: string | null;
    save_ability: string | null;
    half_damage_on_save: boolean;
    description: string;
    cost: string;
    resource_key: string | null;
    resource_cost: number;
    resolution_kind: "damage" | "narrative";
  },
  spellSaveDc: number,
  prepared = true,
): Record<string, unknown> {
  return {
    name: spell.name,
    source_record_id: spell.source_record_id,
    source_path: spell.source_path,
    spell_level: spell.level,
    prepared: spell.level === 0 || prepared,
    classes: spell.classes,
    school: spell.school,
    casting_time: spell.casting_time,
    range: spell.range,
    components: spell.components,
    duration: spell.duration,
    concentration: spell.concentration,
    ritual: spell.ritual,
    damage: spell.damage_expression,
    damage_type: spell.damage_type,
    save_ability: spell.save_ability,
    save_dc: spell.save_ability ? spellSaveDc : undefined,
    half_damage_on_save: spell.half_damage_on_save,
    description: spell.description,
    cost: spell.cost,
    resource_key: spell.resource_key ?? undefined,
    resource_cost: spell.resource_cost,
    resolution_kind: spell.resolution_kind,
  };
}

export const SPECIES_2024: SpeciesRule[] = [
  { name: "阿斯莫", speed: 30, size: "中型或小型", features: ["黑暗视觉", "天界抗性", "治疗之手", "天界显现"] },
  { name: "龙裔", speed: 30, size: "中型", features: ["龙族血统", "吐息武器", "伤害抗性", "黑暗视觉"] },
  { name: "矮人", speed: 30, size: "中型", features: ["黑暗视觉", "矮人韧性", "石中感知", "坚韧生命"] },
  { name: "精灵", speed: 30, size: "中型", features: ["黑暗视觉", "精类血统", "敏锐感官", "出神"] },
  { name: "侏儒", speed: 30, size: "小型", features: ["黑暗视觉", "侏儒狡黠", "侏儒血统"] },
  { name: "歌利亚", speed: 35, size: "中型", features: ["巨人血统", "大体格", "强力体格"] },
  { name: "半身人", speed: 30, size: "小型", features: ["勇敢", "半身人灵巧", "幸运", "天生隐匿"] },
  { name: "人类", speed: 30, size: "中型或小型", features: ["足智多谋", "技艺精通", "多才多艺"] },
  { name: "兽人", speed: 30, size: "中型", features: ["肾上腺素爆发", "黑暗视觉", "不屈耐力"] },
  { name: "提夫林", speed: 30, size: "中型或小型", features: ["黑暗视觉", "异界遗产", "异界风采"] },
];

export const BACKGROUNDS_2024: BackgroundRule[] = [
  { name: "侍僧", skills: ["洞悉", "宗教"], feat: "魔法学徒（牧师）", equipment: ["圣徽", "祈祷书", "长袍"] },
  { name: "工匠", skills: ["调查", "游说"], feat: "工匠", equipment: ["工匠工具", "旅行者服装"] },
  { name: "骗子", skills: ["欺瞒", "巧手"], feat: "熟练", equipment: ["伪装工具", "精美服装"] },
  { name: "罪犯", skills: ["巧手", "隐匿"], feat: "警觉", equipment: ["盗贼工具", "两把匕首"] },
  { name: "艺人", skills: ["杂技", "表演"], feat: "音乐家", equipment: ["乐器", "戏服"] },
  { name: "农夫", skills: ["驯兽", "自然"], feat: "健壮", equipment: ["镰刀", "治疗包"] },
  { name: "守卫", skills: ["运动", "察觉"], feat: "警觉", equipment: ["长矛", "轻弩"] },
  { name: "向导", skills: ["隐匿", "生存"], feat: "魔法学徒（德鲁伊）", equipment: ["短弓", "制图工具"] },
  { name: "隐士", skills: ["医药", "宗教"], feat: "治疗者", equipment: ["治疗包", "草药工具"] },
  { name: "商人", skills: ["驯兽", "游说"], feat: "幸运", equipment: ["导航工具", "旅行者服装"] },
  { name: "贵族", skills: ["历史", "游说"], feat: "熟练", equipment: ["精美服装", "游戏套组"] },
  { name: "学者", skills: ["奥秘", "历史"], feat: "魔法学徒（法师）", equipment: ["法杖", "书法工具"] },
  { name: "水手", skills: ["杂技", "察觉"], feat: "酒馆斗殴者", equipment: ["匕首", "导航工具"] },
  { name: "书记员", skills: ["调查", "察觉"], feat: "熟练", equipment: ["书法工具", "羊皮纸"] },
  { name: "士兵", skills: ["运动", "威吓"], feat: "凶蛮打手", equipment: ["长矛", "短弓"] },
  { name: "流浪者", skills: ["洞悉", "隐匿"], feat: "幸运", equipment: ["匕首", "盗贼工具"] },
];

export const CLASSES_2024: ClassRule[] = [
  { name: "野蛮人", hitDie: 12, primary: "力量", saves: ["力量", "体质"], proficiencies: ["轻甲", "中甲", "盾牌", "军用武器"], defaultSkills: ["运动", "生存"], equipment: ["巨斧", "四把手斧", "探索套组"], actions: [{ name: "巨斧", description: "近战武器攻击", damage: "1d12+力量 挥砍", range: "5尺", cost: "动作" }, { name: "狂暴", description: "进入狂暴并获得对应增益", cost: "附赠动作", resource: "rage" }], resources: { rage: { label: "狂暴", current: 2, max: 2, recovery: "long_rest" } } },
  { name: "吟游诗人", hitDie: 8, primary: "魅力", saves: ["敏捷", "魅力"], proficiencies: ["简易武器", "轻甲", "乐器"], defaultSkills: ["表演", "游说", "洞悉"], equipment: ["细剑", "乐器", "艺人套组"], actions: [{ name: "细剑", description: "灵巧近战攻击", damage: "1d8+敏捷 穿刺", range: "5尺", cost: "动作" }, { name: "吟游诗人激励", description: "给予盟友一枚激励骰", cost: "附赠动作", resource: "bardic_inspiration" }], resources: { bardic_inspiration: { label: "诗人激励", current: 2, max: 2, recovery: "long_rest" } }, spellcasting: { ability: "魅力", mode: "slots", level1Slots: 2 } },
  { name: "牧师", hitDie: 8, primary: "感知", saves: ["感知", "魅力"], proficiencies: ["轻甲", "中甲", "盾牌", "简易武器"], defaultSkills: ["洞悉", "宗教"], equipment: ["硬头锤", "鳞甲", "盾牌", "圣徽"], actions: [{ name: "硬头锤", description: "近战武器攻击", damage: "1d6+力量 钝击", range: "5尺", cost: "动作" }], resources: { channel_divinity: { label: "引导神力", current: 2, max: 2, recovery: "short_rest" } }, spellcasting: { ability: "感知", mode: "slots", level1Slots: 2 } },
  { name: "德鲁伊", hitDie: 8, primary: "感知", saves: ["智力", "感知"], proficiencies: ["轻甲", "盾牌", "简易武器", "草药工具"], defaultSkills: ["自然", "生存"], equipment: ["木盾", "短棍", "德鲁伊法器"], actions: [{ name: "短棍", description: "近战武器攻击", damage: "1d6+力量 钝击", range: "5尺", cost: "动作" }], resources: { wild_shape: { label: "荒野形态", current: 2, max: 2, recovery: "short_rest" } }, spellcasting: { ability: "感知", mode: "slots", level1Slots: 2 } },
  { name: "战士", hitDie: 10, primary: "力量或敏捷", saves: ["力量", "体质"], proficiencies: ["所有护甲", "盾牌", "简易武器", "军用武器"], defaultSkills: ["运动", "察觉"], equipment: ["长剑", "盾牌", "链甲", "轻弩"], actions: [{ name: "长剑", description: "近战武器攻击", damage: "1d8+力量 挥砍", range: "5尺", cost: "动作" }, { name: "第二风息", description: "恢复1d10+战士等级生命值", damage: "治疗1d10+1", range: "自身", cost: "附赠动作", resource: "second_wind" }], resources: { second_wind: { label: "第二风息", current: 2, max: 2, recovery: "short_rest" } } },
  { name: "武僧", hitDie: 8, primary: "敏捷与感知", saves: ["力量", "敏捷"], proficiencies: ["简易武器", "轻型军用武器"], defaultSkills: ["杂技", "洞悉"], equipment: ["短剑", "探索套组"], actions: [{ name: "徒手打击", description: "近战攻击", damage: "1d6+敏捷 钝击", range: "5尺", cost: "动作或附赠动作" }], resources: { focus: { label: "专注点", current: 1, max: 1, recovery: "short_rest" } } },
  { name: "圣武士", hitDie: 10, primary: "力量与魅力", saves: ["感知", "魅力"], proficiencies: ["所有护甲", "盾牌", "简易武器", "军用武器"], defaultSkills: ["运动", "游说"], equipment: ["长剑", "盾牌", "链甲", "圣徽"], actions: [{ name: "长剑", description: "近战武器攻击", damage: "1d8+力量 挥砍", range: "5尺", cost: "动作" }, { name: "圣疗", description: "从圣疗池恢复生命", range: "接触", cost: "附赠动作", resource: "lay_on_hands" }], resources: { lay_on_hands: { label: "圣疗池", current: 5, max: 5, recovery: "long_rest" } }, spellcasting: { ability: "魅力", mode: "slots", level1Slots: 2 } },
  { name: "游侠", hitDie: 10, primary: "敏捷与感知", saves: ["力量", "敏捷"], proficiencies: ["轻甲", "中甲", "盾牌", "军用武器"], defaultSkills: ["自然", "生存", "察觉"], equipment: ["长弓", "两把短剑", "探索套组"], actions: [{ name: "长弓", description: "远程武器攻击", damage: "1d8+敏捷 穿刺", range: "150/600尺", cost: "动作" }], resources: {}, spellcasting: { ability: "感知", mode: "slots", level1Slots: 2 } },
  { name: "游荡者", hitDie: 8, primary: "敏捷", saves: ["敏捷", "智力"], proficiencies: ["轻甲", "简易武器", "灵巧武器", "盗贼工具"], defaultSkills: ["隐匿", "巧手", "察觉", "调查"], equipment: ["细剑", "短弓", "盗贼工具"], actions: [{ name: "细剑", description: "灵巧近战攻击", damage: "1d8+敏捷 穿刺", range: "5尺", cost: "动作" }, { name: "偷袭", description: "满足条件时额外造成伤害", damage: "+1d6", range: "武器射程", cost: "每回合一次" }], resources: {} },
  { name: "术士", hitDie: 6, primary: "魅力", saves: ["体质", "魅力"], proficiencies: ["简易武器"], defaultSkills: ["奥秘", "游说"], equipment: ["轻弩", "奥术法器", "探索套组"], actions: [{ name: "火焰箭", description: "远程法术攻击", damage: "1d10 火焰", range: "120尺", cost: "动作" }], resources: {}, spellcasting: { ability: "魅力", mode: "slots", level1Slots: 2 } },
  { name: "邪术师", hitDie: 8, primary: "魅力", saves: ["感知", "魅力"], proficiencies: ["轻甲", "简易武器"], defaultSkills: ["奥秘", "欺瞒"], equipment: ["轻弩", "奥术法器", "学者套组"], actions: [{ name: "魔能爆", description: "远程法术攻击", damage: "1d10 力场", range: "120尺", cost: "动作" }], resources: { pact_slots: { label: "契约魔法位", current: 1, max: 1, recovery: "short_rest" } }, spellcasting: { ability: "魅力", mode: "slots", level1Slots: 1 } },
  { name: "法师", hitDie: 6, primary: "智力", saves: ["智力", "感知"], proficiencies: ["简易武器"], defaultSkills: ["奥秘", "调查"], equipment: ["法杖", "法术书", "学者套组"], actions: [{ name: "火焰箭", description: "远程法术攻击", damage: "1d10 火焰", range: "120尺", cost: "动作" }], resources: { arcane_recovery: { label: "奥术恢复", current: 1, max: 1, recovery: "long_rest" } }, spellcasting: { ability: "智力", mode: "slots", level1Slots: 2 } },
];
