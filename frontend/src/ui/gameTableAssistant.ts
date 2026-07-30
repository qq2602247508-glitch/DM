export type GameTableAssistantIntent = "ask" | "advance" | "execute";

const EXPLICIT_REPEAT_PATTERN = /(?:再说一遍|重复(?:上一|刚才|前面)?|原样|照抄|复述)/i;
const LEGACY_ASK_PATTERN = /(?:怎么|如何|怎么办|建议|提示|给我|来一段|帮我|请(?:给|写|生成)|朗读|可朗读|导入语|开场白|是否|要不要|可以吗|好吗|\?|？)/i;

export function assistantEntryLabel(
  kind: "dm" | "ai" | "system",
  intent?: GameTableAssistantIntent,
): string {
  if (kind === "system") return "情景变化";
  if (kind === "dm") {
    if (intent === "ask") return "DM 询问";
    if (intent === "execute") return "DM 执行";
    return "DM 推进";
  }
  if (intent === "ask") return "副 DM 回答";
  if (intent === "execute") return "副 DM 执行建议";
  return "副 DM 推进提示";
}

export function gameTableAssistantContract(
  action: string,
  intent: GameTableAssistantIntent,
): string {
  if (intent === "advance") {
    return "请求类型：已确认推进。DM明确表示这段玩家行动或世界变化已经发生。承接已发生事实，给出现场反应、可选后续与必要风险；只有场景目标确实已经完成、绕过或自然收束时才建议转场。";
  }
  if (intent === "execute") {
    return "请求类型：执行草案。DM希望把输入转成可审核的实体、奖励或后果草案；不得声称尚未确认的数据库变化已经发生，也不要把草案当成流程推进。";
  }
  const requestedDeliverable = action.trim().replace(/\s+/g, " ");
  return `请求类型：只询问，不推进。本次唯一交付目标是DM的原始请求：“${requestedDeliverable}”。先准确识别DM要的对象、受众、形式、实际用途和怎样才算完成，再直接交付能完成该用途的内容；不能只模仿文本表面风格。语义与功能都必须对位：问理由就解释成立原因，要台词就让说话者达成台词目的，要引导就给DM可实际采用的引导，要开场内容就真正承担启动对应场面或游戏的作用。不得用通用环境描写、最近一条回答、固定选项或惯用叙事模板替代本次所求。除非DM明确要求，不追加选项列表、风险清单、转场判断或与请求无关的剧情发展。这条输入不代表玩家已经行动、世界已经变化或流程已经推进；不要同步玩家提示、改变流程或把建议写成既成事实。信息不足时给出明确标记的可选假设，不得冒充战役事实。`;
}

function normalizedReply(text: string): string {
  return text
    .replace(/【[^】]{1,16}】/g, "")
    .replace(/(?:可直接朗读|DM备注|副DM回答)[:：]?/gi, "")
    .replace(/\s+/g, "")
    .replace(/[“”‘’「」『』，。！？；：、,.!?;:\-—…]/g, "")
    .trim();
}

function replySimilarity(left: string, right: string): number {
  if (left === right) return 1;
  if (left.length < 20 || right.length < 20) return 0;
  const bigrams = (value: string): Set<string> => {
    const result = new Set<string>();
    for (let index = 0; index < value.length - 1; index += 1) {
      result.add(value.slice(index, index + 2));
    }
    return result;
  };
  const leftPairs = bigrams(left);
  const rightPairs = bigrams(right);
  let shared = 0;
  for (const pair of leftPairs) {
    if (rightPairs.has(pair)) shared += 1;
  }
  return (2 * shared) / (leftPairs.size + rightPairs.size);
}

export function isUnwantedRepeatedReply(
  action: string,
  reply: string,
  previousReply: string | null | undefined,
): boolean {
  if (!previousReply?.trim() || EXPLICIT_REPEAT_PATTERN.test(action)) return false;
  const current = normalizedReply(reply);
  const previous = normalizedReply(previousReply);
  return current === previous || replySimilarity(current, previous) >= 0.82;
}

export function inferLegacyAssistantIntent(text: string): GameTableAssistantIntent {
  return LEGACY_ASK_PATTERN.test(text) ? "ask" : "advance";
}

export function repairLegacyAssistantHistory<T extends {
  kind: "dm" | "ai" | "system";
  intent?: GameTableAssistantIntent;
  text: string;
}>(entries: T[]): T[] {
  const repaired: T[] = [];
  let pendingIntent: GameTableAssistantIntent = "advance";
  let pendingAction = "";
  let previousAi: string | null = null;
  for (const entry of entries) {
    if (entry.kind === "dm") {
      pendingIntent = entry.intent ?? inferLegacyAssistantIntent(entry.text);
      pendingAction = entry.text;
      repaired.push({ ...entry, intent: pendingIntent });
      continue;
    }
    if (entry.kind === "ai") {
      const intent = entry.intent ?? pendingIntent;
      if (
        intent === "ask"
        && isUnwantedRepeatedReply(pendingAction, entry.text, previousAi)
      ) {
        continue;
      }
      previousAi = entry.text;
      repaired.push({ ...entry, intent });
      continue;
    }
    repaired.push(entry);
  }
  return repaired;
}
