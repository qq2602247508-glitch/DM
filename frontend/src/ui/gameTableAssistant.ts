export type GameTableAssistantIntent = "ask" | "advance" | "execute";
export type AssistantDeliveryMode = "read_aloud" | "spoken_line" | "dm_guidance" | "explanation" | "revision" | "other";

const REVISION_PATTERN = /(?:再说一遍|重复(?:上一|刚才|前面)?|原样|照抄|复述|再短|太短|不够长|缩短|精简|长一点|再长|扩写|展开|详细一点|改写|润色|改成|换成|上一(?:条|段)|刚才|把它|没有发生|不是事实|不要再使用|别再提)/i;
const EXPANSION_PATTERN = /(?:太短|不够长|长一点|再长|扩写|展开|详细一点|写长|比较长)/i;
const EXPLICIT_REPEAT_PATTERN = REVISION_PATTERN;
const LEGACY_ASK_PATTERN = /(?:怎么|如何|怎么办|建议|提示|给我|来一段|帮我|请(?:给|写|生成)|朗读|可朗读|导入语|开场白|是否|要不要|可以吗|好吗|\?|？)/i;

export function inferAssistantDeliveryMode(
  request: string,
  modelMode: AssistantDeliveryMode,
): AssistantDeliveryMode {
  if (REVISION_PATTERN.test(request)) {
    return "revision";
  }
  if (/(?:怎么|如何).{0,8}(?:给|向|对).{0,5}玩家.{0,10}(?:开场|开始)|(?:给|向|对)玩家.{0,12}(?:开场白|开场|导入语|opener)/i.test(request)) {
    return "read_aloud";
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
  request = "",
  previousText = "",
): string | null {
  const compact = text.trim();
  if (!compact) return "回答为空";
  const requestedCharacters = Number(request.match(/(?:大约|约|至少)?\s*(\d{2,4})\s*字/)?.[1] ?? 0);
  if (requestedCharacters >= 80 && compact.length < Math.floor(requestedCharacters * 0.8)) {
    return `DM要求约${requestedCharacters}字，但回答明显不足`;
  }
  if (/(?:比较长|长一点|写长|详细一点|展开)/i.test(request) && compact.length < 180) {
    return "DM明确要求较长成品，但回答仍然太短";
  }
  if (/(?:不要|不用|别让).{0,10}玩家.{0,8}(?:说太多|介绍太多|逐个介绍|逐个发言|回答太多)/i.test(request)
    && /(?:每位|每个|依次|逐一).{0,12}(?:玩家|角色).{0,16}(?:介绍|回答|说明|发言)|玩家.{0,12}(?:介绍.*为何|逐个(?:回答|发言))/i.test(compact)) {
    return "回答仍要求玩家逐个进行较长介绍，违背了DM的明确限制";
  }
  if (mode === "revision" && EXPANSION_PATTERN.test(request) && previousText
    && compact.length < Math.ceil(previousText.trim().length * 1.25)) {
    return "DM要求扩写，但改写结果没有明显比上一条更完整";
  }
  if (mode === "read_aloud") {
    const handsBackControl = /(?:你们|各位|现在).{0,18}(?:怎么做|如何做|准备|打算|决定|行动|回应|介绍|谁先|轮到)|(?:怎么做|如何行动|谁先来)[？?]?/i;
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

export function repairReadAloudCandidate(request: string, text: string): string {
  const asksForLittlePlayerSpeech = /(?:不要|不用|别让).{0,10}玩家.{0,8}(?:说太多|介绍太多|逐个介绍|逐个发言|回答太多)/i.test(request);
  const paragraphs = text
    .trim()
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  const repairedParagraphs = paragraphs
    .map((paragraph) => paragraph
      .split(/(?<=[。！？!?])/)
      .filter((sentence) => !(
        asksForLittlePlayerSpeech
        && /(?:每位|每个|依次|逐一|从左手边).{0,16}(?:玩家|角色).{0,20}(?:介绍|回答|说明|发言)|(?:玩家|角色).{0,12}(?:逐个|依次).{0,10}(?:介绍|回答|说明|发言)/i.test(sentence)
      ))
      .join("")
      .trim())
    .filter(Boolean);
  let repaired = repairedParagraphs
    .join("\n\n")
    .replace(/你(?!们)(?=站|坐|走|听见|看见|闻到|感觉|察觉|打算|准备|决定|注意)/g, "你们");
  if (assistantDeliveryIssue("read_aloud", repaired) !== null) {
    repaired = `${repaired}${repaired ? "\n\n" : ""}短暂的安静把这一刻留给了你们。现在，你们准备先做什么？`;
  }
  return repaired;
}

export function buildSafeReadAloudFallback(input: {
  requestText: string;
  sceneName: string;
  locationName: string;
  sceneDescription?: string | null;
  locationDescription?: string | null;
  presentNames: string[];
}): string {
  const present = input.presentNames.filter(Boolean).slice(0, 2);
  const company = present.length > 0 ? `${present.join("、")}也在场。` : "这里已经有人在等待回应。";
  const wantsLong = /(?:比较长|长一点|写长|详细一点|展开|太短|不够长|(?:大约|约|至少)?\s*[1-9]\d{2}\s*字)/i.test(input.requestText);
  const wantsLittlePlayerSpeech = /(?:不要|不用|别让).{0,10}玩家.{0,8}(?:说太多|介绍太多|逐个介绍|回答太多)/i.test(input.requestText);
  if (wantsLong) {
    const safeSentences = (value: string | null | undefined) => (value ?? "")
      .split(/(?<=[。！？!?])/)
      .map((sentence) => sentence
        .replace(/[，,]?(?:适合|用于|可供)(?:测试|验收).*$/i, "。")
        .replace(/^玩家(?=从|已|正|来到|进入)/, "你们")
        .trim())
      .filter((sentence) => sentence.length >= 8 && !/(?:测试|验收|DM|秘密|隐藏|潜伏|怪物|陷阱|幕后|真相|机关数据|可疑|警铃|假销)/i.test(sentence))
      .slice(0, 2)
      .join("");
    const sceneDetail = safeSentences(input.sceneDescription);
    const locationDetail = safeSentences(input.locationDescription);
    const setting = locationDetail
      ? `${input.locationName}，${locationDetail.replace(/[。！？!?]+$/, "")}。`
      : `${input.locationName}。`;
    const handoff = wantsLittlePlayerSpeech
      ? "你们不需要逐一讲述漫长的过去，也不必先回答一连串问题。等我停下时，只要由最先采取行动的人直接告诉我：你们准备先做什么？"
      : "等我停下时，请用一句话说明各自为何在场，然后由最先采取行动的人告诉我：你们准备先做什么？";
    return `你们已经来到${setting}${sceneDetail ? `${sceneDetail}` : ""}${company}\n\n一路上的猜测和迟疑，都在真正抵达这里时暂时停了下来。你们各自带着怎样的过去、又为何走到这里，可以留到之后慢慢揭开；此刻真正重要的是，你们已经站在同一处，面对同一个尚未作出的决定。眼前的人和事不会替你们选择，接下来发生什么，将从你们的第一个行动开始。\n\n${handoff}`;
  }
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
  if (EXPANSION_PATTERN.test(input.requestText)) {
    return `${input.previousText}\n\n你们不需要立刻决定彼此是否值得信任，也不必现在解释为什么愿意同行。队伍会在接下来的选择中慢慢形成。此刻，所有人的注意力只需要落在同一个问题上：谁先行动，以及其他人是否跟上。`;
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
