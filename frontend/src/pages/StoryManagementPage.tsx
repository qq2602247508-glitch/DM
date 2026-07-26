import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import { createNarrative, listNarrative, updateNarrative } from "../api/entities";
import type { NarrativeRecord } from "../api/types";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { useToast } from "../hooks/toastContext";
import { Button, EmptyState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls } from "../ui/styles";

type Tab = "quests" | "clues" | "story-beats" | "quest-objectives" | "npc-memories" | "faction-reputations" | "clue-discoveries" | "downtime-activities";
const tabs: { id: Tab; label: string; title: string }[] = [
  { id: "quests", label: "任务", title: "任务" }, { id: "clues", label: "线索", title: "线索" },
  { id: "story-beats", label: "剧情节点", title: "剧情分支" }, { id: "quest-objectives", label: "任务目标", title: "目标与结局" },
  { id: "npc-memories", label: "NPC 记忆", title: "态度、承诺、谎言与欠债" }, { id: "faction-reputations", label: "阵营声望", title: "关系与声望" },
  { id: "clue-discoveries", label: "发现记录", title: "线索发现" }, { id: "downtime-activities", label: "停工期", title: "制作、训练与研究" },
];
const text = (value: unknown, fallback: string) => typeof value === "string" || typeof value === "number" ? String(value) : fallback;

function NarrativeContent({ campaignId }: { campaignId: string }): ReactElement {
  const [tab, setTab] = useState<Tab>("quests"); const [title, setTitle] = useState(""); const [detail, setDetail] = useState(""); const [status, setStatus] = useState("planned");
  const { showToast } = useToast(); const client = useQueryClient();
  const nativeTab = tab === "quests" || tab === "clues";
  const records = useQuery({ queryKey: ["narrative", campaignId, tab], queryFn: ({ signal }) => listNarrative(campaignId, tab, signal) });
  const create = useMutation({ mutationFn: () => {
    if (!title.trim()) throw new Error("名称不能为空");
    if (tab === "quests") return createNarrative(campaignId, tab, { name: title.trim(), description: detail || null, status: status === "planned" ? "open" : status });
    if (tab === "clues") return createNarrative(campaignId, tab, { name: title.trim(), description: detail || null });
    const base = { title: title.trim(), description: detail || null, status };
    if (tab === "npc-memories") return createNarrative(campaignId, tab, { ...base, summary: detail || title, npc_id: "" });
    if (tab === "downtime-activities") return createNarrative(campaignId, tab, { ...base, activity_type: "training", character_id: "", duration_days: 1 });
    return createNarrative(campaignId, tab, base);
  }, onSuccess: () => { setTitle(""); setDetail(""); void client.invalidateQueries({ queryKey: ["narrative", campaignId, tab] }); showToast("已创建事实草案；请继续补全关联对象后确认推进"); }, onError: (e) => showToast(e instanceof Error ? e.message : "创建失败", "error") });
  const transition = useMutation({ mutationFn: (row: NarrativeRecord) => updateNarrative(campaignId, tab, row.id, { status: status === "planned" ? "completed" : status }, row.version), onSuccess: () => { void client.invalidateQueries({ queryKey: ["narrative", campaignId, tab] }); showToast("状态已确认写入"); }, onError: () => showToast("版本冲突或写入失败，请刷新后重试", "error") });
  const active = tabs.find((item) => item.id === tab)!;
  return <div className="mx-auto max-w-[1200px] p-4 lg:p-6"><div className="mb-4 flex flex-wrap gap-1.5">{tabs.map((item) => <button className={`rounded-md border px-3 py-1.5 text-sm ${tab === item.id ? "border-ember-500/60 bg-ember-500/10 text-ember-200" : "border-ink-600 text-stone-500"}`} key={item.id} onClick={() => setTab(item.id)} type="button">{item.label}</button>)}</div>
    <Panel eyebrow="叙事推进 · 所有改变需 DM 确认" title={active.title}><div className="grid gap-2 md:grid-cols-[1fr_1fr_10rem_auto]"><input className={inputCls} onChange={(e) => setTitle(e.target.value)} placeholder="名称 / 标题" value={title} /><input className={inputCls} onChange={(e) => setDetail(e.target.value)} placeholder="描述、后果或备注" value={detail} /><select className={selectCls} onChange={(e) => setStatus(e.target.value)} value={status}><option value="planned">计划</option><option value="active">进行中</option><option value="completed">完成</option><option value="partial">部分完成</option><option value="failed">失败</option><option value="timed_out">超时</option><option value="skipped">跳过</option></select><Button loading={create.isPending} onClick={() => create.mutate()} variant="primary">创建草案</Button></div><p className="mb-0 mt-2 text-2xs text-stone-500">任务奖励、阵营数值与 NPC 关联对象需使用推进台的预览确认流程；本页保留可审计的叙事事实记录。</p></Panel>
    <Panel className="mt-4" eyebrow={nativeTab ? "既有记录" : "已确认 / 待推进"} title={`${active.label}列表`}>{records.isLoading ? <LoadingBlock /> : null}{!records.isLoading && !records.data?.length ? <EmptyState title="暂无记录" hint="先创建可编辑草案。" /> : <ul className="m-0 divide-y divide-ink-700 p-0">{records.data?.map((row) => <li className="flex items-center gap-3 py-3" key={row.id}><div className="min-w-0 flex-1"><strong className="text-sm text-parchment-100">{text(row.name ?? row.title ?? row.summary, "未命名")}</strong><p className="mb-0 mt-1 text-xs text-stone-500">{text(row.description ?? row.notes, "暂无说明")}</p></div><span className="text-xs text-amber-300">{text(row.status, "记录")}</span>{!nativeTab ? <Button loading={transition.isPending} onClick={() => transition.mutate(row)} size="sm">确认状态</Button> : null}</li>)}</ul>}</Panel></div>;
}

export function StoryManagementPage(): ReactElement { return <RequireCampaign>{(id) => <NarrativeContent campaignId={id} />}</RequireCampaign>; }
