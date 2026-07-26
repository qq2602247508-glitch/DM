import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactElement } from "react";

import { confirmRest, listResourcePools, previewRest } from "../api/entities";
import type { Character, RestPreview, RestPreviewRequest, RestType } from "../api/types";
import { useToast } from "../hooks/toastContext";
import { Button } from "../ui/primitives";
import { selectCls } from "../ui/styles";

type Props = { campaignId: string; characters: Character[]; defaultCharacterIds?: string[]; compact?: boolean };

function makeKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

export function RestPanel({ campaignId, characters, defaultCharacterIds, compact = false }: Props): ReactElement {
  const { showToast } = useToast();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [restType, setRestType] = useState<RestType>("short");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rolls, setRolls] = useState<Record<string, string>>({});
  const [interrupted, setInterrupted] = useState(false);
  const [fallback, setFallback] = useState(false);
  const [interruptionReason, setInterruptionReason] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [preview, setPreview] = useState<RestPreview | null>(null);
  const pools = useQuery({ queryKey: ["resources", campaignId], queryFn: ({ signal }) => listResourcePools(campaignId, undefined, signal), enabled: open });

  useEffect(() => {
    if (!open) return;
    const valid = new Set(characters.map((item) => item.id));
    const initial = (defaultCharacterIds?.filter((id) => valid.has(id)) ?? characters.map((item) => item.id));
    setSelected(new Set(initial)); setRolls({}); setInterrupted(false);
    setFallback(false); setInterruptionReason(""); setOverrideReason(""); setPreview(null);
  }, [open, characters, defaultCharacterIds]);

  const request = (): RestPreviewRequest => ({
    rest_type: restType,
    duration_minutes: restType === "long" ? 480 : 60,
    interrupted,
    interruption_reason: interruptionReason || null,
    fallback_to_short_rest: restType === "long" && interrupted && fallback,
    dm_override_reason: overrideReason || null,
    participants: characters.filter((item) => selected.has(item.id)).map((character) => ({
      character_id: character.id, character_version: character.version, excluded_resource_keys: [],
      hit_dice: (restType === "short" || (restType === "long" && interrupted && fallback))
        ? (pools.data ?? []).filter((pool) => pool.character_id === character.id && pool.category === "hit_die")
          .flatMap((pool) => (rolls[pool.id] ?? "").split(/[,，\s]+/).filter(Boolean)
            .map((roll) => ({ resource_pool_id: pool.id, roll: Number(roll) })))
        : [],
    })),
  });
  const previewMutation = useMutation({
    mutationFn: () => { const body = request(); if (!body.participants.length) throw new Error("至少选择一名角色"); return previewRest(campaignId, body); },
    onSuccess: setPreview,
    onError: (error) => showToast(error instanceof Error ? error.message : "休息预览失败", "error"),
  });
  const confirmMutation = useMutation({
    mutationFn: () => { if (!preview) throw new Error("请先生成预览"); return confirmRest(campaignId, { ...request(), preview_token: preview.preview_token, idempotency_key: makeKey() }); },
    onSuccess: () => {
      for (const key of ["characters", "resources", "campaign-state", "campaigns"]) void client.invalidateQueries({ queryKey: [key, campaignId] });
      showToast("休息已确认并同步到战役状态"); setOpen(false);
    }, onError: (error) => showToast(error instanceof Error ? error.message : "确认休息失败", "error"),
  });
  const selectedCharacters = useMemo(() => characters.filter((item) => selected.has(item.id)), [characters, selected]);
  return <>
    <Button disabled={!characters.length} onClick={() => setOpen(true)} size="sm" variant={compact ? "ghost" : "primary"}>{compact ? "队伍休息" : "短休 / 长休"}</Button>
    {!open ? null : <div aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/80 p-4 backdrop-blur-sm" role="dialog">
      <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-ink-600 bg-ink-900 shadow-panel">
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-3"><h3 className="m-0 font-display text-base text-parchment-100">队伍休息</h3><Button onClick={() => setOpen(false)} size="sm">关闭</Button></div>
        <div className="space-y-4 px-5 py-4 text-sm text-stone-300">
          <div className="flex flex-wrap items-center gap-3"><label>休息类型 <select className={selectCls} onChange={(e) => { setRestType(e.target.value as RestType); setPreview(null); }} value={restType}><option value="short">短休（60 分钟）</option><option value="long">长休（8 小时）</option></select></label><span className="text-xs text-stone-500">所有写入均需预览后确认。</span></div>
          <div className="flex flex-wrap items-center gap-3 rounded border border-ink-700 p-3">
            <label className="flex items-center gap-2"><input checked={interrupted} onChange={(e) => { setInterrupted(e.target.checked); if (!e.target.checked) setFallback(false); setPreview(null); }} type="checkbox" />休息被中断</label>
            {interrupted ? <input className={`${selectCls} min-w-64 flex-1`} onChange={(e) => { setInterruptionReason(e.target.value); setPreview(null); }} placeholder="中断原因，例如进入先攻或受到伤害" value={interruptionReason} /> : null}
            {interrupted && restType === "long" ? <label className="flex items-center gap-2"><input checked={fallback} onChange={(e) => { setFallback(e.target.checked); setPreview(null); }} type="checkbox" />已休息至少 1 小时，折算短休收益</label> : null}
            {restType === "long" ? <input className={`${selectCls} min-w-64 flex-1`} onChange={(e) => { setOverrideReason(e.target.value); setPreview(null); }} placeholder="DM 规则覆盖理由（仅需要时填写）" value={overrideReason} /> : null}
          </div>
          <div className="rounded border border-ink-700 p-3"><strong className="text-xs text-parchment-100">参与角色</strong><div className="mt-2 grid gap-2 sm:grid-cols-2">{characters.map((character) => <label className="flex items-center gap-2" key={character.id}><input checked={selected.has(character.id)} onChange={(e) => { setSelected((old) => { const next = new Set(old); if (e.target.checked) next.add(character.id); else next.delete(character.id); return next; }); setPreview(null); }} type="checkbox" />{character.name} <span className="text-2xs text-stone-500">HP {character.hp}/{character.max_hp}</span></label>)}</div></div>
          {restType === "short" ? <div className="rounded border border-ink-700 p-3"><strong className="text-xs text-parchment-100">生命骰（逐枚决定、逐枚填值）</strong><p className="mb-1 mt-1 text-xs text-stone-500">按实际掷骰顺序填写，用逗号分隔；例如 6, 8 表示依次消耗两枚。</p>{pools.isLoading ? <p>读取资源中…</p> : selectedCharacters.map((character) => (pools.data ?? []).filter((pool) => pool.character_id === character.id && pool.category === "hit_die").map((pool) => <div className="mt-2 flex flex-wrap items-center gap-2" key={pool.id}><span className="min-w-40">{character.name} · {pool.label}（可用 {pool.current}/{pool.maximum}）</span><input className={`${selectCls} min-w-56`} onChange={(e) => { setRolls((old) => ({ ...old, [pool.id]: e.target.value })); setPreview(null); }} placeholder={`逐枚 d${pool.die_size ?? "?"} 骰值，如 6,8`} value={rolls[pool.id] ?? ""} /></div>))}</div> : null}
          {preview ? <div className="rounded border border-violet-800/60 bg-violet-950/20 p-3"><strong>预览：{preview.effective_rest_type === "long" ? "长休" : "短休"}</strong><p className="mb-2 mt-1 text-xs">世界时间：{preview.world_time_before ?? "未设置"} → {preview.world_time_after ?? "未设置"}</p>{preview.participants.map((item) => <div className="border-t border-ink-700 py-2" key={item.character_id}><strong>{item.character_name}</strong> · HP {item.before.hp} → {item.after.hp}<ul className="mb-0 mt-1 pl-5 text-xs">{item.changes.map((change, i) => <li key={`${change.type}-${change.key ?? i}`}>{change.label ?? change.key ?? change.type}：{change.before} → {change.after}{change.explanation ? `（${change.explanation}）` : ""}</li>)}</ul></div>)}{preview.warnings.map((warning) => <p className="mb-0 mt-2 text-xs text-amber-300" key={warning}>警告：{warning}</p>)}{preview.rule_reference ? <p className="mb-0 mt-2 text-2xs text-stone-500">规则：{preview.rule_reference}</p> : null}</div> : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-ink-700 px-5 py-3"><Button onClick={() => setOpen(false)}>取消</Button><Button disabled={!selected.size} loading={previewMutation.isPending} onClick={() => previewMutation.mutate()}>{preview ? "重新预览" : "生成预览"}</Button><Button disabled={!preview} loading={confirmMutation.isPending} onClick={() => confirmMutation.mutate()} variant="primary">DM 确认休息</Button></div>
      </div>
    </div>}
  </>;
}
