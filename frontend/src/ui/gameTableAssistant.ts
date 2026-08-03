export type GameTableAssistantIntent = "ask" | "advance" | "execute";
export type AssistantDeliveryMode = "read_aloud" | "spoken_line" | "dm_guidance" | "explanation" | "revision" | "other";

const REVISION_PATTERN = /(?:再说一遍|重复(?:上一|刚才|前面)?|原样|照抄|复述|再短|太短|太长|不够长|缩短|精简|压(?:缩)?到|长一点|再长|扩写|展开|详细一点|改写|重写|润色|改成|改为|改得|换成|换为|删掉|去掉|再来一版|另一版|没有发生|不是事实|不要再使用|别再提|纠正|(?:保持|沿用).{0,8}(?:刚才|上一).{0,8}(?:风格|语气|结构)|(?:刚才|上一(?:条|段)).{0,8}(?:不对|错了|有误))/i;
const EXPANSION_PATTERN = /(?:太短|不够长|长一点|再长|扩写|展开|详细一点|写长|比较长)/i;
const EXPLICIT_REPEAT_PATTERN = REVISION_PATTERN;
const LEGACY_ASK_PATTERN = /(?:怎么|如何|怎么办|建议|提示|给我|来一段|帮我|请(?:给|写|生成)|朗读|可朗读|导入语|开场白|是否|要不要|可以吗|好吗|\?|？)/i;
const UNSPECIFIED_INVESTIGATION_PATTERN = /(?:没有|未|没).{0,8}(?:说明|指定|提到|交代).{0,8}(?:调查|检查|搜索|查看).{0,8}(?:对象|目标)|(?:调查|检查|搜索|查看).{0,8}(?:对象|目标).{0,8}(?:不明|未说明|没有说明)/i;
const UNSPECIFIED_INVESTIGATION_OBJECT_PATTERN = /(?:门|石板|箱子?|宝箱|柜子?|墙壁|地面|地板|裂痕|裂缝|机关|锁|钥匙|账本|物件|道具|烛火|酒桶|压力板)/i;
const PLAYER_AGENCY_PATTERN = /(?:你们?|玩家们?)(?:伸手|指尖(?:触|碰|掠过)|后退|转身|环顾|抬头|低头|回头|走向|走进|打开|触碰|碰到|猛地|立刻|不由得|意识到|明白|觉得|感觉到|感受到|听见|听到|看见|看到|闻到|察觉到|注意到|感到|害怕|决定|选择)/i;

export function inferAssistantDeliveryMode(
  request: string,
  modelMode: AssistantDeliveryMode,
): AssistantDeliveryMode {
  if (REVISION_PATTERN.test(request)) {
    return "revision";
  }
  const requestedContent = request.replace(
    /(?:不要|不用|无需|不需要|别)(?:(?![，,。；;！？!?]).){1,40}(?=[，,。；;！？!?]|$)/gi,
    "",
  );
  if (/(?:怎么|如何).{0,8}(?:给|向|对).{0,5}玩家.{0,10}(?:开场|开始)|(?:给|向|对)玩家.{0,12}(?:开场白|开场|导入语|opener)/i.test(requestedContent)) {
    return "read_aloud";
  }
  if (/(?:台词|对白|亲口说|说一句|一句话(?:警告|告诉|回应)|(?:会|该|要|能)(?:怎么|如何)说|会怎么回应|说点什么|如何回答)/i.test(requestedContent)) {
    return "spoken_line";
  }
  if (/(?:给|写|来|生成).{0,8}(?:玩家)?(?:一段|几句).{0,16}(?:描写|描述|旁白|叙事|场面)|(?:朗读|可朗读)/i.test(requestedContent)) {
    return "read_aloud";
  }
  if (/(?:怎么|如何|怎么办|建议|方法|引导|组织|安排|提示)/i.test(requestedContent)) {
    return "dm_guidance";
  }
  if (/(?:为什么|为何|理由|原因|动机|缘由|依据|怎么会)/i.test(requestedContent)) {
    return "explanation";
  }
  if (/(?:给玩家|向玩家|对玩家).{0,16}(?:朗读|描述|开场|开始|导入)|(?:opener|开场白|导入语|可朗读)/i.test(requestedContent)) {
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
  if (requestedCharacters >= 80 && compact.length > Math.ceil(requestedCharacters * 1.3)) {
    return `DM要求约${requestedCharacters}字，但回答明显超出目标长度`;
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
    if (/(?:不要|不用|别).{0,12}(?:替|让).{0,6}玩家.{0,12}(?:决定|行动|反应|感受)|不要替玩家决定反应/i.test(request)
      && PLAYER_AGENCY_PATTERN.test(compact)) {
      return "可朗读文案替玩家决定了动作、感受或理解";
    }
    if (UNSPECIFIED_INVESTIGATION_PATTERN.test(request) && UNSPECIFIED_INVESTIGATION_OBJECT_PATTERN.test(compact)) {
      return "未说明调查对象时，回答擅自指定了具体物件或调查目标";
    }
    const handsBackControl = /(?:你们|各位|现在).{0,18}(?:怎么做|如何做|做什么|怎么继续|如何继续|准备|打算|决定|行动|回应|介绍|谁先|轮到)|(?:怎么做|如何行动|谁先来)[？?]?/i;
    return handsBackControl.test(compact) ? null : "可朗读成品没有把明确的行动或发言机会交给玩家";
  }
  if (mode === "spoken_line") {
    const looksLikeAdviceOrNarration = /(?:^|\n)\s*(?:\d+[.、]|[-*])|(?:建议|可以让|DM|旁白|他说|她说|走向|目光|环境|选项)[：:]/i;
    if (looksLikeAdviceOrNarration.test(compact)) return "角色台词混入了建议、旁白或选项";
    if (/(?:一句|一句话)/i.test(request) && compact.length > 120) return "DM只要求一句台词，但回答明显过长";
    if (/(?:撒谎|说谎|谎话|说的是假话)/i.test(request)
      && !/(?:实话|真话|说法|故事|这话|刚才.{0,6}(?:说|那句)|相信|编得|瞒|坦白|再说一遍|确定)/i.test(compact)) {
      return "台词没有让听者感受到说话者已经察觉谎言";
    }
    return null;
  }
  if (mode === "dm_guidance") {
    if (/(?:不要|不用|别).{0,16}(?:NPC)?(?:台词|对白)/i.test(request)
      && /[“”‘’「」『』]/.test(compact)) {
      return "DM明确不要NPC台词或对白，但回答仍写了世界内台词";
    }
    if (/(?:不要|不用|别).{0,20}(?:环境事件|新事件|新线索|异象|剧情钩子)/i.test(request)
      && /(?:突然|传来|出现|渗出|藏着|暗示|异象|新线索|已经?注意到|阴影.{0,8}(?:逼近|避开|笼罩))/i.test(compact)) {
      return "DM明确不要新增事件或线索，但回答仍创作了世界内变化";
    }
    if (/(?:不要|不用|别).{0,12}(?:开场旁白|旁白)/i.test(request)
      && /(?:钟声|失踪|突然|旅店大厅|扮演|本能反应|看到什么|NPC|老板|守卫|门口|火光)/i.test(compact)) {
      return "DM要求主持步骤而非开场旁白，但回答仍预写了场景事件或角色反应";
    }
    if (/(?:三|3)条/i.test(request)) {
      const numberedItems = compact.match(/(?:^|[\n\s])(?:[123]|[一二三])[.、：:]/g)?.length ?? 0;
      if (numberedItems < 3) return "DM要求三条建议，但回答没有交付三条可区分的方法";
    }
    const actionable = /(?:先|再|让|请|要求|询问|邀请|安排|给出|轮流|引导|可以)/;
    return actionable.test(compact) ? null : "给 DM 的方法没有可执行动作";
  }
  if (mode === "explanation") {
    const asksForDesignedReason = /(?:给|想|编|设计|提供).{0,12}(?:共同)?理由/i.test(request);
    if (asksForDesignedReason) {
      if (!/(?:可以设定|可设定|可采用|可以采用|一种自然的解释|建议设定|作为可选理由)/i.test(compact)) {
        return "DM要求设计一个理由，但回答把新设定写成了已经确认的事实";
      }
      if (/(?:一个|一种|一条|简短)/i.test(request)) {
        const sentences = compact.split(/[。！？!?]+/).map((sentence) => sentence.trim()).filter(Boolean);
        const proposalTone = /(?:可|可以|如果|若|建议|只需|不必|无需|暂时|短期|作为)/i;
        if (sentences.length > 1 && sentences.slice(1).some((sentence) => !proposalTone.test(sentence))) {
          return "DM只要一个可选理由，但回答扩展成了过度具体的既定剧情";
        }
        if (/(?:必须|若不|否则|将会|会被|被封印|失控|吞噬|神祇|心灵感应|古代|[一二三四五六七八九十\d]+轮)/i.test(compact)) {
          return "DM只要一个可选理由，但回答扩展成了过度具体的既定剧情";
        }
      }
    }
    if (/(?:不要|不用|别).{0,18}(?:写死|预写|设定).{0,8}(?:个人)?背景/i.test(request)
      && /(?:每个人|每人|他们|三人|有人|自身).{0,24}(?:曾经|过去|梦中|梦境|遭遇|家人|故乡|秘密)/i.test(compact)) {
      return "DM明确不要替玩家写死个人背景，但回答仍给角色追加了既往经历";
    }
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
    .replace(/你(?!们)(?=站|坐|走|指尖|环顾|抬头|低头|回头|听见|看见|闻到|感觉|察觉|打算|准备|决定|注意|还?能)/g, "你们");
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
  const wantsLittlePlayerSpeech = /(?:不要|不用|别让).{0,10}玩家.{0,8}(?:说太多|介绍太多|逐个介绍|逐个发言|回答太多)/i.test(input.requestText);
  if (/(?:失败|没成功|没有成功|没找到|没有找到).{0,18}(?:调查|搜索|察看|检定)|(?:调查|搜索|察看|检定).{0,18}(?:失败|没成功|没有成功)/i.test(input.requestText)) {
    return `刚才检查的地方没有揭开预期中的答案。${input.locationName}仍保持着原来的模样，没有哪一处主动承认自己藏着秘密；但失败也没有抹去已经公开的痕迹，只是让它们暂时无法组成完整结论。时间仍在向前，现场也不会永远保持不变。你们可以换一种观察方式、请同伴从不同角度协助，或暂时记下疑点去处理别的事情。答案没有出现，但选择仍在你们手里。现在，你们准备怎么继续？`;
  }
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
  requestText?: string;
  sceneName: string;
  locationName: string;
}): string {
  if (/(?:合作|同行|组队|结盟)/i.test(input.requestText ?? "")) {
    return `可采用的共同理由是：众人眼前正面对一个单靠任何一人都难以稳妥处理的公共问题，于是先达成一份短期、务实的合作约定。他们不必拥有共同过去，也不用立刻彼此信任；只需同意共享眼前的信息与风险，等问题解决后再决定是否继续同行。`;
  }
  return `就“${input.requestText || input.sceneName}”而言，当前能确认的共同基础只有：众人同处${input.locationName}，并面对「${input.sceneName}」。更具体的原因应作为可选解释交给 DM 选择，不能替玩家写死个人经历，也不能冒充已经发生的战役事实。`;
}

export function buildSafeGuidanceFallback(input: {
  requestText?: string;
  sceneName: string;
  locationName: string;
}): string {
  if (/(?:互相认识|相识|破冰|认识彼此|彼此认识)/i.test(input.requestText ?? "")) {
    return `针对“${input.requestText}”：\n1. 先请每位玩家只选另一名角色此刻可见的一个细节，并说出自己的角色为什么愿意对这个细节作出回应；不追问过去。\n2. 让第一位角色向对方提出一个只关于眼前处境的简短问题；回答者答完后，再自行选择下一位接话，直到每个人都自然说过一次。\n3. 最后由 DM 复述三人刚刚共同关注的一件眼前问题，不替他们定义关系；直接问他们接下来是否一起行动。`;
  }
  return `针对“${input.requestText || input.sceneName}”：\n1. 先用一句话复述并确认玩家已经作出的选择，不质疑，也不立即投放新的剧情钩子。\n2. 直接询问他们现在想达成什么；若目的还不清楚，就给时间讨论，而不是替他们决定替代路线。\n3. 只说明当前已经公开的选择空间，再把行动权交还玩家；等他们采取行动后，${input.locationName}才根据该行动产生后果。`;
}

export function buildSafeSpokenLineFallback(request: string): string {
  if (/(?:撒谎|说谎|谎话|说的是假话)/i.test(request)) {
    return "“我不急着拆穿你。想清楚了，再把刚才那句话说一遍。”";
  }
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
  const targetCharacters = Number(input.requestText.match(/(\d{2,4})\s*字/)?.[1] ?? 0);
  if (/(?:再短|太长|缩短|精简|压(?:缩)?到|删掉|去掉)/i.test(input.requestText) && targetCharacters >= 20) {
    const numberedItems = [...input.previousText.matchAll(/(?:^|\s)([1-9])[.、]\s*(.*?)(?=\s[1-9][.、]|$)/g)]
      .map((match) => (match[2] ?? "").trim())
      .filter(Boolean);
    if (numberedItems.length >= 2 && /(?:保留|保持).{0,8}(?:结构|步骤|编号)/i.test(input.requestText)) {
      const itemBudget = Math.max(8, Math.floor((targetCharacters - numberedItems.length * 3) / numberedItems.length));
      return numberedItems
        .map((item, index) => `${index + 1}. ${item.length > itemBudget ? `${item.slice(0, itemBudget).replace(/[，、；：\s]+$/, "")}。` : item}`)
        .join(" ")
        .slice(0, targetCharacters);
    }
    return input.previousText.length > targetCharacters
      ? `${input.previousText.slice(0, targetCharacters - 1).replace(/[，、；：\s]+$/, "")}。`
      : input.previousText;
  }
  if (/(?:再短|太长|缩短|精简|压缩)/i.test(input.requestText)) {
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
