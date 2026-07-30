import { describe, expect, it } from "vitest";

import {
  assistantDeliveryIssue,
  assistantEntryLabel,
  buildSafeExplanationFallback,
  buildSafeGuidanceFallback,
  buildSafeReadAloudFallback,
  buildSafeRevisionFallback,
  buildSafeSpokenLineFallback,
  confirmedAssistantContextEntries,
  gameTableAssistantContract,
  inferAssistantDeliveryMode,
  isUnwantedRepeatedReply,
  repairReadAloudCandidate,
  repairLegacyAssistantHistory,
} from "./gameTableAssistant";

describe("game table assistant intent", () => {
  it("corrects model delivery types with one general intent classifier", () => {
    expect(inferAssistantDeliveryMode("给一段玩家来这里的理由", "read_aloud")).toBe("explanation");
    expect(inferAssistantDeliveryMode("我该怎么引导玩家互相认识？", "read_aloud")).toBe("dm_guidance");
    expect(inferAssistantDeliveryMode("给店主一句警告玩家的台词", "read_aloud")).toBe("spoken_line");
    expect(inferAssistantDeliveryMode("给玩家一段描述，作为跑团开始", "other")).toBe("read_aloud");
    expect(inferAssistantDeliveryMode("我该怎么给玩家开场？", "dm_guidance")).toBe("read_aloud");
    expect(inferAssistantDeliveryMode("把它改成店主亲口说的", "spoken_line")).toBe("revision");
    expect(inferAssistantDeliveryMode("太短了", "other")).toBe("revision");
  });

  it("checks delivery function by semantic mode instead of request keywords", () => {
    expect(assistantDeliveryIssue("read_aloud", "雨声敲窗，火光摇曳。")).toContain("行动");
    expect(assistantDeliveryIssue("read_aloud", "委托就在桌上。你们打算怎么做？")).toBeNull();
    expect(assistantDeliveryIssue("dm_guidance", "众人沉默地看着彼此。")).toContain("可执行");
    expect(assistantDeliveryIssue("dm_guidance", "先请每人介绍一个共同经历，再让下一位接话。")).toBeNull();
    expect(assistantDeliveryIssue("explanation", "因为都收到奥尔莎的委托，所以他们在旅店会合。")).toBeNull();
  });

  it("builds a fact-bounded read-aloud fallback with an explicit player handoff", () => {
    const text = buildSafeReadAloudFallback({
      requestText: "给玩家一个开场",
      sceneName: "提灯旅店的委托",
      locationName: "提灯旅店",
      presentNames: ["店主奥尔莎", "村卫学徒玛拉"],
    });
    expect(text).toContain("店主奥尔莎、村卫学徒玛拉也在场");
    expect(text).toMatch(/(?:第一个行动是什么|准备做的第一件事|首先采取什么行动)/);
    expect(text).not.toContain("钟声");
    expect(text).not.toContain("泛黄");
  });

  it("varies safe read-aloud structure for distinct requests", () => {
    const base = {
      sceneName: "提灯旅店的委托",
      locationName: "提灯旅店",
      presentNames: ["店主奥尔莎", "村卫学徒玛拉"],
    };
    expect(buildSafeReadAloudFallback({ ...base, requestText: "给我一段给玩家的 opener" }))
      .not.toBe(buildSafeReadAloudFallback({ ...base, requestText: "给玩家一段描述，作为这个跑团的开始" }));
  });

  it("honors a long opener request without forcing every player through an interview", () => {
    const request = "不要让玩家说太多，你给我一个比较长的开场白，自然一点";
    const text = buildSafeReadAloudFallback({
      requestText: request,
      sceneName: "雾锁钟楼综合验收场",
      locationName: "雾锁钟楼旅店",
      sceneDescription: "玩家从旅店大厅进入钟楼地下层。门锁带警铃假销。南侧潜伏着怪物。",
      locationDescription: "一座建在废弃钟楼下的两层旅店。这里适合测试战斗网格。",
      presentNames: ["旅店老板玛拉", "钟表匠奥杜"],
    });
    expect(text.length).toBeGreaterThanOrEqual(180);
    expect(text).toContain("只要由最先采取行动的人直接告诉我");
    expect(text).toContain("一座建在废弃钟楼下的两层旅店");
    expect(text).toContain("你们从旅店大厅进入钟楼地下层");
    expect(text).not.toContain("测试战斗网格");
    expect(text).not.toContain("警铃假销");
    expect(text).not.toMatch(/每位玩家|依次介绍|邪教狂信徒/);
    expect(assistantDeliveryIssue("read_aloud", text, request)).toBeNull();
    expect(assistantDeliveryIssue("read_aloud", "你们已经来到旅店。现在打算怎么做？", request)).toContain("太短");
    expect(assistantDeliveryIssue("read_aloud", "你们来到旅店。现在准备做什么？", "写一段约250字的开场白"))
      .toContain("约250字");
    expect(assistantDeliveryIssue("read_aloud", "甲".repeat(170) + "。你们准备做什么？", "写一段约250字的开场白"))
      .toContain("约250字");
  });

  it("keeps a strong read-aloud candidate and repairs only its player handoff", () => {
    const request = "给我一段约270字的自然开场白，不要让玩家逐个介绍";
    const candidate = "炉火在壁炉里低语，橙红的光晕漫过斑驳的橡木桌。空气里浮动着烤洋葱与迷迭香的香气。城卫军士蕾娜靠在门边，目光落在桌上的热汤上。";
    const repaired = repairReadAloudCandidate(request, candidate);
    expect(repaired).toContain(candidate);
    expect(repaired).toContain("你们准备先做什么？");
    expect(assistantDeliveryIssue("read_aloud", repaired)).toBeNull();

    const interviewEnding = `${candidate}从左手边的玩家开始，依次介绍角色为何到场；然后告诉我你们准备做什么？`;
    const withoutInterview = repairReadAloudCandidate(request, interviewEnding);
    expect(withoutInterview).not.toContain("依次介绍");
    expect(withoutInterview).toContain("你们准备先做什么？");

    const partyVoice = repairReadAloudCandidate(request, "你站在门边，听见远处的钟声。现在，你打算做什么？");
    expect(partyVoice).toContain("你们站在门边");
    expect(partyVoice).toContain("你们打算做什么？");
  });

  it("builds a reason without inventing a fixed personal backstory", () => {
    const text = buildSafeExplanationFallback({
      sceneName: "提灯旅店的委托",
      locationName: "提灯旅店",
    });
    expect(text).toContain("共同事项");
    expect(text).toContain("个人动机不要替玩家定死");
    expect(text).not.toContain("工头");
    expect(text).not.toContain("召唤");
  });

  it("builds DM guidance that asks players to author their own motives and links", () => {
    const text = buildSafeGuidanceFallback({
      sceneName: "提灯旅店的委托",
      locationName: "提灯旅店",
    });
    expect(text).toContain("依次问每位玩家");
    expect(text).toContain("接住一个细节");
    expect(text).toContain("不要替玩家预写个人经历");
  });

  it("builds a minimal spoken warning without inventing the danger's cause", () => {
    expect(buildSafeSpokenLineFallback("给店主一句警告玩家不要靠近地下室的台词"))
      .toBe("“别靠近地下室。我说认真的。”");
    expect(buildSafeSpokenLineFallback("给店主一句提醒大家该出发的台词"))
      .toBe("“各位，该出发了。”");
  });

  it("turns revision failures into actual shortened or spoken content", () => {
    const previous = "先只说明共同事实：你们都因委托来到提灯旅店。然后让每位玩家说明个人动机。";
    expect(buildSafeRevisionFallback({
      requestText: "再短一点",
      previousText: previous,
      locationName: "提灯旅店",
    })).toBe("先只说明共同事实：你们都因委托来到提灯旅店。 ".trim());
    expect(buildSafeRevisionFallback({
      requestText: "把它改成店主亲口说的",
      previousText: previous,
      locationName: "提灯旅店",
    })).toContain("为什么来到提灯旅店");
    expect(buildSafeRevisionFallback({
      requestText: "刚才那个主轴倒转并没有发生，不要再使用",
      previousText: previous,
      locationName: "提灯旅店",
    })).toContain("不作为战役事实");
    expect(buildSafeRevisionFallback({
      requestText: "太短了",
      previousText: "你们来到旅店。现在打算怎么做？",
      locationName: "提灯旅店",
    }).length).toBeGreaterThan("你们来到旅店。现在打算怎么做？".length);
    expect(assistantDeliveryIssue("revision", "短到不能再短。")).toContain("元说明");
    expect(assistantDeliveryIssue("revision", "还是很短。", "太短了", "上一条其实更长一些。")).toContain("没有明显比上一条更完整");
  });

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
    expect(isUnwantedRepeatedReply("再短一点", "雨点敲窗。", old)).toBe(false);
    expect(isUnwantedRepeatedReply("给我一个新建议", "钟声突然停了。", old)).toBe(false);
  });

  it("detects a repeated body even when the heading or a short tail changed", () => {
    const first = "【可直接朗读】雨点敲打窗棂，壁炉的火光在墙上投下摇曳的影。店主擦拭酒杯，村卫靠在门边。";
    const withoutHeading = "雨点敲打窗棂，壁炉的火光在墙上投下摇曳的影。店主擦拭酒杯，村卫靠在门边。";
    const tinyChange = `${withoutHeading} 远处钟声响起。`;
    expect(isUnwantedRepeatedReply("玩家为什么聚集在这里", withoutHeading, first)).toBe(true);
    expect(isUnwantedRepeatedReply("玩家为什么聚集在这里", tinyChange, first)).toBe(true);
  });

  it("blocks the same narrative skeleton after surface wording changes", () => {
    const first = "雨点敲打着提灯旅店的窗棂，火光在墙上投下摇曳的影。一张泛黄纸条写着暮铃磨坊连续三夜无人归来。";
    const second = "雨点敲打着窗棂，炉火在铁架上跳动。墙上一张泛黄纸条仍写着暮铃磨坊连续三夜无人归来。";
    expect(isUnwantedRepeatedReply("给玩家一个开场", second, first)).toBe(true);
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

  it("keeps unconfirmed questions and AI drafts out of future factual context", () => {
    const entries = [
      { kind: "system" as const, text: "DM进入提灯旅店" },
      { kind: "dm" as const, intent: "ask" as const, text: "为什么来这里？" },
      { kind: "ai" as const, intent: "ask" as const, text: "主轴倒转，古老之物苏醒。" },
      { kind: "dm" as const, intent: "execute" as const, text: "起草一个工头" },
      { kind: "ai" as const, intent: "execute" as const, text: "工头冲出林间。" },
      { kind: "dm" as const, intent: "advance" as const, text: "玩家接受奥尔莎的委托" },
      { kind: "ai" as const, intent: "advance" as const, text: "奥尔莎把委托纸交给玩家" },
    ];
    expect(confirmedAssistantContextEntries(entries).map((entry) => entry.text)).toEqual([
      "DM进入提灯旅店",
      "玩家接受奥尔莎的委托",
      "奥尔莎把委托纸交给玩家",
    ]);
  });
});
