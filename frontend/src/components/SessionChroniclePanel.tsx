import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import { runAssistantTurn } from "../api/assistant";
import { listEvents, listQuests, listClues, createEvent } from "../api/entities";
import { listCombats } from "../api/entities";
import { formatDateTime } from "../ui/format";
import { soundboard } from "../ui/soundboard";
import { useToast } from "../hooks/toastContext";

export function SessionChroniclePanel({ campaignId }: { campaignId: string }): ReactElement {
  const { showToast } = useToast();
  const [recapText, setRecapText] = useState<string>("");
  const [chronicleText, setChronicleText] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"chronicle" | "recap" | "raw">("chronicle");

  const eventsQuery = useQuery({
    queryKey: ["events", campaignId],
    queryFn: ({ signal }) => listEvents(campaignId, signal),
  });

  const questsQuery = useQuery({
    queryKey: ["quests", campaignId],
    queryFn: ({ signal }) => listQuests(campaignId, signal),
  });

  const cluesQuery = useQuery({
    queryKey: ["clues", campaignId],
    queryFn: ({ signal }) => listClues(campaignId, signal),
  });

  const combatsQuery = useQuery({
    queryKey: ["combats", campaignId],
    queryFn: ({ signal }) => listCombats(campaignId, signal),
  });

  const generateRecapMutation = useMutation({
    mutationFn: async () => {
      const recentEvents = (eventsQuery.data ?? []).slice(0, 10).map((e) => `${e.title}: ${e.description ?? ""}`).join("\n");
      const activeQuests = (questsQuery.data ?? []).map((q) => `任务[${q.name}]: ${q.description ?? ""}`).join("\n");
      const foundClues = (cluesQuery.data ?? []).filter((c) => c.discovered).map((c) => `线索[${c.name}]: ${c.description ?? ""}`).join("\n");

      const prompt = `请根据本战役最近发生的重大事件与线索，生成一段简短、充满史诗悬念与沉浸感的主持人开场白（100-200字左右），用于本次开团给玩家朗读的"上集提要 (Previously on D&D...)"。请使用极具电影感和冒险氛围的中文：\n\n【最近事件】\n${recentEvents || "冒险者们在酒馆聚集，初次踏入未知荒野"}\n\n【进行中任务】\n${activeQuests}\n\n【已发现线索】\n${foundClues}`;

      const res = await runAssistantTurn(campaignId, prompt, { mode: "narrative" });
      return res.dm_hint?.text ?? "未能生成上集提要";
    },
    onSuccess: (text) => {
      setRecapText(text);
      setActiveTab("recap");
      soundboard.playHandout();
      showToast("✨ AI 冒险上集提要已生成！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "生成提要失败", "error");
    },
  });

  const generateChronicleMutation = useMutation({
    mutationFn: async () => {
      const eventsSummary = (eventsQuery.data ?? []).slice(0, 15).map((e) => `- ${e.title} (${e.event_type}): ${e.description ?? ""}`).join("\n");
      const combatsSummary = (combatsQuery.data ?? []).slice(0, 5).map((c) => `- 战斗[${c.name}] 轮数: ${c.round_number}, 状态: ${c.status}`).join("\n");

      const prompt = `请将以下本场跑团的实际战斗、遭遇、线索发现与关键事件，整理汇编为一篇文采飞扬、结构清晰的《冒险编年史·章节战报》Markdown文本。包含【本章提要】、【关键战斗与突破】、【未解之谜与后续伏笔】：\n\n【事件流水】\n${eventsSummary || "冒险者探索了地下城"}\n\n【战斗记录】\n${combatsSummary || "暂无战斗"}`;

      const res = await runAssistantTurn(campaignId, prompt, { mode: "narrative" });
      return res.dm_hint?.text ?? "未能生成战报";
    },
    onSuccess: (text) => {
      setChronicleText(text);
      setActiveTab("chronicle");
      soundboard.playHandout();
      showToast("📖 本场冒险编年史战报已生成！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "生成战报失败", "error");
    },
  });

  const saveChronicleAsEventMutation = useMutation({
    mutationFn: async () => {
      if (!chronicleText) return;
      await createEvent(campaignId, {
        event_type: "story_milestone",
        title: "📖 冒险编年史章节记录",
        description: chronicleText.slice(0, 3000),
      });
    },
    onSuccess: () => {
      showToast("已将编年史沉淀保存为战役里程碑事件！", "success");
      void eventsQuery.refetch();
    },
  });

  const copyToClipboard = (text: string) => {
    void navigator.clipboard.writeText(text);
    showToast("已复制到剪贴板！", "success");
  };

  return (
    <div className="rounded-xl border border-ink-700/80 bg-ink-950/80 p-4 shadow-xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-800 pb-3">
        <div className="flex items-center gap-2.5">
          <span className="text-xl">📜</span>
          <div>
            <h3 className="font-display text-base font-bold text-parchment-100">战役编年史与上集提要</h3>
            <p className="text-2xs text-stone-400">基于战役事实事件自动提炼史诗战报与开团朗读引言</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-600/60 bg-amber-950/40 px-3 py-1.5 text-xs font-medium text-amber-200 transition hover:bg-amber-900/50 disabled:opacity-50"
            disabled={generateRecapMutation.isPending}
            onClick={() => generateRecapMutation.mutate()}
            type="button"
          >
            <span>🎙️</span>
            <span>{generateRecapMutation.isPending ? "正在构思开场白…" : "生成开团「上集提要」"}</span>
          </button>
          <button
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-600/60 bg-emerald-950/40 px-3 py-1.5 text-xs font-medium text-emerald-200 transition hover:bg-emerald-900/50 disabled:opacity-50"
            disabled={generateChronicleMutation.isPending}
            onClick={() => generateChronicleMutation.mutate()}
            type="button"
          >
            <span>📖</span>
            <span>{generateChronicleMutation.isPending ? "正在编写战报…" : "生成本场「冒险战报」"}</span>
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="mt-3 flex gap-2 border-b border-ink-850 pb-2 text-xs">
        <button
          className={`rounded-md px-3 py-1 transition-colors ${
            activeTab === "chronicle"
              ? "bg-amber-500/20 font-medium text-amber-300"
              : "text-stone-400 hover:text-stone-200"
          }`}
          onClick={() => setActiveTab("chronicle")}
          type="button"
        >
          📖 冒险编年史 {chronicleText ? "•" : ""}
        </button>
        <button
          className={`rounded-md px-3 py-1 transition-colors ${
            activeTab === "recap"
              ? "bg-amber-500/20 font-medium text-amber-300"
              : "text-stone-400 hover:text-stone-200"
          }`}
          onClick={() => setActiveTab("recap")}
          type="button"
        >
          🎙️ 开团上集提要 {recapText ? "•" : ""}
        </button>
        <button
          className={`rounded-md px-3 py-1 transition-colors ${
            activeTab === "raw"
              ? "bg-amber-500/20 font-medium text-amber-300"
              : "text-stone-400 hover:text-stone-200"
          }`}
          onClick={() => setActiveTab("raw")}
          type="button"
        >
          ⏱️ 战役原始事件流 ({eventsQuery.data?.length ?? 0})
        </button>
      </div>

      {/* Tab Content */}
      <div className="mt-3 min-h-[160px]">
        {activeTab === "recap" ? (
          <div>
            {recapText ? (
              <div className="relative rounded-lg border border-amber-900/50 bg-gradient-to-br from-amber-950/25 to-ink-950 p-4">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-2xs font-semibold uppercase tracking-wider text-amber-400">
                    🎙️ DM 开团朗读卡 (Read Aloud)
                  </span>
                  <button
                    className="rounded border border-ink-700 bg-ink-900 px-2 py-0.5 text-2xs text-stone-300 hover:text-stone-100"
                    onClick={() => copyToClipboard(recapText)}
                    type="button"
                  >
                    复制朗读文本
                  </button>
                </div>
                <blockquote className="border-l-2 border-amber-500/80 pl-3 font-serif text-sm italic leading-relaxed text-parchment-200">
                  {recapText}
                </blockquote>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-8 text-center text-xs text-stone-500">
                <span>🎙️ 还没有生成开团上集提要</span>
                <span className="mt-1 text-2xs text-stone-600">点击右上角「生成开团上集提要」，AI 将根据历史线索生成一段充满悬念的开场朗读引言</span>
              </div>
            )}
          </div>
        ) : null}

        {activeTab === "chronicle" ? (
          <div>
            {chronicleText ? (
              <div className="rounded-lg border border-ink-800 bg-ink-900/40 p-4">
                <div className="mb-2 flex items-center justify-between border-b border-ink-800 pb-2">
                  <span className="font-display text-sm font-semibold text-parchment-100">
                    📖 冒险编年史战报
                  </span>
                  <div className="flex gap-2">
                    <button
                      className="rounded border border-emerald-800/60 bg-emerald-950/30 px-2 py-0.5 text-2xs text-emerald-300 hover:bg-emerald-900/40"
                      disabled={saveChronicleAsEventMutation.isPending}
                      onClick={() => saveChronicleAsEventMutation.mutate()}
                      type="button"
                    >
                      {saveChronicleAsEventMutation.isPending ? "保存中…" : "保存为里程碑事件"}
                    </button>
                    <button
                      className="rounded border border-ink-700 bg-ink-900 px-2 py-0.5 text-2xs text-stone-300 hover:text-stone-100"
                      onClick={() => copyToClipboard(chronicleText)}
                      type="button"
                    >
                      复制Markdown
                    </button>
                  </div>
                </div>
                <div className="prose prose-invert max-w-none whitespace-pre-wrap font-sans text-xs leading-relaxed text-stone-300">
                  {chronicleText}
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-8 text-center text-xs text-stone-500">
                <span>📖 暂无生成的编年史战报</span>
                <span className="mt-1 text-2xs text-stone-600">点击上方「生成本场冒险战报」，AI 将提炼整理本场战斗、任务、线索生成完整章节记录</span>
              </div>
            )}
          </div>
        ) : null}

        {activeTab === "raw" ? (
          <div className="max-h-60 space-y-1.5 overflow-y-auto pr-1">
            {(eventsQuery.data ?? []).length > 0 ? (
              (eventsQuery.data ?? []).map((ev) => (
                <div
                  className="flex items-start justify-between rounded border border-ink-800/60 bg-ink-900/30 px-2.5 py-1.5 text-2xs"
                  key={ev.id}
                >
                  <div>
                    <strong className="text-stone-200">{ev.title}</strong>
                    {ev.description ? <p className="mt-0.5 text-stone-400">{ev.description}</p> : null}
                  </div>
                  <span className="shrink-0 text-stone-600">{formatDateTime(ev.occurred_at)}</span>
                </div>
              ))
            ) : (
              <p className="py-4 text-center text-2xs text-stone-500">当前战役尚无事件记录</p>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
