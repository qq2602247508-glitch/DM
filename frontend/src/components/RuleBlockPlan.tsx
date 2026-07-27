import type { ReactElement } from "react";

import {
  buildRuleBlockPlan,
  type RuleBlockKind,
  type RuleBlockPlan as RuleBlockPlanData,
} from "../ui/ruleBlocks";

const BLOCK_STYLES: Record<RuleBlockKind, string> = {
  trigger: "border-sky-800/60 bg-sky-950/20 text-sky-100",
  target: "border-cyan-800/60 bg-cyan-950/20 text-cyan-100",
  range: "border-blue-800/60 bg-blue-950/20 text-blue-100",
  cost: "border-amber-800/60 bg-amber-950/20 text-amber-100",
  roll: "border-violet-800/60 bg-violet-950/20 text-violet-100",
  save: "border-fuchsia-800/60 bg-fuchsia-950/20 text-fuchsia-100",
  effect: "border-red-800/60 bg-red-950/20 text-red-100",
  condition: "border-orange-800/60 bg-orange-950/20 text-orange-100",
  duration: "border-emerald-800/60 bg-emerald-950/20 text-emerald-100",
  repeat: "border-teal-800/60 bg-teal-950/20 text-teal-100",
  special: "border-ink-600 bg-ink-900/70 text-stone-200",
};

const AUTOMATION_STYLES: Record<RuleBlockPlanData["automation"], string> = {
  automatic: "border-emerald-700/60 bg-emerald-950/25 text-emerald-200",
  partial: "border-amber-700/60 bg-amber-950/25 text-amber-200",
  manual: "border-red-700/60 bg-red-950/25 text-red-200",
};

export function RuleBlockPlan({
  source,
  title = "规则执行积木",
}: {
  source: unknown;
  title?: string;
}): ReactElement {
  const plan = buildRuleBlockPlan(source);

  return (
    <section aria-label={title} className="mt-3 rounded-lg border border-ink-700 bg-ink-950/35 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="m-0 mr-auto text-xs font-semibold text-parchment-100">{title}</h4>
        <span
          className={`rounded border px-2 py-1 text-2xs ${AUTOMATION_STYLES[plan.automation]}`}
          data-automation={plan.automation}
        >
          {plan.automationLabel}
        </span>
      </div>
      <p className="mb-0 mt-2 text-2xs leading-5 text-stone-500">{plan.reason}</p>
      {plan.blocks.length ? (
        <ol className="mb-0 mt-3 grid list-none gap-2 p-0 sm:grid-cols-2">
          {plan.blocks.map((block, index) => (
            <li
              className={`rounded border p-2.5 ${BLOCK_STYLES[block.kind]}`}
              key={`${block.kind}-${index}`}
            >
              <span className="block text-2xs opacity-65">
                {index + 1}. {block.label}
              </span>
              <strong className="mt-1 block whitespace-pre-wrap text-xs font-medium">
                执行：{block.value}
              </strong>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mb-0 mt-3 rounded border border-dashed border-ink-600 p-3 text-xs text-stone-500">
          没有可展示的结构化规则字段；请查看来源规则并由 DM 裁定。
        </p>
      )}
    </section>
  );
}
