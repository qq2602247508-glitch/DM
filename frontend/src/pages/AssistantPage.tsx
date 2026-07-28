import { useMutation } from "@tanstack/react-query";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactElement,
} from "react";

import {
  runAssistantTurn,
  type AssistantMode,
} from "../api/assistant";
import { answerKnowledge } from "../api/knowledge";
import type { AgentResponse, GroundedAnswer } from "../api/types";
import { AgentResponseView, RulesAnswerView } from "../components/assistant/AgentResponseView";
import { RequireCampaign } from "../components/RequireCampaign";
import { useAssistantPrefill } from "../hooks/appContexts";
import { Icon } from "../ui/icons";
import { Button, ErrorState, Spinner } from "../ui/primitives";

type Mode = "quick" | "rules" | "story" | "combat";

const AGENT_MODE_BY_UI_MODE: Record<Exclude<Mode, "rules">, AssistantMode> = {
  quick: "quick",
  story: "narrative",
  combat: "combat",
};

const MODES: { id: Mode; label: string; hint: string; placeholder: string }[] = [
  {
    id: "quick",
    label: "快速模式",
    hint: "交给本地意图模型自动规划：按需检索规则、读取战役状态并给出建议",
    placeholder: "玩家想调查酒馆老板是否撒谎…",
  },
  {
    id: "rules",
    label: "规则查询",
    hint: "只查规则库：回答全部来自检索到的规则原文并附引用，证据不足会明说",
    placeholder: "2024 版火球术如何豁免？",
  },
  {
    id: "story",
    label: "剧情建议",
    hint: "偏重剧情走向、NPC 反应与后果（仍为建议，不会自动改状态）",
    placeholder: "玩家想绕过城门守卫潜入城堡，可能有什么后果？",
  },
  {
    id: "combat",
    label: "战斗辅助",
    hint: "偏重战斗流程、动作经济与规则注意事项",
    placeholder: "三只座狼围攻 Lv4 队伍，需要注意什么？",
  },
];

type ThreadEntry =
  | { id: number; kind: "user"; text: string; mode: Mode }
  | { id: number; kind: "agent"; response: AgentResponse }
  | { id: number; kind: "rules"; answer: GroundedAnswer }
  | { id: number; kind: "error"; error: unknown; text: string; mode: Mode };

type NewThreadEntry =
  | { kind: "user"; text: string; mode: Mode }
  | { kind: "agent"; response: AgentResponse }
  | { kind: "rules"; answer: GroundedAnswer }
  | { kind: "error"; error: unknown; text: string; mode: Mode };

const EXAMPLES: { mode: Mode; text: string }[] = [
  { mode: "quick", text: "玩家想调查酒馆老板是否撒谎" },
  { mode: "rules", text: "2024版火球术如何豁免？" },
  { mode: "story", text: "玩家想把偷来的宝石卖给公会会长，可能引发什么？" },
  { mode: "combat", text: "玩家在高处推下巨石砸向敌人，怎么处理？" },
];

function sessionKey(campaignId: string): string {
  return `dnd-dm-assistant-thread:${campaignId}`;
}

function loadSession(campaignId: string): ThreadEntry[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(sessionKey(campaignId)) ?? "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is ThreadEntry => {
      if (typeof item !== "object" || item === null) return false;
      const kind = (item as { kind?: unknown }).kind;
      return kind === "user" || kind === "agent" || kind === "rules";
    });
  } catch {
    return [];
  }
}

function AssistantContent({ campaignId }: { campaignId: string }): ReactElement {
  const { prefill, clearPrefill } = useAssistantPrefill();
  const [mode, setMode] = useState<Mode>("quick");
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState<ThreadEntry[]>(() => loadSession(campaignId));
  const nextId = useRef(entries.reduce((max, entry) => Math.max(max, entry.id), 0) + 1);
  const threadEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (prefill !== null) {
      setInput(prefill);
      clearPrefill();
      inputRef.current?.focus();
    }
  }, [prefill, clearPrefill]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries]);

  useEffect(() => {
    const durable = entries.filter((entry) => entry.kind !== "error");
    localStorage.setItem(sessionKey(campaignId), JSON.stringify(durable));
  }, [campaignId, entries]);

  const push = (entry: NewThreadEntry) => {
    const id = nextId.current;
    nextId.current += 1;
    setEntries((prev) => [...prev, { ...entry, id }]);
  };

  const turn = useMutation<
    AgentResponse | GroundedAnswer,
    unknown,
    { text: string; selectedMode: Mode }
  >({
    mutationFn: ({ text, selectedMode }: { text: string; selectedMode: Mode }) =>
      selectedMode === "rules"
        ? answerKnowledge(text)
        : runAssistantTurn(campaignId, text, {
            mode: AGENT_MODE_BY_UI_MODE[selectedMode],
          }),
    onSuccess: (data, { selectedMode }) => {
      if (selectedMode === "rules") {
        push({ kind: "rules", answer: data as GroundedAnswer });
      } else {
        push({ kind: "agent", response: data as AgentResponse });
      }
    },
    onError: (error, { text, selectedMode }) => {
      push({ kind: "error", error, text, mode: selectedMode });
    },
  });

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const text = input.trim();
    if (!text || turn.isPending) {
      return;
    }
    push({ kind: "user", text, mode });
    turn.mutate({ text, selectedMode: mode });
    setInput("");
  };

  const retry = (entry: Extract<ThreadEntry, { kind: "error" }>) => {
    if (turn.isPending) {
      return;
    }
    push({ kind: "user", text: entry.text, mode: entry.mode });
    turn.mutate({ text: entry.text, selectedMode: entry.mode });
    setEntries((prev) => prev.filter((item) => item.id !== entry.id));
  };

  const activeMode = MODES.find((item) => item.id === mode) ?? MODES[0]!;

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col px-4 py-4">
      {/* Thread */}
      <div className="min-h-0 flex-1 overflow-y-auto pb-4">
        {entries.length > 0 ? (
          <div className="mb-3 flex justify-end">
            <Button
              onClick={() => {
                setEntries([]);
                localStorage.removeItem(sessionKey(campaignId));
              }}
              size="sm"
            >
              清空本地对话
            </Button>
          </div>
        ) : null}
        {entries.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <span
              aria-hidden="true"
              className="grid size-12 place-items-center rounded-full border border-violet-700/50 bg-violet-950/40 text-violet-300"
            >
              <Icon name="sparkle" size={22} />
            </span>
            <div>
              <p className="m-0 font-display text-xl text-parchment-100">DM 私密助手</p>
              <p className="mb-0 mt-2 max-w-md text-sm leading-6 text-stone-500">
                描述玩家的行动或提问规则。AI 只提供建议与待确认提案，
                永远不会直接写入战役数据库。
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {EXAMPLES.map((example) => (
                <button
                  className="rounded-md border border-ink-600 bg-ink-900/80 px-3 py-2 text-left text-xs leading-5 text-stone-400 transition-colors hover:border-violet-700/60 hover:text-parchment-100"
                  key={example.text}
                  onClick={() => {
                    setMode(example.mode);
                    setInput(example.text);
                    inputRef.current?.focus();
                  }}
                  type="button"
                >
                  {example.text}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ol className="m-0 flex list-none flex-col gap-4 p-0">
            {entries.map((entry) => {
              if (entry.kind === "user") {
                const modeLabel = MODES.find((item) => item.id === entry.mode)?.label ?? "";
                return (
                  <li className="flex justify-end" key={entry.id}>
                    <div className="max-w-[85%] rounded-lg border border-ink-600 bg-ink-800/80 px-4 py-2.5">
                      <p className="m-0 text-2xs text-stone-500">{modeLabel}</p>
                      <p className="prose-block mb-0 mt-1 text-sm text-parchment-100">{entry.text}</p>
                    </div>
                  </li>
                );
              }
              if (entry.kind === "error") {
                return (
                  <li key={entry.id}>
                    <ErrorState error={entry.error} onRetry={() => retry(entry)} />
                  </li>
                );
              }
              return (
                <li
                  className="rounded-lg border border-ink-700 bg-ink-900/90 px-4 py-3.5"
                  key={entry.id}
                >
                  {entry.kind === "agent" ? (
                    <AgentResponseView response={entry.response} />
                  ) : (
                    <RulesAnswerView answer={entry.answer} />
                  )}
                </li>
              );
            })}
          </ol>
        )}
        {turn.isPending ? (
          <div className="mt-4 flex items-center gap-2.5 rounded-lg border border-violet-900/50 bg-violet-950/20 px-4 py-3 text-sm text-violet-200/90">
            <Spinner size={14} />
            {mode === "rules" ? "正在检索规则库…" : "本地模型正在思考（可能需要几十秒）…"}
          </div>
        ) : null}
        <div ref={threadEndRef} />
      </div>

      {/* Composer */}
      <form
        className="rounded-lg border border-ink-600 bg-ink-900/95 p-3 shadow-panel"
        onSubmit={submit}
      >
        <div className="mb-2.5 flex flex-wrap items-center gap-1.5" role="tablist">
          {MODES.map((item) => {
            const selected = item.id === mode;
            return (
              <button
                aria-selected={selected}
                className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
                  selected
                    ? "border-violet-600/60 bg-violet-950/60 text-violet-200"
                    : "border-ink-600 text-stone-500 hover:text-stone-300"
                }`}
                key={item.id}
                onClick={() => setMode(item.id)}
                role="tab"
                title={item.hint}
                type="button"
              >
                {item.label}
              </button>
            );
          })}
          <span className="ml-2 hidden text-2xs text-stone-600 sm:inline">{activeMode.hint}</span>
        </div>
        <label className="sr-only" htmlFor="assistant-input">
          描述玩家行动或输入问题
        </label>
        <textarea
          className="min-h-20 w-full resize-none rounded-md border border-ink-600 bg-ink-950/80 px-3 py-2 text-sm leading-6 text-parchment-100 outline-none placeholder:text-stone-600 focus:border-violet-500/60"
          id="assistant-input"
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={activeMode.placeholder}
          ref={inputRef}
          value={input}
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-2xs text-stone-600">
            Enter 发送 · Shift+Enter 换行 · 对话保存在本机浏览器，战役事实以数据库为准
          </span>
          <Button
            disabled={!input.trim() || turn.isPending}
            icon="send"
            loading={turn.isPending}
            type="submit"
            variant="ai"
          >
            发送
          </Button>
        </div>
      </form>
    </div>
  );
}

export function AssistantPage(): ReactElement {
  return (
    <div className="h-full">
      <RequireCampaign>
        {(campaignId) => <AssistantContent campaignId={campaignId} key={campaignId} />}
      </RequireCampaign>
    </div>
  );
}
