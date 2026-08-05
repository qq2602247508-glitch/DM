import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import {
  attackWithMyCombatant,
  bindMyCharacter,
  castMyCombatAction,
  submitMyFeatureAction,
  confirmMyCommerce,
  createMyCharacter,
  dismissMySummon,
  endMyTurn,
  getMyPlayerRoom,
  isPlayerSessionMissing,
  joinPlayerRoom,
  logoutPlayerRoom,
  moveMyCombatant,
  performMyCombatManeuver,
  summonMyCompanion,
  previewMyCommerce,
  planMyNoncombatAction,
  rollMyNoncombatAction,
  resolveMyOpportunityReaction,
  resolveMyDeflectRedirect,
  resolveMyPreDamageReaction,
  searchPlayerRules,
  submitMyDeathSave,
  submitMyActionRequest,
  submitMyPlayerRoll,
  switchPlayerRoom,
  type PlayerRoomSnapshot,
  type PlayerCombatant,
  type PlayerCommerceOperation,
  type PlayerCombatSnapshot,
  type PlayerCombatManeuver,
  type PlayerShop,
  type SafePlayerCharacter,
} from "../api/playerRoom";
import { createClientId } from "../ui/id";
import { getCharacterOptions } from "../api/entities";
import {
  ABILITY_GENERATION_METHODS, BACKGROUND_CREATION_RULES, BACKGROUNDS_2024,
  CLASSES_2024, LANGUAGES_2024, SPECIES_2024, STANDARD_ARRAY,
  abilityGenerationIsValid, classSkillSelection, rolledAbilityScore,
  spellChoiceCounts, spellChoicesComplete, spellIsAvailable, spellSelectionRule,
  spellToCharacterAction,
} from "../ui/characterRules";
import { Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { SceneMap } from "../components/SceneMap";
import { RuleBlockPlan } from "../components/RuleBlockPlan";
import { PlayerEquipmentPanel } from "../components/player/PlayerEquipmentPanel";
import { useOffline } from "../hooks/useOffline";
import { usePlayerRealtime } from "../hooks/useRealtimeInvalidation";
import {
  evaluateTargetingElevation,
  explicitElevationFt,
  getTargetingCells,
  gridDistanceFt,
  hasLineOfSight,
  type GridPoint,
  type TargetingTemplate,
} from "../ui/gridTargeting";
import { buildRuleBlockPlan, targetingFromRulePlan } from "../ui/ruleBlocks";
import {
  actionDamageLabel,
  criticalDamageExpression,
  isEnemyAiControlledCombatant,
  upcastExpression,
} from "../ui/combatAutomation";
import { damageComponentsByTargetSummary, damageComponentsSummary } from "../ui/combatPresentation";

const ABILITIES: Record<string, string> = {
  strength: "力量",
  dexterity: "敏捷",
  constitution: "体质",
  intelligence: "智力",
  wisdom: "感知",
  charisma: "魅力",
};
const COMBAT_MANEUVER_LABELS: Record<PlayerCombatManeuver["action_type"], string> = {
  dash: "疾走",
  dodge: "闪避",
  help: "协助",
  ready: "准备动作",
  search: "搜索",
  hide: "隐藏",
  use_item: "使用物品",
  grapple: "擒抱",
  shove: "推撞",
  object_interaction: "物件互动",
  disengage: "撤离",
  stand_up: "起身",
};
const inputCls = "w-full rounded border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-parchment-100 outline-none focus:border-amber-500";
const cardCls = "rounded-xl border border-ink-700 bg-ink-900/70 p-4";
const SIMULATION_CAMPAIGN_NAME = "【系统】召唤物与法术战斗模拟";

type PlayerActionCost = "action" | "bonus_action" | "reaction" | "legendary_action" | "lair_action" | "none";

function playerActionCost(action: Record<string, unknown> | undefined): PlayerActionCost {
  const explicit = action?.action_type;
  if (explicit === "action" || explicit === "bonus_action" || explicit === "reaction" || explicit === "legendary_action" || explicit === "lair_action") {
    return explicit;
  }
  const costText = typeof action?.cost === "string" ? action.cost : "动作";
  const descriptionText = typeof action?.description === "string" ? action.description : "";
  const text = `${costText} ${descriptionText}`;
  if (/附赠|bonus/i.test(text)) return "bonus_action";
  if (/反应|reaction/i.test(text)) return "reaction";
  if (/传奇动作|legendary/i.test(text)) return "legendary_action";
  if (/巢穴动作|lair/i.test(text)) return "lair_action";
  if (/无需动作|不消耗动作|free action/i.test(text)) return "none";
  return "action";
}

function playerActionCostLabel(cost: PlayerActionCost): string {
  return {
    action: "动作",
    bonus_action: "附赠动作",
    reaction: "反应",
    legendary_action: "传奇动作",
    lair_action: "巢穴动作",
    none: "不消耗动作",
  }[cost];
}

function playerHasActionEconomy(own: PlayerCombatant | undefined, cost: PlayerActionCost): boolean {
  if (!own || cost === "none") return true;
  if (cost === "action") return Boolean(own.action_available || (own.extra_action_budget ?? 0) > 0);
  if (cost === "bonus_action") return Boolean(own.bonus_action_available);
  if (cost === "reaction") return Boolean(own.reaction_available);
  return false;
}

function readSimulationJoin(): { code: string; name: string } | null {
  const queryStart = window.location.hash.indexOf("?");
  if (queryStart < 0) return null;
  const params = new URLSearchParams(window.location.hash.slice(queryStart + 1));
  const code = params.get("simulation_join_code")?.trim().toUpperCase();
  if (!code) return null;
  return {
    code,
    name: params.get("simulation_name")?.trim() || "模拟玩家",
  };
}

function display(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value && typeof value === "object" && "name" in value) {
    const name = (value as { name?: unknown }).name;
    if (typeof name === "string" || typeof name === "number") return String(name);
  }
  return JSON.stringify(value);
}

function advancedRollWindowLabel(actionCost: unknown): string | null {
  if (actionCost === "reaction") return "反应窗口";
  if (actionCost === "legendary_action") return "传奇动作窗口";
  if (actionCost === "lair_action") return "巢穴动作窗口";
  return null;
}

function ruleFieldText(
  block: Record<string, unknown> | undefined,
  field: string,
  fallback: string,
): string {
  const value = block?.[field];
  if (typeof value === "string") return value;
  if (typeof value === "number") return value.toString();
  return fallback;
}

function damageFormulaForAction(action: Record<string, unknown> | undefined): string | null {
  if (!action) return null;
  for (const key of ["damage", "damage_expression", "damage_dice"]) {
    const value = action[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  const effect = buildRuleBlockPlan(action).blocks.find(
    (block) => block.kind === "effect" && /伤害/.test(block.value),
  );
  if (effect?.value) return effect.value;
  const description = action.description;
  const dice = typeof description === "string"
    ? description.match(/\b\d+\s*d\s*\d+(?:\s*[+-]\s*\d+)?\b/i)?.[0]
    : undefined;
  return dice?.replace(/\s+/g, "") ?? null;
}

function damageInstructionForAction(action: Record<string, unknown> | undefined): string {
  const formula = damageFormulaForAction(action);
  if (!formula) {
    return actionDamageLabel(action);
  }
  const typeLabels: Record<string, string> = {
    slashing: "挥砍", piercing: "穿刺", bludgeoning: "钝击", fire: "火焰",
    cold: "寒冷", lightning: "闪电", thunder: "雷鸣", acid: "酸蚀",
    poison: "毒素", psychic: "心灵", necrotic: "黯蚀", radiant: "光耀", force: "力场",
  };
  const rawType = typeof action?.damage_type === "string" ? action.damage_type : "";
  const formulaType = Object.keys(typeLabels).find((type) => formula.toLowerCase().includes(type));
  const damageType = typeLabels[rawType] ?? typeLabels[formulaType ?? ""] ?? rawType;
  if (!damageType) return formula;
  if (formula.includes(damageType)) return formula;
  const cleanedFormula = formulaType
    ? formula.replace(new RegExp(`\\b${formulaType}\\b`, "i"), "").trim()
    : formula;
  return `${cleanedFormula} ${damageType}伤害`;
}

function hasAutomaticCriticalCondition(target: PlayerCombatant | undefined): boolean {
  if (!target || !Array.isArray(target.conditions)) return false;
  return target.conditions.some((raw) => {
    const value = raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as { name?: unknown; condition_name?: unknown }).name
        ?? (raw as { condition_name?: unknown }).condition_name
      : raw;
    const normalized = typeof value === "string"
      ? value.trim().toLowerCase().replaceAll("-", "_")
      : "";
    return normalized === "paralyzed" || normalized === "麻痹"
      || normalized === "unconscious" || normalized === "昏迷";
  });
}

function actionCategoryLabel(action: Record<string, unknown>): string {
  if (action.runtime_feature === true) return "职业特性";
  const plan = action.rule_plan;
  const blocks = plan && typeof plan === "object" && Array.isArray((plan as { blocks?: unknown[] }).blocks)
    ? (plan as { blocks: unknown[] }).blocks
    : [];
  const kinds = new Set(
    blocks.flatMap((block) => typeof block === "object" && block !== null && typeof (block as { kind?: unknown }).kind === "string"
      ? [String((block as { kind: string }).kind)]
      : []),
  );
  if (kinds.has("summon")) return "召唤";
  if (kinds.has("condition") || kinds.has("modifier") || kinds.has("defense")) return "状态/效果";
  if (kinds.has("area_effect") || kinds.has("move")) return "区域/位移";
  if (action.auto_hit === true) return "特殊攻击";
  if (kinds.has("damage") || action.damage !== undefined) return "攻击/伤害";
  return "其他技能";
}

function savingThrowForAction(action: Record<string, unknown> | undefined): {
  ability: string;
  dc: number;
} | null {
  if (!action) return null;
  const directDc = Number(action.save_dc);
  const directAbility = typeof action.save_ability === "string" ? action.save_ability : "";
  if (Number.isFinite(directDc) && directAbility) return { ability: directAbility, dc: directDc };
  const plan = action.rule_plan;
  const blocks = plan && typeof plan === "object" && Array.isArray((plan as { blocks?: unknown[] }).blocks)
    ? (plan as { blocks: unknown[] }).blocks
    : [];
  const save = blocks.find((block): block is Record<string, unknown> => (
    typeof block === "object"
    && block !== null
    && (block as { kind?: unknown }).kind === "save"
  ));
  const dc = Number(save?.dc);
  const ability = typeof save?.ability === "string" ? save.ability : "";
  return Number.isFinite(dc) && ability ? { ability, dc } : null;
}

type RestRequestInput = {
  restType: "short" | "long";
  hitDice: Array<{ resource_pool_id: string; roll: number }>;
};

function gridLine(
  start: { row: number; col: number },
  end: { row: number; col: number },
): Array<{ row: number; col: number }> {
  let { row, col } = start;
  const result = [{ row, col }];
  while (row !== end.row || col !== end.col) {
    if (row !== end.row) row += end.row > row ? 1 : -1;
    if (col !== end.col) col += end.col > col ? 1 : -1;
    result.push({ row, col });
  }
  return result;
}

function targetingForAction(action: Record<string, unknown> | undefined): TargetingTemplate | null {
  if (!action) return null;
  const compiled = targetingFromRulePlan(action);
  if (compiled) return compiled;
  const text = [
    display(action.range ?? ""),
    display(action.description ?? ""),
    display(action.area ?? ""),
  ].join(" ");
  const numbers = [...text.matchAll(/(\d+)\s*尺/g)].map((match) => Number(match[1]));
  const shape = /锥形|锥状|锥体/.test(text)
    ? "cone"
    : /直线|束/.test(text)
      ? "line"
      : /立方/.test(text)
        ? "cube"
        : /半径|球形|爆发|圆形/.test(text)
          ? "circle"
          : "single";
  const originSelf = /自身|self/i.test(text);
  if (!originSelf && numbers.length === 0) return null;
  return {
    shape,
    rangeFt: numbers[0] ?? 0,
    sizeFt: shape === "circle" || shape === "cube"
      ? numbers[1] ?? 20
      : shape === "line" || shape === "cone"
        ? numbers[0] ?? 5
        : undefined,
    widthFt: shape === "line" ? numbers[1] ?? 5 : undefined,
    originSelf,
  };
}

function JoinRoom({ onJoined }: { onJoined: () => void }): ReactElement {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const join = useMutation({
    mutationFn: () => joinPlayerRoom(code, name),
    onSuccess: onJoined,
  });
  return (
    <main className="flex min-h-screen items-center justify-center bg-ink-950 p-4">
      <section className="w-full max-w-md rounded-2xl border border-amber-900/60 bg-ink-900 p-6 shadow-2xl">
        <p className="m-0 text-xs uppercase tracking-[.22em] text-amber-300">D&D 5e 玩家入口</p>
        <h1 className="mb-2 mt-3 font-display text-3xl text-parchment-100">加入跑团房间</h1>
        <p className="text-sm leading-6 text-stone-400">请连接到 DM 的同一局域网，输入主控台显示的 6 位房间码。</p>
        <p className="mb-0 mt-2 text-xs leading-5 text-amber-200/80">进入房间并绑定角色后，顶部会出现“商店”页签；购买需要使用该角色的钱包。</p>
        <label className="mt-5 block text-xs text-stone-400">房间码
          <input aria-label="房间码" autoCapitalize="characters" className={`${inputCls} mt-1 text-center font-mono text-2xl tracking-[.28em]`} maxLength={8} onChange={(event) => setCode(event.target.value.toUpperCase())} value={code} />
        </label>
        <label className="mt-3 block text-xs text-stone-400">玩家称呼
          <input aria-label="玩家称呼" className={`${inputCls} mt-1`} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder="例如：小林" value={name} />
        </label>
        <Button className="mt-5 w-full" disabled={code.trim().length < 6 || !name.trim()} loading={join.isPending} onClick={() => join.mutate()} variant="primary">进入房间</Button>
        {join.isError ? <p className="mb-0 mt-3 text-sm text-red-300">{join.error.message}</p> : null}
      </section>
    </main>
  );
}

function CharacterBuilder({ snapshot, onDone }: { snapshot: PlayerRoomSnapshot; onDone: () => void }): ReactElement {
  const [mode, setMode] = useState<"choose" | "create">(
    snapshot.available_characters?.length ? "choose" : "create",
  );
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [race, setRace] = useState("");
  const [className, setClassName] = useState("");
  const [background, setBackground] = useState("");
  const [spellSearch, setSpellSearch] = useState("");
  const [selectedSpells, setSelectedSpells] = useState<string[]>([]);
  const [preparedSpellIds, setPreparedSpellIds] = useState<string[]>([]);
  const [selectedClassSkills, setSelectedClassSkills] = useState<string[]>([]);
  const [abilityGenerationMethod, setAbilityGenerationMethod] = useState<
    "standard_array" | "point_buy" | "rolled_4d6_drop_lowest"
  >("standard_array");
  const [abilityRolls, setAbilityRolls] = useState<Record<string, number[]>>(
    () => Object.fromEntries(Object.keys(ABILITIES).map((ability) => [ability, [0, 0, 0, 0]])),
  );
  const [originMode, setOriginMode] = useState<"two_plus_one" | "three_plus_one">("two_plus_one");
  const [originPrimary, setOriginPrimary] = useState("");
  const [originSecondary, setOriginSecondary] = useState("");
  const [backgroundTool, setBackgroundTool] = useState("");
  const [languages, setLanguages] = useState<[string, string]>(["精灵语", "龙语"]);
  const [scores, setScores] = useState<Record<string, number>>({
    strength: 15, dexterity: 14, constitution: 13,
    intelligence: 12, wisdom: 10, charisma: 8,
  });
  const bind = useMutation({ mutationFn: () => bindMyCharacter(selected), onSuccess: onDone });
  const characterOptions = useQuery({
    queryKey: ["character-options", snapshot.campaign.id],
    queryFn: ({ signal }) => getCharacterOptions(signal, snapshot.campaign.id),
    staleTime: 60 * 60 * 1000,
  });
  const selectedClass = CLASSES_2024.find((item) => item.name === className);
  const selectedBackground = BACKGROUNDS_2024.find((item) => item.name === background);
  const selectedBackgroundCreation = selectedBackground
    ? BACKGROUND_CREATION_RULES[selectedBackground.name]
    : undefined;
  const baseScores = useMemo(() => (
    abilityGenerationMethod === "rolled_4d6_drop_lowest"
      ? Object.fromEntries(
        Object.keys(ABILITIES).map((ability) => [ability, rolledAbilityScore(abilityRolls[ability] ?? []) ?? 0]),
      ) as Record<string, number>
      : scores
  ), [abilityGenerationMethod, abilityRolls, scores]);
  const originIncreases = useMemo(() => {
    if (!selectedBackgroundCreation) return {};
    if (originMode === "three_plus_one") {
      return Object.fromEntries(selectedBackgroundCreation.abilityOptions.map((ability) => [ability, 1]));
    }
    if (!originPrimary || !originSecondary || originPrimary === originSecondary) return {};
    return { [originPrimary]: 2, [originSecondary]: 1 };
  }, [originMode, originPrimary, originSecondary, selectedBackgroundCreation]);
  const finalScores = useMemo(() => Object.fromEntries(
    Object.entries(baseScores).map(([ability, score]) => [ability, score + (originIncreases[ability] ?? 0)]),
  ) as Record<string, number>, [baseScores, originIncreases]);
  const validAbilityGeneration = abilityGenerationIsValid(
    abilityGenerationMethod,
    baseScores,
    abilityRolls,
  );
  const originComplete = Object.keys(originIncreases).length > 0;
  const languagesComplete = languages.every(Boolean) && languages[0] !== languages[1]
    && !languages.includes("通用语");
  const skillRule = classSkillSelection(className, selectedBackground?.skills);
  const spellLimits = spellSelectionRule(className);
  const availableSpells = (characterOptions.data?.spells ?? [])
    .filter((spell) => spellIsAvailable(spell, className));
  const spellCounts = spellChoiceCounts(selectedSpells, availableSpells);
  const preparedRequired = spellLimits.preparedLeveled ?? 0;
  const preparedCount = preparedSpellIds.filter((id) => selectedSpells.includes(id)).length;
  const preparedComplete = preparedRequired === 0 || preparedCount === preparedRequired;
  const choicesComplete = selectedClassSkills.length === skillRule.count
    && spellChoicesComplete(className, selectedSpells, availableSpells)
    && preparedComplete;
  const create = useMutation({
    mutationFn: () => {
      const abilityKey = {
        力量: "strength", 敏捷: "dexterity", 体质: "constitution",
        智力: "intelligence", 感知: "wisdom", 魅力: "charisma",
      }[selectedClass?.spellcasting?.ability ?? "智力"] ?? "intelligence";
      const spellSaveDc = 10 + Math.floor(((finalScores[abilityKey] ?? 10) - 10) / 2);
      return createMyCharacter({
        name, race, class_name: className, background, ability_scores: finalScores,
        ability_generation_method: abilityGenerationMethod,
        ability_rolls: abilityGenerationMethod === "rolled_4d6_drop_lowest" ? abilityRolls : {},
        origin_ability_increases: originIncreases,
        background_tool_proficiency: backgroundTool,
        languages,
        starter_equipment_option: "fixed_package",
        equipment: [],
        skill_proficiencies: selectedClassSkills,
        spells: availableSpells
          .filter((spell) => selectedSpells.includes(spell.source_record_id))
          .map((spell) => spellToCharacterAction(
            spell,
            spellSaveDc,
            className !== "法师" || preparedSpellIds.includes(spell.source_record_id),
          )),
      });
    },
    onSuccess: onDone,
  });
  const toggleSpell = (id: string, level: number, checked: boolean) => {
    if (!checked) {
      setSelectedSpells((current) => current.filter((item) => item !== id));
      setPreparedSpellIds((current) => current.filter((item) => item !== id));
      return;
    }
    const limit = level === 0 ? spellLimits.cantrips : spellLimits.leveled;
    const count = level === 0 ? spellCounts.cantrips : spellCounts.leveled;
    if (count >= limit) return;
    setSelectedSpells((current) => [...current, id]);
  };
  return (
    <main className="mx-auto min-h-screen max-w-4xl p-4 lg:p-8">
      <header className="mb-5">
        <p className="m-0 text-xs uppercase tracking-[.2em] text-amber-300">已加入 · {snapshot.campaign.name}</p>
        <h1 className="mb-1 mt-2 font-display text-3xl text-parchment-100">选择或创建你的角色</h1>
        <p className="text-sm text-stone-400">角色与这个跑团房间绑定；其他玩家无法查看或占用你的完整角色卡。</p>
        <p className="text-xs leading-5 text-amber-200/80">绑定或创建角色后，回到顶部“商店”页签即可查看当前 Scene 公开的商店。</p>
        {(characterOptions.data?.extension_character_options?.length ?? 0) > 0 ? <p className="text-2xs leading-5 text-amber-200/80">本战役已启用 {characterOptions.data?.extension_character_options?.length} 项扩展职业/子职/专长资料；它们仅供查阅并由 DM 裁定，不会进入自动车卡选择器。</p> : null}
      </header>
      <div className="mb-4 flex gap-2">
        <Button onClick={() => setMode("choose")} variant={mode === "choose" ? "primary" : "ghost"}>选择已有角色</Button>
        <Button onClick={() => setMode("create")} variant={mode === "create" ? "primary" : "ghost"}>按规则车卡</Button>
      </div>
      {mode === "choose" ? (
        <section className={cardCls}>
          <h2 className="mt-0 font-display text-xl">未被认领的角色</h2>
          {!snapshot.available_characters?.length ? <EmptyState hint="可以切换到“按规则车卡”创建新角色。" title="暂无可选角色" /> : (
            <div className="grid gap-3 md:grid-cols-2">
              {snapshot.available_characters.map((character) => (
                <button className={`rounded-lg border p-3 text-left ${selected === character.id ? "border-amber-400 bg-amber-500/10" : "border-ink-700 bg-ink-950/40"}`} key={character.id} onClick={() => setSelected(character.id)} type="button">
                  <strong>{character.name}</strong><span className="mt-1 block text-xs text-stone-400">{character.race || "未知种族"} · {character.class_name || "未知职业"} Lv{character.level}</span>
                </button>
              ))}
            </div>
          )}
          <Button className="mt-4" disabled={!selected} loading={bind.isPending} onClick={() => bind.mutate()} variant="primary">绑定所选角色</Button>
          {bind.isError ? <p className="text-sm text-red-300">{bind.error.message}</p> : null}
        </section>
      ) : (
        <section className={cardCls}>
          {characterOptions.data?.rule_extensions?.length ? <div className="mb-4 rounded border border-violet-800/60 bg-violet-950/20 p-3 text-xs text-violet-100"><strong>本团已启用规则扩展：</strong>{characterOptions.data.rule_extensions.map((item) => <span className="ml-2 inline-flex rounded bg-violet-500/15 px-2 py-1 text-2xs" key={item.key}>{item.label} · {item.automation_status === "partial" ? "部分自动" : item.automation_status === "dm_only" ? "DM裁定" : "自动"}</span>)}<p className="mb-0 mt-2 text-2xs text-violet-200/70">需要数值或前置条件的扩展仍需 DM 最终确认。</p></div> : null}
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-xs text-stone-400">角色名<input className={`${inputCls} mt-1`} onChange={(event) => setName(event.target.value)} value={name} /></label>
            <label className="text-xs text-stone-400">种族（2024核心）
              <select className={`${inputCls} mt-1`} onChange={(event) => setRace(event.target.value)} value={race}><option value="">请选择</option>{SPECIES_2024.map((item) => <option key={item.name}>{item.name}</option>)}</select>
            </label>
            <label className="text-xs text-stone-400">职业（全部12个核心职业）
              <select className={`${inputCls} mt-1`} onChange={(event) => { setClassName(event.target.value); setSelectedClassSkills([]); setSelectedSpells([]); setPreparedSpellIds([]); }} value={className}><option value="">请选择</option>{CLASSES_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · d{item.hitDie}</option>)}</select>
            </label>
            <label className="text-xs text-stone-400">背景（2024核心）
              <select className={`${inputCls} mt-1`} onChange={(event) => {
                const nextBackground = event.target.value;
                const creation = BACKGROUND_CREATION_RULES[nextBackground];
                setBackground(nextBackground);
                setSelectedClassSkills([]);
                setOriginPrimary(creation?.abilityOptions[0] ?? "");
                setOriginSecondary(creation?.abilityOptions[1] ?? "");
                setBackgroundTool(creation?.toolChoices[0] ?? "");
              }} value={background}><option value="">请选择</option>{BACKGROUNDS_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.skills.join("、")}</option>)}</select>
            </label>
          </div>
          <section className="mt-5 rounded border border-ink-700 bg-ink-950/40 p-3">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div><h3 className="m-0 text-sm text-parchment-100">属性生成</h3><p className="mb-0 mt-1 text-xs text-stone-500">背景起源加值会在下方单独选择并计入最终属性。</p></div>
              <label className="text-xs text-stone-400">方法<select className={`${inputCls} mt-1`} onChange={(event) => setAbilityGenerationMethod(event.target.value as typeof abilityGenerationMethod)} value={abilityGenerationMethod}>{ABILITY_GENERATION_METHODS.map((method) => <option key={method.key} value={method.key}>{method.label}</option>)}</select></label>
            </div>
            {abilityGenerationMethod === "rolled_4d6_drop_lowest" ? (
              <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(ABILITIES).map(([key, label]) => <label className="rounded border border-ink-700 p-2 text-xs text-stone-400" key={key}>{label}<span className="mt-1 grid grid-cols-4 gap-1">{[0, 1, 2, 3].map((index) => <input aria-label={`${label}第${index + 1}骰`} className="min-w-0 rounded border border-ink-600 bg-ink-950 px-1 py-1 text-center text-parchment-100" key={index} max="6" min="1" onChange={(event) => setAbilityRolls((current) => ({ ...current, [key]: (current[key] ?? [0, 0, 0, 0]).map((roll, rollIndex) => rollIndex === index ? Number(event.target.value) : roll) }))} type="number" value={abilityRolls[key]?.[index] || ""} />)}</span><span className="mt-1 block text-amber-200">去最低后：{baseScores[key] || "—"}</span></label>)}
              </div>
            ) : (
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-6">
                {Object.entries(ABILITIES).map(([key, label]) => <label className="text-xs text-stone-400" key={key}>{label}{abilityGenerationMethod === "standard_array" ? <select className={`${inputCls} mt-1`} onChange={(event) => setScores((current) => ({ ...current, [key]: Number(event.target.value) }))} value={scores[key]}>{[...STANDARD_ARRAY].reverse().map((value) => <option key={value}>{value}</option>)}</select> : <input className={`${inputCls} mt-1`} max="15" min="8" onChange={(event) => setScores((current) => ({ ...current, [key]: Number(event.target.value) }))} type="number" value={scores[key]} />}</label>)}
              </div>
            )}
            {!validAbilityGeneration ? <p className="mb-0 mt-2 text-sm text-red-300">{abilityGenerationMethod === "standard_array" ? "标准数组的每个数值必须恰好使用一次。" : abilityGenerationMethod === "point_buy" ? "27 点购点必须恰好花费 27 点，且每项介于 8 到 15。" : "请为每项属性填入四个 1–6 的骰子，系统会去掉最低骰。"}</p> : null}
          </section>
          {selectedBackgroundCreation ? <section className="mt-3 rounded border border-violet-800/60 bg-violet-950/15 p-3">
            <h3 className="m-0 text-sm text-parchment-100">背景起源、工具与语言</h3>
            <p className="mb-2 mt-1 text-xs text-stone-400">{background} 可提升：{selectedBackgroundCreation.abilityOptions.map((ability) => ABILITIES[ability]).join("、")}。</p>
            <div className="flex flex-wrap gap-3 text-xs text-stone-300"><label><input checked={originMode === "two_plus_one"} className="mr-1" onChange={() => setOriginMode("two_plus_one")} type="radio" />一项 +2、另一项 +1</label><label><input checked={originMode === "three_plus_one"} className="mr-1" onChange={() => setOriginMode("three_plus_one")} type="radio" />三项各 +1</label></div>
            {originMode === "two_plus_one" ? <div className="mt-2 grid gap-2 sm:grid-cols-2"><label className="text-xs text-stone-400">+2<select className={`${inputCls} mt-1`} onChange={(event) => { setOriginPrimary(event.target.value); if (event.target.value === originSecondary) setOriginSecondary(""); }} value={originPrimary}><option value="">请选择</option>{selectedBackgroundCreation.abilityOptions.map((ability) => <option key={ability} value={ability}>{ABILITIES[ability]}</option>)}</select></label><label className="text-xs text-stone-400">+1<select className={`${inputCls} mt-1`} onChange={(event) => setOriginSecondary(event.target.value)} value={originSecondary}><option value="">请选择</option>{selectedBackgroundCreation.abilityOptions.filter((ability) => ability !== originPrimary).map((ability) => <option key={ability} value={ability}>{ABILITIES[ability]}</option>)}</select></label></div> : null}
            <div className="mt-2 grid gap-2 sm:grid-cols-3"><label className="text-xs text-stone-400">背景工具熟练<select className={`${inputCls} mt-1`} onChange={(event) => setBackgroundTool(event.target.value)} value={backgroundTool}><option value="">请选择</option>{selectedBackgroundCreation.toolChoices.map((tool) => <option key={tool}>{tool}</option>)}</select></label><label className="text-xs text-stone-400">额外语言一<select className={`${inputCls} mt-1`} onChange={(event) => setLanguages((current) => [event.target.value, current[1]])} value={languages[0]}><option value="">请选择</option>{LANGUAGES_2024.filter((language) => language !== "通用语").map((language) => <option key={language}>{language}</option>)}</select></label><label className="text-xs text-stone-400">额外语言二<select className={`${inputCls} mt-1`} onChange={(event) => setLanguages((current) => [current[0], event.target.value])} value={languages[1]}><option value="">请选择</option>{LANGUAGES_2024.filter((language) => language !== "通用语").map((language) => <option key={language}>{language}</option>)}</select></label></div>
            {!originComplete || !languagesComplete ? <p className="mb-0 mt-2 text-xs text-amber-200">请选择合法的背景起源加值与两门不重复的额外语言；通用语会自动记录。</p> : null}
          </section> : null}
          <section className="mt-3 rounded border border-ink-700 bg-ink-950/40 p-3 text-xs text-stone-400"><strong className="text-parchment-100">起始装备</strong><p className="mb-0 mt-1">玩家入口使用固定的职业与背景起始装备包：{[...(selectedClass?.equipment ?? []), ...(selectedBackground?.equipment ?? [])].join("、") || "请选择职业与背景后显示"}。自定义追加装备由 DM 在车卡后授予。</p></section>
          <div className="mt-5 rounded border border-ink-700 bg-ink-950/40 p-3">
            <h3 className="m-0 text-sm text-parchment-100">职业选项</h3>
            <p className="mb-2 mt-1 text-xs text-stone-500">当前创建1级角色；子职通常在3级解锁，升级时再从该职业完整子职库中选择。</p>
            <div className="mb-3 rounded border border-ink-700 p-2">
              <p className="mb-2 mt-0 text-xs text-stone-400">职业技能：已选 <strong className={selectedClassSkills.length === skillRule.count ? "text-emerald-300" : "text-amber-300"}>{selectedClassSkills.length}/{skillRule.count}</strong>；背景固定提供 {selectedBackground?.skills.join("、") || "无"}。</p>
              <div className="flex flex-wrap gap-2">
                {skillRule.choices.map((skill) => <label className={`rounded border px-2 py-1 text-xs ${selectedClassSkills.includes(skill) ? "border-emerald-500 text-emerald-200" : "border-ink-700 text-stone-400"}`} key={skill}><input checked={selectedClassSkills.includes(skill)} className="mr-1" onChange={(event) => { if (!event.target.checked) setSelectedClassSkills((current) => current.filter((item) => item !== skill)); else if (selectedClassSkills.length < skillRule.count) setSelectedClassSkills((current) => [...current, skill]); }} type="checkbox" />{skill}</label>)}
              </div>
            </div>
            {selectedClass?.spellcasting ? (
              <>
                <input aria-label="玩家搜索法术" className={inputCls} onChange={(event) => setSpellSearch(event.target.value)} placeholder="搜索并选择初始法术" value={spellSearch} />
                <div className="mt-2 max-h-56 overflow-y-auto rounded border border-ink-700 p-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    {availableSpells.filter((spell) => !spellSearch.trim() || `${spell.name} ${spell.source_path}`.toLowerCase().includes(spellSearch.trim().toLowerCase())).map((spell) => <label className={`flex gap-2 rounded border p-2 text-xs ${selectedSpells.includes(spell.source_record_id) ? "border-amber-500 bg-amber-950/20" : "border-ink-700"}`} key={spell.source_record_id}><input checked={selectedSpells.includes(spell.source_record_id)} onChange={(event) => toggleSpell(spell.source_record_id, spell.level, event.target.checked)} type="checkbox" /><span><strong className="block">{spell.name} · {spell.level === 0 ? "戏法" : "1环"}</strong><span className="text-2xs text-stone-600">{spell.casting_time || "施法时间未记录"} · {spell.range || "距离未记录"} · {spell.damage_expression || "叙事/辅助效果"}</span></span></label>)}
                  </div>
                </div>
                <p className={`mb-0 mt-2 text-xs ${spellCounts.cantrips === spellLimits.cantrips && spellCounts.leveled === spellLimits.leveled ? "text-emerald-300" : "text-amber-200"}`}>必须选择：戏法 {spellCounts.cantrips}/{spellLimits.cantrips} · {spellLimits.leveledLabel} {spellCounts.leveled}/{spellLimits.leveled}。</p>
                {preparedRequired > 0 ? <div className="mt-3 rounded border border-sky-800/60 p-2"><p className="mb-2 mt-0 text-xs text-sky-200">再从法术书中准备 {preparedRequired} 个1环法术（{preparedCount}/{preparedRequired}）；只有已准备法术能在战斗中施放。</p><div className="flex flex-wrap gap-2">{availableSpells.filter((spell) => spell.level === 1 && selectedSpells.includes(spell.source_record_id)).map((spell) => <label className={`rounded border px-2 py-1 text-xs ${preparedSpellIds.includes(spell.source_record_id) ? "border-sky-500 text-sky-200" : "border-ink-700 text-stone-500"}`} key={`prepared-${spell.source_record_id}`}><input checked={preparedSpellIds.includes(spell.source_record_id)} className="mr-1" onChange={(event) => { if (!event.target.checked) setPreparedSpellIds((current) => current.filter((id) => id !== spell.source_record_id)); else if (preparedCount < preparedRequired) setPreparedSpellIds((current) => [...current, spell.source_record_id]); }} type="checkbox" />准备 · {spell.name}</label>)}</div></div> : null}
              </>
            ) : <p className="mb-0 text-xs text-stone-600">该职业1级没有法术选择。</p>}
          </div>
          <Button className="mt-5" disabled={!name.trim() || !race || !className || !background || !validAbilityGeneration || !originComplete || !backgroundTool || !languagesComplete || !choicesComplete} loading={create.isPending} onClick={() => create.mutate()} variant="primary">创建并绑定角色</Button>
          {create.isError ? <p className="text-sm text-red-300">{create.error.message}</p> : null}
        </section>
      )}
    </main>
  );
}

function CharacterView({
  character,
  onChanged,
}: {
  character: SafePlayerCharacter;
  onChanged: () => void;
}): ReactElement {
  const resources = Object.entries(character.resources ?? {}).map(([key, value]) => {
    const resource = typeof value === "object" && value !== null
      ? value as Record<string, unknown>
      : {};
    return {
      key,
      label: display(resource.label ?? key),
      current: resource.current,
      max: resource.max,
      recovery: resource.recovery === "short_rest"
        ? "短休恢复"
        : resource.recovery === "long_rest"
          ? "长休恢复"
          : display(resource.recovery ?? ""),
    };
  });
  const spellcastingAbility = display(character.spellcasting?.ability ?? "");
  const atomicEquipmentNames = new Set(
    (character.equipment_assets ?? []).map((item) => item.name),
  );
  const ordinaryInventory = character.inventory.filter(
    (item) => !atomicEquipmentNames.has(display(item)),
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className={cardCls}>
        <h2 className="mt-0 font-display text-2xl">{character.name}</h2>
        <p className="text-sm text-amber-200">{character.race} · {character.class_name} Lv{character.level} · {character.background}</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">{[["HP", `${character.hp}/${character.max_hp}`], ["AC", character.armor_class], ["速度", `${character.speed}尺`], ["经验", `${character.experience} XP`], ["金币", `${character.wallet?.gp ?? 0} GP`]].map(([label, value]) => <div className="rounded bg-ink-950 p-3 text-center" key={label}><span className="block text-2xs text-stone-500">{label}</span><strong className="font-mono text-lg">{value}</strong></div>)}</div>
        <div className="mt-3 grid grid-cols-3 gap-2">{Object.entries(ABILITIES).map(([key, label]) => <div className="rounded border border-ink-700 p-2 text-center" key={key}><span className="block text-2xs text-stone-500">{label}</span><strong>{character.ability_scores[key] ?? 10}</strong></div>)}</div>
      </section>
      <section className={cardCls}><h2 className="mt-0 font-display text-xl">动作与法术</h2>{spellcastingAbility ? <p className="text-xs text-amber-200">施法属性：{spellcastingAbility}</p> : null}{[...character.actions, ...character.spells].length ? [...character.actions, ...character.spells].map((item, index) => <details className="mb-2 rounded border border-ink-700 p-2" key={`${display(item)}-${index}`}><summary className="cursor-pointer text-sm text-parchment-100">{display(item)}</summary><pre className="whitespace-pre-wrap text-xs text-stone-400">{JSON.stringify(item, null, 2)}</pre></details>) : <p className="text-sm text-stone-500">暂无动作或法术。</p>}</section>
      <PlayerEquipmentPanel character={character} onChanged={onChanged} />
      <section className={cardCls}><h2 className="mt-0 font-display text-xl">背包与普通道具</h2>{ordinaryInventory.length ? <ul className="pl-5 text-sm">{ordinaryInventory.map((item, index) => <li className="mb-1" key={`${display(item)}-${index}`}>{display(item)}</li>)}</ul> : <p className="text-sm text-stone-500">背包里暂无普通道具。</p>}</section>
      <section className={cardCls}><h2 className="mt-0 font-display text-xl">特性、技能与资源</h2><div className="flex flex-wrap gap-2">{character.features.map((item, index) => <span className="rounded bg-violet-500/10 px-2 py-1 text-xs text-violet-200" key={`${display(item)}-${index}`} title={display(item)}>{display(item)}</span>)}</div><p className="mt-4 text-xs text-stone-400">熟练：{character.proficiencies.map(display).join("、") || "无"}</p><p className="text-xs text-stone-400">技能：{Object.keys(character.skills).join("、") || "无"}</p>{resources.map((resource) => <div className="mt-2 flex items-center gap-3 rounded border border-ink-700 p-3 text-xs" key={resource.key}><strong className="mr-auto text-parchment-100">{resource.label}</strong>{resource.current !== undefined && resource.max !== undefined ? <span className="font-mono text-base text-amber-200">{display(resource.current)}/{display(resource.max)}</span> : null}{resource.recovery ? <span className="text-stone-500">{resource.recovery}</span> : null}</div>)}</section>
    </div>
  );
}

type PendingShopPurchase = {
  itemName: string;
  input: PlayerCommerceOperation;
  preview: Record<string, unknown>;
};

function copperLabel(value: unknown): string {
  const copper = Number(value);
  if (!Number.isFinite(copper)) return "—";
  return `${copper} cp（${(copper / 100).toFixed(2)} gp）`;
}

function PlayerShopView({
  shops,
  wallet,
  refresh,
}: {
  shops: PlayerShop[];
  wallet: SafePlayerCharacter["wallet"];
  refresh: () => void;
}): ReactElement {
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<PendingShopPurchase | null>(null);
  const previewMutation = useMutation({
    mutationFn: ({ item, quantity }: { item: PlayerShop["stock"][number]; quantity: number }) => {
      if (!wallet?.id || wallet.version === undefined) throw new Error("角色钱包尚未同步");
      const input: PlayerCommerceOperation = {
        wallet_id: wallet.id,
        wallet_version: wallet.version,
        shop_inventory_id: item.id,
        shop_version: item.version,
        quantity,
      };
      return previewMyCommerce(input).then((preview) => ({ itemName: item.name, input, preview }));
    },
    onSuccess: setPending,
  });
  const confirmMutation = useMutation({
    mutationFn: () => {
      if (!pending) throw new Error("没有待确认的购买");
      return confirmMyCommerce({
        ...pending.input,
        preview_token: String(pending.preview.preview_token),
        idempotency_key: createClientId("player-commerce"),
      });
    },
    onSuccess: () => {
      setPending(null);
      refresh();
    },
  });

  if (!shops.length) {
    return (
      <section className={cardCls}>
        <h2 className="mt-0 font-display text-2xl">当前场景商店</h2>
        <EmptyState
          hint="请让 DM 在“商人与商店”中创建商店，并绑定到当前 Scene；绑定后这里会自动出现。"
          title="当前 Scene 没有公开商店"
        />
      </section>
    );
  }
  return (
    <div className="space-y-4">
      <section className={`${cardCls} border-violet-700/60 bg-violet-950/15`}>
        <p className="m-0 text-2xs font-semibold uppercase tracking-[.18em] text-violet-300">玩家商店</p>
        <h2 className="mb-1 mt-1 font-display text-2xl">当前场景可购买的商品</h2>
        <p className="mb-0 text-sm text-stone-400">购买只会读取当前 Scene 已公开的库存。每次购买都先预览余额、库存和负重，再确认写入角色背包。</p>
        <p className="mb-0 mt-2 text-sm text-amber-200">当前钱包：{wallet ? copperLabel(wallet.copper) : "未建立钱包"}</p>
      </section>
      {shops.map((shop) => (
        <section className={cardCls} key={shop.merchant_id}>
          <h2 className="mt-0 font-display text-xl">{shop.name}</h2>
          {shop.description ? <p className="text-sm leading-6 text-stone-400">{shop.description}</p> : null}
          <ul className="m-0 grid gap-2 p-0 md:grid-cols-2">
            {shop.stock.map((item) => {
              const quantity = Math.max(1, Math.min(item.quantity, Number(quantities[item.id] || 1)));
              return (
                <li className="rounded border border-ink-700 bg-ink-950/40 p-3" key={item.id}>
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <strong className="text-sm text-parchment-100">{item.name}</strong>
                      <p className="mb-0 mt-1 text-xs text-stone-500">{copperLabel(item.price_copper)} · 库存 {item.quantity}{item.category ? ` · ${item.category}` : ""}</p>
                    </div>
                    <input
                      aria-label={`${item.name}购买数量`}
                      className={`${inputCls} w-20`}
                      disabled={!wallet || previewMutation.isPending}
                      max={item.quantity}
                      min={1}
                      onChange={(event) => setQuantities((current) => ({ ...current, [item.id]: event.target.value }))}
                      type="number"
                      value={quantities[item.id] ?? "1"}
                    />
                  </div>
                  <Button
                    className="mt-2 w-full"
                    disabled={!wallet?.id || wallet.version === undefined || item.quantity < 1 || !Number.isFinite(quantity)}
                    loading={previewMutation.isPending && previewMutation.variables?.item.id === item.id}
                    onClick={() => previewMutation.mutate({ item, quantity })}
                    size="sm"
                    variant="primary"
                  >预览购买</Button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      {previewMutation.isError ? <p className="text-sm text-red-300">{previewMutation.error.message}</p> : null}
      {pending ? (
        <section className="rounded-xl border border-amber-700/70 bg-amber-950/20 p-4">
          <h2 className="m-0 font-display text-xl text-amber-100">购买预览 · {pending.itemName}</h2>
          <p className="mb-0 mt-2 text-sm text-stone-300">支付 {copperLabel(pending.preview.total_copper)}；余额将从 {copperLabel(pending.preview.wallet_before)} 变为 {copperLabel(pending.preview.wallet_after)}。</p>
          <p className="mb-0 mt-1 text-xs text-stone-500">库存将从 {display(pending.preview.stock_before)} 变为 {display(pending.preview.stock_after)}。确认后商品会进入“我的角色”的装备/消耗品列表。</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button loading={confirmMutation.isPending} onClick={() => confirmMutation.mutate()} variant="primary">确认购买</Button>
            <Button disabled={confirmMutation.isPending} onClick={() => setPending(null)}>取消</Button>
          </div>
          {confirmMutation.isError ? <p className="mb-0 mt-2 text-sm text-red-300">{confirmMutation.error.message}</p> : null}
        </section>
      ) : null}
    </div>
  );
}

function SceneGridView({
  snapshot,
  interactionMode = "move",
  onMove,
  selectedTargetKey,
  selectableTargetKeys,
  onTargetSelect,
  onAimSelect,
  canSelectAimCell,
  selectedTargetKeys,
  affectedCellKeys,
  movementCellKeys,
  rangeCellKeys,
  enemyRangeCellKeys,
  dangerCellKeys,
  positionOverrides,
}: {
  snapshot: PlayerRoomSnapshot;
  interactionMode?: "move" | "action";
  onMove: (row: number, col: number) => void;
  selectedTargetKey?: string;
  selectableTargetKeys?: ReadonlySet<string>;
  onTargetSelect?: (targetKey: string) => void;
  onAimSelect?: (row: number, col: number) => void;
  canSelectAimCell?: (row: number, col: number) => boolean;
  selectedTargetKeys?: ReadonlySet<string>;
  affectedCellKeys?: ReadonlySet<string>;
  movementCellKeys?: ReadonlySet<string>;
  rangeCellKeys?: ReadonlySet<string>;
  enemyRangeCellKeys?: ReadonlySet<string>;
  dangerCellKeys?: ReadonlySet<string>;
  positionOverrides?: Record<string, { row: number; col: number }>;
}): ReactElement {
  const scene = snapshot.table.scene;
  const combat = snapshot.combat;
  if (!scene?.grid) return <EmptyState hint="等待 DM 选择带网格的场景。" title="尚无公开地图" />;
  const own = combat?.combatants.find((item) => item.is_own);
  const tokens = combat
    ? combat.combatants.flatMap((item) => {
        const position = positionOverrides?.[item.id] ?? item.position;
        return position ? [{
          id: item.id,
          entity_id: item.id,
          entity_type: item.entity_type,
          label: item.name,
          row: position.row,
          col: position.col,
          targetKey: `combatant:${item.id}`,
          isOwn: item.is_own,
        }] : [];
      })
    : scene.tokens.map((item) => ({
        ...item,
        targetKey: item.entity_id ? `${item.entity_type}:${item.entity_id}` : undefined,
        isOwn: item.entity_type === "character" && item.entity_id === snapshot.character?.id,
      }));
  return (
    <SceneMap
      canSelectCell={(row, col) => Boolean(
        interactionMode === "move"
        && combat?.is_my_turn
        && own
        && movementCellKeys?.has(`${row}:${col}`),
      )}
      compactCells={Boolean(combat)}
      grid={scene.grid}
      objects={scene.objects.map((item) => ({ ...item, targetKey: `object:${item.id}` }))}
      onCellSelect={onMove}
      onTargetSelect={onTargetSelect}
      onAimSelect={onAimSelect}
      canSelectAimCell={canSelectAimCell}
      affectedCellKeys={affectedCellKeys}
      dangerCellKeys={dangerCellKeys}
      enemyRangeCellKeys={enemyRangeCellKeys}
      movementCellKeys={movementCellKeys}
      rangeCellKeys={rangeCellKeys}
      selectedTargetKey={selectedTargetKey}
      selectedTargetKeys={selectedTargetKeys}
      selectableTargetKeys={selectableTargetKeys}
      title={combat ? "玩家战斗地图 · 与 DM 共用当前 Scene" : "玩家场景地图 · 点击绿色目标"}
      tokens={tokens}
    />
  );
}

function NoncombatActionPanel({
  snapshot,
  refresh,
}: {
  snapshot: PlayerRoomSnapshot;
  refresh: () => void;
}): ReactElement {
  const actions = snapshot.table.noncombat?.available_actions ?? [];
  const pending = snapshot.table.noncombat?.pending_actions ?? [];
  const [actionId, setActionId] = useState("");
  const [targetValue, setTargetValue] = useState("");
  const [message, setMessage] = useState("");
  const [rolls, setRolls] = useState<Record<string, string>>({});
  const selected = actions.find((item) => item.id === actionId);
  const targets = selected ? [
    ...(selected.target_types.includes("self") ? [{ value: `self:${snapshot.character?.id ?? ""}`, label: `自己 · ${snapshot.character?.name}` }] : []),
    ...(selected.target_types.includes("area") ? [{ value: "area:", label: "当前地点 / 区域" }] : []),
    ...snapshot.table.scene!.tokens
      .filter((token) => token.entity_id && selected.target_types.includes(token.entity_type as "npc" | "monster"))
      .map((token) => ({ value: `${token.entity_type}:${token.entity_id}`, label: `${token.entity_type === "npc" ? "NPC" : "怪物"} · ${token.label}` })),
    ...snapshot.table.scene!.objects
      .filter((object) => selected.target_types.includes("object")
        && (selected.kind !== "tool" || ["door", "trap", "treasure", "portal"].includes(object.object_type)))
      .map((object) => ({ value: `object:${object.id}`, label: `物体 · ${object.label}（${object.state}）` })),
  ] : [];
  const mutation = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => {
      setMessage("");
      refresh();
    },
  });
  const submit = () => {
    const [targetType, targetId] = targetValue.split(":");
    if (!selected || !targetType) return;
    mutation.mutate(() => planMyNoncombatAction(
      selected.id,
      targetType as "self" | "npc" | "monster" | "object" | "area",
      targetId || null,
      message || `${snapshot.character?.name}尝试使用${selected.name}`,
    ));
  };
  return (
    <section className={cardCls}>
      <h2 className="mt-0 font-display text-xl">场景行动与非伤害能力</h2>
      <p className="text-xs leading-5 text-stone-400">选择角色真实拥有的能力和公开目标。系统校验目标、距离、资源和投骰；世界状态仍由 DM 最终确认。</p>
      <label className="block text-xs text-stone-400">技能 / 工具 / 已准备法术
        <select className={`${inputCls} mt-1`} onChange={(event) => { setActionId(event.target.value); setTargetValue(""); }} value={actionId}>
          <option value="">请选择行动</option>
          {actions.map((action) => <option key={action.id} value={action.id}>{action.kind === "spell" ? "法术" : action.kind === "tool" ? "工具" : "技能"} · {action.name}</option>)}
        </select>
      </label>
      {selected ? <div className="mt-2 rounded border border-sky-900/60 bg-sky-950/20 p-3 text-xs leading-5 text-sky-100">
        <strong>{selected.name}</strong>
        <span className="block text-stone-400">{selected.description}</span>
        <span className="block">{selected.ability_label ? `检定属性：${selected.ability_label}` : "按法术规则处理"}{selected.range ? ` · 距离 ${selected.range}` : ""}{selected.concentration ? " · 需要专注" : ""}</span>
      </div> : null}
      {selected?.rule_plan ? <RuleBlockPlan source={{ rule_plan: selected.rule_plan }} title={`${selected.name} · 规则积木`} /> : null}
      <label className="mt-2 block text-xs text-stone-400">目标
        <select className={`${inputCls} mt-1`} disabled={!selected} onChange={(event) => setTargetValue(event.target.value)} value={targetValue}>
          <option value="">请选择合法目标</option>
          {targets.map((target) => <option key={target.value} value={target.value}>{target.label}</option>)}
        </select>
      </label>
      <div className="mt-3">
        <SceneGridView
          onMove={() => undefined}
          onTargetSelect={setTargetValue}
          selectedTargetKey={targetValue}
          selectableTargetKeys={new Set(targets.map((target) => target.value))}
          snapshot={snapshot}
        />
      </div>
      <textarea className={`${inputCls} mt-2`} onChange={(event) => setMessage(event.target.value)} placeholder="补充你具体想怎么做；例如：低声命令守卫“离开”。" rows={2} value={message} />
      <Button className="mt-2 w-full" disabled={!selected || !targetValue} loading={mutation.isPending} onClick={submit} variant="primary">按规则生成行动计划</Button>
      {mutation.isError ? <p className="text-sm text-red-300">{mutation.error.message}</p> : null}
      {pending.length ? <div className="mt-4 border-t border-ink-700 pt-3">
        <strong className="text-sm">待完成 / 待 DM 确认</strong>
        {pending.map((request) => {
          const resolution = request.payload.resolution;
          const awaiting = request.payload.phase === "awaiting_player_roll";
          return <article className="mt-2 rounded border border-violet-800/70 bg-violet-950/20 p-3" key={request.id}>
            <strong className="text-sm">{request.payload.action?.name ?? "非战斗行动"} → {request.payload.target?.name ?? "当前区域"}</strong>
            <p className="mb-1 mt-2 text-xs leading-5 text-stone-300">{resolution?.instruction ?? request.payload.proposal?.summary ?? "规则计划已完成，等待 DM 确认。"}</p>
            {resolution?.save ? <p className="my-1 text-xs text-violet-200">目标豁免已由系统计算：{display(resolution.save.total)} vs DC {display(resolution.save.dc)} · {resolution.save.success ? "成功" : "失败"}</p> : null}
            {awaiting ? <div className="mt-2 flex gap-2"><input aria-label={`${request.id}裸骰`} className={inputCls} max={20} min={1} onChange={(event) => setRolls((current) => ({ ...current, [request.id]: event.target.value }))} placeholder="输入 d20 裸骰" type="number" value={rolls[request.id] ?? ""} /><Button disabled={!rolls[request.id]} onClick={() => mutation.mutate(() => rollMyNoncombatAction(request.id, request.version, Number(rolls[request.id])))} variant="primary">提交裸骰</Button></div> : <span className="mt-2 block text-2xs text-amber-200">已完成规则结算，等待 DM 接受或驳回。</span>}
          </article>;
        })}
      </div> : null}
    </section>
  );
}

function PlayerCombatantStrip({
  activeId,
  combatants,
}: {
  activeId: string | null;
  combatants: PlayerCombatant[];
}): ReactElement {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const expanded = combatants.find((item) => item.id === expandedId);
  return (
    <section className="mb-3 rounded-lg border border-ink-700 bg-ink-950/45 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs">
        <strong>先攻轨道</strong>
        <span className="text-stone-500">当前单位有橙色描边；点击卡片查看公开战斗属性</span>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {combatants.map((item, index) => (
          <button
            aria-expanded={expandedId === item.id}
            className={`min-w-48 rounded-lg border p-3 text-left text-xs transition ${
              item.id === activeId
                ? "border-amber-400 bg-amber-950/25 ring-2 ring-amber-500/40"
                : expandedId === item.id
                  ? "border-sky-600 bg-sky-950/15"
                  : "border-ink-700 bg-ink-900 hover:border-ink-500"
            }`}
            key={item.id}
            onClick={() => setExpandedId((current) => current === item.id ? null : item.id)}
            type="button"
          >
            <span className="flex items-center gap-2">
              <b className="flex size-8 items-center justify-center rounded-full bg-ink-950 font-mono text-amber-200">{item.initiative}</b>
              <span><strong className="block">{item.name}</strong><span className="text-stone-500">{item.entity_type === "character" ? "玩家" : item.entity_type === "companion" ? (item.is_own ? "我的召唤物" : "召唤物") : item.entity_type === "npc" ? "NPC" : "怪物"} · 第 {index + 1} 位</span></span>
            </span>
            <span className="mt-2 grid grid-cols-3 gap-1 text-center text-2xs">
              <span className="rounded bg-ink-950 py-1"><b className="block">AC {item.armor_class}</b>护甲</span>
              <span className="rounded bg-ink-950 py-1"><b className="block">{item.hp === undefined ? item.health_status : `${item.hp}/${item.max_hp}`}</b>生命{item.temporary_hp ? ` +${item.temporary_hp} 临时` : ""}</span>
              <span className="rounded bg-ink-950 py-1"><b className="block">{item.speed_ft}尺</b>速度</span>
            </span>
          </button>
        ))}
      </div>
      {expanded ? (
        <div className="mt-2 rounded border border-sky-800/50 bg-sky-950/10 p-3" data-testid="player-combatant-detail">
          <div className="flex flex-wrap gap-2"><strong className="text-sky-100">{expanded.name} · 详细战斗卡</strong><span className="text-xs text-stone-500">状态：{expanded.conditions?.map(display).join("、") || expanded.health_status}</span></div>
          <div className="mt-2 grid grid-cols-3 gap-1 sm:grid-cols-6">
            {Object.entries(ABILITIES).map(([key, label]) => {
              const score = expanded.ability_scores[key] ?? 10;
              const modifier = Math.floor((score - 10) / 2);
              return <span className="rounded border border-ink-700 p-2 text-center text-2xs text-stone-500" key={key}>{label}<b className="block text-sm text-parchment-100">{score}（{modifier >= 0 ? "+" : ""}{modifier}）</b></span>;
            })}
          </div>
          <p className="mb-0 mt-2 text-xs text-stone-400">
            AC {expanded.armor_class} · 速度 {expanded.speed_ft}尺
            {expanded.damage_resistances?.length ? ` · 抗性 ${expanded.damage_resistances.join("、")}` : ""}
            {expanded.damage_vulnerabilities?.length ? ` · 易伤 ${expanded.damage_vulnerabilities.join("、")}` : ""}
            {expanded.damage_immunities?.length ? ` · 免疫 ${expanded.damage_immunities.join("、")}` : ""}
          </p>
          {expanded.active_effects?.length ? <p className="mb-0 mt-2 text-xs text-violet-200">已生效：{expanded.active_effects.map((effect) => {
            const block = effect.rule_block;
            const detail = block && typeof block === "object"
              ? [block.stat, block.operation, block.value, block.damage_type, block.expression, block.condition]
                .filter((value) => value != null)
                .map((value) => display(value))
                .join(" ")
              : "";
            const lifecycle = effect.duration_unit === "until_save"
              ? "（持续至重复豁免成功；未收到待掷骰请求前仍未结算）"
              : "";
            return `${effect.name}${detail ? `（${detail}）` : ""}${lifecycle}`;
          }).join("、")}</p> : null}
          {expanded.actions?.length ? <div className="mt-2 flex flex-wrap gap-1">{expanded.actions.map((action, index) => <span className="rounded border border-violet-800/50 bg-violet-950/20 px-2 py-1 text-2xs text-violet-200" key={`${display(action)}-${index}`}>{typeof action === "string" ? action : [display(action.name ?? `动作 ${index + 1}`), display(action.damage ?? ""), display(action.range ?? ""), display(action.cost ?? "")].filter(Boolean).join(" · ")}</span>)}</div> : <p className="mb-0 mt-2 text-xs text-stone-500">没有可公开的动作资料。</p>}
        </div>
      ) : null}
    </section>
  );
}

type PlayerCombatLogEntry = PlayerCombatSnapshot["log"][number];

function combatLogKey(entry: PlayerCombatLogEntry): string {
  return `${entry.id}:${entry.status}`;
}

function CombatView({ snapshot, refresh }: { snapshot: PlayerRoomSnapshot; refresh: () => void }): ReactElement {
  const combat = snapshot.combat;
  const [combatMode, setCombatMode] = useState<"move" | "action">("move");
  const [selectedControlledUnitId, setSelectedControlledUnitId] = useState("");
  const [actionName, setActionName] = useState("");
  const [companionId, setCompanionId] = useState("");
  const [summonCount, setSummonCount] = useState("1");
  const [slotLevel, setSlotLevel] = useState(0);
  const [targetId, setTargetId] = useState("");
  const [attackTotal, setAttackTotal] = useState("");
  const [damageTotal, setDamageTotal] = useState("");
  const [useDivineSmite, setUseDivineSmite] = useState(false);
  const [divineSmiteSlotLevel, setDivineSmiteSlotLevel] = useState("1");
  const [divineSmiteDamageTotal, setDivineSmiteDamageTotal] = useState("");
  const [damageComponentTotals, setDamageComponentTotals] = useState<Record<string, string>>({});
  const [targetDamageComponentTotals, setTargetDamageComponentTotals] = useState<Record<string, string>>({});
  const [specialRow, setSpecialRow] = useState("");
  const [specialCol, setSpecialCol] = useState("");
  const [teleportDestinations, setTeleportDestinations] = useState<Record<string, { row: string; col: string }>>({});
  const [specialTemplate, setSpecialTemplate] = useState("");
  const [specialDestinationId, setSpecialDestinationId] = useState("");
  const [specialFormArmorClass, setSpecialFormArmorClass] = useState("");
  const [specialFormHp, setSpecialFormHp] = useState("");
  const [specialFormMaxHp, setSpecialFormMaxHp] = useState("");
  const [specialFormSpeed, setSpecialFormSpeed] = useState("");
  const [specialCount, setSpecialCount] = useState("1");
  const [specialEffectIds, setSpecialEffectIds] = useState("");
  const [dispelCheckTotal, setDispelCheckTotal] = useState("");
  const [dispelCheckDc, setDispelCheckDc] = useState("");
  const [choiceSelections, setChoiceSelections] = useState<Record<string, string[]>>({});
  const [areaOrigins, setAreaOrigins] = useState<Record<string, { row: string; col: string }>>({});
  const [aimPoint, setAimPoint] = useState<GridPoint | null>(null);
  const [summonPosition, setSummonPosition] = useState<GridPoint | null>(null);
  const [reactionTrigger, setReactionTrigger] = useState("");
  const [preDamageReductionRolls, setPreDamageReductionRolls] = useState<Record<string, string>>({});
  const [deflectRedirectTargets, setDeflectRedirectTargets] = useState<Record<string, string>>({});
  const [deflectRedirectSaves, setDeflectRedirectSaves] = useState<Record<string, string>>({});
  const [deflectRedirectDamageRolls, setDeflectRedirectDamageRolls] = useState<Record<string, string[]>>({});
  const [criticalHit, setCriticalHit] = useState(false);
  const [rolls, setRolls] = useState<Record<string, string>>({});
  const [deathSaveRoll, setDeathSaveRoll] = useState("");
  const [endTurnAfterAttack, setEndTurnAfterAttack] = useState(true);
  const [disengage, setDisengage] = useState(false);
  const [maneuverAction, setManeuverAction] = useState<PlayerCombatManeuver["action_type"]>("dash");
  const [maneuverTargetId, setManeuverTargetId] = useState("");
  const [maneuverOutcome, setManeuverOutcome] = useState<"" | "success" | "failure">("");
  const [maneuverNote, setManeuverNote] = useState("");
  const [helpTrigger, setHelpTrigger] = useState("");
  const [readyTrigger, setReadyTrigger] = useState("");
  const [readyResponse, setReadyResponse] = useState("");
  const [shoveMode, setShoveMode] = useState<"prone" | "push">("prone");
  const [pushDistance, setPushDistance] = useState("5");
  const [itemId, setItemId] = useState("");
  const [itemVersion, setItemVersion] = useState("1");
  const [objectId, setObjectId] = useState("");
  const [objectState, setObjectState] = useState<NonNullable<PlayerCombatManeuver["object_state"]>>("open");
  const [objectVersion, setObjectVersion] = useState("1");
  const [lastResolution, setLastResolution] = useState("");
  const [actionQueue, setActionQueue] = useState<PlayerCombatLogEntry[]>([]);
  const [presentation, setPresentation] = useState<PlayerCombatLogEntry | null>(null);
  const [positionOverrides, setPositionOverrides] = useState<Record<string, { row: number; col: number }>>({});
  const seenCombatLogKeys = useRef<Set<string>>(new Set());
  const replayCombatId = useRef<string | null>(null);
  useEffect(() => {
    if (!combat) return;
    if (replayCombatId.current !== combat.id) {
      replayCombatId.current = combat.id;
      seenCombatLogKeys.current = new Set(combat.log.map(combatLogKey));
      setActionQueue([]);
      setPresentation(null);
      setPositionOverrides({});
      return;
    }
    const unseen = combat.log
      .filter((entry) => !seenCombatLogKeys.current.has(combatLogKey(entry)))
      .reverse();
    if (!unseen.length) return;
    for (const entry of unseen) seenCombatLogKeys.current.add(combatLogKey(entry));
    const visibleEnemyEvents = unseen.filter((entry) => {
      const actor = combat.combatants.find((item) => item.id === entry.actor_combatant_id);
      return actor?.entity_type === "monster"
        || actor?.entity_type === "npc"
        || entry.action_type === "advance_turn";
    });
    if (visibleEnemyEvents.length) {
      setActionQueue((current) => [...current, ...visibleEnemyEvents]);
    }
  }, [combat]);
  useEffect(() => {
    if (presentation || !actionQueue.length) return;
    const nextPresentation = actionQueue[0];
    if (!nextPresentation) return;
    setPresentation(nextPresentation);
    setActionQueue((current) => current.slice(1));
  }, [actionQueue, presentation]);
  useEffect(() => {
    if (!presentation) return;
    let cancelled = false;
    const wait = (milliseconds: number) => new Promise<void>((resolve) => {
      window.setTimeout(resolve, milliseconds);
    });
    const replay = async () => {
      const actorId = presentation.actor_combatant_id;
      const from = presentation.from_position;
      const to = presentation.to_position;
      if (presentation.action_type === "move" && actorId && from && to) {
        setPositionOverrides((current) => ({ ...current, [actorId]: from }));
        for (const point of gridLine(from, to).slice(1)) {
          await wait(240);
          if (cancelled) return;
          setPositionOverrides((current) => ({ ...current, [actorId]: point }));
        }
        await wait(700);
        if (cancelled) return;
        setPositionOverrides((current) => {
          const next = { ...current };
          delete next[actorId];
          return next;
        });
      } else {
        await wait(presentation.action_type === "advance_turn" ? 850 : 1500);
      }
      if (!cancelled) setPresentation(null);
    };
    void replay();
    return () => {
      cancelled = true;
    };
  }, [presentation]);
  const activeOwn = combat?.combatants.find(
    (item) => item.id === combat.active_combatant_id && item.is_own,
  );
  const ownCombatants = combat?.combatants.filter((item) => item.is_own) ?? [];
  const selectedControlledUnit = ownCombatants.find((item) => item.id === selectedControlledUnitId);
  const own = activeOwn ?? selectedControlledUnit ?? ownCombatants[0];
  const ownUntilSaveEffects = ownCombatants.flatMap((combatant) => (
    (combatant.active_effects ?? [])
      .filter((effect) => effect.duration_unit === "until_save")
      .map((effect) => ({ combatant, effect }))
  ));
  const companionTurn = activeOwn?.entity_type === "companion";
  const actions = companionTurn
    ? (activeOwn?.actions ?? []).filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    : [
        ...(snapshot.character?.actions ?? []),
        ...(snapshot.character?.spells ?? []),
      ].filter((item): item is Record<string, unknown> => {
        if (typeof item !== "object" || item === null) return false;
        const record = item as Record<string, unknown>;
        if (!(snapshot.character?.spells ?? []).includes(item)) return true;
        if (record.prepared === false) return false;
        const plan = record.rule_plan as { blocks?: unknown[] } | undefined;
        const hasSummon = Array.isArray(plan?.blocks)
          && plan.blocks.some((block) => typeof block === "object" && block !== null && (block as { kind?: unknown }).kind === "summon");
        const hasSupportEffect = Array.isArray(plan?.blocks)
          && plan.blocks.some((block) => typeof block === "object" && block !== null && [
            "heal", "condition", "modifier", "defense", "repeat",
          ].includes(String((block as { kind?: unknown }).kind)));
        const hasChoiceSensitiveEffect = Array.isArray(plan?.blocks)
          && plan.blocks.some((block) => typeof block === "object" && block !== null && [
            "teleport", "transformation", "creation", "dispel", "area_effect", "choice",
          ].includes(String((block as { kind?: unknown }).kind)));
        return Boolean(
          damageFormulaForAction(record)
          || record.attack_bonus !== undefined
          || record.to_hit !== undefined
          || (record.save_dc !== undefined && record.save_ability !== undefined)
          || hasSummon
          || hasSupportEffect
          || hasChoiceSensitiveEffect,
        );
      });
  const enemies = combat?.combatants.filter((item) => (
    item.health_status !== "倒地"
    && (item.disposition === "enemy" || item.entity_type === "monster" || item.entity_type === "npc")
  )) ?? [];
  const friendlyTargets = combat?.combatants.filter((item) => (
    item.health_status !== "倒地"
    && item.disposition !== "enemy"
    && item.entity_type !== "monster"
    && item.entity_type !== "npc"
  )) ?? [];
  const selectedActionBase = actions.find((item) => display(item.name) === actionName);
  const isRuntimeFeatureAction = selectedActionBase?.runtime_feature === true;
  const featureNeedsHealingRoll = isRuntimeFeatureAction
    && selectedActionBase?.resolution_kind === "healing";
  const divineSmiteRider = Array.isArray(selectedActionBase?.attack_riders)
    ? selectedActionBase.attack_riders.find((item): item is Record<string, unknown> => (
        typeof item === "object"
        && item !== null
        && (item as Record<string, unknown>).id === "divine_smite:bonus_damage"
      ))
    : undefined;
  const divineSmiteSlotOptions = Array.from({ length: 5 }, (_, index) => index + 1)
    .filter((level) => snapshot.character?.resources?.[`spell_slots_${level}`] != null);
  const divineSmiteDiceCount = Math.min(5, Number(divineSmiteSlotLevel) + 1);
  const divineSmiteReportedTotal = Number(divineSmiteDamageTotal);
  const divineSmiteDamageValid = !useDivineSmite || (
    Boolean(divineSmiteRider)
    && divineSmiteSlotOptions.includes(Number(divineSmiteSlotLevel))
    && Number.isInteger(divineSmiteReportedTotal)
    && divineSmiteReportedTotal >= divineSmiteDiceCount * (criticalHit ? 2 : 1)
    && divineSmiteReportedTotal <= divineSmiteDiceCount * 8 * (criticalHit ? 2 : 1)
  );
  const selectedAction = useMemo(() => {
    if (!selectedActionBase) return undefined;
    const baseLevel = Number(selectedActionBase.spell_level ?? 0);
    if (baseLevel <= 0 || slotLevel < baseLevel) return selectedActionBase;
    return {
      ...selectedActionBase,
      damage: upcastExpression(typeof selectedActionBase.damage === "string" ? selectedActionBase.damage : "", slotLevel, baseLevel, Number(selectedActionBase.upcast_damage_dice ?? 0)),
      healing: upcastExpression(typeof selectedActionBase.healing === "string" ? selectedActionBase.healing : "", slotLevel, baseLevel, Number(selectedActionBase.upcast_healing_dice ?? 0)),
    };
  }, [selectedActionBase, slotLevel]);
  const selectedSpellLevel = Number(selectedActionBase?.spell_level ?? 0);
  const selectedSummonBlock = (() => {
    const plan = selectedActionBase?.rule_plan;
    const blocks = plan && typeof plan === "object" && Array.isArray((plan as { blocks?: unknown[] }).blocks)
      ? (plan as { blocks: unknown[] }).blocks
      : [];
    return blocks.find((block): block is { kind: "summon"; creature_ref?: unknown; enters_combat?: unknown; count?: unknown; count_expression?: unknown } => (
      typeof block === "object" && block !== null && (block as { kind?: unknown }).kind === "summon"
    ));
  })();
  const selectedRuleBlocks = (() => {
    const plan = selectedActionBase?.rule_plan;
    const blocks = plan && typeof plan === "object" && Array.isArray((plan as { blocks?: unknown[] }).blocks)
      ? (plan as { blocks: unknown[] }).blocks
      : [];
    return blocks.filter((block): block is Record<string, unknown> => typeof block === "object" && block !== null);
  })();
  const selectedDamageBlocks = selectedRuleBlocks.filter((block) => block.kind === "damage" && typeof block.id === "string");
  const sharedDamageBlocks = selectedDamageBlocks.filter((block) => block.shared_roll !== false);
  const targetDamageBlocks = selectedDamageBlocks.filter((block) => block.shared_roll === false);
  const areaEffectBlocks = selectedRuleBlocks.filter((block) => block.kind === "area_effect" && typeof block.id === "string");
  const areaChildIds = new Set(
    areaEffectBlocks.flatMap((block) => Array.isArray(block.effect_block_ids)
      ? block.effect_block_ids.filter((value): value is string => typeof value === "string")
      : []),
  );
  const selectedChoiceBlocks = selectedRuleBlocks.filter((block) => block.kind === "choice" && typeof block.id === "string");
  const isSupportAction = selectedRuleBlocks.some((block) => [
    "heal", "condition", "modifier", "defense", "repeat",
  ].includes(String(block.kind))) && !selectedRuleBlocks.some((block) => [
    "summon", "teleport", "transformation", "creation", "dispel",
  ].includes(String(block.kind))) && !selectedRuleBlocks.some((block) => [
    "damage", "save", "move",
  ].includes(String(block.kind)) && !areaChildIds.has(String(block.id)));
  const specialRuleKinds = selectedRuleBlocks
    .map((block) => String(block.kind))
    .filter((kind): kind is "teleport" | "transformation" | "creation" | "dispel" | "area_effect" => [
      "teleport", "transformation", "creation", "dispel", "area_effect",
    ].includes(kind));
  const needsChoiceSensitiveInput = specialRuleKinds.length > 0 || selectedChoiceBlocks.length > 0;
  const isSpecialAction = specialRuleKinds.length > 0;
  const isDispelAction = specialRuleKinds.includes("dispel");
  const hasAreaEffect = areaEffectBlocks.length > 0;
  const hasHealingBlock = selectedRuleBlocks.some((block) => block.kind === "heal");
  const isAutoHitAction = selectedAction?.auto_hit === true
    || selectedRuleBlocks.some((block) => block.kind === "auto_hit");
  const savingThrow = savingThrowForAction(selectedAction);
  const isSavingThrowAction = Boolean(savingThrow);
  const usesLegacyDamageTotal = sharedDamageBlocks.length === 1 && targetDamageBlocks.length === 0;
  const requiresComponentTotals = selectedDamageBlocks.length > 0 && !usesLegacyDamageTotal;
  const damageOrSaveBlocks = selectedRuleBlocks.some((block) => ["damage", "save", "move"].includes(String(block.kind)));
  const selectedActionCost = playerActionCost(selectedAction);
  const hasReactionCost = selectedActionCost === "reaction";
  const needsReactionTriggerInput = hasReactionCost;
  const summonEntersCombat = selectedSummonBlock?.enters_combat !== false;
  const availableSlotLevels = selectedSpellLevel > 0
    ? Array.from({ length: 10 - selectedSpellLevel }, (_, index) => selectedSpellLevel + index)
      .filter((level) => snapshot.character?.resources?.[`spell_slots_${level}`] != null)
    : [];
  const availableSummonCompanions = (snapshot.character?.companions ?? []).filter((item) => item.active);
  const targeting = targetingForAction(selectedAction);
  const isAreaTargeting = Boolean(targeting && targeting.shape !== "single");
  const targetCandidates = isRuntimeFeatureAction
    ? (activeOwn ? [activeOwn] : [])
    : isAreaTargeting
    ? enemies
    : hasAreaEffect
      ? (activeOwn ? [activeOwn] : [])
    : isDispelAction
      ? [...friendlyTargets, ...enemies]
      : isSupportAction || specialRuleKinds.includes("teleport") || specialRuleKinds.includes("transformation") || specialRuleKinds.includes("creation")
        ? friendlyTargets
        : enemies;
  const selectedTarget = targetCandidates.find((item) => item.id === targetId);
  const rawAttackBonus = selectedAction?.attack_bonus ?? selectedAction?.to_hit;
  const parsedAttackBonus = rawAttackBonus === undefined || rawAttackBonus === null || rawAttackBonus === ""
    ? NaN
    : Number(rawAttackBonus);
  const attackBonus = Number.isFinite(parsedAttackBonus) ? parsedAttackBonus : null;
  const actorPosition = own?.position;
  const grid = snapshot.table.scene?.grid;
  const automaticCriticalForSelectedTarget = Boolean(
    !isSavingThrowAction
    && !isAutoHitAction
    && targeting?.shape === "single"
    && actorPosition
    && selectedTarget?.position
    && grid
    && gridDistanceFt(actorPosition, selectedTarget.position, grid.cell_size_ft) <= 5
    && hasAutomaticCriticalCondition(selectedTarget)
  );
  const damageInstruction = automaticCriticalForSelectedTarget
    ? criticalDamageExpression(damageInstructionForAction(selectedAction))
    : damageInstructionForAction(selectedAction);
  const aimPosition = aimPoint ?? selectedTarget?.position ?? (targeting?.originSelf ? actorPosition : undefined);
  const rangeCellKeys = new Set<string>();
  if (grid && actorPosition && targeting) {
    const aimRangeFt = targeting.originSelf
      ? Math.max(targeting.sizeFt ?? grid.cell_size_ft, grid.cell_size_ft)
      : targeting.rangeFt;
    for (let row = 1; row <= grid.height; row += 1) {
      for (let col = 1; col <= grid.width; col += 1) {
        if (gridDistanceFt(actorPosition, { row, col }, grid.cell_size_ft) <= aimRangeFt) {
          if (hasLineOfSight(grid, actorPosition, { row, col })) {
            rangeCellKeys.add(`${row}:${col}`);
          }
        }
      }
    }
  }
  const affectedCells = grid && actorPosition && (aimPosition || targeting?.originSelf) && targeting
      ? getTargetingCells(
        {
          width: grid.width,
          height: grid.height,
          cell_size_ft: grid.cell_size_ft,
          cells: grid.cells,
        },
        actorPosition,
        aimPosition ?? actorPosition,
        targeting,
      )
    : [];
  const affectedCellKeys = new Set(affectedCells.map((cell) => `${cell.row}:${cell.col}`));
  const elevationValidForTarget = (enemy: PlayerCombatant, selectedAim = aimPosition): boolean => {
    if (!targeting || !grid || !actorPosition || !enemy.position || targeting.shape === "single") {
      return true;
    }
    const targetAim = selectedAim ?? actorPosition;
    return evaluateTargetingElevation(
      grid,
      actorPosition,
      targetAim,
      enemy.position,
      targeting,
      explicitElevationFt(actorPosition),
      explicitElevationFt(enemy.position),
    ).valid;
  };
  const affectedEnemies = targeting && aimPosition
    ? (targeting.shape === "single"
        ? (selectedTarget ? [selectedTarget] : [])
        : targetCandidates.filter((enemy) => (
            enemy.position
            && affectedCellKeys.has(`${enemy.position.row}:${enemy.position.col}`)
            && elevationValidForTarget(enemy)
          )))
    : [];
  const targetableEnemies = targetCandidates.filter((enemy) => (
    enemy.position
    && (isAreaTargeting
      ? affectedCellKeys.has(`${enemy.position.row}:${enemy.position.col}`)
        && elevationValidForTarget(enemy)
      : rangeCellKeys.has(`${enemy.position.row}:${enemy.position.col}`))
  ));
  const aimSelectionEnabled = Boolean(
    combat?.is_my_turn
    && combatMode === "action"
    && own
    && (isAreaTargeting || (selectedSummonBlock && summonEntersCombat)),
  );
  const handleAimSelect = (row: number, col: number) => {
    const point = { row, col };
    if (selectedSummonBlock && summonEntersCombat) {
      setSummonPosition(point);
      return;
    }
    if (!targeting || !actorPosition || !grid) return;
    setAimPoint(point);
    const cells = getTargetingCells(
      { width: grid.width, height: grid.height, cell_size_ft: grid.cell_size_ft, cells: grid.cells },
      actorPosition,
      point,
      targeting,
    );
    const keys = new Set(cells.map((cell) => `${cell.row}:${cell.col}`));
    const firstAffected = targetCandidates.find((enemy) => (
      enemy.position
      && keys.has(`${enemy.position.row}:${enemy.position.col}`)
      && elevationValidForTarget(enemy, point)
    ));
    setTargetId(firstAffected?.id ?? "");
  };
  const canSelectAimCell = (row: number, col: number) => {
    const key = `${row}:${col}`;
    if (!aimSelectionEnabled || !rangeCellKeys.has(key)) return false;
    if (selectedSummonBlock && summonEntersCombat) {
      return !(combat?.combatants ?? []).some((item) => item.position?.row === row && item.position?.col === col);
    }
    return true;
  };
  const visibleAffectedCellKeys = new Set([
    ...affectedCellKeys,
    ...(summonPosition ? [`${summonPosition.row}:${summonPosition.col}`] : []),
  ]);
  const presentationActor = combat?.combatants.find(
    (item) => item.id === presentation?.actor_combatant_id,
  );
  const presentationTargets = (presentation?.target_combatant_ids ?? [])
    .map((id) => combat?.combatants.find((item) => item.id === id))
    .filter((item): item is PlayerCombatant => Boolean(item));
  const replayTargetCellKeys = new Set(
    presentationTargets
      .filter((item) => item.position)
      .map((item) => `${item.position?.row}:${item.position?.col}`),
  );
  const displayAffectedCellKeys = new Set([...affectedCellKeys, ...replayTargetCellKeys]);
  const activeCombatant = combat?.combatants.find(
    (item) => item.id === combat.active_combatant_id,
  );
  const activeEnemyAiControlled = activeCombatant
    ? isEnemyAiControlledCombatant(activeCombatant.entity_type, {
        controller: activeCombatant.controller,
        disposition: activeCombatant.disposition,
        enemy_ai_mode: activeCombatant.summon?.enemy_ai_mode,
      })
    : false;
  const pendingRoll = combat?.pending_rolls[0];
  const pendingActor = combat?.combatants.find(
    (item) => item.id === pendingRoll?.actor_combatant_id,
  );
  const pendingAction = pendingActor?.actions.find(
    (item): item is Record<string, unknown> => (
      typeof item === "object"
      && item !== null
      && display(item.name) === pendingRoll?.action_name
    ),
  );
  const pendingTargeting = targetingForAction(pendingAction);
  const activeEnemyAction = !combat?.is_my_turn && activeEnemyAiControlled
    ? activeCombatant?.active_action ?? undefined
    : undefined;
  const activeEnemyTargeting = targetingForAction(activeEnemyAction);
  const presentationType = presentationActor?.entity_type;
  const presentationStatus = presentation
    ? presentation.action_type === "advance_turn"
      ? "正在展示回合切换"
      : presentationType === "npc"
        ? "正在展示 NPC 行动"
      : presentationType === "monster" || presentationType === "companion"
        ? "正在展示敌方行动"
          : "正在展示玩家行动"
    : null;
  const dangerCellKeys = new Set(
    grid
    && pendingActor?.position
    && own?.position
    && pendingTargeting
      ? getTargetingCells(
        {
          width: grid.width,
          height: grid.height,
          cell_size_ft: grid.cell_size_ft,
          cells: grid.cells,
        },
        pendingActor.position,
        own.position,
        pendingTargeting,
      ).map((cell) => `${cell.row}:${cell.col}`)
      : [],
  );
  const activeEnemyDangerCellKeys = new Set(
    activeCombatant?.entity_type === "monster"
    && activeCombatant.position
    && own?.position
    && activeEnemyTargeting
      ? getTargetingCells(
        {
          width: grid?.width ?? 0,
          height: grid?.height ?? 0,
          cell_size_ft: grid?.cell_size_ft ?? 5,
          cells: grid?.cells,
        },
        activeCombatant.position,
        own.position,
        activeEnemyTargeting,
      ).map((cell) => `${cell.row}:${cell.col}`)
      : [],
  );
  const activeEnemyRangeCellKeys = new Set(
    activeCombatant?.entity_type === "monster"
    && activeCombatant.position
    && grid
    && activeEnemyTargeting
      ? Array.from({ length: grid.width * grid.height }, (_, index) => ({
          row: Math.floor(index / grid.width) + 1,
          col: index % grid.width + 1,
        }))
        .filter((point) => (
          gridDistanceFt(activeCombatant.position!, point, grid.cell_size_ft) <= activeEnemyTargeting.rangeFt
          && hasLineOfSight(grid, activeCombatant.position!, point)
        ))
        .map((point) => `${point.row}:${point.col}`)
      : [],
  );
  const visibleEnemyDangerCellKeys = new Set([...dangerCellKeys, ...activeEnemyDangerCellKeys]);
  const movementCellKeys = new Set<string>();
  if (combat?.is_my_turn && grid && actorPosition && (own?.movement_remaining_ft ?? 0) > 0) {
    const occupied = new Set(
      (combat?.combatants ?? [])
        .filter((item) => item.id !== own?.id && item.position)
        .map((item) => `${item.position?.row}:${item.position?.col}`),
    );
    const blocked = new Set<string>();
    const difficult = new Set<string>();
    for (const object of snapshot.table.scene?.objects ?? []) {
      for (let row = object.row; row < object.row + object.height_cells; row += 1) {
        for (let col = object.col; col < object.col + object.width_cells; col += 1) {
          const key = `${row}:${col}`;
          if (object.object_type === "terrain" && object.state === "active") difficult.add(key);
          if (
            object.object_type === "wall"
            || (object.object_type === "door" && ["active", "closed"].includes(object.state))
            || (["cover", "furniture"].includes(object.object_type) && object.state === "active")
          ) blocked.add(key);
        }
      }
    }
    for (let row = 1; row <= grid.height; row += 1) {
      for (let col = 1; col <= grid.width; col += 1) {
        const key = `${row}:${col}`;
        if (occupied.has(key) || blocked.has(key)) continue;
        const path = gridLine(actorPosition, { row, col });
        if (path.slice(1).some((cell) => blocked.has(`${cell.row}:${cell.col}`))) continue;
        const spent = path.slice(1).reduce(
          (total, cell) => total + grid.cell_size_ft * (difficult.has(`${cell.row}:${cell.col}`) ? 2 : 1),
          0,
        );
        if (spent <= (own?.movement_remaining_ft ?? 0)) movementCellKeys.add(key);
      }
    }
  }
  const selectedResourceKey = typeof selectedAction?.resource_key === "string"
    ? selectedAction.resource_key
    : undefined;
  const selectedResource = selectedResourceKey
    ? snapshot.character?.resources?.[selectedResourceKey] as { current?: number; max?: number; label?: string } | undefined
    : undefined;
  const selectedResourceCost = Math.max(1, Number(selectedAction?.resource_cost ?? 1));
  const selectedResourceAvailable = !selectedResourceKey
    || Number(selectedResource?.current ?? 0) >= selectedResourceCost;
  const selectedActionAvailable = Boolean(
    own
    && playerHasActionEconomy(own, selectedActionCost)
    && selectedResourceAvailable,
  );
  const effectiveEndTurnAfterAttack = selectedActionCost === "reaction" ? false : endTurnAfterAttack;
  const maneuverNeedsTarget = ["grapple", "shove", "help", "search"].includes(maneuverAction);
  const maneuverNeedsOutcome = [
    "grapple", "shove", "search", "hide", "use_item", "object_interaction",
  ].includes(maneuverAction);
  const maneuverNeedsNote = maneuverNeedsOutcome || ["help", "ready"].includes(maneuverAction);
  const maneuverTarget = combat?.combatants.find((item) => item.id === maneuverTargetId);
  const maneuverObject = snapshot.table.scene?.objects.find((item) => item.id === objectId);
  const maneuverValid = Boolean(
    combat
    && own
    && combat.is_my_turn
    && combat.status !== "ended"
    && (own.action_available || own.bonus_action_available || own.reaction_available)
    && (!maneuverNeedsTarget || (maneuverTarget && maneuverTarget.version))
    && (!maneuverNeedsOutcome || maneuverOutcome)
    && (!maneuverNeedsNote || maneuverNote.trim())
    && (maneuverAction !== "help" || helpTrigger.trim())
    && (maneuverAction !== "ready" || (readyTrigger.trim() && readyResponse.trim()))
    && (maneuverAction !== "shove" || (shoveMode === "prone" || Number(pushDistance) > 0))
    && (maneuverAction !== "use_item" || itemId.trim())
    && (maneuverAction !== "object_interaction" || (maneuverObject && objectVersion.trim()))
  );
  const teleportBlock = selectedRuleBlocks.find((block) => block.kind === "teleport");
  const transformationBlock = selectedRuleBlocks.find((block) => block.kind === "transformation");
  const creationBlock = selectedRuleBlocks.find((block) => block.kind === "creation");
  const dispelBlock = selectedRuleBlocks.find((block) => block.kind === "dispel");
  const teleportDestinationKind = ruleFieldText(teleportBlock, "destination_kind", "chosen_space");
  const transformationNeedsStats = ["polymorph", "shapechange", "alter"].includes(ruleFieldText(transformationBlock, "mode", "polymorph"));
  const selectedEffectIds = specialEffectIds.split(",").map((item) => item.trim()).filter(Boolean);
  const choicesValid = selectedChoiceBlocks.every((choice) => {
    const selected = choiceSelections[String(choice.id)] ?? [];
    const minimum = Number(choice.minimum_choices ?? 1);
    const maximum = Number(choice.maximum_choices ?? 1);
    return selected.length >= minimum && selected.length <= maximum;
  });
  const componentInputValid = (
    (sharedDamageBlocks.length <= 1 || sharedDamageBlocks.every((block) => {
      const value = damageComponentTotals[String(block.id)];
      return value !== undefined && value !== "" && Number(value) >= 0;
    }))
    && (!targetDamageBlocks.length || affectedEnemies.every((target) => targetDamageBlocks.every((block) => {
      const value = targetDamageComponentTotals[`${target.id}:${String(block.id)}`];
      return value !== undefined && value !== "" && Number(value) >= 0;
    })))
  );
  const specialInputs = (): Record<string, unknown> => {
    const result: Record<string, unknown> = {};
    if (specialRuleKinds.includes("teleport")) {
      if (teleportDestinationKind === "object") {
        result.teleport = { object_id: specialDestinationId };
      } else if (teleportDestinationKind === "creature") {
        result.teleport = { combatant_id: specialDestinationId };
      } else if (affectedEnemies.length > 1) {
        result.teleport = {
          destinations: Object.fromEntries(affectedEnemies.map((target) => {
            const destination = teleportDestinations[target.id] ?? { row: "", col: "" };
            return [target.id, { row: Number(destination.row), col: Number(destination.col) }];
          })),
        };
      } else {
        result.teleport = { row: Number(specialRow), col: Number(specialCol) };
      }
    }
    if (specialRuleKinds.includes("transformation")) {
      const form: Record<string, unknown> = { form_ref: specialTemplate.trim() };
      if (transformationNeedsStats) {
        form.armor_class = Number(specialFormArmorClass);
        form.hp = Number(specialFormHp);
        form.max_hp = Number(specialFormMaxHp);
        form.speed_ft = Number(specialFormSpeed);
      }
      result.transformation = { form };
    }
    if (specialRuleKinds.includes("creation")) {
      result.creation = {
        template_ref: specialTemplate.trim(),
        count: Number(specialCount),
        row: Number(specialRow),
        col: Number(specialCol),
      };
    }
    if (areaEffectBlocks.length) {
      result.areas = Object.fromEntries(areaEffectBlocks.map((block) => {
        if (block.origin === "self") return [String(block.id), {}];
        const origin = areaOrigins[String(block.id)] ?? { row: "", col: "" };
        return [String(block.id), { row: Number(origin.row), col: Number(origin.col) }];
      }));
    }
    if (aimPoint) result.aim_point = { row: aimPoint.row, col: aimPoint.col };
    if (selectedChoiceBlocks.length) {
      result.choice_selections = Object.fromEntries(selectedChoiceBlocks.map((choice) => {
        const values = choiceSelections[String(choice.id)] ?? [];
        return [String(choice.id), values.length === 1 ? values[0] : values];
      }));
    }
    if (isDispelAction) {
      result.effect_ids = selectedEffectIds;
      if (dispelBlock?.check_required === true) {
        result.dispel_checks = Object.fromEntries(selectedEffectIds.map((effectId) => [
          effectId,
          { total: Number(dispelCheckTotal), dc: Number(dispelCheckDc) },
        ]));
      }
    }
    if (reactionTrigger.trim()) result.reaction_trigger = reactionTrigger.trim();
    if (useDivineSmite && divineSmiteRider) {
      result.attack_rider_eligibility = { "divine_smite:bonus_damage": true };
      result.attack_rider_totals = { "divine_smite:bonus_damage": divineSmiteReportedTotal };
      result.divine_smite_slot_level = Number(divineSmiteSlotLevel);
    }
    return result;
  };
  const specialInputValid = (
    (!specialRuleKinds.includes("teleport") || (
      (teleportDestinationKind === "object" || teleportDestinationKind === "creature")
        ? Boolean(specialDestinationId)
        : affectedEnemies.length > 1
          ? affectedEnemies.every((target) => {
            const destination = teleportDestinations[target.id];
            return Number(destination?.row) >= 1 && Number(destination?.col) >= 1;
          })
          : Number(specialRow) >= 1 && Number(specialCol) >= 1
    ))
    && (!specialRuleKinds.includes("creation") || (
      Boolean(specialTemplate.trim())
      && Number(specialCount) >= 1
      && (ruleFieldText(creationBlock, "creation_kind", "object") === "item" || (
        Number(specialRow) >= 1 && Number(specialCol) >= 1
      ))
    ))
    && (!specialRuleKinds.includes("transformation") || (
      Boolean(specialTemplate.trim())
      && (!transformationNeedsStats || [
        specialFormArmorClass,
        specialFormHp,
        specialFormMaxHp,
        specialFormSpeed,
      ].every((value) => value !== "" && Number(value) >= 0))
    ))
    && (!areaEffectBlocks.length || areaEffectBlocks.every((block) => {
      if (block.origin === "self") return true;
      const origin = areaOrigins[String(block.id)];
      return Number(origin?.row) >= 1 && Number(origin?.col) >= 1;
    }))
    && choicesValid
    && (!isDispelAction || (
      selectedEffectIds.length > 0
      && (dispelBlock?.check_required !== true || (
        dispelCheckTotal !== "" && dispelCheckDc !== "" && Number(dispelCheckDc) >= 0
      ))
    ))
    && (!needsReactionTriggerInput || Boolean(reactionTrigger.trim()))
  );
  // Instantaneous damage/save areas must use the attack endpoint so their
  // geometry, per-target saves, and typed damage are resolved together.  Only
  // support/special blocks without an immediate combat effect use cast.
  const isCastAction = !isRuntimeFeatureAction && (isSupportAction || (isSpecialAction && !damageOrSaveBlocks));
  const needsDamageRoll = !isCastAction && selectedDamageBlocks.length > 0;
  const mutation = useMutation({ mutationFn: async (fn: () => Promise<unknown>) => fn(), onSuccess: refresh });
  const reactionMutation = useMutation({
    mutationFn: ({ id, version, decision }: { id: string; version: number; decision: "accept" | "reject" }) =>
      resolveMyOpportunityReaction(id, version, decision),
    onSuccess: (_result, variables) => {
      setLastResolution(variables.decision === "accept" ? "已发动借机攻击；系统正在执行一次结构化攻击。" : "已放弃本次借机攻击。" );
      refresh();
    },
  });
  const preDamageReactionMutation = useMutation({
    mutationFn: ({ id, version, decision, featureId, reductionRoll }: { id: string; version: number; decision: "accept" | "reject"; featureId?: string; reductionRoll?: number }) =>
      resolveMyPreDamageReaction(id, version, decision, featureId, reductionRoll),
    onSuccess: (_result, variables) => {
      setLastResolution(variables.decision === "accept" && variables.featureId === "deflect_attacks" ? "已使用偏转攻击；原攻击正在按减伤骰结算。" : variables.decision === "accept" ? "已使用直觉闪避；原攻击正在按减半伤害结算。" : "已放弃伤害前反应；原攻击正在正常结算。");
      refresh();
    },
  });
  const deflectRedirectMutation = useMutation({
    mutationFn: (input: { id: string; version: number; decision: "accept" | "reject"; targetId?: string; targetVersion?: number; savingThrowRoll?: number; damageRolls?: number[] }) =>
      resolveMyDeflectRedirect(input.id, input.version, {
        decision: input.decision,
        target_combatant_id: input.targetId ?? null,
        target_version: input.targetVersion ?? null,
        saving_throw_roll: input.savingThrowRoll ?? null,
        damage_rolls: input.damageRolls ?? [],
      }),
    onSuccess: (_result, variables) => {
      setLastResolution(variables.decision === "accept" ? "已消耗 Focus；偏转攻击反击正在结算。" : "已放弃偏转攻击反击。" );
      refresh();
    },
  });
  const maneuverMutation = useMutation({
    mutationFn: () => {
      if (!own) throw new Error("当前没有可控单位");
      const input: PlayerCombatManeuver = {
        action_type: maneuverAction,
        actor_version: own.version ?? 1,
      };
      if (maneuverNeedsTarget && maneuverTarget) {
        input.target_combatant_id = maneuverTarget.id;
        input.target_version = maneuverTarget.version ?? 1;
      }
      if (maneuverNeedsOutcome) input.outcome = maneuverOutcome as "success" | "failure";
      if (maneuverNeedsNote) input.adjudication_note = maneuverNote.trim();
      if (maneuverAction === "help") input.help_trigger = helpTrigger.trim();
      if (maneuverAction === "ready") {
        input.ready_trigger = readyTrigger.trim();
        input.ready_response = readyResponse.trim();
      }
      if (maneuverAction === "shove") {
        input.shove_mode = shoveMode;
        if (shoveMode === "push") input.push_distance_ft = Number(pushDistance);
      }
      if (maneuverAction === "use_item") {
        input.item_id = itemId.trim();
        input.item_version = Number(itemVersion);
      }
      if (maneuverAction === "object_interaction" && maneuverObject) {
        input.object_id = maneuverObject.id;
        input.object_version = Number(objectVersion);
        input.object_state = objectState;
      }
      return performMyCombatManeuver(input);
    },
    onSuccess: (result) => {
      const rawNote = (result as { result?: { adjudication_note?: unknown } }).result?.adjudication_note;
      const note = typeof rawNote === "string" && rawNote.trim() ? rawNote : "战斗引擎已完成结算";
      setLastResolution(`${COMBAT_MANEUVER_LABELS[maneuverAction]}已写入战斗状态；${note}`);
      setManeuverOutcome("");
      setManeuverNote("");
      refresh();
    },
  });
  const dismissMutation = useMutation({
    mutationFn: () => {
      if (!activeOwn || activeOwn.entity_type !== "companion") throw new Error("当前没有可结束的召唤物回合");
      return dismissMySummon(activeOwn.id, activeOwn.version ?? 1);
    },
    onSuccess: refresh,
  });
  const deathSaveMutation = useMutation({
    mutationFn: () => {
      if (!combat?.death_save || !own) throw new Error("当前没有可提交的死亡豁免");
      const roll = Number(deathSaveRoll);
      if (!Number.isInteger(roll) || roll < 1 || roll > 20) throw new Error("死亡豁免必须是 1–20 的 d20 结果");
      return submitMyDeathSave(own.version ?? 1, roll);
    },
    onSuccess: (result) => {
      const deathSave = (result as { death_save?: { stable?: boolean; dead?: boolean; pending_death_confirmation?: boolean } }).death_save;
      setDeathSaveRoll("");
      setLastResolution(
        deathSave?.dead
          ? "死亡豁免三次失败，等待 DM 确认死亡。"
          : deathSave?.pending_death_confirmation
            ? "死亡豁免达到致命条件，等待 DM 确认。"
            : deathSave?.stable
              ? "你已稳定，战斗回合已继续。"
              : "死亡豁免已结算，战斗回合已继续。",
      );
      refresh();
    },
  });
  const summonMutation = useMutation({
    mutationFn: () => {
      if (!selectedAction || !companionId) throw new Error("请选择要召唤的战斗模板");
      return summonMyCompanion(
        companionId,
        display(selectedAction.name),
        Math.max(1, Math.min(20, Number(summonCount) || 1)),
        summonPosition ?? undefined,
      );
    },
    onSuccess: () => {
      setSummonPosition(null);
      refresh();
    },
  });
  if (!combat) return <EmptyState hint="DM 从当前 Scene 发起战斗后，这里会自动切换。" title="当前没有战斗" />;
  const ended = combat.status === "ended";
  return (
    <div
      className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]"
      data-testid="player-combat-layout"
    >
      <section className={`${cardCls} min-w-0`}>
        <div className="mb-3 flex flex-wrap items-center gap-2"><h2 className="m-0 mr-auto font-display text-2xl">{combat.name}</h2><span className="rounded bg-ink-950 px-2 py-1 text-xs">第 {combat.round_number} 轮</span><span className={`rounded px-2 py-1 text-xs ${ended ? "bg-amber-500/20 text-amber-200" : combat.is_my_turn ? "bg-emerald-500/20 text-emerald-200" : "bg-ink-800 text-stone-400"}`}>{ended ? "战斗已结束" : presentationStatus ?? (combat.is_my_turn ? "轮到你行动" : `${activeCombatant?.name ?? "其他单位"}行动中`)}</span></div>
        <PlayerCombatantStrip activeId={combat.active_combatant_id} combatants={combat.combatants} />
        <div className="mb-3 min-h-[5.75rem]">
        {presentation ? (
          <div className="h-full rounded-lg border-2 border-red-700/60 bg-red-950/20 p-3" data-testid="player-enemy-action-banner">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-red-500/20 px-2 py-1 text-2xs text-red-200">
                {presentation.action_type === "advance_turn"
                  ? "回合切换"
                  : presentation.action_type === "move"
                    ? presentationType === "npc" ? "NPC移动" : presentationType === "monster" ? "敌方移动" : "玩家移动"
                    : presentationType === "npc" ? "NPC动作" : presentationType === "monster" ? "敌方动作" : "玩家动作"}
              </span>
              <strong className="text-sm text-parchment-100">{presentationActor?.name ?? presentation.actor_name ?? "战斗单位"}</strong>
              {presentation.action_name ? <span className="text-xs text-red-200">使用「{presentation.action_name}」</span> : null}
            </div>
            <p className="mb-0 mt-2 text-xs leading-5 text-stone-300">{presentation.summary}</p>
            {presentationTargets.length ? <p className="mb-0 mt-1 text-2xs text-amber-200">目标：{presentationTargets.map((item) => item.name).join("、")}</p> : null}
          </div>
        ) : <div aria-hidden="true" className="h-[5.75rem] rounded-lg border border-transparent" />}
        </div>
        <div data-testid="player-combat-map">
          <SceneGridView
            interactionMode={combatMode}
            onMove={(row, col) => own && combatMode === "move" && mutation.mutate(() => moveMyCombatant(row, col, own.version ?? 1, disengage))}
            onTargetSelect={(value) => combatMode === "action" && setTargetId(value.replace(/^combatant:/, ""))}
            onAimSelect={handleAimSelect}
            canSelectAimCell={canSelectAimCell}
            selectedTargetKey={targetId ? `combatant:${targetId}` : undefined}
            selectedTargetKeys={new Set(affectedEnemies.map((item) => `combatant:${item.id}`))}
            selectableTargetKeys={new Set(targetableEnemies.map((item) => `combatant:${item.id}`))}
            affectedCellKeys={new Set([...displayAffectedCellKeys, ...visibleAffectedCellKeys])}
            dangerCellKeys={visibleEnemyDangerCellKeys}
            enemyRangeCellKeys={activeEnemyRangeCellKeys}
            movementCellKeys={movementCellKeys}
            positionOverrides={positionOverrides}
            rangeCellKeys={rangeCellKeys}
            snapshot={snapshot}
          />
        </div>
        <section className="mt-3 rounded border border-amber-800/60 bg-amber-950/15 p-3" data-testid="player-combat-mode">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-auto text-sm text-amber-100">当前操作模式</strong>
            <Button
              onClick={() => setCombatMode("move")}
              size="sm"
              variant={combatMode === "move" ? "primary" : "ghost"}
            >移动</Button>
            <Button
              onClick={() => setCombatMode("action")}
              size="sm"
              variant={combatMode === "action" ? "primary" : "ghost"}
            >攻击 / 技能</Button>
          </div>
          {ownCombatants.length > 1 ? (
            <div className="mt-2 flex flex-wrap gap-2">
              <span className="self-center text-2xs text-stone-400">可操控单位：</span>
              {ownCombatants.map((unit) => (
                <Button
                  key={unit.id}
                  onClick={() => setSelectedControlledUnitId(unit.id)}
                  size="sm"
                  variant={own?.id === unit.id ? "primary" : "ghost"}
                >
                  {unit.name}{unit.entity_type === "companion" ? "（召唤物）" : ""}{unit.id === combat.active_combatant_id ? " · 当前回合" : ""}
                </Button>
              ))}
            </div>
          ) : null}
          <p className="mb-0 mt-2 text-2xs leading-5 text-stone-400">
            {combatMode === "move"
              ? "现在只有绿色格可以点击移动；不会因为点击地图而选中攻击目标。"
              : "现在蓝色格用于选择法术落点/方向，绿色虚线用于选择目标；不会因为瞄准而移动单位。"}
            {activeOwn ? ` 当前行动单位：${activeOwn.name}。` : " 当前不是你的回合，操作按钮会等待先攻轮到你的单位。"}
          </p>
        </section>
        <label className="mt-2 flex items-start gap-2 rounded border border-amber-800/60 bg-amber-950/15 p-2 text-xs text-amber-100">
          <input checked={disengage} onChange={(event) => setDisengage(event.target.checked)} type="checkbox" />
          <span><strong>撤离（Disengage）</strong><span className="block text-2xs text-stone-400">本次移动不触发借机攻击；会消耗你的动作。</span></span>
        </label>
        <section className="mt-3 rounded border border-sky-800/60 bg-sky-950/15 p-3" data-testid="player-standard-maneuvers">
          <strong className="text-sm text-sky-100">战斗标准动作</strong>
          <p className="mb-2 mt-1 text-2xs leading-5 text-stone-300">疾走、闪避、协助、准备、搜索、隐藏、使用物品、擒抱、推撞和物件互动会直接调用规则引擎。需要 DM 裁定的动作必须填写裁定结果和说明，系统不会替你猜检定结果。</p>
          <select
            aria-label="战斗标准动作"
            className={inputCls}
            disabled={ended || !combat.is_my_turn}
            onChange={(event) => {
              setCombatMode("action");
              setManeuverAction(event.target.value as PlayerCombatManeuver["action_type"]);
              setManeuverTargetId("");
              setManeuverOutcome("");
              setManeuverNote("");
            }}
            value={maneuverAction}
          >
            {Object.entries(COMBAT_MANEUVER_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          {maneuverNeedsTarget ? <label className="mt-2 block text-2xs text-stone-300">目标
            <select aria-label="标准动作目标" className={`${inputCls} mt-1`} onChange={(event) => setManeuverTargetId(event.target.value)} value={maneuverTargetId}>
              <option value="">选择目标</option>
              {combat.combatants.filter((item) => item.id !== own?.id && (maneuverAction !== "help" || item.is_own)).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.entity_type === "companion" ? "召唤物" : item.is_own ? "友方" : "敌方"} · v{item.version ?? 1}</option>)}
            </select>
          </label> : null}
          {maneuverAction === "help" ? <label className="mt-2 block text-2xs text-stone-300">协助触发条件<input className={`${inputCls} mt-1`} onChange={(event) => setHelpTrigger(event.target.value)} placeholder="例如：帮助目标下一次攻击" value={helpTrigger} /></label> : null}
          {maneuverAction === "ready" ? <div className="mt-2 grid gap-2 sm:grid-cols-2"><label className="text-2xs text-stone-300">触发条件<input className={`${inputCls} mt-1`} onChange={(event) => setReadyTrigger(event.target.value)} placeholder="例如：敌人进入门口" value={readyTrigger} /></label><label className="text-2xs text-stone-300">准备的响应<input className={`${inputCls} mt-1`} onChange={(event) => setReadyResponse(event.target.value)} placeholder="例如：施放雷鸣波" value={readyResponse} /></label></div> : null}
          {maneuverAction === "shove" ? <label className="mt-2 block text-2xs text-stone-300">推撞结果<select className={`${inputCls} mt-1`} onChange={(event) => setShoveMode(event.target.value as "prone" | "push")} value={shoveMode}><option value="prone">推倒（倒地）</option><option value="push">推离（需明确距离）</option></select></label> : null}
          {maneuverAction === "shove" && shoveMode === "push" ? <label className="mt-2 block text-2xs text-stone-300">推离距离（尺）<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setPushDistance(event.target.value)} type="number" value={pushDistance} /></label> : null}
          {maneuverAction === "use_item" ? <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_6rem]"><label className="text-2xs text-stone-300">物品 ID<input className={`${inputCls} mt-1`} onChange={(event) => setItemId(event.target.value)} placeholder="从角色物品卡复制" value={itemId} /></label><label className="text-2xs text-stone-300">版本<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setItemVersion(event.target.value)} type="number" value={itemVersion} /></label></div> : null}
          {maneuverAction === "object_interaction" ? <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_8rem_6rem]"><label className="text-2xs text-stone-300">场景物件<select aria-label="标准动作物件" className={`${inputCls} mt-1`} onChange={(event) => { const next = snapshot.table.scene?.objects.find((item) => item.id === event.target.value); setObjectId(event.target.value); setObjectVersion(String(next?.version ?? 1)); }} value={objectId}><option value="">选择公开物件</option>{snapshot.table.scene?.objects.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.state}</option>)}</select></label><label className="text-2xs text-stone-300">目标状态<select className={`${inputCls} mt-1`} onChange={(event) => setObjectState(event.target.value as NonNullable<PlayerCombatManeuver["object_state"]>)} value={objectState}><option value="open">打开</option><option value="closed">关闭</option><option value="disarmed">解除</option><option value="picked_up">拾取</option><option value="destroyed">摧毁</option></select></label><label className="text-2xs text-stone-300">版本<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setObjectVersion(event.target.value)} type="number" value={objectVersion} /></label></div> : null}
          {maneuverNeedsOutcome ? <label className="mt-2 block text-2xs text-stone-300">DM 裁定结果<select aria-label="标准动作裁定结果" className={`${inputCls} mt-1`} onChange={(event) => setManeuverOutcome(event.target.value as "" | "success" | "failure")} value={maneuverOutcome}><option value="">等待 DM 裁定</option><option value="success">成功</option><option value="failure">失败</option></select></label> : null}
          {maneuverNeedsNote ? <label className="mt-2 block text-2xs text-stone-300">裁定说明<textarea className={`${inputCls} mt-1`} onChange={(event) => setManeuverNote(event.target.value)} placeholder="例如：DM 已确认目标的对抗检定结果" rows={2} value={maneuverNote} /></label> : null}
          <Button className="mt-2 w-full" disabled={!maneuverValid} loading={maneuverMutation.isPending} onClick={() => maneuverMutation.mutate()} variant="primary">执行{COMBAT_MANEUVER_LABELS[maneuverAction]}</Button>
          {maneuverMutation.isError ? <p className="mb-0 mt-2 text-xs text-red-300">{maneuverMutation.error.message}</p> : null}
        </section>
          {own ? <p className="mb-0 mt-2 text-xs text-stone-400">剩余移动 {own.movement_remaining_ft ?? 0}尺 · 动作 {own.action_available ? "可用" : "已用"} · 附赠动作 {own.bonus_action_available ? "可用" : "已用"} · 反应 {own.reaction_available ? "可用" : "已用"}</p> : null}
          {activeOwn?.entity_type === "companion" ? <Button className="mt-2" disabled={ended || !combat.is_my_turn} loading={dismissMutation.isPending} onClick={() => dismissMutation.mutate()} variant="ghost">结束当前召唤物</Button> : null}
      </section>
      <aside className="min-w-0 space-y-4" data-testid="player-combat-sidebar">
        <section className={cardCls}>
          <h2 className="mt-0 font-display text-xl">当前战斗面板</h2>
          <div className="mb-3 min-h-[6.75rem]">
          {!combat.is_my_turn && activeCombatant ? (
            <div className="h-full rounded border border-red-900/60 bg-red-950/15 p-3" data-testid="player-active-enemy-panel">
              <strong className="text-sm text-red-100">{activeCombatant.name} · 当前行动单位</strong>
              <p className="mb-0 mt-1 text-xs leading-5 text-stone-300">
                {activeCombatant.entity_type === "monster"
                  ? `怪物正在由战斗 AI 移动并选择攻击。AC ${activeCombatant.armor_class} · HP ${activeCombatant.hp}/${activeCombatant.max_hp} · 剩余移动 ${activeCombatant.movement_remaining_ft ?? 0}尺。`
                  : activeCombatant.is_own
                    ? `这是你的可控单位。AC ${activeCombatant.armor_class} · HP ${activeCombatant.hp}/${activeCombatant.max_hp} · 剩余移动 ${activeCombatant.movement_remaining_ft ?? 0}尺。`
                    : "NPC / 敌方召唤物正在按当前战斗状态行动。"}
              </p>
              {activeEnemyAction ? <p className="mb-0 mt-1 text-2xs text-orange-200">当前 AI 动作：{display(activeEnemyAction.name)} · {damageInstructionForAction(activeEnemyAction)}；橙色为可达范围，红色为本次实际影响范围。</p> : null}
              {(activeCombatant.actions ?? []).length ? <p className="mb-0 mt-1 text-2xs text-stone-500">可见动作：{activeCombatant.actions.map(display).join("、")}</p> : null}
            </div>
          ) : <div aria-hidden="true" className="h-[6.75rem] rounded border border-transparent" />}
          </div>
          {combat.death_save && own?.hp === 0 ? (
            <section className="mb-3 rounded border border-red-700 bg-red-950/30 p-3" data-testid="player-death-save-panel">
              <strong className="text-sm text-red-100">倒地：死亡豁免</strong>
              <p className="mb-2 mt-1 text-xs leading-5 text-stone-300">每次自己的回合提交一次 d20。自然 20 恢复 1 点生命；三次成功稳定；三次失败等待 DM 确认死亡。</p>
              <div className="mb-2 grid grid-cols-3 gap-2 text-center text-2xs">
                <span className="rounded bg-emerald-950/60 py-2 text-emerald-200">成功 {combat.death_save.successes}/3</span>
                <span className="rounded bg-red-950/70 py-2 text-red-200">失败 {combat.death_save.failures}/3</span>
                <span className="rounded bg-ink-950 py-2 text-stone-300">上次 {combat.death_save.last_roll ?? "—"}</span>
              </div>
              {combat.death_save.pending_death_confirmation || combat.death_save.dead ? (
                <p className="mb-0 rounded border border-red-800/60 bg-red-950/40 p-2 text-xs text-red-200">已达到致命条件，等待 DM 确认。</p>
              ) : combat.death_save.stable ? (
                <p className="mb-0 rounded border border-emerald-800/60 bg-emerald-950/30 p-2 text-xs text-emerald-200">你已稳定，等待后续治疗或 DM 处理。</p>
              ) : (
                <div className="flex gap-2">
                  <input aria-label="死亡豁免骰值" className={inputCls} max="20" min="1" onChange={(event) => setDeathSaveRoll(event.target.value)} placeholder="d20" type="number" value={deathSaveRoll} />
                  <Button disabled={!combat.is_my_turn || !deathSaveRoll} loading={deathSaveMutation.isPending} onClick={() => deathSaveMutation.mutate()} variant="primary">提交死亡豁免</Button>
                </div>
              )}
              {deathSaveMutation.isError ? <p className="mb-0 mt-2 text-xs text-red-300">{deathSaveMutation.error.message}</p> : null}
            </section>
          ) : null}
          {ownUntilSaveEffects.length > 0 ? (
            <section className="mb-3 rounded border border-amber-800/60 bg-amber-950/15 p-3" data-testid="player-until-save-status">
              <strong className="text-sm text-amber-100">持续状态 · 等待重复豁免</strong>
              <p className="mb-2 mt-1 text-xs leading-5 text-stone-300">下列效果仍在生效，直到 DM 确认相应豁免成功。仅显示这个状态不代表已经有可提交骰子，也不表示效果已经结束；若服务器已创建可提交请求，会显示在下面。</p>
              <div className="space-y-1 text-2xs text-amber-100">
                {ownUntilSaveEffects.map(({ combatant, effect }) => <p className="m-0 rounded border border-amber-900/60 bg-ink-950/40 px-2 py-1" key={`${combatant.id}:${effect.id}`}>{combatant.name} · {effect.name} · 状态仍生效</p>)}
              </div>
            </section>
          ) : null}
          {(combat.pending_reactions ?? []).map((reaction) => (
            reaction.kind === "deflect_redirect" ? (
              <div className="mb-3 rounded border border-fuchsia-700 bg-fuchsia-950/25 p-3" data-testid="player-pending-deflect-redirect" key={reaction.id}>
                {(() => {
                  const targetId = deflectRedirectTargets[reaction.id] ?? "";
                  const target = (combat.combatants ?? []).find((item) => item.id === targetId);
                  const rolls = deflectRedirectDamageRolls[reaction.id] ?? ["", ""];
                  const sides = reaction.damage_die_sides ?? 0;
                  const saveRoll = deflectRedirectSaves[reaction.id] ?? "";
                  const canAccept = Boolean(target && target.version && saveRoll && rolls.length === 2 && rolls.every((value) => Number.isInteger(Number(value)) && Number(value) >= 1 && (!sides || Number(value) <= sides)));
                  return (
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <strong className="text-sm text-fuchsia-100">偏转攻击反击 · 等待选择</strong>
                        <span className="rounded border border-fuchsia-700/70 px-1.5 py-0.5 text-2xs text-fuchsia-200">伤害已归零</span>
                      </div>
                      <p className="mb-2 mt-1 text-xs leading-5 text-stone-300">{reaction.message ?? "偏转攻击将伤害降为 0；可消耗 1 点 Focus 反击。"}</p>
                      <div className="grid gap-2 sm:grid-cols-2">
                        <label className="text-2xs text-fuchsia-100">反击目标
                          <select aria-label={`${reaction.id} 偏转攻击反击目标`} className="ml-2 rounded border border-fuchsia-800 bg-ink-950 px-1.5 py-1" onChange={(event) => setDeflectRedirectTargets((current) => ({ ...current, [reaction.id]: event.target.value }))} value={targetId}>
                            <option value="">请选择 5 尺内目标</option>
                            {(reaction.candidate_target_ids ?? []).map((candidateId) => <option key={candidateId} value={candidateId}>{reaction.candidate_target_names?.[candidateId] ?? combat.combatants.find((item) => item.id === candidateId)?.name ?? candidateId}</option>)}
                          </select>
                        </label>
                        <label className="text-2xs text-fuchsia-100">敏捷豁免总值
                          <input aria-label={`${reaction.id} 偏转反击敏捷豁免`} className="ml-2 w-20 rounded border border-fuchsia-800 bg-ink-950 px-1.5 py-1" onChange={(event) => setDeflectRedirectSaves((current) => ({ ...current, [reaction.id]: event.target.value }))} placeholder="d20+加值" type="number" value={saveRoll} />
                          <span className="ml-1 text-stone-400">vs DC {reaction.save_dc ?? "—"}</span>
                        </label>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-2xs text-fuchsia-100">
                        <span>反击伤害：{reaction.damage_dice_count ?? 2}×{reaction.damage_die_expression ?? "武艺骰"} + 敏捷调整值（{reaction.damage_modifier ?? 0}）</span>
                        {[0, 1].map((index) => <input aria-label={`${reaction.id} 偏转反击武艺骰${index + 1}`} className="w-16 rounded border border-fuchsia-800 bg-ink-950 px-1.5 py-1" key={index} max={sides || undefined} min="1" onChange={(event) => setDeflectRedirectDamageRolls((current) => ({ ...current, [reaction.id]: (current[reaction.id] ?? ["", ""]).map((value, itemIndex) => itemIndex === index ? event.target.value : value) }))} placeholder={`d${sides || "?"}`} type="number" value={rolls[index] ?? ""} />)}
                      </div>
                      <p className="mb-0 mt-1 text-2xs text-fuchsia-200">豁免成功造成一半伤害；失败造成全额伤害。消耗 {reaction.resource_cost ?? 1} 点 {reaction.resource_key ?? "Focus"}。</p>
                      <div className="mt-2 flex gap-2">
                        <Button disabled={deflectRedirectMutation.isPending || !canAccept} loading={deflectRedirectMutation.isPending && deflectRedirectMutation.variables?.id === reaction.id && deflectRedirectMutation.variables.decision === "accept"} onClick={() => deflectRedirectMutation.mutate({ id: reaction.id, version: reaction.version, decision: "accept", targetId, targetVersion: target?.version, savingThrowRoll: Number(saveRoll), damageRolls: rolls.map(Number) })} variant="danger">消耗 Focus 并反击</Button>
                        <Button disabled={deflectRedirectMutation.isPending} loading={deflectRedirectMutation.isPending && deflectRedirectMutation.variables?.id === reaction.id && deflectRedirectMutation.variables.decision === "reject"} onClick={() => deflectRedirectMutation.mutate({ id: reaction.id, version: reaction.version, decision: "reject" })}>放弃反击</Button>
                      </div>
                    </div>
                  );
                })()}
              </div>
            ) : reaction.kind === "pre_damage" ? (
              <div className="mb-3 rounded border border-amber-700 bg-amber-950/25 p-3" data-testid="player-pending-pre-damage-reaction" key={reaction.id}>
                {(() => {
                  const requiresReductionRoll = reaction.requires_reduction_roll === true;
                  const reductionRoll = preDamageReductionRolls[reaction.id] ?? "";
                  const reductionBonus = reaction.damage_reduction_bonus ?? 0;
                  const canAccept = !requiresReductionRoll || (Number.isInteger(Number(reductionRoll)) && Number(reductionRoll) >= 1 && Number(reductionRoll) <= 10);
                  return (
                <div>
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="text-sm text-amber-100">伤害前反应暂停 · {reaction.source_name ?? "攻击者"} · {reaction.feature_name ?? "直觉闪避"}</strong>
                  <span className="rounded border border-amber-700/70 px-1.5 py-0.5 text-2xs text-amber-200">伤害尚未落地</span>
                  {requiresReductionRoll ? <label className="flex items-center gap-1 text-2xs text-amber-100">d10减伤骰<input aria-label={`${reaction.id} 偏转攻击减伤骰`} className="w-16 rounded border border-amber-800 bg-ink-950 px-1.5 py-1" max="10" min="1" onChange={(event) => setPreDamageReductionRolls((current) => ({ ...current, [reaction.id]: event.target.value }))} type="number" value={reductionRoll} /><span className="text-stone-400">+{reductionBonus}</span></label> : null}
                </div>
                <p className="mb-0 mt-1 text-xs leading-5 text-stone-300">{reaction.message ?? "你被攻击命中；请选择是否使用反应。"}</p>
                <p className="mb-0 mt-1 text-2xs text-amber-200">「{reaction.source_action_name ?? "攻击"}」命中你。{requiresReductionRoll ? `使用偏转攻击会用 d10 + 敏捷调整值 + 职业等级（固定加值 ${reductionBonus}）从攻击伤害中扣除；若归零，随后会打开独立的 Focus 反击窗口。` : "使用直觉闪避会在抗性/免疫结算前将本次攻击每段伤害向下取整减半。"}</p>
                <div className="mt-2 flex gap-2">
                  <Button disabled={preDamageReactionMutation.isPending || !canAccept} loading={preDamageReactionMutation.isPending && preDamageReactionMutation.variables?.id === reaction.id && preDamageReactionMutation.variables.decision === "accept"} onClick={() => preDamageReactionMutation.mutate({ id: reaction.id, version: reaction.version, decision: "accept", featureId: reaction.feature_id ?? "uncanny_dodge", reductionRoll: requiresReductionRoll ? Number(reductionRoll) : undefined })} variant="danger">使用{reaction.feature_name ?? "直觉闪避"}</Button>
                  <Button disabled={preDamageReactionMutation.isPending} loading={preDamageReactionMutation.isPending && preDamageReactionMutation.variables?.id === reaction.id && preDamageReactionMutation.variables.decision === "reject"} onClick={() => preDamageReactionMutation.mutate({ id: reaction.id, version: reaction.version, decision: "reject" })}>不使用</Button>
                </div>
                </div>
                  );
                })()}
              </div>
            ) : (
              <div className="mb-3 rounded border border-red-700 bg-red-950/25 p-3" data-testid="player-pending-reaction" key={reaction.id}>
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="text-sm text-red-100">借机攻击提示 · {reaction.source_name ?? "敌人"}</strong>
                  <span className="rounded border border-red-700/70 px-1.5 py-0.5 text-2xs text-red-200">等待你的选择</span>
                </div>
                <p className="mb-0 mt-1 text-xs leading-5 text-stone-300">{reaction.message ?? reaction.reaction_trigger ?? "敌人离开了你的近战范围。"}</p>
                <p className="mb-0 mt-1 text-2xs text-amber-200">使用「{reaction.source_action_name ?? "近战攻击"}」；伤害骰 {reaction.damage_expression ?? "按结构化攻击积木"}{reaction.damage_type ? ` · ${reaction.damage_type}` : ""}。选择发动后，系统会自动掷攻击骰和伤害骰并结算。</p>
                <div className="mt-2 flex gap-2">
                  <Button disabled={reactionMutation.isPending} loading={reactionMutation.isPending && reactionMutation.variables?.id === reaction.id && reactionMutation.variables.decision === "accept"} onClick={() => reactionMutation.mutate({ id: reaction.id, version: reaction.version, decision: "accept" })} variant="danger">发动借机攻击</Button>
                  <Button disabled={reactionMutation.isPending} loading={reactionMutation.isPending && reactionMutation.variables?.id === reaction.id && reactionMutation.variables.decision === "reject"} onClick={() => reactionMutation.mutate({ id: reaction.id, version: reaction.version, decision: "reject" })}>不发动</Button>
                </div>
              </div>
            )
          ))}
          {combat.pending_rolls.map((roll) => {
            const windowLabel = advancedRollWindowLabel(roll.action_cost);
            const damageSegments = (roll.damage_components_on_failure?.length
              ? roll.damage_components_on_failure
              : roll.damage_components_on_success) ?? [];
            const damageSegmentSummary = damageComponentsSummary(damageSegments);
            return (
            <div className="mb-3 rounded border border-violet-700 bg-violet-950/20 p-3" data-testid="player-pending-roll" key={roll.id}>
              <div className="flex flex-wrap items-center gap-2">
                <strong className="text-sm text-violet-100">待掷骰 · {roll.actor_name ?? "战斗单位"} 请求你进行「{roll.action_name}」</strong>
                {windowLabel ? <span className="rounded border border-fuchsia-700/70 bg-fuchsia-950/30 px-1.5 py-0.5 text-2xs text-fuchsia-200">{windowLabel}</span> : null}
                <span className="rounded border border-violet-700/60 px-1.5 py-0.5 text-2xs text-violet-200">尚未结算</span>
              </div>
              {roll.description ? <p className="mb-0 mt-1 text-xs leading-5 text-stone-300">{roll.description}</p> : null}
              {windowLabel ? <p className="mb-0 mt-1 text-2xs text-fuchsia-200">这是怪物回合外的高级动作请求。DM 已记录触发窗口和资源；你的骰子提交前，传奇点、巢穴本轮次数或反应资源不会再次消耗。</p> : null}
              {roll.action_cost === "legendary_action" && roll.legendary_cost ? <p className="mb-0 mt-1 text-2xs text-fuchsia-200">本次消耗传奇动作点：{roll.legendary_cost} / 动作池上限 {roll.legendary_pool_max ?? "未同步"}</p> : null}
              {roll.action_cost === "reaction" && roll.reaction_trigger ? <p className="mb-0 mt-1 text-2xs text-fuchsia-200">实际触发事件：{roll.reaction_trigger}</p> : null}
              <p className="mb-0 mt-2 text-xs text-stone-400">请掷 {roll.roll_formula}，总值需达到 DC {roll.dc}（{roll.ability || roll.skill || roll.resolution_type}）。{roll.effect_target_name && roll.effect_target_name !== snapshot.character?.name ? `成功后的效果目标：${roll.effect_target_name}。` : ""}{roll.damage_on_failure ? `失败将承受 ${roll.damage_on_failure} 点${roll.damage_type ?? ""}伤害` : ""}{roll.damage_on_success ? `；成功仍承受 ${roll.damage_on_success} 点${roll.damage_type ?? ""}伤害` : ""}</p>
              {damageSegments.length > 1 && damageSegmentSummary ? <p className="mb-0 mt-1 text-2xs text-stone-300">复合伤害会逐段结算抗性/易伤/免疫：{damageSegmentSummary}</p> : null}
              <p className="mb-0 mt-1 text-2xs text-violet-200">提交骰子前，伤害、状态和后续回合都尚未完成。</p>
              {dangerCellKeys.size ? <p className="text-2xs text-red-300">地图上的红色描边为「{roll.action_name}」当前影响范围。</p> : null}
              <div className="mt-2 flex gap-2">
                <input aria-label={`${roll.action_name}骰值`} className={inputCls} onChange={(event) => setRolls((current) => ({ ...current, [roll.id]: event.target.value }))} type="number" value={rolls[roll.id] ?? ""} />
                <Button disabled={!rolls[roll.id] || mutation.isPending} loading={mutation.isPending} onClick={() => mutation.mutate(async () => {
                  const result = await submitMyPlayerRoll(roll.id, roll.version, Number(rolls[roll.id]));
                  const next = (result as { turn_advance?: { active_combatant?: { display_name?: string } } }).turn_advance?.active_combatant?.display_name;
                  setLastResolution(`已提交「${roll.action_name}」的检定${next ? `；服务器已推进到 ${next} 的回合` : "；服务器已同步本次结果。若仍有其他待掷骰请求或 DM 确认，战斗会继续保持等待"}。`);
                  return result;
                })} variant="primary">提交骰子并同步战斗</Button>
              </div>
            </div>
            );
          })}
          {ended ? <p className="rounded border border-amber-800/60 bg-amber-950/20 p-3 text-sm text-amber-100">战斗已由 DM 结束。你仍可查看地图和完整公开日志；奖励请到“我的角色”查看。</p> : null}
          {companionTurn && activeOwn ? <section className="mb-3 rounded border border-violet-700/70 bg-violet-950/20 p-3 text-xs text-violet-100" data-testid="player-summon-turn-panel"><strong>{activeOwn.name} · 独立召唤物回合</strong><p className="mb-0 mt-1 leading-5 text-stone-300">现在控制的是该召唤物本身：移动、动作、附赠动作和结束回合都会写入它自己的 Combatant 与先攻位置，不会代替施法者行动。</p></section> : null}
          <label className="block text-xs text-stone-400">{companionTurn ? "召唤物动作" : "攻击 / 技能 / 特殊效果"}<select className={`${inputCls} mt-1`} disabled={ended || !combat.is_my_turn} onChange={(event) => { const next = event.target.value; setCombatMode("action"); setActionName(next); const action = actions.find((item) => display(item.name) === next); setTargetId(action?.runtime_feature === true ? (activeOwn?.id ?? own?.id ?? "") : ""); setAimPoint(null); setSummonPosition(null); setSlotLevel(Number(action?.spell_level ?? 0)); setDamageComponentTotals({}); setTargetDamageComponentTotals({}); setChoiceSelections({}); setAreaOrigins({}); setSpecialEffectIds(""); setReactionTrigger(""); setUseDivineSmite(false); setDivineSmiteDamageTotal(""); setDivineSmiteSlotLevel("1"); }} value={actionName}><option value="">{companionTurn ? "选择该召唤物的模板动作" : "选择角色卡动作或法术/特殊技能"}</option>{actions.map((action, index) => { const cost = playerActionCost(action); const available = playerHasActionEconomy(own, cost); return <option disabled={!available} key={`${display(action.name)}-${index}`} value={display(action.name)}>{playerActionCostLabel(cost)} · {actionCategoryLabel(action)} · {display(action.name)} · {damageInstructionForAction(action)}{available ? "" : " · 资源已用"}</option>; })}</select></label>
          {selectedSpellLevel > 0 ? <label className="mt-2 block text-xs text-stone-400">使用法术环阶<select aria-label="玩家使用法术环阶" className={`${inputCls} mt-1`} onChange={(event) => setSlotLevel(Number(event.target.value))} value={Math.max(selectedSpellLevel, slotLevel)}>{(availableSlotLevels.length ? availableSlotLevels : [selectedSpellLevel]).map((level) => { const slot = snapshot.character?.resources?.[`spell_slots_${level}`] as { label?: string; current?: number; max?: number } | undefined; return <option disabled={Number(slot?.current ?? 0) < 1} key={level} value={level}>{level}环 · {slot?.label ?? `法术位${level}`} · 可用 {Number(slot?.current ?? 0)}/{Number(slot?.max ?? 0)}</option>; })}</select><span className="mt-1 block text-2xs text-amber-200">当前施法：{Math.max(selectedSpellLevel, slotLevel)}环；伤害骰会按升环规则增加。</span></label> : null}
          {selectedAction ? <p className="mb-0 mt-2 text-2xs text-stone-400" data-testid="player-selected-action-constraints">资源/窗口：{playerActionCostLabel(selectedActionCost)} · {selectedActionCost === "reaction" ? "填写实际触发事件；不自动结束当前回合" : selectedActionCost === "legendary_action" ? "仅限传奇动作窗口" : selectedActionCost === "lair_action" ? "仅限巢穴动作窗口" : "当前回合"}{selectedResourceKey ? ` · ${selectedResource?.label ?? selectedResourceKey} ${Number(selectedResource?.current ?? 0)}/${Number(selectedResource?.max ?? 0)}` : ""}{!selectedActionAvailable ? " · 当前不可用" : ""}{targeting?.requiresElevation ? ` · 三维区域：锚点 ${targeting.anchorHeightFt ?? "未记录"}尺；目标必须有 elevation_ft` : ""}</p> : null}
          {divineSmiteRider ? <div className="mt-2 rounded border border-yellow-800/60 bg-yellow-950/20 p-3 text-xs text-yellow-100" data-testid="player-divine-smite-input"><label className="flex items-center gap-2"><input checked={useDivineSmite} onChange={(event) => setUseDivineSmite(event.target.checked)} type="checkbox" />命中后使用圣武斩</label>{useDivineSmite ? <><label className="mt-2 block">消耗法术位环阶<select aria-label="圣武斩法术位环阶" className={`${inputCls} mt-1`} onChange={(event) => setDivineSmiteSlotLevel(event.target.value)} value={divineSmiteSlotLevel}>{(divineSmiteSlotOptions.length ? divineSmiteSlotOptions : [1]).map((level) => { const resource = snapshot.character?.resources?.[`spell_slots_${level}`] as { label?: string; current?: number; max?: number } | undefined; return <option disabled={Number(resource?.current ?? 0) < 1} key={level} value={level}>{level}环 · 可用 {Number(resource?.current ?? 0)}/{Number(resource?.max ?? 0)}</option>; })}</select></label><label className="mt-2 block">圣武斩光耀伤害骰总值（{divineSmiteDiceCount}d8{criticalHit ? "×2" : ""}）<input aria-label="圣武斩伤害骰总值" className={`${inputCls} mt-1`} min={divineSmiteDiceCount * (criticalHit ? 2 : 1)} onChange={(event) => setDivineSmiteDamageTotal(event.target.value)} type="number" value={divineSmiteDamageTotal} /></label></> : <p className="mb-0 mt-1 text-2xs text-stone-300">只在近战武器或徒手攻击命中后使用；不选择则不消耗法术位。</p>}</div> : null}
          {selectedSummonBlock ? <div className="mt-2 rounded border border-violet-800/60 bg-violet-950/20 p-3 text-xs text-violet-100">
            <strong>召唤积木：{typeof selectedSummonBlock.creature_ref === "string" ? selectedSummonBlock.creature_ref : "召唤物"}</strong>
            {summonEntersCombat ? <>
              <p className="mb-2 mt-1 text-2xs text-stone-300">选择一个由 DM 建立的完整战斗模板；确认后消耗本单位动作，系统会为它掷先攻并加入回合轨道。</p>
              {availableSummonCompanions.length ? (
                <select aria-label="选择召唤战斗模板" className={inputCls} onChange={(event) => setCompanionId(event.target.value)} value={companionId}><option value="">选择自己的召唤物模板</option>{availableSummonCompanions.map((item) => <option key={item.id} value={item.id}>{item.name} · HP {item.hp}/{item.max_hp} · AC {item.armor_class}</option>)}</select>
              ) : <p className="mb-2 mt-2 rounded border border-amber-800/50 bg-amber-950/15 p-2 text-2xs leading-5 text-amber-200">你还没有可用的召唤物战斗模板。请先让 DM 建立明确的 HP、AC、速度和动作模板；没有完整模板时不会凭空生成战斗单位。</p>}
              <label className="mt-2 block text-2xs text-stone-300">召唤数量（每个都会建立独立单位）<input aria-label="召唤数量" className={`${inputCls} mt-1`} max="20" min="1" onChange={(event) => setSummonCount(event.target.value)} type="number" value={summonCount} /></label>
              {selectedSummonBlock.count_expression ? <p className="mb-0 mt-1 text-2xs text-amber-200">资料库数量表达式：{display(selectedSummonBlock.count_expression)}；请按法术表 / DM 裁定填写实际数量。</p> : null}
              <p className="mb-0 mt-2 text-2xs text-amber-200">请先在左侧地图蓝色范围内点击空格选择召唤落点{summonPosition ? `（已选 ${summonPosition.row},${summonPosition.col}）` : ""}；系统不会再把召唤物默认塞到施法者旁边。</p>
              <Button className="mt-2 w-full" disabled={!combat.is_my_turn || !companionId || !summonPosition || ended || !availableSummonCompanions.length} loading={summonMutation.isPending} onClick={() => summonMutation.mutate()} variant="primary">召唤并加入先攻轨道</Button>
            </> : <p className="mb-0 mt-1 text-2xs text-stone-300">这是非生物召唤效果，不会生成独立 HP/先攻单位；按规则由 DM 记录其持续时间与可操作范围。</p>}
            {summonMutation.isError ? <p className="mb-0 mt-2 text-xs text-red-300">{summonMutation.error.message}</p> : null}
          </div> : null}
          {needsChoiceSensitiveInput ? <div className="mt-2 rounded border border-cyan-800/60 bg-cyan-950/20 p-3 text-xs text-cyan-100">
            <strong>特殊规则输入</strong>
            <p className="mb-2 mt-1 text-2xs leading-5 text-stone-300">这些效果不能凭法术名称猜目的地、模板、分支或要结束的效果；提交前请填写规则积木要求的明确选择。</p>
            {specialRuleKinds.includes("teleport") ? (
              <>
                {(() => {
                  if (teleportDestinationKind === "object") {
                    return <label className="block">传送参照物<select className={`${inputCls} mt-1`} onChange={(event) => setSpecialDestinationId(event.target.value)} value={specialDestinationId}><option value="">选择当前场景中已存在的物件</option>{(snapshot.table.scene?.objects ?? []).map((item) => <option key={item.id} value={item.id}>{item.label}（{item.row}, {item.col}）</option>)}</select></label>;
                  }
                  if (teleportDestinationKind === "creature") {
                    return <label className="block">传送参照生物<select className={`${inputCls} mt-1`} onChange={(event) => setSpecialDestinationId(event.target.value)} value={specialDestinationId}><option value="">选择当前战斗中的生物</option>{combat.combatants.filter((item) => item.position).map((item) => <option key={item.id} value={item.id}>{item.name}（{item.position?.row}, {item.position?.col}）</option>)}</select></label>;
                  }
                  if (affectedEnemies.length > 1) {
                    return <div className="mt-2 space-y-2"><p className="m-0 text-2xs text-amber-100">每个受影响目标必须各自指定传送位置：</p>{affectedEnemies.map((target) => { const destination = teleportDestinations[target.id] ?? { row: "", col: "" }; return <div className="grid grid-cols-[1fr_6rem_6rem] gap-2" key={target.id}><span className="self-end pb-2 text-stone-200">{target.name}</span><label>行<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setTeleportDestinations((current) => ({ ...current, [target.id]: { ...destination, row: event.target.value } }))} type="number" value={destination.row} /></label><label>列<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setTeleportDestinations((current) => ({ ...current, [target.id]: { ...destination, col: event.target.value } }))} type="number" value={destination.col} /></label></div>; })}</div>;
                  }
                  return <div className="grid grid-cols-2 gap-2"><label>传送行<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setSpecialRow(event.target.value)} type="number" value={specialRow} /></label><label>传送列<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setSpecialCol(event.target.value)} type="number" value={specialCol} /></label></div>;
                })()}
              </>
            ) : null}
            {specialRuleKinds.includes("creation") || specialRuleKinds.includes("transformation") ? <label className="mt-2 block">模板/形态引用<input className={`${inputCls} mt-1`} onChange={(event) => setSpecialTemplate(event.target.value)} placeholder="DM 已建立的模板名称或引用" value={specialTemplate} /></label> : null}
            {specialRuleKinds.includes("transformation") && transformationNeedsStats ? <div className="mt-2 grid grid-cols-2 gap-2"><label>形态 AC<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setSpecialFormArmorClass(event.target.value)} type="number" value={specialFormArmorClass} /></label><label>形态当前 HP<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setSpecialFormHp(event.target.value)} type="number" value={specialFormHp} /></label><label>形态最大 HP<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setSpecialFormMaxHp(event.target.value)} type="number" value={specialFormMaxHp} /></label><label>形态速度（尺）<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setSpecialFormSpeed(event.target.value)} type="number" value={specialFormSpeed} /></label></div> : null}
            {specialRuleKinds.includes("creation") ? <div className="mt-2 grid grid-cols-3 gap-2"><label>数量<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setSpecialCount(event.target.value)} type="number" value={specialCount} /></label>{ruleFieldText(creationBlock, "creation_kind", "object") !== "item" ? <><label>放置行<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setSpecialRow(event.target.value)} type="number" value={specialRow} /></label><label>放置列<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setSpecialCol(event.target.value)} type="number" value={specialCol} /></label></> : <span className="self-end pb-2 text-2xs text-stone-300">创造物品会真实写入当前场景地点。</span>}</div> : null}
            {areaEffectBlocks.map((block) => {
              if (block.origin === "self") return <p className="mb-0 mt-2 text-2xs text-stone-300" key={String(block.id)}>区域「{String(block.shape)} {String(block.size_ft)}尺」以施法者当前位置为原点。</p>;
              const origin = areaOrigins[String(block.id)] ?? { row: "", col: "" };
              return <div className="mt-2 grid grid-cols-[1fr_6rem_6rem] gap-2" key={String(block.id)}><span className="self-end pb-2 text-2xs text-stone-300">区域原点 · {String(block.shape)} {String(block.size_ft)}尺</span><label>行<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setAreaOrigins((current) => ({ ...current, [String(block.id)]: { ...origin, row: event.target.value } }))} type="number" value={origin.row} /></label><label>列<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setAreaOrigins((current) => ({ ...current, [String(block.id)]: { ...origin, col: event.target.value } }))} type="number" value={origin.col} /></label></div>;
            })}
            {selectedChoiceBlocks.map((choice) => {
              const options = Array.isArray(choice.options) ? choice.options.filter((option): option is Record<string, unknown> => typeof option === "object" && option !== null) : [];
              const selected = choiceSelections[String(choice.id)] ?? [];
              const maximum = Number(choice.maximum_choices ?? 1);
              return <fieldset className="mt-2 rounded border border-cyan-800/60 p-2" key={String(choice.id)}><legend className="px-1 text-2xs text-cyan-100">{ruleFieldText(choice, "label", "选择规则分支")}（选 {Number(choice.minimum_choices ?? 1)}–{maximum} 项）</legend>{options.map((option) => { const key = typeof option.key === "string" ? option.key : ""; const checked = selected.includes(key); return <label className="mt-1 flex items-center gap-2 text-2xs text-stone-200" key={key}><input checked={checked} disabled={!key} onChange={(event) => setChoiceSelections((current) => { const currentValues = current[String(choice.id)] ?? []; const next = event.target.checked ? (maximum === 1 ? [key] : [...new Set([...currentValues, key])]) : currentValues.filter((value) => value !== key); return { ...current, [String(choice.id)]: next }; })} type="checkbox" />{ruleFieldText(option, "label", key || "未命名分支")}</label>; })}</fieldset>;
            })}
            {isDispelAction ? <><label className="mt-2 block">要结束的效果 ID（逗号分隔）<input className={`${inputCls} mt-1`} onChange={(event) => setSpecialEffectIds(event.target.value)} placeholder="从 DM 效果列表复制" value={specialEffectIds} /></label>{dispelBlock?.check_required === true ? <div className="mt-2 grid grid-cols-2 gap-2"><label>驱散检定总值<input className={`${inputCls} mt-1`} onChange={(event) => setDispelCheckTotal(event.target.value)} type="number" value={dispelCheckTotal} /></label><label>本次目标 DC<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setDispelCheckDc(event.target.value)} type="number" value={dispelCheckDc} /></label></div> : null}</> : null}
          </div> : null}
          {needsReactionTriggerInput ? <label className="mt-2 block text-xs text-stone-400">反应触发说明（必填）<input aria-label="玩家反应触发说明" className={`${inputCls} mt-1`} onChange={(event) => setReactionTrigger(event.target.value)} placeholder="例如：敌人进入射程（由 DM 确认）" value={reactionTrigger} /></label> : null}
          <label className="mt-2 block text-xs text-stone-400">目标<select className={`${inputCls} mt-1`} disabled={ended || !combat.is_my_turn || Boolean(selectedSummonBlock)} onChange={(event) => setTargetId(event.target.value)} value={targetId}><option value="">{isCastAction ? "选择规则效果目标" : "选择合法敌人"}</option>{targetCandidates.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.health_status}</option>)}</select></label>
          <div className="mt-3 rounded border border-amber-800/60 bg-amber-950/20 p-3 text-xs leading-5 text-amber-100">
            {selectedAction && selectedTarget ? (
              <>
                <strong>{selectedAction.name as string} → {selectedTarget.name}</strong>
                <span className="mt-1 block">
                  {isRuntimeFeatureAction
                    ? featureNeedsHealingRoll
                      ? <>这是可执行的职业特性；请掷治疗骰 {display(selectedAction?.healing ?? selectedAction?.healing_formula ?? "1d10+职业等级")}，填写最终总值。</>
                      : <>这是可执行的职业特性；提交后会消耗对应资源并真实改变战斗状态。</>
                  : isCastAction
                    ? hasHealingBlock
                      ? <>这是友方治疗效果；请掷治疗骰 {typeof selectedAction?.healing === "string" ? selectedAction.healing : "（资料库未记录，请由 DM 裁定）"}，把骰子结果相加后填入“治疗骰最终总值”。</>
                      : isSpecialAction
                        ? <>这是需要明确目的地、模板或效果 ID 的规则效果；完成上方选择后，系统会把对应积木实际写入战斗状态。</>
                        : <>这是友方战斗效果，不需要攻击骰或伤害骰；提交后会把规则积木写入目标的有效效果。</>
                  : isSavingThrowAction
                    ? <>该能力不需要玩家掷命中；请掷伤害骰 {damageInstruction}，把骰子结果相加后填入“伤害骰最终总值”。系统会让范围内的每个目标分别进行 {display(savingThrow?.ability)} 豁免（DC {display(savingThrow?.dc)}）。</>
                    : isAutoHitAction
                      ? <>这是自动命中的特殊技能，不需要 d20 命中骰；请按提示掷伤害骰 {damageInstruction}，系统会按力场等明确伤害类型结算。</>
                  : <>先掷 d20{attackBonus === null ? "，再加入角色卡命中调整值" : ` + ${attackBonus} 命中加值`}；最终总值需要达到 AC {selectedTarget.armor_class}（≥ {selectedTarget.armor_class}）才命中。命中后掷伤害骰 {damageInstruction}，把骰子结果相加后填入“伤害骰最终总值”。</>}
                </span>
                {automaticCriticalForSelectedTarget ? <p className="mb-0 mt-2 rounded border border-red-800/70 bg-red-950/30 p-2 text-2xs text-red-200">自动暴击已由 5 尺内的麻痹/昏迷状态触发。请按显示的双倍伤害骰（{damageInstruction}）重新掷骰；系统不会把你提交的最终总值再次翻倍。</p> : null}
              </>
            ) : (
              <span>先选择攻击/技能和目标；这里会明确显示命中所需 AC、命中加值与伤害骰。</span>
            )}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2"><label className="text-xs text-stone-400">d20命中总值<input className={`${inputCls} mt-1`} disabled={isAutoHitAction || isCastAction || isRuntimeFeatureAction || isSavingThrowAction} onChange={(event) => setAttackTotal(event.target.value)} placeholder={isAutoHitAction || isRuntimeFeatureAction ? "该特性无需命中" : isCastAction || isSavingThrowAction ? "该效果无需命中" : ""} type="number" value={attackTotal} /></label>{featureNeedsHealingRoll || hasHealingBlock || usesLegacyDamageTotal ? <label className="text-xs text-stone-400">{featureNeedsHealingRoll || hasHealingBlock ? "治疗骰最终总值" : "伤害骰最终总值"}<input className={`${inputCls} mt-1`} disabled={(isCastAction && !hasHealingBlock) || (isSpecialAction && !hasHealingBlock)} onChange={(event) => setDamageTotal(event.target.value)} type="number" value={damageTotal} /></label> : <span className="self-end pb-2 text-xs text-stone-400">此动作须在下方逐伤害段填写最终总值。</span>}</div>
          {requiresComponentTotals ? <fieldset className="mt-2 rounded border border-amber-800/60 bg-amber-950/15 p-3 text-xs text-amber-100"><legend className="px-1 text-2xs">逐伤害段掷骰总值</legend><p className="mb-2 mt-0 text-2xs leading-5 text-stone-300">每段都会独立提交给战斗引擎，因此抗性、易伤与免疫会按伤害类型分别结算；系统不会从总伤害中猜测分配。</p>{sharedDamageBlocks.map((block) => <label className="mt-2 block" key={String(block.id)}>{ruleFieldText(block, "damage_type", "未标注类型")} · {ruleFieldText(block, "expression", "伤害段")}<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setDamageComponentTotals((current) => ({ ...current, [String(block.id)]: event.target.value }))} type="number" value={damageComponentTotals[String(block.id)] ?? ""} /></label>)}{targetDamageBlocks.length ? <div className="mt-2 space-y-2">{affectedEnemies.map((target) => <div className="rounded border border-ink-700 p-2" key={target.id}><strong className="text-2xs text-stone-200">{target.name} 的分别伤害</strong>{targetDamageBlocks.map((block) => { const key = `${target.id}:${String(block.id)}`; return <label className="mt-1 block text-2xs text-stone-300" key={String(block.id)}>{ruleFieldText(block, "damage_type", "未标注类型")} · {ruleFieldText(block, "expression", "伤害段")}<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setTargetDamageComponentTotals((current) => ({ ...current, [key]: event.target.value }))} type="number" value={targetDamageComponentTotals[key] ?? ""} /></label>; })}</div>)}</div> : null}</fieldset> : null}
          {!isCastAction && !isSavingThrowAction ? <label className="mt-2 flex items-center gap-2 text-xs text-amber-200"><input checked={criticalHit} onChange={(event) => setCriticalHit(event.target.checked)} type="checkbox" />天然 20 暴击（每个伤害段请使用对应的暴击骰总值）</label> : null}
          <label className="mt-2 flex items-start gap-2 rounded border border-ink-700 p-2 text-xs text-stone-400"><input checked={endTurnAfterAttack} disabled={selectedActionCost === "reaction"} onChange={(event) => setEndTurnAfterAttack(event.target.checked)} type="checkbox" /><span>{selectedActionCost === "reaction" ? "反应不会自动结束你的当前回合。" : "攻击结算后自动结束回合并切到下一位。取消勾选可在攻击后继续使用剩余移动或附赠动作。"}</span></label>
          <Button className="mt-3 w-full" disabled={Boolean(selectedSummonBlock) || ended || !combat.is_my_turn || !actionName || !targetId || (!isAutoHitAction && !isCastAction && !isRuntimeFeatureAction && !isSavingThrowAction && !attackTotal) || (needsDamageRoll && usesLegacyDamageTotal && !damageTotal) || (featureNeedsHealingRoll && !damageTotal) || !divineSmiteDamageValid || !componentInputValid || !specialInputValid || !selectedActionAvailable} loading={mutation.isPending} onClick={() => mutation.mutate(async () => {
            if (isRuntimeFeatureAction) {
              const featureId = typeof selectedAction?.feature_id === "string" ? selectedAction.feature_id : "";
              const result = await submitMyFeatureAction(featureId, targetId, featureNeedsHealingRoll ? Number(damageTotal) : null) as { result?: { feature_name?: string; healing?: { hp_gained?: number } } };
              setAttackTotal("");
              setDamageTotal("");
              setLastResolution(`${result.result?.feature_name ?? actionName}已执行${result.result?.healing ? `；恢复 ${result.result.healing.hp_gained ?? 0} 点生命` : ""}。`);
              return result;
            }
            if (isCastAction) {
              const result = await castMyCombatAction(targetId, affectedEnemies.map((item) => item.id), actionName, selectedSpellLevel > 0 ? Math.max(selectedSpellLevel, slotLevel) : null, Number(hasHealingBlock ? damageTotal : 0), effectiveEndTurnAfterAttack, specialInputs()) as { target_count?: number; results?: Array<{ action?: { summary?: string; result_json?: Record<string, unknown> } }>; turn_advance?: { active_combatant?: { display_name?: string } } };
              setAttackTotal("");
              setDamageTotal("");
              const next = result.turn_advance?.active_combatant?.display_name;
              setLastResolution([`${actionName}已对 ${result.target_count ?? affectedEnemies.length} 个友方目标生效。`, ...(result.results ?? []).flatMap((item) => { const summary = item.action?.summary; const components = damageComponentsSummary(item.action?.result_json?.damage_components); return [summary, components ? `伤害段：${components}` : null].filter((value): value is string => Boolean(value)); }), effectiveEndTurnAfterAttack ? (next ? `回合已切换至 ${next}。` : "回合已经结束并完成同步。") : "你仍可移动、使用附赠动作或手动结束回合。"].join("\n"));
              return result;
            }
            const result = await attackWithMyCombatant(targetId, affectedEnemies.map((item) => item.id), actionName, selectedSpellLevel > 0 ? Math.max(selectedSpellLevel, slotLevel) : null, Number(attackTotal || 0), Number(damageTotal), criticalHit, effectiveEndTurnAfterAttack, {
              damageComponentTotals: Object.fromEntries(sharedDamageBlocks.flatMap((block) => {
                const value = damageComponentTotals[String(block.id)];
                return value === undefined || value === "" ? [] : [[String(block.id), Number(value)]];
              })),
              targetDamageComponentTotals: Object.fromEntries(targetDamageBlocks.length ? affectedEnemies.map((target) => [target.id, Object.fromEntries(targetDamageBlocks.map((block) => {
                const key = `${target.id}:${String(block.id)}`;
                return [String(block.id), Number(targetDamageComponentTotals[key])];
              }))]) : []),
              reactionTrigger: reactionTrigger.trim() || undefined,
              specialInputs: specialInputs(),
            }) as { target_count?: number; results?: Array<{ action?: { summary?: string; result_json?: Record<string, unknown> } }>; turn_advance?: { active_combatant?: { display_name?: string } } };
            setAttackTotal("");
            setDamageTotal("");
            setCriticalHit(false);
            const summaries = (result.results ?? []).flatMap((item) => { const summary = item.action?.summary; const components = damageComponentsSummary(item.action?.result_json?.damage_components); return [summary, components ? `伤害段：${components}` : null].filter((value): value is string => Boolean(value)); });
            const next = result.turn_advance?.active_combatant?.display_name;
            setLastResolution([`${actionName}已完成全部 ${result.target_count ?? affectedEnemies.length} 个目标的结算。`, ...summaries, effectiveEndTurnAfterAttack ? (next ? `回合已切换至 ${next}。` : "回合已经结束并完成同步。") : "你仍可移动、使用附赠动作或手动结束回合。"].join("\n"));
            return result;
          })} variant="primary">{isRuntimeFeatureAction ? "执行职业特性" : isCastAction ? (isSpecialAction ? (endTurnAfterAttack ? "执行规则效果并结束回合" : "执行规则效果并同步") : (endTurnAfterAttack ? "施放友方效果并结束回合" : "施放友方效果并同步")) : isSavingThrowAction ? `提交玩家伤害骰并结算 ${affectedEnemies.length} 个目标` : isAutoHitAction ? (endTurnAfterAttack ? "自动命中并提交伤害后结束回合" : "自动命中并提交伤害") : endTurnAfterAttack ? "提交攻击并结束回合" : "提交攻击并同步结算"}</Button>
          <Button className="mt-2 w-full" disabled={ended || !combat.is_my_turn} onClick={() => mutation.mutate(() => endMyTurn(combat.version))}>结束我的回合</Button>
          {lastResolution ? <p className="mb-0 mt-2 whitespace-pre-line rounded border border-emerald-800/60 bg-emerald-950/20 p-2 text-xs text-emerald-200" data-testid="player-last-resolution">{lastResolution}</p> : null}
          {mutation.isError ? <p className="text-sm text-red-300">{mutation.error.message}</p> : null}
        </section>
        <section className={cardCls}><h2 className="mt-0 font-display text-xl">公开战斗日志</h2><div className="max-h-72 space-y-2 overflow-auto">{combat.log.map((entry) => { const components = damageComponentsSummary(entry.damage_components); const byTarget = damageComponentsByTargetSummary(entry.damage_components_by_target); return <div className="border-b border-ink-800 pb-2" key={entry.id}><p className="m-0 text-xs text-stone-400"><span className="text-amber-300">R{entry.round_number}</span> {entry.summary}</p>{components ? <p className="m-0 mt-1 text-2xs text-amber-200">伤害段：{components}</p> : null}{byTarget ? <p className="m-0 mt-1 text-2xs text-amber-200">逐目标：{byTarget}</p> : null}</div>; })}</div></section>
      </aside>
    </div>
  );
}

function PlayerDashboard({
  snapshot,
  refresh,
  syncing,
  updatedAt,
  offline,
  degraded,
}: {
  snapshot: PlayerRoomSnapshot;
  refresh: () => void;
  syncing: boolean;
  updatedAt: number;
  offline: boolean;
  degraded: boolean;
}): ReactElement {
  const [tab, setTab] = useState<"table" | "character" | "shop" | "combat" | "rules">(
    snapshot.combat?.status === "active" ? "combat" : "table",
  );
  const [intent, setIntent] = useState("");
  const [ruleText, setRuleText] = useState("");
  const [ruleHits, setRuleHits] = useState<Awaited<ReturnType<typeof searchPlayerRules>>>([]);
  const [showRoomSwitch, setShowRoomSwitch] = useState(false);
  const [switchCode, setSwitchCode] = useState("");
  const [restRequestSent, setRestRequestSent] = useState<"short" | "long" | null>(null);
  const [restHitDice, setRestHitDice] = useState<Record<string, string>>({});
  const hitDice = snapshot.character?.hit_dice ?? [];
  const intentMutation = useMutation({ mutationFn: () => submitMyActionRequest("player_intent", intent), onSuccess: () => setIntent("") });
  const levelRequestMutation = useMutation({
    mutationFn: (transition: NonNullable<PlayerRoomSnapshot["table"]["scene"]>["available_transitions"][number]) =>
      submitMyActionRequest(
        "site_level_transition",
        `申请通过「${transition.label}」前往${transition.target_level_name}。`,
        { connector_id: transition.connector_id },
      ),
    onSuccess: refresh,
  });
  const restRequestMutation = useMutation({
    mutationFn: ({ restType, hitDice: selectedHitDice }: RestRequestInput) => submitMyActionRequest(
      "rest_request",
      `申请进行${restType === "long" ? "长休" : "短休"}。`,
      { schema_version: "1.0", rest_type: restType, hit_dice: selectedHitDice },
    ),
    onSuccess: (_result, request) => {
      setRestRequestSent(request.restType);
      refresh();
    },
  });
  const rulesMutation = useMutation({ mutationFn: () => searchPlayerRules(ruleText), onSuccess: setRuleHits });
  const roomSwitchMutation = useMutation({
    mutationFn: () => switchPlayerRoom(switchCode, snapshot.player.display_name),
    onSuccess: () => window.location.reload(),
  });
  useEffect(() => {
    if (snapshot.combat?.status === "active") setTab("combat");
  }, [snapshot.combat?.id, snapshot.combat?.status]);
  const availableTransitions = snapshot.table.scene?.available_transitions ?? [];
  const latestGuidance = snapshot.table.shared_log.find(
    (event) => event.event_type === "player_guidance",
  );
  const guidanceSuggestions = latestGuidance?.description
    ?.split("\n")
    .map((item) => item.trim())
    .filter(Boolean) ?? [];
  const publicLog = snapshot.table.shared_log.filter(
    (event) => event.event_type !== "player_guidance",
  );
  const suggestedCharacterActions = snapshot.table.noncombat?.available_actions.slice(0, 3) ?? [];
  return (
    <main className="mx-auto min-h-screen max-w-[1500px] p-3 lg:p-6">
      <header className="mb-4 flex flex-wrap items-center gap-3 border-b border-ink-700 pb-4">
        <div className="mr-auto"><p className="m-0 text-xs uppercase tracking-[.18em] text-amber-300">玩家辅助台 · {snapshot.player.display_name}</p><h1 className="mb-0 mt-1 font-display text-2xl">{snapshot.campaign.name}</h1></div>
        <span className="text-xs text-stone-500">{snapshot.character?.name}</span>
        <span
          className={`rounded border px-2 py-1 text-2xs ${offline || degraded ? "border-red-800/60 bg-red-950/30 text-red-200" : syncing ? "border-amber-800/60 bg-amber-950/30 text-amber-200" : "border-emerald-800/60 bg-emerald-950/25 text-emerald-300"}`}
          title={updatedAt ? `最后同步：${new Date(updatedAt).toLocaleTimeString()}` : "尚未完成同步"}
        >
          {offline ? "网络已断开" : degraded ? "服务器连接中断 · 保留当前画面" : syncing ? "正在同步…" : "已同步"}
        </span>
        <Button onClick={() => setShowRoomSwitch((current) => !current)} size="sm" variant="primary">切换跑团</Button>
        <Button onClick={() => void logoutPlayerRoom().then(() => window.location.reload())} size="sm">退出房间</Button>
      </header>
      {showRoomSwitch ? (
        <section className="mb-4 rounded-xl border border-amber-700/70 bg-amber-950/20 p-4">
          <strong className="text-sm text-amber-100">切换到 DM 当前发布的新团</strong>
          <p className="mb-3 mt-1 text-xs leading-5 text-stone-400">
            输入新团房间码。验证成功后才会离开“{snapshot.campaign.name}”；错误房间码不会影响当前会话。
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="新团房间码"
              autoCapitalize="characters"
              className={`${inputCls} max-w-56 text-center font-mono tracking-[.2em]`}
              maxLength={8}
              onChange={(event) => setSwitchCode(event.target.value.toUpperCase())}
              placeholder="6位房间码"
              value={switchCode}
            />
            <Button
              disabled={switchCode.trim().length < 6}
              loading={roomSwitchMutation.isPending}
              onClick={() => roomSwitchMutation.mutate()}
              variant="primary"
            >
              确认切换
            </Button>
            <Button onClick={() => setShowRoomSwitch(false)}>取消</Button>
          </div>
          {roomSwitchMutation.isError ? <p className="mb-0 mt-2 text-sm text-red-300">{roomSwitchMutation.error.message}</p> : null}
        </section>
      ) : null}
      <nav className="mb-4 flex gap-2 overflow-x-auto">{([["table", "游戏推进"], ["character", "我的角色"], ["shop", "商店"], ["combat", snapshot.combat?.status === "active" ? "战斗中" : "战斗"], ["rules", "规则搜索"]] as const).map(([key, label]) => <Button key={key} onClick={() => setTab(key)} variant={tab === key ? "primary" : "ghost"}>{label}</Button>)}</nav>
      {tab === "character" && snapshot.character ? <CharacterView character={snapshot.character} onChanged={refresh} /> : null}
      {tab === "shop" && snapshot.character ? <PlayerShopView shops={snapshot.table.shops ?? []} wallet={snapshot.character.wallet} refresh={refresh} /> : null}
      {tab === "combat" ? <CombatView refresh={refresh} snapshot={snapshot} /> : null}
      {tab === "rules" ? <section className={cardCls}><h2 className="mt-0 font-display text-2xl">D&D 5e 本地规则搜索</h2><p className="text-sm text-stone-400">只做确定性关键词检索，不调用本地生成AI。</p><div className="flex gap-2"><input aria-label="规则关键词" className={inputCls} onChange={(event) => setRuleText(event.target.value)} placeholder="例如：擒抱、火球术、倒地" value={ruleText} /><Button disabled={!ruleText.trim()} loading={rulesMutation.isPending} onClick={() => rulesMutation.mutate()} variant="primary">搜索</Button></div><div className="mt-4 space-y-3">{ruleHits.map((hit, index) => <article className="rounded border border-ink-700 p-3" key={`${hit.name}-${index}`}><strong>{hit.name}</strong><span className="ml-2 text-2xs text-stone-500">{hit.edition} · {hit.content_type}</span><p className="mb-0 text-sm leading-6 text-stone-400">{hit.excerpt}</p></article>)}</div></section> : null}
      {tab === "table" ? <div className="grid gap-4 lg:grid-cols-[1.2fr_.8fr]">
        <div className="space-y-4">
          {latestGuidance ? (
            <section
              aria-live="polite"
              className={`${cardCls} border-violet-700/70 bg-violet-950/20`}
              data-testid="player-live-guidance"
              key={latestGuidance.id}
            >
              <p className="m-0 text-2xs font-semibold uppercase tracking-[.18em] text-violet-300">随 DM 推进自动更新</p>
              <h2 className="mb-2 mt-1 font-display text-xl text-violet-50">{latestGuidance.title}</h2>
              <ul className="m-0 space-y-2 pl-5 text-sm leading-6 text-stone-300">
                {guidanceSuggestions.map((suggestion) => <li key={suggestion}>{suggestion}</li>)}
              </ul>
              {suggestedCharacterActions.length ? (
                <div className="mt-3 border-t border-violet-800/50 pt-3">
                  <span className="text-2xs text-stone-500">结合你的角色，可考虑：</span>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {suggestedCharacterActions.map((action) => <span className="rounded border border-violet-800/60 bg-ink-950/50 px-2 py-1 text-xs text-violet-200" key={action.id}>{action.name}</span>)}
                  </div>
                </div>
              ) : null}
            </section>
          ) : null}
          <section className={cardCls}><h2 className="mt-0 font-display text-2xl">{snapshot.table.scene?.name ?? "等待 DM 选择 Scene"}</h2><p className="whitespace-pre-wrap text-sm leading-6 text-stone-400">{snapshot.table.scene?.description}</p>
            {availableTransitions.length ? (
              <div className="mt-3 rounded border border-violet-800/60 bg-violet-950/20 p-3">
                <strong className="text-sm text-violet-100">已发现楼层连接</strong>
                <p className="mb-2 mt-1 text-2xs text-stone-400">这里只显示战争迷雾已经公开的楼梯。提交后需由 DM 批准并切换公开 Scene。</p>
                <div className="flex flex-wrap gap-2">
                  {availableTransitions.map((transition) => (
                    <Button
                      key={transition.connector_id}
                      loading={levelRequestMutation.isPending}
                      onClick={() => levelRequestMutation.mutate(transition)}
                      size="sm"
                      variant="primary"
                    >
                      {transition.direction === "stairs_up"
                        ? "申请前往上一层"
                        : "申请前往下一层"}
                      {` · ${transition.target_level_name}`}
                    </Button>
                  ))}
                </div>
                {levelRequestMutation.isSuccess ? <p className="mb-0 mt-2 text-2xs text-emerald-300">换层申请已发送，等待 DM 处理。</p> : null}
                {levelRequestMutation.isError ? <p className="mb-0 mt-2 text-2xs text-red-300">{levelRequestMutation.error.message}</p> : null}
              </div>
            ) : null}
          </section>
          {snapshot.table.scene ? <NoncombatActionPanel refresh={refresh} snapshot={snapshot} /> : null}
        </div>
        <aside className="space-y-4">
          <section className={cardCls}>
            <h2 className="mt-0 font-display text-xl">休息申请</h2>
            <p className="text-xs leading-5 text-stone-400">短休或长休都要先提交给 DM；DM 批准后才会执行规则结算并更新你的角色状态。</p>
            {hitDice.length ? (
              <div className="mb-3 rounded border border-ink-700 bg-ink-950/40 p-3">
                <strong className="text-xs text-parchment-100">短休生命骰</strong>
                <p className="mb-2 mt-1 text-2xs leading-5 text-stone-500">短休时可选填要消耗的生命骰；按实际掷骰结果逐枚填写，例如 6,8。留空则只恢复短休资源，不消耗生命骰。</p>
                {hitDice.map((pool) => (
                  <label className="mt-2 block text-xs text-stone-400" key={pool.id}>
                    {pool.label} · 可用 {pool.current}/{pool.maximum}
                    <input
                      aria-label={`${pool.label}结果`}
                      className={`${inputCls} mt-1`}
                      disabled={pool.current < 1 || restRequestMutation.isPending}
                      inputMode="numeric"
                      onChange={(event) => setRestHitDice((current) => ({ ...current, [pool.id]: event.target.value }))}
                      placeholder={`例如 ${Math.max(1, Math.floor((pool.die_size ?? 8) / 2))}`}
                      value={restHitDice[pool.id] ?? ""}
                    />
                  </label>
                ))}
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button disabled={restRequestMutation.isPending} loading={restRequestMutation.isPending && restRequestMutation.variables?.restType === "short"} onClick={() => restRequestMutation.mutate({ restType: "short", hitDice: hitDice.flatMap((pool) => (restHitDice[pool.id] ?? "").split(/[,，\s]+/).filter(Boolean).map((roll) => ({ resource_pool_id: pool.id, roll: Number(roll) }))) })} variant="primary">申请短休 · 1小时</Button>
              <Button disabled={restRequestMutation.isPending} loading={restRequestMutation.isPending && restRequestMutation.variables?.restType === "long"} onClick={() => restRequestMutation.mutate({ restType: "long", hitDice: [] })} variant="primary">申请长休 · 8小时</Button>
            </div>
            {restRequestSent ? <p className="mb-0 mt-2 text-xs text-emerald-300">{restRequestSent === "long" ? "长休" : "短休"}申请已发送，等待 DM 批准。</p> : null}
            {restRequestMutation.isError ? <p className="mb-0 mt-2 text-xs text-red-300">{restRequestMutation.error.message}</p> : null}
          </section>
          <section className={cardCls}><h2 className="mt-0 font-display text-xl">公开游戏日志</h2>{publicLog.length ? publicLog.map((event) => <article className="mb-3 border-l-2 border-amber-700 pl-3" key={event.id}><strong className="text-sm">{event.title}</strong><p className="mb-0 mt-1 text-xs text-stone-400">{event.description}</p></article>) : <p className="text-sm text-stone-500">等待 DM 推进。</p>}</section>
          <section className={cardCls}><h2 className="mt-0 font-display text-xl">公开讲义</h2>{snapshot.table.handouts.map((handout) => <details className="mb-2 rounded border border-ink-700 p-2" key={handout.id}><summary>{handout.title}</summary><p className="whitespace-pre-wrap text-sm text-stone-400">{handout.body}</p></details>)}</section>
          <section className={cardCls}><h2 className="mt-0 font-display text-xl">自由行动</h2><p className="text-xs text-stone-500">规则列表没有覆盖时，仍可用自然语言告诉 DM。</p><textarea className={inputCls} onChange={(event) => setIntent(event.target.value)} placeholder="例如：我把耳朵贴在门上听里面的声音。" rows={3} value={intent} /><Button className="mt-2" disabled={!intent.trim()} loading={intentMutation.isPending} onClick={() => intentMutation.mutate()} variant="primary">提交给 DM 裁定</Button></section>
        </aside>
      </div> : null}
    </main>
  );
}

export function PlayerPage(): ReactElement {
  const client = useQueryClient();
  const offline = useOffline();
  const simulationJoin = useMemo(readSimulationJoin, []);
  const room = useQuery({
    queryKey: ["my-player-room"],
    queryFn: ({ signal }) => getMyPlayerRoom(signal),
    retry: false,
    // Keep the join form stable while the player is unauthenticated. Polling
    // the 401 response every few seconds can remount the gate while someone
    // is typing, which looks like the page refreshed and clears the room code.
    refetchInterval: false,
  });
  const missing = room.isError && isPlayerSessionMissing(room.error);
  const content = useMemo(() => room.data, [room.data]);
  const autoJoin = useMutation({
    mutationFn: () => joinPlayerRoom(simulationJoin?.code ?? "", simulationJoin?.name ?? "模拟玩家"),
    onSuccess: () => void room.refetch(),
  });
  const autoSwitch = useMutation({
    mutationFn: () => switchPlayerRoom(simulationJoin?.code ?? "", simulationJoin?.name ?? "模拟玩家"),
    onSuccess: () => void room.refetch(),
  });
  const autoBind = useMutation({
    mutationFn: (characterId: string) => bindMyCharacter(characterId),
    onSuccess: () => void room.refetch(),
  });
  const autoRoomAttempted = useRef(false);
  const autoBindAttempted = useRef(false);

  useEffect(() => {
    const alreadyInSimulation = content?.campaign.name === SIMULATION_CAMPAIGN_NAME;
    if (
      !simulationJoin
      || room.isLoading
      || (!content && !missing)
      || alreadyInSimulation
      || autoRoomAttempted.current
      || autoJoin.isPending
      || autoSwitch.isPending
    ) return;
    autoRoomAttempted.current = true;
    if (content) autoSwitch.mutate();
    else autoJoin.mutate();
  }, [autoJoin, autoSwitch, content, missing, room.isLoading, simulationJoin]);

  useEffect(() => {
    const candidate = content?.available_characters?.find((item) => item.name === "模拟玩家·奥术师");
    if (
      !simulationJoin
      || !content
      || content.character
      || !candidate
      || autoBindAttempted.current
      || autoBind.isPending
    ) return;
    autoBindAttempted.current = true;
    autoBind.mutate(candidate.id);
  }, [autoBind, content, simulationJoin]);

  usePlayerRealtime(Boolean(room.data));
  const refresh = () => { void client.invalidateQueries({ queryKey: ["my-player-room"] }); };
  if (simulationJoin && (autoJoin.isPending || autoSwitch.isPending)) {
    return <LoadingBlock label="正在切换到模拟玩家房间…" />;
  }
  if (room.isLoading) return <LoadingBlock label="正在连接玩家房间…" />;
  if (missing && !content) {
    return <JoinRoom onJoined={refresh} />;
  }
  if (room.isError && !content) return <main className="mx-auto max-w-xl p-6"><ErrorState error={room.error} onRetry={() => void room.refetch()} /></main>;
  if (!content) return <JoinRoom onJoined={refresh} />;
  if (simulationJoin && autoBind.isPending) return <LoadingBlock label="正在绑定模拟玩家角色…" />;
  if (!content.character) return <CharacterBuilder onDone={refresh} snapshot={content} />;
  return (
    <PlayerDashboard
      offline={offline}
      degraded={room.isError}
      refresh={refresh}
      snapshot={content}
      syncing={room.isFetching}
      updatedAt={room.dataUpdatedAt}
    />
  );
}
