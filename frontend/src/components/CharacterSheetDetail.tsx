import { useQuery } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

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
  const prof = proficiencyBonus(character.level);
  const skills = Object.entries(SKILL_ABILITY);
  const actions = character.actions.map(objectValue);
  const resources = Object.values(character.resources).map(objectValue);

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
              <div><h3 className="text-sm text-parchment-100">特性</h3><div className="flex flex-wrap gap-2">{character.features.length ? character.features.map((feature, index) => <span className="rounded border border-violet-800/50 bg-violet-950/20 px-2 py-1 text-xs text-violet-200" key={`${text(feature)}-${index}`}>{text(objectValue(feature).name ?? feature)}</span>) : <span className="text-xs text-stone-600">暂无特性</span>}</div></div>
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
            <div className="grid gap-4 md:grid-cols-2">
              <section><h3 className="mt-0 text-sm text-parchment-100">职业资源</h3><div className="space-y-2">{resources.map((resource, index) => <div className="rounded border border-ink-700 p-3" key={`${text(resource.label)}-${index}`}><div className="flex"><strong className="mr-auto text-xs text-parchment-100">{text(resource.label, "资源")}</strong><span className="font-mono text-violet-300">{text(resource.current, "0")}/{text(resource.max, "0")}</span></div><p className="mb-0 mt-1 text-2xs text-stone-600">{resource.recovery === "short_rest" ? "短休恢复" : "长休恢复"}</p></div>)}{resources.length === 0 ? <p className="text-xs text-stone-600">暂无职业资源。</p> : null}</div></section>
              <section><h3 className="mt-0 text-sm text-parchment-100">法术</h3><div className="space-y-2">{character.spells.map((spell, index) => { const data = objectValue(spell); return <div className="rounded border border-ink-700 p-3" key={`${text(data.name ?? spell)}-${index}`} title={text(data.description, "暂无法术说明")}><strong className="text-xs text-parchment-100">{text(data.name ?? spell)}</strong><p className="mb-0 mt-1 text-2xs text-stone-500">{text(data.level, "法术")} · {text(data.range, "距离未记录")}</p></div>; })}{character.spells.length === 0 ? <p className="text-xs text-stone-600">暂无已记录法术。</p> : null}</div></section>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
