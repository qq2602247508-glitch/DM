import type { Monster, Npc } from "../api/types";
import { Badge, Button, EmptyState } from "../ui/primitives";

const ABILITIES: Record<string, string> = {
  strength: "力量",
  dexterity: "敏捷",
  constitution: "体质",
  intelligence: "智力",
  wisdom: "感知",
  charisma: "魅力",
};

function signedModifier(score: number): string {
  const value = Math.floor((score - 10) / 2);
  return value >= 0 ? `+${value}` : String(value);
}

function signed(value: number): string {
  return value >= 0 ? `+${value}` : String(value);
}

function isNpc(entity: Npc | Monster): entity is Npc {
  return "attitude" in entity;
}

export function SceneEntityDetailDialog({
  entity,
  entityType,
  onClose,
}: {
  entity: Npc | Monster;
  entityType: "npc" | "monster";
  onClose: () => void;
}) {
  const npc = isNpc(entity) ? entity : null;
  const monster: Monster | null = npc ? null : entity as Monster;
  const kindLabel = entityType === "npc" ? "NPC 原子详情" : "怪物原子详情";

  return (
    <div
      aria-label={`${entity.name}${kindLabel}`}
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-ink-950/80 p-3 backdrop-blur-sm"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
      role="dialog"
    >
      <section className="flex max-h-[94vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-violet-700/50 bg-ink-900 shadow-2xl">
        <header className="flex flex-wrap items-start gap-3 border-b border-ink-700 px-5 py-4">
          <div className="mr-auto">
            <p className="m-0 text-2xs uppercase tracking-[0.2em] text-violet-400">D&amp;D 5e 2024 · {kindLabel}</p>
            <h2 className="m-0 mt-1 font-display text-2xl text-parchment-100">{entity.name}</h2>
            <div className="mt-2 flex flex-wrap gap-2">
              <Badge tone={entityType === "npc" ? "ai" : "danger"}>{entityType === "npc" ? "NPC" : "怪物"}</Badge>
              <Badge>CR {entity.challenge_rating ?? "未记录"}</Badge>
              {npc ? <Badge tone={npc.status === "active" ? "ok" : "neutral"}>{npc.status}</Badge> : null}
              {npc?.attitude ? <Badge tone="warn">态度：{npc.attitude}</Badge> : null}
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[["AC", entity.armor_class], ["HP", `${entity.hp}/${entity.max_hp}`], ["速度", `${entity.speed}尺`]].map(([label, value]) => (
              <div className="min-w-16 rounded border border-ink-700 bg-ink-950/60 px-2 py-1.5" key={label}>
                <span className="block text-2xs text-stone-600">{label}</span>
                <strong className="font-mono text-sm text-parchment-100">{value}</strong>
              </div>
            ))}
          </div>
          <Button aria-label={`关闭${kindLabel}`} onClick={onClose}>关闭</Button>
        </header>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          <section>
            <h3 className="mt-0 text-sm text-parchment-100">六维属性</h3>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
              {Object.entries(ABILITIES).map(([key, label]) => {
                const score = entity.ability_scores[key] ?? 10;
                return <div className="rounded-lg border border-ink-700 bg-ink-950/50 p-3 text-center" key={key}><span className="block text-2xs text-stone-500">{label}</span><strong className="block font-mono text-xl text-parchment-100">{score}</strong><span className="text-xs text-violet-300">{signedModifier(score)}</span></div>;
              })}
            </div>
          </section>

          {npc ? (
            <section className="grid gap-3 md:grid-cols-2">
              {[
                ["外观与描述", npc.description],
                ["性格", npc.personality],
                ["目标", npc.goal],
                ["恐惧", npc.fear],
                ["关系", npc.relationship],
                ["已知信息", npc.known_information],
                ["DM秘密", npc.secrets],
              ].map(([label, value]) => (
                <article className="rounded-lg border border-ink-700 bg-ink-950/45 p-3" key={label}>
                  <h3 className="m-0 text-xs text-violet-200">{label}</h3>
                  <p className="mb-0 mt-2 whitespace-pre-wrap text-xs leading-5 text-stone-400">{value || "未记录"}</p>
                </article>
              ))}
            </section>
          ) : (
            <section className="grid gap-3 md:grid-cols-2">
              <article className="rounded-lg border border-ink-700 bg-ink-950/45 p-3"><h3 className="m-0 text-xs text-violet-200">来源</h3><p className="mb-0 mt-2 text-xs text-stone-400">{monster?.source_name || "自定义 / 未记录"}</p><p className="mb-0 mt-1 break-all text-2xs text-stone-600">记录：{monster?.source_record_id || "—"}</p></article>
              <article className="rounded-lg border border-ink-700 bg-ink-950/45 p-3"><h3 className="m-0 text-xs text-violet-200">DM备注</h3><p className="mb-0 mt-2 whitespace-pre-wrap text-xs text-stone-400">{monster?.notes || "未记录"}</p></article>
            </section>
          )}

          <section>
            <h3 className="text-sm text-parchment-100">动作、攻击与法术</h3>
            <div className="grid gap-3 md:grid-cols-2">
              {entity.actions.map((action, index) => (
                <article className="rounded-lg border border-ink-700 bg-ink-950/45 p-4" key={`${action.name}-${index}`}>
                  <div className="flex flex-wrap items-center gap-2"><strong className="mr-auto text-sm text-parchment-100">{action.name}</strong>{action.damage ? <Badge tone="danger">{action.damage}{action.damage_type ? ` ${action.damage_type}` : ""}</Badge> : null}</div>
                  <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <div><dt className="text-stone-600">距离 / 范围</dt><dd className="m-0 text-stone-300">{action.range || "未记录"}</dd></div>
                    <div><dt className="text-stone-600">行动消耗</dt><dd className="m-0 text-stone-300">{action.cost || "动作"}</dd></div>
                    <div><dt className="text-stone-600">攻击加值</dt><dd className="m-0 text-stone-300">{action.attack_bonus === undefined ? "—" : signed(action.attack_bonus)}</dd></div>
                    <div><dt className="text-stone-600">豁免</dt><dd className="m-0 text-stone-300">{action.save_dc ? `${action.save_ability || "属性"} DC ${action.save_dc}` : "—"}</dd></div>
                  </dl>
                  <p className="mb-0 mt-3 whitespace-pre-wrap text-xs leading-5 text-stone-400">{action.description || "暂无动作说明"}</p>
                  {action.recharge ? <p className="mb-0 mt-2 text-2xs text-amber-300">恢复 / 限制：{action.recharge}</p> : null}
                </article>
              ))}
              {entity.actions.length === 0 ? <EmptyState title="暂无动作资料" hint="可回到 NPC 或怪物原子页面补充动作、伤害、范围与使用限制。" /> : null}
            </div>
          </section>

          {npc ? (
            <section>
              <h3 className="text-sm text-parchment-100">携带物品</h3>
              <div className="grid gap-2 md:grid-cols-2">
                {npc.equipment.map((item, index) => <article className="rounded border border-ink-700 bg-ink-950/45 p-3" key={`${item.name}-${index}`}><strong className="text-xs text-parchment-100">{item.name} × {item.quantity}</strong><p className="mb-0 mt-1 text-2xs text-stone-500">{item.unit_weight_lb * item.quantity} 磅 · {item.price_cp * item.quantity} cp</p><p className="mb-0 mt-2 text-xs text-stone-400">{item.description || item.interactive_note || "无说明"}</p></article>)}
                {npc.equipment.length === 0 ? <p className="text-xs text-stone-600">未记录携带物品。</p> : null}
              </div>
            </section>
          ) : null}
        </div>
      </section>
    </div>
  );
}
