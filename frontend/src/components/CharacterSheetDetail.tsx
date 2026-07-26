import { useQuery } from "@tanstack/react-query";
import { useId, useState, type ReactElement } from "react";

import { getCharacterAssets } from "../api/entities";
import { getInventory } from "../api/world";
import type { Character } from "../api/types";
import { Button, EmptyState, LoadingBlock } from "../ui/primitives";
import { AdvancementDialog } from "./AdvancementDialog";

const ABILITIES: Record<string, string> = {
  strength: "力量",
  dexterity: "敏捷",
  constitution: "体质",
  intelligence: "智力",
  wisdom: "感知",
  charisma: "魅力",
};

const SKILL_ABILITY: Record<string, keyof typeof ABILITIES> = {
  运动: "strength",
  杂技: "dexterity",
  巧手: "dexterity",
  隐匿: "dexterity",
  奥秘: "intelligence",
  历史: "intelligence",
  调查: "intelligence",
  自然: "intelligence",
  宗教: "intelligence",
  驯兽: "wisdom",
  洞悉: "wisdom",
  医药: "wisdom",
  察觉: "wisdom",
  生存: "wisdom",
  欺瞒: "charisma",
  威吓: "charisma",
  表演: "charisma",
  游说: "charisma",
};

const FEATURE_HELP: Record<string, string> = {
  黑暗视觉: "在昏暗或黑暗环境中仍能依照该种族规则看清周围。",
  天界抗性: "对光耀与黯蚀伤害具有种族提供的抗性。",
  治疗之手: "通过接触为一个生物恢复生命值；使用次数按种族规则恢复。",
  天界显现: "暂时显现天界力量，并获得所选显现形态的战斗效果。",
  龙族血统: "决定角色的龙族祖先、伤害类型及相关种族能力。",
  吐息武器: "以吐息覆盖一定区域并造成龙族血统对应类型的伤害。",
  伤害抗性: "对种族或血统指定的一种伤害类型具有抗性。",
  矮人韧性: "增强对毒素的抵抗能力，并影响相关豁免与伤害。",
  石中感知: "帮助角色感知石造环境、结构或异常。",
  坚韧生命: "提高角色的生命值上限，并随等级成长。",
  精类血统: "角色属于精类血统，影响部分法术与状态的作用方式。",
  敏锐感官: "赋予角色与感官相关的技能熟练。",
  出神: "精灵以出神代替正常睡眠，并按对应规则完成休息。",
  侏儒狡黠: "强化特定心智属性豁免，帮助抵抗魔法影响。",
  侏儒血统: "提供所选侏儒血统对应的特殊能力。",
  巨人血统: "提供所选巨人祖先对应、具有使用次数的能力。",
  大体格: "在搬运、推动或体格相关情境中按大一级体型处理。",
  强力体格: "提高角色脱离控制或维持移动的能力。",
  勇敢: "帮助角色抵抗或摆脱恐慌状态。",
  半身人灵巧: "可穿过体型比自己更大的生物所占空间。",
  幸运: "在特定 d20 掷骰出现最低结果时获得重掷机会。",
  天生隐匿: "可借助更大型生物的遮挡尝试隐藏。",
  足智多谋: "在完成长休后获得一次英雄激励。",
  技艺精通: "获得一项额外技能熟练。",
  多才多艺: "获得一项额外起源专长。",
  肾上腺素爆发: "以附赠动作疾走，并获得由种族规则提供的临时生命值。",
  不屈耐力: "受到足以降至 0 HP 的伤害时，有机会改为保留 1 HP。",
  异界遗产: "决定角色的异界血统、伤害抗性和可使用法术。",
  异界风采: "获得与欺瞒、威吓或表演相关的种族优势。",
};

type Tab = "overview" | "skills" | "actions" | "inventory" | "magic";

function numberModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function signed(value: number): string {
  return value >= 0 ? `+${value}` : String(value);
}

function proficiencyBonus(level: number): number {
  return 2 + Math.floor((Math.max(1, level) - 1) / 4);
}

function objectValue(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
}

function text(value: unknown, fallback = "—"): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : fallback;
}

function featureDescription(feature: unknown): string {
  const data = objectValue(feature);
  const name = text(data.name ?? feature, "未命名特性");
  const description = text(
    data.description ?? data.effect ?? data.rules_text ?? data.summary,
    "",
  );
  if (description) return `${name}：${description}`;
  const knownDescription = FEATURE_HELP[name];
  if (knownDescription) return `${name}：${knownDescription}`;
  if (name.startsWith("背景专长：")) {
    return `${name}：由角色背景获得的起源专长；具体触发、加值或使用次数以该专长的 D&D 5e 2024 规则为准。`;
  }
  return `${name}：该角色拥有此特性。具体触发条件、效果、使用次数与恢复方式以角色所选种族、背景或职业的 D&D 5e 2024 规则为准。`;
}

function FeatureHelp({ feature }: { feature: unknown }): ReactElement {
  const [open, setOpen] = useState(false);
  const tooltipId = useId();
  const name = text(objectValue(feature).name ?? feature);
  const description = featureDescription(feature);

  return (
    <span className="relative inline-flex">
      <button
        aria-describedby={open ? tooltipId : undefined}
        aria-expanded={open}
        className="cursor-help rounded border border-violet-700/70 bg-violet-950/30 px-2.5 py-1.5 text-left text-xs text-violet-100 outline-none transition hover:border-violet-400 hover:bg-violet-900/40 focus-visible:ring-2 focus-visible:ring-violet-300"
        onBlur={() => setOpen(false)}
        onClick={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        type="button"
      >
        {name}
        <span aria-hidden="true" className="ml-1 text-violet-400">ⓘ</span>
      </button>
      {open ? (
        <span
          className="absolute left-0 top-full z-30 mt-2 w-72 max-w-[calc(100vw-3rem)] rounded-lg border border-violet-600/70 bg-ink-950 p-3 text-xs leading-5 text-parchment-100 shadow-2xl"
          id={tooltipId}
          role="tooltip"
        >
          <strong className="mb-1 block text-violet-200">{name}</strong>
          {description.replace(`${name}：`, "")}
          <span aria-hidden="true" className="absolute -top-1 left-4 h-2 w-2 rotate-45 border-l border-t border-violet-600/70 bg-ink-950" />
        </span>
      ) : null}
    </span>
  );
}

type SpellView = {
  name: string;
  level: string;
  prepared: boolean | null;
  description: string;
  damage: string;
  range: string;
  castingTime: string;
  duration: string;
  components: string;
  limitation: string;
  source: string;
};

function spellView(spell: unknown): SpellView {
  const raw = objectValue(spell);
  const metadata = objectValue(raw.metadata_json ?? raw.metadata);
  const data = { ...metadata, ...raw };
  const numericLevel = typeof data.spell_level === "number"
    ? data.spell_level
    : typeof data.level === "number"
      ? data.level
      : null;
  const levelText = numericLevel === 0
    ? "戏法"
    : numericLevel !== null
      ? `${numericLevel}环`
      : text(data.level, "环级未记录");
  const concentration = data.concentration === true ? "专注" : "";
  const ritual = data.ritual === true ? "仪式" : "";
  const limitations = [
    text(data.cost ?? data.resource_cost ?? data.slot_cost, ""),
    concentration,
    ritual,
    text(data.uses ?? data.limit ?? data.restriction, ""),
  ].filter(Boolean);

  return {
    name: text(data.name ?? spell, "未命名法术"),
    level: levelText,
    prepared: typeof data.prepared === "boolean" ? data.prepared : null,
    description: text(
      data.description ?? data.effect ?? data.rules_text ?? data.summary,
      "尚未录入法术效果说明；可在原子化法术资料中补充。",
    ),
    damage: text(
      data.damage_expression ?? data.damage ?? data.healing,
      "无直接伤害或尚未记录",
    ),
    range: text(data.range, "距离未记录"),
    castingTime: text(data.casting_time ?? data.castingTime ?? data.action, "施法时间未记录"),
    duration: text(data.duration, "持续时间未记录"),
    components: text(data.components, "成分未记录"),
    limitation: limitations.join(" · ") || "通常消耗对应环级法术位；具体限制尚未记录",
    source: text(data.source_reference ?? data.source, ""),
  };
}

export function CharacterSheetDetail({
  campaignId,
  character,
  onClose,
}: {
  campaignId: string;
  character: Character;
  onClose: () => void;
}): ReactElement {
  const [tab, setTab] = useState<Tab>("overview");
  const inventory = useQuery({
    queryKey: ["inventory", campaignId, character.id],
    queryFn: ({ signal }) => getInventory(campaignId, character.id, signal),
    enabled: tab === "inventory",
  });
  const characterAssets = useQuery({
    queryKey: ["character-assets", campaignId, character.id],
    queryFn: ({ signal }) => getCharacterAssets(campaignId, character.id, signal),
    enabled: tab === "magic",
  });
  const prof = proficiencyBonus(character.level);
  const skills = Object.entries(SKILL_ABILITY);
  const actions = character.actions.map(objectValue);
  const resources = Object.values(character.resources).map(objectValue);
  const spells = [
    ...(characterAssets.data?.spells ?? []),
    ...character.spells,
  ].map(spellView).filter((spell, index, all) => (
    all.findIndex((candidate) => candidate.name === spell.name) === index
  ));
  const spellcasting = objectValue(character.spellcasting);
  const spellAbilityRaw = text(spellcasting.ability, "");
  const abilityKey = spellAbilityRaw in ABILITIES
    ? spellAbilityRaw
    : Object.entries(ABILITIES).find(([, label]) => label === spellAbilityRaw)?.[0];
  const spellAbility = abilityKey ? ABILITIES[abilityKey] : spellAbilityRaw;
  const spellAbilityModifier = abilityKey
    ? numberModifier(character.ability_scores[abilityKey] ?? 10)
    : null;
  const spellAttack = spellAbilityModifier === null ? null : prof + spellAbilityModifier;
  const spellSaveDc = spellAbilityModifier === null ? null : 8 + prof + spellAbilityModifier;
  const resourceSlots = Object.entries(character.resources)
    .filter(([key, value]) => key.startsWith("spell_slots_") || /法术位|魔法位/.test(text(objectValue(value).label, "")))
    .map(([, value]) => objectValue(value));
  const nestedSlots = Object.entries(objectValue(spellcasting.slots)).map(([level, value]) => ({
    label: `${level}环法术位`,
    ...objectValue(value),
  }));
  const legacyLevelOneSlots = resourceSlots.length === 0
    && nestedSlots.length === 0
    && typeof spellcasting.level1Slots === "number"
    ? [{
      label: "1环法术位",
      current: spellcasting.level1Slots,
      max: spellcasting.level1Slots,
    }]
    : [];
  const spellSlotResources = [...resourceSlots, ...nestedSlots, ...legacyLevelOneSlots]
    .filter((slot, index, all) => all.findIndex((candidate) => (
      text(candidate.label) === text(slot.label)
    )) === index);

  return (
    <div
      aria-label={`${character.name}详细角色卡`}
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-ink-950/80 p-3 backdrop-blur-sm"
      role="dialog"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
    >
      <section className="flex max-h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-ember-700/50 bg-ink-900 shadow-2xl">
        <header className="flex flex-wrap items-start gap-3 border-b border-ink-700 px-5 py-4">
          <div className="mr-auto">
            <p className="m-0 text-2xs uppercase tracking-[0.2em] text-ember-400">D&D 5e 2024 · 完整角色卡</p>
            <h2 className="m-0 mt-1 font-display text-2xl text-parchment-100">{character.name}</h2>
            <p className="mb-0 mt-1 text-xs text-stone-500">
              {character.race || "未选种族"} · {character.class_name || "未选职业"} Lv {character.level} · {character.background || "未选背景"}
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[["AC", character.armor_class], ["HP", `${character.hp}/${character.max_hp}`], ["速度", `${character.speed}尺`]].map(([label, value]) => (
              <div className="min-w-16 rounded border border-ink-700 bg-ink-950/60 px-2 py-1.5" key={label}>
                <span className="block text-2xs text-stone-600">{label}</span>
                <strong className="font-mono text-sm text-parchment-100">{value}</strong>
              </div>
            ))}
          </div>
          <Button aria-label="关闭角色卡" onClick={onClose}>关闭</Button>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-ink-700 px-4 py-2">
          {([
            ["overview", "总览"],
            ["skills", "技能与检定"],
            ["actions", "攻击与动作"],
            ["inventory", "背包与负重"],
            ["magic", "资源与法术"],
          ] as [Tab, string][]).map(([id, label]) => (
            <button
              className={`whitespace-nowrap rounded px-3 py-1.5 text-xs ${tab === id ? "bg-ember-500/15 text-ember-200" : "text-stone-500 hover:bg-ink-800 hover:text-parchment-100"}`}
              key={id}
              onClick={() => setTab(id)}
              type="button"
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {tab === "overview" ? (
            <div className="space-y-5">
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                {Object.entries(ABILITIES).map(([key, label]) => {
                  const score = character.ability_scores[key] ?? 10;
                  return <div className="rounded-lg border border-ink-700 bg-ink-950/50 p-3 text-center" key={key}><span className="block text-2xs text-stone-500">{label}</span><strong className="block font-mono text-xl text-parchment-100">{score}</strong><span className="text-xs text-violet-300">{signed(numberModifier(score))}</span></div>;
                })}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-lg border border-ink-700 p-4"><h3 className="mt-0 text-sm text-parchment-100">成长</h3><p className="text-xs text-stone-400">{character.experience.toLocaleString()} XP · 熟练加值 +{prof}</p><AdvancementDialog campaignId={campaignId} character={character} /></div>
                <div className="rounded-lg border border-ink-700 p-4"><h3 className="mt-0 text-sm text-parchment-100">状态与说明</h3><p className="whitespace-pre-wrap text-xs text-stone-400">{character.notes || "暂无角色备注。"}</p></div>
              </div>
              <div>
                <h3 className="text-sm text-parchment-100">特性</h3>
                <p className="mt-0 text-2xs text-stone-500">悬停、聚焦或点击特性，即可查看完整说明。</p>
                <div className="flex flex-wrap gap-2">
                  {character.features.length ? character.features.map((feature, index) => (
                    <FeatureHelp
                      feature={feature}
                      key={`${text(objectValue(feature).name ?? feature)}-${index}`}
                    />
                  )) : <span className="text-xs text-stone-600">暂无特性</span>}
                </div>
              </div>
            </div>
          ) : null}
          {tab === "skills" ? (
            <div>
              <p className="mt-0 text-xs text-stone-500">将鼠标移到技能上可查看判定方法。带“熟练”的技能已计入 +{prof} 熟练加值。</p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {skills.map(([name, ability]) => {
                  const setting = objectValue(character.skills[name]);
                  const proficient = setting.proficient === true;
                  const expertise = setting.expertise === true;
                  const bonus = numberModifier(character.ability_scores[ability] ?? 10) + (proficient ? prof * (expertise ? 2 : 1) : 0);
                  const method = `掷 d20 + ${ABILITIES[ability]}调整值${proficient ? ` + 熟练加值${expertise ? "×2" : ""}` : ""}；最终加值 ${signed(bonus)}。DC 由 DM 按难度决定。`;
                  return <article className="rounded-lg border border-ink-700 bg-ink-950/45 p-3" key={name} title={method}><div className="flex items-center gap-2"><strong className="mr-auto text-sm text-parchment-100">{name}</strong><span className="font-mono text-lg text-emerald-300">{signed(bonus)}</span></div><p className="mb-0 mt-1 text-2xs text-stone-500">{ABILITIES[ability]}检定 · {expertise ? "专精" : proficient ? "熟练" : "未熟练"}</p></article>;
                })}
              </div>
            </div>
          ) : null}
          {tab === "actions" ? (
            <div className="grid gap-3 md:grid-cols-2">
              {actions.length ? actions.map((action, index) => {
                const description = text(action.description, "暂无说明");
                const tooltip = `${description}；伤害 ${text(action.damage)}；距离 ${text(action.range)}；消耗 ${text(action.cost, "动作")}${action.resource ? `；资源 ${text(action.resource)}` : ""}`;
                return <article className="rounded-lg border border-ink-700 bg-ink-950/45 p-4" key={`${text(action.name)}-${index}`} title={tooltip}><div className="flex items-start gap-3"><strong className="mr-auto text-sm text-parchment-100">{text(action.name, "未命名动作")}</strong><span className="rounded bg-red-950/50 px-2 py-1 font-mono text-xs text-red-200">{text(action.damage, "无伤害")}</span></div><dl className="mt-3 grid grid-cols-2 gap-2 text-xs"><div><dt className="text-stone-600">距离</dt><dd className="m-0 text-stone-300">{text(action.range)}</dd></div><div><dt className="text-stone-600">消耗</dt><dd className="m-0 text-stone-300">{text(action.cost, "动作")}</dd></div></dl><p className="mb-0 mt-3 text-xs leading-5 text-stone-400">{description}</p></article>;
              }) : <EmptyState title="暂无攻击或动作" hint="创建角色时会按职业配置基础动作，也可在角色数据中补充。" />}
            </div>
          ) : null}
          {tab === "inventory" ? (
            <div>
              {inventory.isLoading ? <LoadingBlock label="读取背包与负重…" /> : null}
              {inventory.data ? <><div className="mb-4 grid gap-3 sm:grid-cols-3"><div className="rounded border border-ink-700 p-3"><span className="block text-2xs text-stone-600">当前负重</span><strong className="text-lg text-parchment-100">{inventory.data.total_weight_lb} 磅</strong></div><div className="rounded border border-ink-700 p-3"><span className="block text-2xs text-stone-600">负重上限</span><strong className="text-lg text-parchment-100">{inventory.data.maximum_weight_lb ?? "忽略"}{inventory.data.maximum_weight_lb === null ? "" : " 磅"}</strong></div><div className="rounded border border-ink-700 p-3"><span className="block text-2xs text-stone-600">状态</span><strong className="text-lg text-emerald-300">{({ normal: "正常", encumbered: "负重", heavily_encumbered: "重度负重", over_capacity: "超载", ignored: "未启用" } as const)[inventory.data.state]}</strong></div></div><div className="space-y-2">{inventory.data.items.map((item) => <article className="flex items-center gap-3 rounded border border-ink-700 bg-ink-950/45 p-3" key={item.id} title={item.description ?? item.name}><div className="mr-auto"><strong className="text-sm text-parchment-100">{item.name}</strong><p className="mb-0 mt-1 text-2xs text-stone-500">{item.category} · {item.quantity} 件</p></div><span className="text-xs text-stone-300">{item.unit_weight_lb * item.quantity} 磅</span><span className="text-xs text-amber-300">{item.price_cp * item.quantity} cp</span></article>)}</div>{inventory.data.items.length === 0 ? <EmptyState title="背包为空" hint="在地点中拾取的原子物品会进入这里。" /> : null}</> : null}
            </div>
          ) : null}
          {tab === "magic" ? (
            <div className="space-y-5">
              <section aria-label="施法概览" className="rounded-lg border border-violet-800/60 bg-violet-950/15 p-4">
                <div className="flex flex-wrap items-start gap-3">
                  <div className="mr-auto">
                    <p className="m-0 text-2xs uppercase tracking-[0.16em] text-violet-400">Spellcasting</p>
                    <h3 className="mb-0 mt-1 text-base text-parchment-100">法术与施法</h3>
                    <p className="mb-0 mt-1 text-xs text-stone-400">
                      {spellAbility
                        ? `施法关键属性：${spellAbility}`
                        : "当前职业尚未记录施法能力；若通过种族、背景或专长获得法术，可继续录入。"}
                    </p>
                  </div>
                  {spellAbility ? (
                    <div className="grid grid-cols-2 gap-2 text-center">
                      <div className="rounded border border-ink-700 bg-ink-950/60 px-3 py-2">
                        <span className="block text-2xs text-stone-600">法术攻击</span>
                        <strong className="font-mono text-base text-violet-200">{spellAttack === null ? "—" : signed(spellAttack)}</strong>
                      </div>
                      <div className="rounded border border-ink-700 bg-ink-950/60 px-3 py-2">
                        <span className="block text-2xs text-stone-600">法术豁免 DC</span>
                        <strong className="font-mono text-base text-violet-200">{spellSaveDc ?? "—"}</strong>
                      </div>
                    </div>
                  ) : null}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {spellSlotResources.length ? spellSlotResources.map((slot, index) => (
                    <span className="rounded border border-violet-800/50 bg-ink-950/45 px-2.5 py-1 text-xs text-stone-300" key={`${text(slot.label)}-${index}`}>
                      {text(slot.label, "法术位")}：
                      <strong className="font-mono text-violet-200">{text(objectValue(slot).current, "0")}/{text(objectValue(slot).max, "0")}</strong>
                    </span>
                  )) : (
                    <span className="text-xs text-stone-500">
                      {spellAbility ? "尚未记录可用法术位；戏法通常不消耗法术位。" : "该角色目前没有职业法术位。"}
                    </span>
                  )}
                </div>
              </section>
              <div className="grid gap-4 lg:grid-cols-[0.65fr_1.35fr]">
                <section>
                  <h3 className="mt-0 text-sm text-parchment-100">职业资源</h3>
                  <div className="space-y-2">
                    {resources.map((resource, index) => <div className="rounded border border-ink-700 p-3" key={`${text(resource.label)}-${index}`}><div className="flex"><strong className="mr-auto text-xs text-parchment-100">{text(resource.label, "资源")}</strong><span className="font-mono text-violet-300">{text(resource.current, "0")}/{text(resource.max, "0")}</span></div><p className="mb-0 mt-1 text-2xs text-stone-600">{resource.recovery === "short_rest" ? "短休恢复" : "长休恢复"}</p></div>)}
                    {resources.length === 0 ? <p className="text-xs text-stone-600">暂无职业资源。</p> : null}
                  </div>
                </section>
                <section aria-label="角色法术栏">
                  <div className="mb-2 flex items-end gap-2">
                    <h3 className="m-0 text-sm text-parchment-100">法术栏</h3>
                    <span className="text-2xs text-stone-600">{spells.length} 个已知法术</span>
                  </div>
                  {characterAssets.isLoading ? <LoadingBlock label="读取原子化法术…" /> : null}
                  <div className="space-y-3">
                    {spells.map((spell, index) => (
                      <article className="rounded-lg border border-ink-700 bg-ink-950/45 p-4" key={`${spell.name}-${index}`}>
                        <div className="flex flex-wrap items-center gap-2">
                          <strong className="mr-auto text-sm text-parchment-100">{spell.name}</strong>
                          <span className="rounded bg-violet-950/60 px-2 py-1 text-2xs text-violet-200">{spell.level}</span>
                          {spell.prepared !== null ? (
                            <span className={`rounded px-2 py-1 text-2xs ${spell.prepared ? "bg-emerald-950/60 text-emerald-200" : "bg-amber-950/50 text-amber-200"}`}>
                              {spell.prepared ? "已准备" : "未准备"}
                            </span>
                          ) : null}
                        </div>
                        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
                          <div><dt className="text-stone-600">施法时间</dt><dd className="m-0 text-stone-300">{spell.castingTime}</dd></div>
                          <div><dt className="text-stone-600">距离</dt><dd className="m-0 text-stone-300">{spell.range}</dd></div>
                          <div><dt className="text-stone-600">伤害 / 治疗</dt><dd className="m-0 text-red-200">{spell.damage}</dd></div>
                          <div><dt className="text-stone-600">持续时间</dt><dd className="m-0 text-stone-300">{spell.duration}</dd></div>
                          <div><dt className="text-stone-600">成分</dt><dd className="m-0 text-stone-300">{spell.components}</dd></div>
                          <div><dt className="text-stone-600">消耗 / 限制</dt><dd className="m-0 text-amber-200">{spell.limitation}</dd></div>
                        </dl>
                        <p className="mb-0 mt-3 text-xs leading-5 text-stone-400">{spell.description}</p>
                        {spell.source ? <p className="mb-0 mt-2 text-2xs text-stone-600">来源：{spell.source}</p> : null}
                      </article>
                    ))}
                    {!characterAssets.isLoading && spells.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-ink-600 bg-ink-950/35 p-4">
                        <strong className="text-sm text-parchment-100">
                          {spellAbility ? "尚未学习或准备法术" : "当前角色没有已记录法术"}
                        </strong>
                        <p className="mb-0 mt-2 text-xs leading-5 text-stone-500">
                          {spellAbility
                            ? `该角色使用${spellAbility}施法，但法术栏还是空的。请在升级或角色资产中录入已知/准备法术；录入后这里会显示伤害、范围、施法时间、成分、持续时间和法术位消耗。`
                            : "如果角色通过种族、背景、职业或专长获得法术，请在角色资产中录入。法术会与角色绑定，不会混入其他角色。"}
                        </p>
                      </div>
                    ) : null}
                  </div>
                </section>
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
