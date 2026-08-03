import type { Combatant } from "../../api/types";
import { Badge } from "../../ui/primitives";

const ABILITY_LABELS = [
  ["strength", "力量"],
  ["dexterity", "敏捷"],
  ["constitution", "体质"],
  ["intelligence", "智力"],
  ["wisdom", "感知"],
  ["charisma", "魅力"],
] as const;

function entityLabel(fighter: Combatant): string {
  if (fighter.entity_type === "character") return "玩家";
  if (fighter.entity_type === "npc") return "NPC";
  if (fighter.entity_type === "companion") {
    return fighter.snapshot_json.controller === "player" ? "玩家召唤物" : "敌方召唤物";
  }
  return "怪物";
}

export function InitiativeCardStrip({
  currentIndex,
  expandedId,
  fighters,
  onToggle,
}: {
  currentIndex: number;
  expandedId: string | null;
  fighters: Combatant[];
  onToggle: (fighterId: string) => void;
}) {
  const expanded = fighters.find((fighter) => fighter.id === expandedId) ?? null;
  const abilities = expanded?.snapshot_json.ability_scores as
    | Record<string, number>
    | undefined;
  const actions = (
    (expanded?.snapshot_json.actions as unknown[] | undefined) ?? []
  ).filter((action): action is string | Record<string, unknown> => (
    typeof action === "string" || Boolean(action && typeof action === "object")
  ));

  return (
    <section className="mt-3 rounded-lg border border-ink-700 bg-ink-950/45 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="ai">先攻轨道</Badge>
        <strong className="text-sm text-parchment-100">本轮行动顺序</strong>
        <span className="text-2xs text-stone-500">从左到右行动；当前单位有橙色描边，点击卡片查看详情</span>
      </div>
      <div className="mt-3 flex gap-2 overflow-x-auto pb-2">
        {fighters.map((fighter, index) => {
          const current = index === currentIndex;
          const selected = fighter.id === expandedId;
          return (
            <button
              aria-expanded={selected}
              className={`min-w-52 rounded-lg border p-3 text-left transition ${
                current
                  ? "border-ember-400 bg-ember-950/25 ring-2 ring-ember-500/45"
                  : selected
                    ? "border-sky-600 bg-sky-950/15"
                    : "border-ink-700 bg-ink-950/70 hover:border-ink-500"
              }`}
              data-testid={`initiative-card-${fighter.id}`}
              key={fighter.id}
              onClick={() => onToggle(fighter.id)}
              type="button"
            >
              <div className="flex items-center gap-2">
                <span className="flex size-8 items-center justify-center rounded-full border border-ink-600 bg-ink-900 font-mono text-sm font-bold text-ember-200">
                  {fighter.initiative}
                </span>
                <div className="min-w-0 flex-1">
                  <strong className="block truncate text-sm text-parchment-100">{fighter.display_name}</strong>
                  <span className="text-2xs text-stone-500">
                    {entityLabel(fighter)}{current ? " · 当前行动" : ` · 第 ${index + 1} 位`}
                  </span>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-1 text-center text-2xs">
                <span className="rounded bg-ink-900 px-1 py-1 text-stone-300"><b className="block text-parchment-100">AC {fighter.armor_class}</b>护甲</span>
                <span className="rounded bg-ink-900 px-1 py-1 text-stone-300"><b className="block text-parchment-100">{fighter.hp}/{fighter.max_hp}</b>生命</span>
                <span className="rounded bg-ink-900 px-1 py-1 text-stone-300"><b className="block text-parchment-100">{fighter.movement_remaining_ft}尺</b>移动</span>
              </div>
            </button>
          );
        })}
      </div>
      {expanded ? (
        <div className="mt-2 rounded-lg border border-sky-800/50 bg-sky-950/10 p-3" data-testid="initiative-card-detail">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="text-sm text-sky-100">{expanded.display_name} · 详细战斗卡</strong>
            <Badge tone={expanded.entity_type === "character" || (expanded.entity_type === "companion" && expanded.snapshot_json.controller === "player") ? "ok" : "danger"}>
              {entityLabel(expanded)}
            </Badge>
            <span className="text-2xs text-stone-500">
              动作{expanded.action_available ? "可用" : "已用"} ·
              附赠{expanded.bonus_action_available ? "可用" : "已用"} ·
              反应{expanded.reaction_available ? "可用" : "已用"}
            </span>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-1 sm:grid-cols-6">
            {ABILITY_LABELS.map(([key, label]) => {
              const score = Number(abilities?.[key] ?? 10);
              const modifier = Math.floor((score - 10) / 2);
              return (
                <span className="rounded border border-ink-700 bg-ink-950/70 px-2 py-1 text-center text-2xs text-stone-500" key={key}>
                  {label}
                  <b className="block text-sm text-parchment-100">
                    {score} ({modifier >= 0 ? "+" : ""}{modifier})
                  </b>
                </span>
              );
            })}
          </div>
          <p className="mb-0 mt-2 text-2xs text-stone-400">
            {expanded.conditions.length > 0 ? `状态：${expanded.conditions.join("、")} · ` : "状态：正常 · "}
            {expanded.damage_resistances.length > 0 ? `抗性：${expanded.damage_resistances.join("、")} · ` : ""}
            {expanded.damage_immunities.length > 0 ? `免疫：${expanded.damage_immunities.join("、")} · ` : ""}
            速度 {expanded.speed_ft}尺
          </p>
          {actions.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {actions.map((action, index) => {
                const rawName = typeof action === "string" ? action : action.name;
                const name = typeof action === "string"
                  ? action
                  : typeof rawName === "string" || typeof rawName === "number"
                    ? String(rawName)
                    : `动作 ${index + 1}`;
                const detail = typeof action === "string"
                  ? ""
                  : [action.damage, action.range, action.cost].filter(Boolean).join(" · ");
                return (
                  <span className="rounded border border-violet-800/50 bg-violet-950/15 px-2 py-1 text-2xs text-violet-200" key={`${name}-${index}`}>
                    {name}{detail ? ` · ${detail}` : ""}
                  </span>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
