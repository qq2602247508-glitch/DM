import type {
  ContentType,
  Edition,
  EventVisibility,
  Officiality,
  ProposalEntityType,
  ProposalStatus,
  StateOperationKind,
  ToolName,
} from "../api/types";

// ---------------------------------------------------------------------------
// Shared class strings
// ---------------------------------------------------------------------------

export const inputCls =
  "w-full rounded-md border border-ink-600 bg-ink-950/80 px-3 py-2 text-sm text-parchment-100 placeholder:text-stone-600 outline-none transition-colors focus:border-ember-400/70 focus:ring-1 focus:ring-ember-400/40 disabled:opacity-50";

export const selectCls = `${inputCls} appearance-none pr-8`;

export const textareaCls = `${inputCls} min-h-20 resize-y leading-6`;

export const btnBase =
  "inline-flex items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember-400 disabled:cursor-not-allowed disabled:opacity-45";

export const btnPrimary = `${btnBase} border-ember-500/70 bg-ember-500/20 text-ember-200 hover:bg-ember-500/30`;

export const btnGhost = `${btnBase} border-ink-600 bg-ink-800/60 text-stone-300 hover:border-ink-600 hover:bg-ink-750 hover:text-parchment-100`;

export const btnDanger = `${btnBase} border-red-900/80 bg-red-950/50 text-red-300 hover:bg-red-950/80`;

export const btnAi = `${btnBase} border-violet-800/80 bg-violet-950/50 text-violet-300 hover:bg-violet-950/80`;

export const badgeBase =
  "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-medium leading-none";

export type Tone = "ok" | "warn" | "danger" | "ai" | "neutral" | "ember";

export const toneClasses: Record<Tone, string> = {
  ok: "border-emerald-800/70 bg-emerald-950/60 text-emerald-300",
  warn: "border-amber-800/70 bg-amber-950/60 text-amber-300",
  danger: "border-red-800/70 bg-red-950/60 text-red-300",
  ai: "border-violet-800/70 bg-violet-950/60 text-violet-300",
  neutral: "border-ink-600 bg-ink-800/80 text-stone-400",
  ember: "border-ember-600/50 bg-ember-500/10 text-ember-300",
};

// ---------------------------------------------------------------------------
// Enum → 中文标签
// ---------------------------------------------------------------------------

export const CONTENT_TYPE_LABELS: Record<ContentType, string> = {
  rules: "规则",
  classes: "职业",
  subclasses: "子职业",
  spells: "法术",
  monsters: "怪物",
  items: "物品",
  feats: "专长",
  backgrounds: "背景",
  conditions: "状态",
  actions: "动作",
  equipment: "装备",
  unknown: "未分类",
};

export const EDITION_LABELS: Record<Edition, string> = {
  "2014": "2014 版",
  "2024": "2024 版",
  "2025": "2025 版",
  legacy: "Legacy",
  mixed: "混合",
  unknown: "未知版本",
};

export const OFFICIALITY_LABELS: Record<Officiality, string> = {
  official: "官方",
  third_party: "第三方",
  unknown: "来源不明",
};

export const PROPOSAL_STATUS_LABELS: Record<ProposalStatus, string> = {
  pending: "待确认",
  confirmed: "已确认",
  rejected: "已拒绝",
  conflict: "版本冲突",
};

export const PROPOSAL_STATUS_TONES: Record<ProposalStatus, Tone> = {
  pending: "warn",
  confirmed: "ok",
  rejected: "neutral",
  conflict: "danger",
};

export const OPERATION_LABELS: Record<StateOperationKind, string> = {
  create: "新建",
  update: "修改",
  delete: "删除",
};

export const ENTITY_TYPE_LABELS: Record<ProposalEntityType, string> = {
  character: "角色",
  npc: "NPC",
  quest: "任务",
  event: "事件",
};

export const QUEST_STATUS_LABELS: Record<string, string> = {
  open: "未开始",
  active: "进行中",
  completed: "已完成",
  failed: "已失败",
};

export const NPC_STATUS_LABELS: Record<string, string> = {
  active: "活跃",
  inactive: "暂离",
  dead: "死亡",
  missing: "失踪",
};

export const COMBAT_STATUS_LABELS: Record<string, string> = {
  active: "进行中",
  ended: "已结束",
};

export const VISIBILITY_LABELS: Record<EventVisibility, string> = {
  dm: "仅 DM",
  players: "玩家可见",
  public: "公开",
};

export const TOOL_LABELS: Record<ToolName, string> = {
  search_rules: "检索规则",
  get_campaign_state: "读取战役状态",
  update_campaign_state: "提议状态修改",
  generate_dm_hint: "生成 DM 提示",
};

/** Entity payload field → 中文标签（用于提案字段对比）。 */
export const FIELD_LABELS: Record<string, string> = {
  name: "名称",
  class_name: "职业",
  level: "等级",
  hp: "当前 HP",
  max_hp: "最大 HP",
  inventory: "装备",
  notes: "备注",
  description: "描述",
  personality: "性格与目标",
  relationship: "关系与态度",
  secrets: "DM 秘密",
  known_information: "已知信息",
  location_id: "所在地点",
  status: "状态",
  title: "标题",
  event_type: "事件类型",
  occurred_at: "发生时间",
  visibility: "可见性",
  metadata_json: "附加数据",
};
