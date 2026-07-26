import type { ReactElement } from "react";

import type { AgentResponse, GroundedAnswer } from "../../api/types";
import { navigate } from "../../hooks/useHashRoute";
import { CitationList } from "../Citations";
import { Icon } from "../../ui/icons";
import { Badge, Button } from "../../ui/primitives";
import { AiTag, CopyButton, DmOnlyTag } from "../../ui/widgets";
import { ToolActivityStrip } from "./ToolActivityStrip";

function HintSection({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "warn" | "ai";
}): ReactElement | null {
  if (items.length === 0) {
    return null;
  }
  const color = tone === "warn" ? "text-amber-300/90" : "text-violet-300/90";
  return (
    <div>
      <p className={`m-0 text-2xs font-semibold uppercase tracking-[0.16em] ${color}`}>{title}</p>
      <ul className="m-0 mt-1.5 list-none space-y-1 p-0">
        {items.map((item, index) => (
          <li className="flex gap-2 text-sm leading-6 text-stone-300" key={index}>
            <span className={`mt-0.5 shrink-0 ${color}`}>·</span>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Renders one assistant/turns response with all trust boundaries visible. */
export function AgentResponseView({ response }: { response: AgentResponse }): ReactElement {
  const hint = response.dm_hint;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <AiTag />
        <DmOnlyTag />
        <span className="text-2xs text-stone-600">不是已确认事实 · 最终裁决权在 DM</span>
        <span className="ml-auto">
          {hint ? <CopyButton text={hint.text} /> : null}
        </span>
      </div>

      {response.errors.length > 0 ? (
        <div className="rounded-md border border-amber-800/60 bg-amber-950/40 px-3 py-2" role="alert">
          {response.errors.map((error, index) => (
            <p className="m-0 flex items-center gap-2 text-xs leading-5 text-amber-200" key={index}>
              <Icon name="alert" size={12} />
              {error}
            </p>
          ))}
        </div>
      ) : null}

      {hint ? (
        <>
          <p className="prose-block m-0 text-[15px] text-parchment-100">{hint.text}</p>
          <HintSection items={hint.assumptions} title="假设" tone="warn" />
          <HintSection items={hint.uncertainties} title="不确定性" tone="warn" />
          {hint.citations.length > 0 ? (
            <div>
              <p className="m-0 text-2xs font-semibold uppercase tracking-[0.16em] text-stone-500">
                规则引用
              </p>
              <div className="mt-1.5">
                <CitationList citations={hint.citations} />
              </div>
            </div>
          ) : null}
          <HintSection items={hint.proposed_changes} title="AI 建议的状态修改（尚未写入）" tone="ai" />
        </>
      ) : response.abstained ? (
        <p className="m-0 rounded-md border border-amber-800/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
          AI 无法给出可靠回答 — 没有足够依据时不编造内容。
        </p>
      ) : null}

      <ToolActivityStrip results={response.tool_results} />

      {response.proposals.length > 0 ? (
        <div className="flex items-center justify-between gap-2 rounded-md border border-amber-800/60 bg-amber-950/40 px-3 py-2">
          <span className="text-xs text-amber-200">
            本轮产生了 {response.proposals.length} 项状态修改提案，等待你确认后才会写入数据库
          </span>
          <Button onClick={() => navigate("/proposals")} size="sm" variant="primary">
            前往确认
          </Button>
        </div>
      ) : null}

      {response.citations.length > 0 && hint && hint.citations.length === 0 ? (
        <div>
          <p className="m-0 text-2xs font-semibold uppercase tracking-[0.16em] text-stone-500">
            检索到的规则引用
          </p>
          <div className="mt-1.5">
            <CitationList citations={response.citations} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** Renders a grounded rules answer (knowledge/answer) — facts, not advice. */
export function RulesAnswerView({ answer }: { answer: GroundedAnswer }): ReactElement {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="ok">规则回答</Badge>
        <span className="text-2xs text-stone-600">仅基于检索到的规则原文</span>
        <span className="ml-auto">
          <CopyButton text={answer.answer} />
        </span>
      </div>
      {answer.abstained ? (
        <p className="m-0 rounded-md border border-amber-800/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
          无法确认 — 现有规则库中没有足够证据回答这个问题
          {answer.reason ? `（${answer.reason}）` : ""}。
        </p>
      ) : (
        <p className="prose-block m-0 text-[15px] text-parchment-100">{answer.answer}</p>
      )}
      {answer.citations.length > 0 ? (
        <div>
          <p className="m-0 text-2xs font-semibold uppercase tracking-[0.16em] text-stone-500">
            引用来源
          </p>
          <div className="mt-1.5">
            <CitationList citations={answer.citations} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
