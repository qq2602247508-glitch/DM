import type { ReactElement } from "react";

import type { ToolResult } from "../../api/types";
import { Icon } from "../../ui/icons";
import { TOOL_LABELS } from "../../ui/styles";

const SCOPE_LABELS: Record<string, string> = {
  campaign: "战役",
  characters: "角色",
  npcs: "NPC",
  locations: "地点",
  quests: "任务",
  open_clues: "线索",
  active_combats: "战斗",
};

function toolDetail(result: ToolResult): string | null {
  if (result.tool === "search_rules") {
    const citations = result.data.citations;
    const count = Array.isArray(citations) ? citations.length : 0;
    if (!result.ok) {
      return "规则证据不足";
    }
    return count > 0 ? `${count} 条引用` : null;
  }
  if (result.tool === "get_campaign_state" && result.ok) {
    const scopes = Object.keys(result.data)
      .filter((key) => key in SCOPE_LABELS)
      .map((key) => SCOPE_LABELS[key])
      .filter((label): label is string => label !== undefined);
    return scopes.length > 0 ? `已读取：${scopes.join("、")}` : "已读取";
  }
  if (result.tool === "update_campaign_state" && result.ok) {
    return "已创建待确认提案";
  }
  return result.ok ? null : (result.error_message ?? "调用失败");
}

/**
 * Transparency strip showing exactly which typed tools the agent invoked for
 * a turn — this is how the DM sees whether campaign state was actually read.
 */
export function ToolActivityStrip({ results }: { results: ToolResult[] }): ReactElement | null {
  if (results.length === 0) {
    return null;
  }
  return (
    <ul aria-label="本轮工具调用" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
      {results.map((result, index) => {
        const detail = toolDetail(result);
        return (
          <li
            className={`flex items-center gap-1.5 rounded border px-2 py-1 text-2xs ${
              result.ok
                ? "border-ink-600 bg-ink-800/70 text-stone-400"
                : "border-red-900/60 bg-red-950/40 text-red-300"
            }`}
            key={`${result.tool}-${index}`}
            title={result.ok ? undefined : (result.error_message ?? undefined)}
          >
            <Icon name={result.ok ? "check" : "x"} size={11} />
            <span>{TOOL_LABELS[result.tool]}</span>
            {detail ? <span className="text-stone-500">· {detail}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}
