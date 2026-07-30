import { describe, expect, it } from "vitest";

import {
  assistantEntryLabel,
  gameTableAssistantContract,
  isUnwantedRepeatedReply,
  repairLegacyAssistantHistory,
} from "./gameTableAssistant";

describe("game table assistant intent", () => {
  it("keeps advice separate from confirmed progress", () => {
    expect(gameTableAssistantContract("我该怎么引导玩家？", "ask")).toContain("只询问，不推进");
    expect(gameTableAssistantContract("玩家已经打开门", "advance")).toContain("已确认推进");
    expect(assistantEntryLabel("dm", "ask")).toBe("DM 询问");
    expect(assistantEntryLabel("ai", "advance")).toBe("副 DM 推进提示");
  });

  it("requests clean player-facing copy without generic options and risks", () => {
    const contract = gameTableAssistantContract("来一段给玩家的最初导入语", "ask");
    expect(contract).toContain("【可直接朗读】");
    expect(contract).toContain("不要追加固定调查选项、风险清单");
  });

  it("blocks stale duplicate replies unless repetition was explicitly requested", () => {
    const old = "雨点敲着窗。\n\n1）询问店主";
    expect(isUnwantedRepeatedReply("给我一个新建议", "雨点敲着窗。 1）询问店主", old)).toBe(true);
    expect(isUnwantedRepeatedReply("再说一遍刚才的内容", old, old)).toBe(false);
    expect(isUnwantedRepeatedReply("给我一个新建议", "钟声突然停了。", old)).toBe(false);
  });

  it("repairs old ask labels and removes the stale duplicate that followed them", () => {
    const oldReply = "雨点敲窗。\n1）询问店主\n风险：钟声。";
    expect(repairLegacyAssistantHistory([
      { kind: "ai" as const, text: oldReply },
      { kind: "dm" as const, text: "来一段给玩家的最初导入语" },
      { kind: "ai" as const, text: oldReply },
    ])).toEqual([
      { kind: "ai", intent: "advance", text: oldReply },
      { kind: "dm", intent: "ask", text: "来一段给玩家的最初导入语" },
    ]);
  });
});
