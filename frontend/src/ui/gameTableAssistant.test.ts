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

  it("uses one semantic contract for different DM requests", () => {
    for (const request of [
      "来一段给玩家的最初导入语",
      "来一段玩家聚集在这里的理由",
      "给店主一句警告玩家的台词",
      "我该怎么引导玩家互相认识？",
    ]) {
      const contract = gameTableAssistantContract(request, "ask");
      expect(contract).toContain(`原始请求：“${request}”`);
      expect(contract).toContain("对象、受众、形式、实际用途");
      expect(contract).toContain("不能只模仿文本表面风格");
      expect(contract).toContain("不得用通用环境描写");
      expect(contract).toContain("不追加选项列表、风险清单");
    }
  });

  it("blocks stale duplicate replies unless repetition was explicitly requested", () => {
    const old = "雨点敲着窗。\n\n1）询问店主";
    expect(isUnwantedRepeatedReply("给我一个新建议", "雨点敲着窗。 1）询问店主", old)).toBe(true);
    expect(isUnwantedRepeatedReply("再说一遍刚才的内容", old, old)).toBe(false);
    expect(isUnwantedRepeatedReply("给我一个新建议", "钟声突然停了。", old)).toBe(false);
  });

  it("detects a repeated body even when the heading or a short tail changed", () => {
    const first = "【可直接朗读】雨点敲打窗棂，壁炉的火光在墙上投下摇曳的影。店主擦拭酒杯，村卫靠在门边。";
    const withoutHeading = "雨点敲打窗棂，壁炉的火光在墙上投下摇曳的影。店主擦拭酒杯，村卫靠在门边。";
    const tinyChange = `${withoutHeading} 远处钟声响起。`;
    expect(isUnwantedRepeatedReply("玩家为什么聚集在这里", withoutHeading, first)).toBe(true);
    expect(isUnwantedRepeatedReply("玩家为什么聚集在这里", tinyChange, first)).toBe(true);
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
