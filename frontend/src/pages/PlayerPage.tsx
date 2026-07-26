import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactElement } from "react";

import { getPlayerCharacter, getPlayerView, submitPlayerAction } from "../api/player";
import { listCharacters } from "../api/entities";
import { RequireCampaign } from "../components/RequireCampaign";
import { Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";

function PlayerContent({ campaignId }: { campaignId: string }): ReactElement {
  const [characterId, setCharacterId] = useState("");
  const [action, setAction] = useState("");
  const [message, setMessage] = useState("");
  const view = useQuery({ queryKey: ["player-view", campaignId], queryFn: ({ signal }) => getPlayerView(campaignId, signal), refetchInterval: 15_000 });
  const characters = useQuery({ queryKey: ["player-characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  useEffect(() => { if (!characterId && characters.data?.[0]) setCharacterId(characters.data[0].id); }, [characterId, characters.data]);
  const character = useQuery({ queryKey: ["player-character", campaignId, characterId], queryFn: ({ signal }) => getPlayerCharacter(campaignId, characterId, signal), enabled: Boolean(characterId) });
  const request = useMutation({ mutationFn: () => submitPlayerAction(campaignId, { character_id: characterId, character_version: character.data?.version ?? 1, player_key: "local-player", action_type: action, message: message || undefined, idempotency_key: crypto.randomUUID() }), onSuccess: () => { setAction(""); setMessage(""); } });
  if (view.isLoading) return <LoadingBlock label="正在加载玩家投屏…" />;
  if (view.isError) return <ErrorState error={view.error} onRetry={() => void view.refetch()} />;
  const data = view.data;
  if (!data) return <EmptyState title="没有公开内容" hint="等待 DM 开始场景或发布讲义。" />;
  return <main className="mx-auto min-h-screen max-w-[1200px] p-4 lg:p-8">
    <header className="mb-6 border-b border-ink-700 pb-4"><p className="m-0 text-xs uppercase tracking-[.2em] text-amber-300">Player View · 仅公开信息</p><h1 className="mb-1 mt-2 font-display text-3xl text-parchment-100">{data.campaign.name}</h1><p className="m-0 text-sm text-stone-400">共享地图、先攻、讲义与行动申请。所有结果由 DM 确认。</p></header>
    <div className="grid gap-5 lg:grid-cols-[1.25fr_.75fr]">
      <section className="rounded-lg border border-ink-700 bg-ink-900/60 p-4"><h2 className="mt-0 font-display text-xl text-parchment-100">{data.scene?.name ?? "当前没有公开场景"}</h2><p className="text-sm text-stone-400">{data.scene?.description ?? ""}</p>{data.scene?.grid ? <div className="grid gap-px border border-ink-600 bg-ink-800 p-1" style={{ gridTemplateColumns: `repeat(${data.scene.grid.width}, minmax(0, 1fr))` }}>{Array.from({ length: data.scene.grid.width * data.scene.grid.height }, (_, index) => <div className="aspect-square bg-ink-950/70" key={index} />)}</div> : null}<div className="mt-3 flex flex-wrap gap-2">{data.scene?.tokens.map((token) => <span className="rounded bg-amber-500/15 px-2 py-1 text-xs text-amber-100" key={token.id}>{token.label} ({token.row},{token.col})</span>)}</div></section>
      <aside className="space-y-5"><section className="rounded-lg border border-ink-700 bg-ink-900/60 p-4"><h2 className="mt-0 font-display text-lg text-parchment-100">公开先攻</h2>{data.initiative.map((item) => <p className="mb-2 flex justify-between text-sm" key={item.id}><span>{item.name}</span><span className="font-mono text-stone-400">{item.hp}/{item.max_hp} · {item.initiative}</span></p>) || <span className="text-sm text-stone-500">未开始战斗</span>}</section><section className="rounded-lg border border-ink-700 bg-ink-900/60 p-4"><h2 className="mt-0 font-display text-lg text-parchment-100">讲义</h2>{data.handouts.map((handout) => <article className="mb-3 border-l-2 border-amber-500/60 pl-3" key={handout.id}><strong className="text-sm text-parchment-100">{handout.title}</strong><p className="mb-0 mt-1 whitespace-pre-wrap text-sm text-stone-400">{handout.body}</p></article>) || <span className="text-sm text-stone-500">暂无讲义</span>}</section></aside>
    </div>
    <section className="mt-5 rounded-lg border border-ink-700 bg-ink-900/60 p-4"><h2 className="mt-0 font-display text-xl text-parchment-100">我的角色与行动申请</h2><select aria-label="选择角色" className="mb-3 rounded border border-ink-600 bg-ink-950 p-2 text-sm" value={characterId} onChange={(e) => setCharacterId(e.target.value)}>{characters.data?.map((c) => <option value={c.id} key={c.id}>{c.name}</option>)}</select>{character.data ? <div className="grid gap-3 md:grid-cols-3"><p className="text-sm">{character.data.name} · HP {character.data.hp}/{character.data.max_hp}</p><p className="text-sm text-stone-400">资源：{Object.keys(character.data.resources).length}</p><p className="text-sm text-stone-400">法术：{character.data.spells.length}</p></div> : null}<div className="mt-3 flex flex-col gap-2 sm:flex-row"><input aria-label="动作申请" value={action} onChange={(e) => setAction(e.target.value)} placeholder="例如：施放治疗真言" className="flex-1 rounded border border-ink-600 bg-ink-950 p-2 text-sm"/><input aria-label="补充说明" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="目标、意图或说明" className="flex-1 rounded border border-ink-600 bg-ink-950 p-2 text-sm"/><Button variant="primary" loading={request.isPending} disabled={!characterId || !action.trim()} onClick={() => request.mutate()}>提交给 DM</Button></div>{request.isSuccess ? <p className="mb-0 mt-2 text-sm text-emerald-300">申请已送达，尚未改变角色或战役事实。</p> : null}{request.isError ? <p className="mb-0 mt-2 text-sm text-red-300">提交失败，请刷新角色状态后重试。</p> : null}</section>
    <section className="mt-5"><h2 className="font-display text-xl text-parchment-100">共享日志</h2>{data.shared_log.map((event) => <article className="border-b border-ink-800 py-2" key={event.id}><strong className="text-sm">{event.title}</strong><p className="m-0 text-sm text-stone-400">{event.description ?? ""}</p></article>)}</section>
  </main>;
}
export function PlayerPage(): ReactElement { return <RequireCampaign>{(id) => <PlayerContent campaignId={id} />}</RequireCampaign>; }
