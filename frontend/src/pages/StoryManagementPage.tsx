import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";
import { createClientId } from "../ui/id";

import {
  confirmNarrativeTransaction, createNarrative, listCharacters, listNarrative,
  listNarrativeRuntimes, listNpcs, previewNarrativeTransaction, updateNarrative,
  type NarrativeRuntime,
} from "../api/entities";
import { publishHandout } from "../api/player";
import type { NarrativeRecord } from "../api/types";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { SessionChroniclePanel } from "../components/SessionChroniclePanel";
import { useToast } from "../hooks/toastContext";
import { soundboard } from "../ui/soundboard";
import { Button, EmptyState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls } from "../ui/styles";

type Tab =
  | "quests"
  | "clues"
  | "story-beats"
  | "quest-objectives"
  | "npc-memories"
  | "faction-reputations"
  | "clue-discoveries"
  | "downtime-activities";

const tabs: { id: Tab; label: string; title: string }[] = [
  { id: "quests", label: "任务", title: "任务" },
  { id: "clues", label: "线索", title: "线索" },
  { id: "story-beats", label: "剧情节点", title: "剧情分支" },
  { id: "quest-objectives", label: "任务目标", title: "目标与结局" },
  { id: "npc-memories", label: "NPC 记忆", title: "态度、承诺、谎言与欠债" },
  { id: "faction-reputations", label: "阵营声望", title: "关系与声望" },
  { id: "clue-discoveries", label: "发现记录", title: "线索发现" },
  { id: "downtime-activities", label: "停工期", title: "制作、训练与研究" },
];

const text = (value: unknown, fallback: string) =>
  typeof value === "string" || typeof value === "number" ? String(value) : fallback;

function NarrativeContent({ campaignId }: { campaignId: string }): ReactElement {
  const [tab, setTab] = useState<Tab>("quests");
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [status, setStatus] = useState("planned");
  const [relatedId, setRelatedId] = useState("");
  const [preview, setPreview] = useState<{
    token: string;
    input: Parameters<typeof previewNarrativeTransaction>[1];
  } | null>(null);

  const { showToast } = useToast();
  const client = useQueryClient();
  const nativeTab = tab === "quests" || tab === "clues";
  const records = useQuery({
    queryKey: ["narrative", campaignId, tab],
    queryFn: ({ signal }) => listNarrative(campaignId, tab, signal),
  });
  const characters = useQuery({
    queryKey: ["characters", campaignId],
    queryFn: ({ signal }) => listCharacters(campaignId, signal),
  });
  const npcs = useQuery({
    queryKey: ["npcs", campaignId],
    queryFn: ({ signal }) => listNpcs(campaignId, signal),
  });
  const runtimes = useQuery({
    queryKey: ["narrative-runtimes", campaignId],
    queryFn: ({ signal }) => listNarrativeRuntimes(campaignId, signal),
  });

  const create = useMutation({
    mutationFn: () => {
      if (!title.trim()) throw new Error("名称不能为空");
      if (tab === "quests")
        return createNarrative(campaignId, tab, {
          name: title.trim(),
          description: detail || null,
          status: status === "planned" ? "open" : status,
        });
      if (tab === "clues")
        return createNarrative(campaignId, tab, {
          name: title.trim(),
          description: detail || null,
        });
      const base = { title: title.trim(), description: detail || null, status };
      if (tab === "npc-memories") {
        if (!relatedId) throw new Error("请选择 NPC");
        return createNarrative(campaignId, tab, {
          ...base,
          summary: detail || title,
          npc_id: relatedId,
        });
      }
      if (tab === "downtime-activities") {
        if (!relatedId) throw new Error("请选择角色");
        return createNarrative(campaignId, tab, {
          ...base,
          activity_type: "training",
          character_id: relatedId,
          duration_days: 1,
        });
      }
      return createNarrative(campaignId, tab, base);
    },
    onSuccess: () => {
      setTitle("");
      setDetail("");
      void client.invalidateQueries({ queryKey: ["narrative", campaignId, tab] });
      showToast("已创建事实草案；请继续补全关联对象后确认推进");
    },
    onError: (e) => showToast(e instanceof Error ? e.message : "创建失败", "error"),
  });

  const transition = useMutation({
    mutationFn: (row: NarrativeRecord) =>
      updateNarrative(
        campaignId,
        tab,
        row.id,
        { status: status === "planned" ? "completed" : status },
        row.version,
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["narrative", campaignId, tab] });
      showToast("状态已确认写入");
    },
    onError: () => showToast("版本冲突或写入失败，请刷新后重试", "error"),
  });

  const broadcastHandoutMutation = useMutation({
    mutationFn: async (row: NarrativeRecord) => {
      const itemTitle = text(row.name ?? row.title ?? row.summary, "重要线索");
      const itemBody = text(row.description ?? row.notes, "暂无详细描述");
      await publishHandout(campaignId, itemTitle, itemBody);
    },
    onSuccess: () => {
      soundboard.playHandout();
      showToast("📜 已广播推送该线索/道具至所有玩家屏幕！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "广播失败", "error");
    },
  });

  const previewMutation = useMutation({
    mutationFn: async (input: Parameters<typeof previewNarrativeTransaction>[1]) =>
      previewNarrativeTransaction(campaignId, input),
    onSuccess: (data, input) => {
      setPreview({ token: data.preview_token, input });
      showToast("已生成事务预览，请确认后才会写入。");
    },
    onError: (e) => showToast(e instanceof Error ? e.message : "预览失败", "error"),
  });

  const confirmMutation = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("请先预览");
      return confirmNarrativeTransaction(campaignId, {
        ...preview.input,
        preview_token: preview.token,
      });
    },
    onSuccess: () => {
      setPreview(null);
      void client.invalidateQueries();
      showToast("叙事事务已确认写入");
    },
    onError: (e) => showToast(e instanceof Error ? e.message : "确认失败", "error"),
  });

  const previewRuntime = (runtime: NarrativeRuntime, outcome: "success" | "failure") =>
    previewMutation.mutate({
      idempotency_key: createClientId("narrative"),
      operations: [
        {
          kind: "runtime",
          runtime_id: runtime.runtime_id,
          mode: runtime.mode as
            | "skill_challenge"
            | "chase"
            | "negotiation"
            | "stealth"
            | "investigation",
          success_delta: outcome === "success" ? 1 : 0,
          failure_delta: outcome === "failure" ? 1 : 0,
        },
      ],
    });

  const startRuntime = (
    mode: "skill_challenge" | "chase" | "negotiation" | "stealth" | "investigation",
  ) =>
    previewMutation.mutate({
      idempotency_key: createClientId("narrative"),
      operations: [
        {
          kind: "runtime",
          runtime_id: createClientId("runtime"),
          mode,
          title: ({
            skill_challenge: "技能挑战",
            chase: "追逐",
            negotiation: "谈判",
            stealth: "潜行",
            investigation: "调查",
          })[mode],
          target_successes: 3,
          target_failures: 3,
        },
      ],
    });

  const active = tabs.find((item) => item.id === tab)!;

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 p-4 lg:p-6">
      {/* Session Chronicle & AI Recap Header Block */}
      <SessionChroniclePanel campaignId={campaignId} />

      {/* Tabs */}
      <div>
        <div className="mb-4 flex flex-wrap gap-1.5">
          {tabs.map((item) => (
            <button
              className={`rounded-md border px-3 py-1.5 text-sm ${
                tab === item.id
                  ? "border-ember-500/60 bg-ember-500/10 text-ember-200"
                  : "border-ink-600 text-stone-500"
              }`}
              key={item.id}
              onClick={() => setTab(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>

        <Panel eyebrow="叙事推进 · 所有改变需 DM 确认" title={active.title}>
          <div className="grid gap-2 md:grid-cols-[1fr_1fr_10rem_auto]">
            <input
              className={inputCls}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="名称 / 标题"
              value={title}
            />
            <input
              className={inputCls}
              onChange={(e) => setDetail(e.target.value)}
              placeholder="描述、后果或备注"
              value={detail}
            />
            <select
              className={selectCls}
              onChange={(e) => setStatus(e.target.value)}
              value={status}
            >
              <option value="planned">计划</option>
              <option value="active">进行中</option>
              <option value="completed">完成</option>
              <option value="partial">部分完成</option>
              <option value="failed">失败</option>
              <option value="timed_out">超时</option>
              <option value="skipped">跳过</option>
            </select>
            <Button loading={create.isPending} onClick={() => create.mutate()} variant="primary">
              创建草案
            </Button>
          </div>
          {tab === "npc-memories" || tab === "downtime-activities" ? (
            <select
              className={`${selectCls} mt-2`}
              onChange={(e) => setRelatedId(e.target.value)}
              value={relatedId}
            >
              <option value="">选择关联{tab === "npc-memories" ? "NPC" : "角色"}</option>
              {(tab === "npc-memories" ? npcs.data ?? [] : characters.data ?? []).map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.name}
                </option>
              ))}
            </select>
          ) : null}
          <p className="mb-0 mt-2 text-2xs text-stone-500">
            关联对象使用实体选择器；草案不会自动改变世界状态。
          </p>
        </Panel>

        <Panel
          className="mt-4"
          eyebrow="叙事运行器 · 跨轮次保存进度"
          title="技能挑战、追逐、谈判、潜行与调查"
        >
          <div className="flex flex-wrap gap-2">
            {(
              [
                "skill_challenge",
                "chase",
                "negotiation",
                "stealth",
                "investigation",
              ] as const
            ).map((mode) => (
              <Button
                key={mode}
                onClick={() => startRuntime(mode)}
                size="sm"
                variant={mode === "skill_challenge" ? "primary" : "ghost"}
              >
                新建{" "}
                {
                  ({
                    skill_challenge: "技能挑战",
                    chase: "追逐",
                    negotiation: "谈判",
                    stealth: "潜行",
                    investigation: "调查",
                  })[mode]
                }
              </Button>
            ))}
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {runtimes.data?.items.map((runtime) => (
              <div
                className={`rounded border p-3 ${
                  runtime.status === "active"
                    ? "border-amber-500/30 bg-ink-800"
                    : runtime.status === "succeeded"
                      ? "border-emerald-500/30 bg-emerald-950/20"
                      : "border-rose-500/30 bg-rose-950/20"
                }`}
                key={runtime.runtime_id}
              >
                <div className="flex items-center gap-2">
                  <strong className="mr-auto text-sm text-parchment-100">{runtime.title}</strong>
                  <span className="text-2xs text-stone-400">
                    {runtime.status === "active"
                      ? "进行中"
                      : runtime.status === "succeeded"
                        ? "成功"
                        : "失败"}
                  </span>
                </div>
                <p className="my-2 text-xs text-stone-400">
                  成功 {runtime.successes}/{runtime.target_successes} · 失败 {runtime.failures}/
                  {runtime.target_failures}
                </p>
                {runtime.status === "active" ? (
                  <div className="flex gap-2">
                    <Button onClick={() => previewRuntime(runtime, "success")} size="sm">
                      记录成功
                    </Button>
                    <Button
                      onClick={() => previewRuntime(runtime, "failure")}
                      size="sm"
                      variant="ghost"
                    >
                      记录失败
                    </Button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
          {preview ? (
            <div className="mt-3 rounded border border-amber-500/30 bg-ink-800 p-3 text-xs text-stone-300">
              <p className="m-0">
                {preview.input.operations[0]?.kind === "runtime"
                  ? "已预览本次进度变化"
                  : `已预览 ${preview.input.operations.length} 个变更`}
                ；尚未写入。
              </p>
              <div className="mt-2 flex gap-2">
                <Button
                  loading={confirmMutation.isPending}
                  onClick={() => confirmMutation.mutate()}
                  size="sm"
                  variant="primary"
                >
                  DM 确认写入
                </Button>
                <Button onClick={() => setPreview(null)} size="sm" variant="ghost">
                  取消
                </Button>
              </div>
            </div>
          ) : null}
        </Panel>

        <Panel
          className="mt-4"
          eyebrow={nativeTab ? "既有记录" : "已确认 / 待推进"}
          title={`${active.label}列表`}
        >
          {records.isLoading ? <LoadingBlock /> : null}
          {!records.isLoading && !records.data?.length ? (
            <EmptyState hint="先创建可编辑草案。" title="暂无记录" />
          ) : (
            <ul className="m-0 divide-y divide-ink-700 p-0">
              {records.data?.map((row) => (
                <li className="flex items-center gap-3 py-3" key={row.id}>
                  <div className="min-w-0 flex-1">
                    <strong className="text-sm text-parchment-100">
                      {text(row.name ?? row.title ?? row.summary, "未命名")}
                    </strong>
                    <p className="mb-0 mt-1 text-xs text-stone-500">
                      {text(row.description ?? row.notes, "暂无说明")}
                    </p>
                  </div>
                  <span className="text-xs text-amber-300">{text(row.status, "记录")}</span>
                  {tab === "clues" || tab === "story-beats" || tab === "quests" ? (
                    <button
                      className="rounded border border-amber-600/50 bg-amber-950/30 px-2 py-1 text-2xs text-amber-300 transition hover:bg-amber-900/40"
                      onClick={() => broadcastHandoutMutation.mutate(row)}
                      title="将此线索/剧情内容以精美讲义推送至所有玩家屏幕"
                      type="button"
                    >
                      📜 广播到玩家
                    </button>
                  ) : null}
                  {!nativeTab ? (
                    <Button
                      loading={transition.isPending}
                      onClick={() => transition.mutate(row)}
                      size="sm"
                    >
                      确认状态
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

export function StoryManagementPage(): ReactElement {
  return (
    <RequireCampaign>
      {(id) => <NarrativeContent campaignId={id} />}
    </RequireCampaign>
  );
}
