export type GameTableAssistantIntent = "ask" | "advance" | "execute";

const PLAYER_READALOUD_PATTERN = /(?:给玩家|玩家听|可朗读|朗读|导入语|开场白|旁白|描述词|念给)/i;
const PARTY_MOTIVATION_PATTERN = /(?:聚集|集合|汇合|碰面|相识|认识).{0,12}(?:理由|原因|动机|目的)|(?:理由|原因|动机|目的).{0,12}(?:聚集|集合|汇合|碰面|相识|认识)/i;
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
  if (PARTY_MOTIVATION_PATTERN.test(action)) {
    return "请求类型：只询问，不推进。DM要的是玩家角色为何在此聚集、愿意一起行动的成立理由。请直接给出共同动机、必要的个人钩子或彼此关系，不要重写开场环境描写，不要把钟声、雨景、NPC动作等气氛段落当作聚集理由。若现有事实不足，明确给出可选设定而不是冒充已确认事实。";
  }
  if (PLAYER_READALOUD_PATTERN.test(action)) {
    return "请求类型：只询问，不推进。DM要的是给玩家直接朗读的文案。请优先完成输入指定的文案，只输出“【可直接朗读】”正文；确有必要时再附一小段“【DM备注】”。不要追加固定调查选项、风险清单或转场判断，除非DM明确要求。";
  }
  return "请求类型：只询问，不推进。直接回答DM当前问题或给出所请求的建议；这条输入不代表玩家已经行动、世界已经变化或流程已经推进。不要擅自生成现场结果、同步玩家提示、判断转场或把建议写成既成事实。";
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
