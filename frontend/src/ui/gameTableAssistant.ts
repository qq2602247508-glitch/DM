export type GameTableAssistantIntent = "ask" | "advance" | "execute";
export type AssistantDeliveryMode = "read_aloud" | "spoken_line" | "dm_guidance" | "explanation" | "revision" | "other";

const EXPLICIT_REPEAT_PATTERN = /(?:再说一遍|重复(?:上一|刚才|前面)?|原样|照抄|复述|再短|缩短|精简|扩写|改写|润色|改成|换成)/i;
const LEGACY_ASK_PATTERN = /(?:怎么|如何|怎么办|建议|提示|给我|来一段|帮我|请(?:给|写|生成)|朗读|可朗读|导入语|开场白|是否|要不要|可以吗|好吗|\?|？)/i;

export function inferAssistantDeliveryMode(
  request: string,
  modelMode: AssistantDeliveryMode,
): AssistantDeliveryMode {
  if (/(?:再短|缩短|精简|扩写|改写|润色|改成|换成|上一(?:条|段)|刚才|把它|没有发生|不是事实|不要再使用|别再提)/i.test(request)) {
    return "revision";
  }
  if (/(?:怎么|如何|怎么办|建议|方法|引导|组织|安排|提示)/i.test(request)) {
    return "dm_guidance";
  }
  if (/(?:为什么|为何|理由|原因|动机|缘由|依据|怎么会)/i.test(request)) {
    return "explanation";
  }
  if (/(?:台词|对白|亲口说|说一句|一句话警告|一句话告诉)/i.test(request)) {
    return "spoken_line";
  }
  if (/(?:给玩家|向玩家|对玩家).{0,16}(?:朗读|描述|开场|开始|导入)|(?:opener|开场白|导入语|可朗读)/i.test(request)) {
    return "read_aloud";
  }
  return modelMode;
}

export function assistantDeliveryIssue(
  mode: AssistantDeliveryMode,
  text: string,
): string | null {
  const compact = text.trim();
  if (!compact) return "回答为空";
  if (mode === "read_aloud") {
    const handsBackControl = /(?:你们|各位|现在).{0,18}(?:怎么做|如何做|打算|决定|行动|回应|介绍|谁先|轮到)|(?:怎么做|如何行动|谁先来)[？?]?/i;
    return handsBackControl.test(compact) ? null : "可朗读成品没有把明确的行动或发言机会交给玩家";
  }
  if (mode === "spoken_line") {
    const looksLikeAdviceOrNarration = /(?:建议|可以让|DM|旁白|他说|她说|走向|目光|环境|选项)[：:]/i;
    return looksLikeAdviceOrNarration.test(compact) ? "角色台词混入了建议、旁白或选项" : null;
  }
  if (mode === "dm_guidance") {
    const actionable = /(?:先|再|让|请|要求|询问|邀请|安排|给出|轮流|引导|可以)/;
    return actionable.test(compact) ? null : "给 DM 的方法没有可执行动作";
  }
  if (mode === "explanation") {
    const causal = /(?:因为|所以|由于|因此|目的是|原因|共同|各自|为了|受邀|委托)/;
    return causal.test(compact) ? null : "原因说明没有直接建立因果或动机";
  }
  if (mode === "revision") {
    return /(?:不能再短|已经?缩短|修改后|改写后|如下)[：:]?/i.test(compact) || compact.length < 8
      ? "改写请求只返回了元说明，没有实际交付改写后的内容"
      : null;
  }
  return null;
}

export function buildSafeReadAloudFallback(input: {
  requestText: string;
  sceneName: string;
  locationName: string;
  presentNames: string[];
}): string {
  const present = input.presentNames.filter(Boolean).slice(0, 2);
  const company = present.length > 0 ? `${present.join("、")}也在场。` : "这里已经有人在等待回应。";
  let variant = 0;
  for (const character of input.requestText) {
    variant = (variant * 33 + (character.codePointAt(0) ?? 0)) % 3;
  }
  if (variant === 1) {
    return `今晚的第一幕发生在${input.locationName}：你们已经来到这里，${company}从左手边的玩家开始，依次介绍角色为何到场、现在最想向谁开口；然后直接说出你们准备做的第一件事。`;
  }
  if (variant === 2) {
    return `「${input.sceneName}」现在开始。你们都在${input.locationName}，${company}请各自介绍角色此行的理由，以及进入房间后最先留意的人；介绍结束时，由一名玩家告诉我队伍首先采取什么行动。`;
  }
  return `故事从「${input.sceneName}」开始。你们的角色此刻都在${input.locationName}，${company}请每位玩家先用一句话介绍自己的角色、为何来到这里，以及此刻最先注意到谁；介绍完后，告诉我你们的第一个行动是什么？`;
}

export function buildSafeExplanationFallback(input: {
  sceneName: string;
  locationName: string;
}): string {
  return `你们并非偶然同处一地：每个人都因「${input.sceneName}」这件共同事项来到${input.locationName}，它给了原本互不相识的角色一个见面并决定是否同行的理由。个人动机不要替玩家定死；请每位玩家补上一句自己为何愿意回应此事，再把这些不同理由汇合成队伍的第一次合作。`;
}

export function buildSafeGuidanceFallback(input: {
  sceneName: string;
  locationName: string;
}): string {
  return `先只说明共同事实：“你们都因「${input.sceneName}」来到${input.locationName}。”然后依次问每位玩家三件事：谁让你愿意到场、你希望从这件事得到什么、你对前一位角色的第一印象是什么。要求下一位从上一位的回答里接住一个细节，最后由 DM 用一句话汇总大家暂时愿意合作的共同目标；不要替玩家预写个人经历。`;
}

export function buildSafeSpokenLineFallback(request: string): string {
  const prohibition = request.match(/(?:不要|别)(.+?)(?:的)?(?:台词|对白|一句话)?[。！？!?]?$/i)?.[1]
    ?.replace(/的$/, "")
    .trim();
  if (prohibition) {
    return `“别${prohibition}。我说认真的。”`;
  }
  const requestedAction = request.match(
    /(?:提醒|告诉|劝|请求|邀请)(?:玩家|大家|众人|他们)?(.+?)(?:的)?(?:台词|对白|一句话)[。！？!?]?$/i,
  )?.[1]?.replace(/的$/, "").trim();
  if (requestedAction) {
    return `“各位，${requestedAction.replace(/了$/, "")}了。”`;
  }
  return "“先停一下。把你们真正想做的事告诉我，再决定下一步。”";
}

export function buildSafeRevisionFallback(input: {
  requestText: string;
  previousText: string;
  locationName: string;
}): string {
  if (/(?:没有发生|不是事实|不要再使用|别再提|纠正)/i.test(input.requestText)) {
    return "已纠正：你指出的内容不作为战役事实，后续回答不会再使用。";
  }
  if (/(?:再短|缩短|精简)/i.test(input.requestText)) {
    const completeSentence = input.previousText.match(/^.{12,100}?[。！？](?:[”’」』])?/)?.[0];
    if (completeSentence && completeSentence.length < input.previousText.length) {
      return completeSentence;
    }
    return input.previousText.length > 80
      ? `${input.previousText.slice(0, 78).replace(/[，、；：\s]+$/, "")}。`
      : input.previousText;
  }
  if (/(?:亲口说|改成|换成).{0,12}(?:说|台词)?|(?:改成|换成).{0,12}(?:店主|NPC|角色)/i.test(input.requestText)) {
    return `“先告诉我：你们为什么来到${input.locationName}，又愿不愿意一起处理眼前这件事？”`;
  }
  return input.previousText;
}

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
  return current === previous || replySimilarity(current, previous) >= 0.35;
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

export function confirmedAssistantContextEntries<T extends {
  kind: "dm" | "ai" | "system";
  intent?: GameTableAssistantIntent;
}>(entries: T[]): T[] {
  return entries
    .filter((entry) => entry.kind === "system" || entry.intent === "advance")
    .slice(-4);
}
