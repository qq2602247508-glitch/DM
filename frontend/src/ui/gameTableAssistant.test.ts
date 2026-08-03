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
    expect(inferAssistantDeliveryMode("店主发现玩家撒谎，她会怎么回应？只给一句台词", "dm_guidance")).toBe("spoken_line");
    expect(inferAssistantDeliveryMode("给我一段玩家推开门后的失败后果描写", "other")).toBe("read_aloud");
    expect(inferAssistantDeliveryMode("玩家不去钟楼，我该怎么办？给三条主持方法，不要写NPC台词、环境事件或新线索", "spoken_line")).toBe("dm_guidance");
    expect(inferAssistantDeliveryMode("把它改成店主亲口说的", "spoken_line")).toBe("revision");
    expect(inferAssistantDeliveryMode("太短了", "other")).toBe("revision");
    expect(inferAssistantDeliveryMode("玩家刚才调查失败，给我一段后果描写", "other")).toBe("read_aloud");
    expect(inferAssistantDeliveryMode("保持刚才的叙事风格，再扩写一点", "other")).toBe("revision");
    expect(inferAssistantDeliveryMode("把刚才那段压到80字，删掉多余比喻", "other")).toBe("revision");
    expect(inferAssistantDeliveryMode("改得更克制，再来一版", "other")).toBe("revision");
  });

  it("checks delivery function by semantic mode instead of request keywords", () => {
    expect(assistantDeliveryIssue("read_aloud", "雨声敲窗，火光摇曳。")).toContain("行动");
    expect(assistantDeliveryIssue("read_aloud", "委托就在桌上。你们打算怎么做？")).toBeNull();
    expect(assistantDeliveryIssue("read_aloud", "调查没有得到答案。你们接下来要做什么？")).toBeNull();
    expect(assistantDeliveryIssue("dm_guidance", "众人沉默地看着彼此。")).toContain("可执行");
    expect(assistantDeliveryIssue("dm_guidance", "先请每人介绍一个共同经历，再让下一位接话。")).toBeNull();
    expect(assistantDeliveryIssue(
      "dm_guidance",
      "1. 店主说：‘你们不去也好。’ 2. 阴影已经避开你们。 3. 旅店藏着新线索。",
      "给三条主持方法，不要写NPC台词、环境事件或新线索",
    )).toContain("台词");
    expect(assistantDeliveryIssue(
      "dm_guidance",
      "1. 让玩家扮演旅店老板。2. 突然响起钟声。3. 请玩家说出本能反应。",
      "给主持步骤，不要变成开场旁白",
    )).toContain("场景事件");
    expect(assistantDeliveryIssue(
      "spoken_line",
      "这杯酒和昨天不太一样。",
      "店主发现玩家撒谎，只给一句克制台词",
    )).toContain("察觉谎言");
    expect(assistantDeliveryIssue(
      "read_aloud",
      "你伸手碰门，猛地后退，并意识到这里很危险。现在，你们准备怎么办？",
      "给一段失败后果描写，不要替玩家决定反应",
    )).toContain("替玩家决定");
    expect(assistantDeliveryIssue(
      "read_aloud",
      "空气里传来低沉的声音。你们感觉到一阵寒意，也听见自己心跳。现在，你们准备怎么办？",
      "调查失败，但不要替玩家决定行动、感受或结论",
    )).toContain("替玩家决定");
    expect(assistantDeliveryIssue(
      "read_aloud",
      "你指尖触过的地方没有回应。你环顾四周，一切如常。现在，你们准备怎么办？",
      "调查失败，但不要替玩家决定行动、感受或结论",
    )).toContain("替玩家决定");
    expect(assistantDeliveryIssue(
      "read_aloud",
      "墙壁浮出一道裂痕，地面微微下陷。现在，你们准备怎么办？",
      "调查失败，但我没有说明调查对象；不要指定具体物件",
    )).toContain("擅自指定");
    expect(assistantDeliveryIssue("explanation", "因为都收到奥尔莎的委托，所以他们在旅店会合。")).toBeNull();
    expect(assistantDeliveryIssue(
      "explanation",
      "出口已经封锁，钥匙藏在地下，所以众人必须合作。",
      "给一个自然可信的共同理由",
    )).toContain("已经确认的事实");
    expect(assistantDeliveryIssue(
      "explanation",
      "可采用的共同理由是：出口暂时封锁，所以众人需要合作。",
      "给一个自然可信的共同理由",
    )).toBeNull();
    expect(assistantDeliveryIssue(
      "explanation",
      "可采用的共同理由是：他们每个人都曾在梦境里听见钟声。",
      "给一个共同合作理由，但不要替他们写死个人背景",
    )).toContain("既往经历");
    expect(assistantDeliveryIssue(
      "explanation",
      "可采用的共同理由是：三人被钟楼深处的低语吸引，必须在三轮内关闭失控的古代装置，否则整座旅店会被吞噬。",
      "三名陌生玩家为什么愿意临时合作？请给一个可选的共同理由，不要写死个人背景",
    )).toContain("过度具体");
    expect(assistantDeliveryIssue(
      "explanation",
      "可采用的共同理由是：三人同时被一道神秘召唤术击中，感知到同一道低语。他们虽互不相识，却都察觉到自身被魔法束缚，唯有合作解开共鸣机关才能脱困。",
      "三名陌生玩家为什么愿意临时合作？请给一个可选的共同理由，不要写死个人背景",
    )).toContain("过度具体");
    expect(assistantDeliveryIssue(
      "explanation",
      "可采用的共同理由是：三名玩家在旅店大厅中同时被一道来自旧祭坛的幽蓝符文光柱击中，瞬间感知到彼此意识中浮现同一段警告——‘钟楼未眠，门已开启，若不共赴其下，将同陷永夜’。这并非幻觉，而是某种空间共鸣的共感现象，暗示他们正被同一股未知力量选中，必须暂时联手才能查明真相并逃离当前的异常状态。",
      "三名陌生玩家为什么愿意临时合作？请给一个可选的共同理由，不要写死个人背景",
    )).toContain("过度具体");
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
    expect(assistantDeliveryIssue("revision", "甲".repeat(120), "把刚才那段压到80字"))
      .toContain("超出目标长度");
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

    const existingHandoff = "调查没有得到答案。你们接下来要做什么？";
    expect(repairReadAloudCandidate(request, existingHandoff)).toBe(existingHandoff);
  });

  it("keeps failed investigation narration moving without puppeting players", () => {
    const text = buildSafeReadAloudFallback({
      requestText: "调查失败但不要卡团，也不要替玩家决定反应",
      sceneName: "雾锁钟楼",
      locationName: "旅店大厅",
      presentNames: [],
    });
    expect(text).toContain("失败也没有抹去已经公开的痕迹");
    expect(text).toContain("选择仍在你们手里");
    expect(text).not.toMatch(/你们?(?:伸手|后退|意识到|感到)/);
    expect(assistantDeliveryIssue("read_aloud", text, "不要替玩家决定反应")).toBeNull();
  });

  it("keeps an unspecified investigation target neutral", () => {
    const request = "调查失败，但我没有说明调查对象；不要替玩家决定行动、感受或结论，也不要指定门、石板、箱子或道具";
    const text = buildSafeReadAloudFallback({
      requestText: request,
      sceneName: "雾锁钟楼",
      locationName: "旅店大厅",
      presentNames: [],
    });
    expect(text).toContain("刚才检查的地方");
    expect(text).not.toMatch(/门|石板|箱子|道具|墙壁|地面|裂痕/);
    expect(assistantDeliveryIssue("read_aloud", text, request)).toBeNull();
  });

  it("builds a reason without inventing a fixed personal backstory", () => {
    const text = buildSafeExplanationFallback({
      requestText: "为什么三名陌生冒险者愿意临时合作？",
      sceneName: "提灯旅店的委托",
      locationName: "提灯旅店",
    });
    expect(text).toContain("可采用的共同理由是");
    expect(text).toContain("不必拥有共同过去");
    expect(text).not.toContain("工头");
    expect(text).not.toContain("召唤");
  });

  it("builds DM guidance that respects player agency without forcing the old route", () => {
    const text = buildSafeGuidanceFallback({
      requestText: "玩家不去钟楼，我怎么接住这个选择？",
      sceneName: "提灯旅店的委托",
      locationName: "提灯旅店",
    });
    expect(text).toContain("玩家不去钟楼");
    expect(text).toContain("现在想达成什么");
    expect(text).toContain("不是替他们决定替代路线");

    const introduction = buildSafeGuidanceFallback({
      requestText: "怎么让三名玩家自然互相认识？",
      sceneName: "提灯旅店的委托",
      locationName: "提灯旅店",
    });
    expect(introduction).toContain("不追问过去");
    expect(introduction).toContain("眼前处境");
    expect(introduction).toContain("不替他们定义关系");
  });

  it("builds a minimal spoken warning without inventing the danger's cause", () => {
    expect(buildSafeSpokenLineFallback("给店主一句警告玩家不要靠近地下室的台词"))
      .toBe("“别靠近地下室。我说认真的。”");
    expect(buildSafeSpokenLineFallback("给店主一句提醒大家该出发的台词"))
      .toBe("“各位，该出发了。”");
    expect(buildSafeSpokenLineFallback("店主发现玩家撒谎，但不要直接撕破脸"))
      .toContain("再把刚才那句话说一遍");
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
    const compressed = buildSafeRevisionFallback({
      requestText: "压到80字，保留三步结构",
      previousText: "1. 先确认玩家已经作出的选择，不质疑也不追加钩子。 2. 再询问他们现在想达成什么，不替他们决定路线。 3. 最后说明公开空间并把行动权交还玩家。",
      locationName: "提灯旅店",
    });
    expect(compressed.length).toBeLessThanOrEqual(80);
    expect(compressed).toMatch(/1\..*2\..*3\./);
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
