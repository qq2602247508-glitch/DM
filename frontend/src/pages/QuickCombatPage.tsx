import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState, type ReactElement } from "react";

import {
  advanceCombatTurn,
  confirmCombatAction,
  createCombat,
  createCombatant,
  listCombatActions,
  listCombatants,
  listCombats,
  updateCombatant,
  type CombatActionCommand,
} from "../api/entities";
import { listCampaigns } from "../api/campaigns";
import { runAssistantTurn } from "../api/assistant";
import { listCharacters } from "../api/entities";
import type { Combat, CombatAction, Combatant, SceneGrid } from "../api/types";
import { RequireCampaign } from "../components/RequireCampaign";
import { InitiativeCardStrip } from "../components/combat/InitiativeCardStrip";
import {
  TurnCommandConsole,
  type CombatTargeting,
  type CombatTargetingValidity,
} from "../components/combat/TurnCommandConsole";
import { PlayerRollPanel } from "../components/combat/PlayerRollPanel";
import { useCurrentCampaign } from "../hooks/appContexts";
import { useToast } from "../hooks/toastContext";
import { soundboard } from "../ui/soundboard";
import { Badge, Button, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls } from "../ui/styles";
import {
  getTargetingCells,
  gridDistanceFt,
  isAimPointInRange,
  type GridPoint,
} from "../ui/gridTargeting";

export type VfxEvent = {
  id: string;
  row: number;
  col: number;
  type: "slash" | "arcane" | "shockwave" | "smite" | "fire" | "dust";
  text?: string;
  isCrit?: boolean;
  isMiss?: boolean;
};

// ---------------------------------------------------------------------------
// 5e Test & Standard Spells Catalog for Player Selection & Upcasting
// ---------------------------------------------------------------------------
export type CombatSpellOption = {
  id: string;
  name: string;
  nameEn: string;
  level: number; // 0 for cantrips, 1..9
  school: string;
  castTime: string; // "1动作", "附赠动作", "反应"
  rangeFt: number; // e.g. 120, 60, 150, 5, 0 (Self)
  shape: "single" | "sphere" | "cone" | "line" | "cube";
  sizeFt?: number; // e.g. 20 (for 20ft sphere/cube/cone)
  originSelf?: boolean;
  damageDiceBase: string; // e.g. "1d10", "3d6", "8d6", "2d8", "1d4+1"
  damageType: string; // "fire", "force", "thunder", "radiant", "lightning", "cold", "healing"
  isAttackRoll: boolean; // true for attack roll, false for saving throw / auto-hit
  saveAbility?: string; // "DEX", "CON", "WIS"
  upcastRule: string; // e.g. "+1d6 伤害/环", "+1 枚飞弹/环", "+1d8 伤害/环"
  description: string;
  vfx: "fire" | "arcane" | "shockwave" | "smite" | "slash";
};

export const DND_TEST_SPELLS: CombatSpellOption[] = [
  {
    id: "fire_bolt",
    name: "火焰箭",
    nameEn: "Fire Bolt",
    level: 0,
    school: "塑能",
    castTime: "1动作",
    rangeFt: 120,
    shape: "single",
    damageDiceBase: "1d10",
    damageType: "fire",
    isAttackRoll: true,
    upcastRule: "人物等级提升时伤害成长 (5级2d10 / 11级3d10)",
    description: "向射程内单一目标投掷炽热火束，造成 1d10 火焰伤害并可点燃未被携带的可燃物。",
    vfx: "fire",
  },
  {
    id: "sacred_flame",
    name: "圣火术",
    nameEn: "Sacred Flame",
    level: 0,
    school: "塑能",
    castTime: "1动作",
    rangeFt: 60,
    shape: "single",
    damageDiceBase: "1d8",
    damageType: "radiant",
    isAttackRoll: false,
    saveAbility: "DEX",
    upcastRule: "人物等级提升时伤害成长 (5级2d8 / 11级3d8)",
    description: "类似光耀烈焰自天而降照射目标，目标须通过敏捷豁免，否则受到 1d8 光耀伤害。目标无法从掩蔽中获得豁免增益。",
    vfx: "smite",
  },
  {
    id: "chill_touch",
    name: "冻寒之触",
    nameEn: "Chill Touch",
    level: 0,
    school: "死灵",
    castTime: "1动作",
    rangeFt: 120,
    shape: "single",
    damageDiceBase: "1d8",
    damageType: "necrotic",
    isAttackRoll: true,
    upcastRule: "人物等级提升时伤害成长 (5级2d8)",
    description: "在目标空间创造一只骷髅幽灵鬼手，造成 1d8 黯蚀伤害，并在你下回合开始前阻止其恢复生命值。",
    vfx: "arcane",
  },
  {
    id: "magic_missile",
    name: "魔法飞弹",
    nameEn: "Magic Missile",
    level: 1,
    school: "塑能",
    castTime: "1动作",
    rangeFt: 120,
    shape: "single",
    damageDiceBase: "1d4+1",
    damageType: "force",
    isAttackRoll: false,
    upcastRule: "使用2环或更高法术位时，每高1环便多创造 1 枚飞弹",
    description: "创造 3 枚必中发光的秘法力场飞弹，每枚造成 1d4+1 力场伤害，可分别射向同一或不同敌人。",
    vfx: "arcane",
  },
  {
    id: "thunderwave",
    name: "雷鸣波",
    nameEn: "Thunderwave",
    level: 1,
    school: "塑能",
    castTime: "1动作",
    rangeFt: 15,
    shape: "cube",
    sizeFt: 15,
    originSelf: true,
    damageDiceBase: "2d8",
    damageType: "thunder",
    isAttackRoll: false,
    saveAbility: "CON",
    upcastRule: "使用2环或更高法术位时，每高1环伤害增加 1d8",
    description: "自自身迸发雷鸣震波，立方体内所有生物须通过体质豁免，失败承受 2d8 雷鸣伤害并被推开 10 尺（2格）。",
    vfx: "shockwave",
  },
  {
    id: "burning_hands",
    name: "燃烧之手",
    nameEn: "Burning Hands",
    level: 1,
    school: "塑能",
    castTime: "1动作",
    rangeFt: 15,
    shape: "cone",
    sizeFt: 15,
    originSelf: true,
    damageDiceBase: "3d6",
    damageType: "fire",
    isAttackRoll: false,
    saveAbility: "DEX",
    upcastRule: "使用2环或更高法术位时，每高1环伤害增加 1d6",
    description: "双手张开喷涌出一道 15 尺扇形锥状烈焰，区域内生物敏捷豁免失败承受 3d6 火焰伤害（成功半伤）。",
    vfx: "fire",
  },
  {
    id: "healing_word",
    name: "治愈真言",
    nameEn: "Healing Word",
    level: 1,
    school: "塑能",
    castTime: "附赠动作",
    rangeFt: 60,
    shape: "single",
    damageDiceBase: "1d4+3",
    damageType: "healing",
    isAttackRoll: false,
    upcastRule: "使用2环或更高法术位时，每高1环治疗量增加 1d4",
    description: "以轻柔祷言治愈射程内的一名可见生物，回复 1d4 + 关键施法属性调整值的生命值。",
    vfx: "smite",
  },
  {
    id: "scorching_ray",
    name: "灼热射线",
    nameEn: "Scorching Ray",
    level: 2,
    school: "塑能",
    castTime: "1动作",
    rangeFt: 120,
    shape: "single",
    damageDiceBase: "2d6",
    damageType: "fire",
    isAttackRoll: true,
    upcastRule: "使用3环或更高法术位时，每高1环便多创造 1 条炽热射线",
    description: "射出 3 道炽热的光束，为每道光束独立进行远程法术攻击，命中造成 2d6 火焰伤害。",
    vfx: "fire",
  },
  {
    id: "shatter",
    name: "碎击波",
    nameEn: "Shatter",
    level: 2,
    school: "塑能",
    castTime: "1动作",
    rangeFt: 60,
    shape: "sphere",
    sizeFt: 10,
    damageDiceBase: "3d8",
    damageType: "thunder",
    isAttackRoll: false,
    saveAbility: "CON",
    upcastRule: "使用3环或更高法术位时，每高1环伤害增加 1d8",
    description: "在射程内指定点爆发出刺耳高频音波（10尺半径球体），造成 3d8 雷鸣伤害，对无机物材质格外致命。",
    vfx: "shockwave",
  },
  {
    id: "misty_step",
    name: "迷踪步",
    nameEn: "Misty Step",
    level: 2,
    school: "咒法",
    castTime: "附赠动作",
    rangeFt: 30,
    shape: "single",
    damageDiceBase: "0",
    damageType: "utility",
    isAttackRoll: false,
    upcastRule: "固定2环",
    description: "被银色迷雾包裹并瞬间传送到 30 尺内可见的一处未被占据的空间（可跨越障碍与脱离纠缠）。",
    vfx: "arcane",
  },
  {
    id: "fireball",
    name: "火球术",
    nameEn: "Fireball",
    level: 3,
    school: "塑能",
    castTime: "1动作",
    rangeFt: 150,
    shape: "sphere",
    sizeFt: 20,
    damageDiceBase: "8d6",
    damageType: "fire",
    isAttackRoll: false,
    saveAbility: "DEX",
    upcastRule: "使用4环或更高法术位时，每高1环伤害增加 1d6",
    description: "自指尖射出一枚明亮火星，在目标点（20尺半径球体）猛烈炸开，范围内生物敏捷豁免失败承受 8d6 火焰伤害（成功半伤）。",
    vfx: "fire",
  },
  {
    id: "lightning_bolt",
    name: "闪电束",
    nameEn: "Lightning Bolt",
    level: 3,
    school: "塑能",
    castTime: "1动作",
    rangeFt: 100,
    shape: "line",
    sizeFt: 100,
    originSelf: true,
    damageDiceBase: "8d6",
    damageType: "lightning",
    isAttackRoll: false,
    saveAbility: "DEX",
    upcastRule: "使用4环或更高法术位时，每高1环伤害增加 1d6",
    description: "自自身释放出一条长 100 尺、宽 5 尺的爆裂雷电巨蟒，直线上所有生物敏捷豁免失败承受 8d6 闪电伤害。",
    vfx: "smite",
  },
  {
    id: "hypnotic_pattern",
    name: "催眠图纹",
    nameEn: "Hypnotic Pattern",
    level: 3,
    school: "幻术",
    castTime: "1动作",
    rangeFt: 120,
    shape: "cube",
    sizeFt: 30,
    damageDiceBase: "0",
    damageType: "condition",
    isAttackRoll: false,
    saveAbility: "WIS",
    upcastRule: "固定3环",
    description: "在空中编织出炫丽迷幻的光彩图案（30尺立方体），区域内生物感知豁免失败陷入【魅惑】与【失能】（速度归零）。",
    vfx: "arcane",
  },
];

// ---------------------------------------------------------------------------
// 5e Conditions Metadata & Rules
// ---------------------------------------------------------------------------
export const DND_CONDITIONS = [
  { id: "prone", name: "倒地 (Prone)", icon: "🧎", desc: "攻击者近战具优势，远程具劣势；自身攻击劣势；起身消耗一半移动速度", tone: "warn" as const },
  { id: "poisoned", name: "中毒 (Poisoned)", icon: "🧪", desc: "攻击检定和所有能力检定具有劣势", tone: "danger" as const },
  { id: "frightened", name: "恐慌 (Frightened)", icon: "😨", desc: "不能主动靠近恐惧源；攻击检定和能力检定具有劣势", tone: "danger" as const },
  { id: "restrained", name: "束缚 (Restrained)", icon: "🕸️", desc: "速度为0；自身攻击劣势；针对目标的攻击具有优势；敏捷豁免劣势", tone: "danger" as const },
  { id: "grappled", name: "擒抱 (Grappled)", icon: "🤼", desc: "速度为0；擒抱者移动时可拖动目标", tone: "warn" as const },
  { id: "blinded", name: "目盲 (Blinded)", icon: "👁️‍🗨️", desc: "目标无法看见；针对目标的攻击具优势；目标攻击具劣势；依赖视觉的检定自动失败", tone: "danger" as const },
  { id: "deafened", name: "耳聋 (Deafened)", icon: "🔇", desc: "目标无法听见；依赖听觉的能力检定自动失败", tone: "neutral" as const },
  { id: "charmed", name: "魅惑 (Charmed)", icon: "💖", desc: "不能攻击魅惑者；魅惑者在与该目标的社交检定中具有优势", tone: "neutral" as const },
  { id: "paralyzed", name: "麻痹 (Paralyzed)", icon: "⚡", desc: "失能且无法移动/言语；力量敏捷豁免自动失败；针对目标的攻击具优势；5尺内近战命中直接自动暴击！", tone: "danger" as const },
  { id: "stunned", name: "震慑 (Stunned)", icon: "💫", desc: "失能且无法移动；言语含糊；力量敏捷豁免自动失败；针对目标的攻击具优势", tone: "danger" as const },
  { id: "unconscious", name: "昏迷 (Unconscious)", icon: "💤", desc: "失能、倒地并掉落所持物；力量敏捷豁免自动失败；针对目标的攻击具优势；5尺内近战命中直接自动暴击！", tone: "danger" as const },
  { id: "invisible", name: "隐形 (Invisible)", icon: "👻", desc: "无法被视觉侦测；自身攻击具有优势；针对自身的攻击具有劣势", tone: "ok" as const },
  { id: "incapacitated", name: "失能 (Incapacitated)", icon: "🛑", desc: "不能进行任何动作、附赠动作或反应；无法维持专注", tone: "danger" as const },
  { id: "concentrating", name: "专注 (Concentrating)", icon: "🔮", desc: "正在维持持续性法术；受到伤害需进行体质豁免 (DC 10 或伤害值的一半)", tone: "ai" as const },
  { id: "exhaustion", name: "力竭 (Exhaustion)", icon: "⌛", desc: "等级累加减值（检定劣势、速度减半、攻击豁免劣势等）", tone: "danger" as const },
];

// ---------------------------------------------------------------------------
// 5e 18 Skills Definitions
// ---------------------------------------------------------------------------
export const DND_SKILLS = [
  { id: "athletics", name: "运动 (Athletics)", ability: "STR", desc: "攀爬、跳跃、游泳、擒抱与推撞对决" },
  { id: "acrobatics", name: "体操 (Acrobatics)", ability: "DEX", desc: "走钢丝、特技翻滚、脱离擒抱" },
  { id: "sleight_of_hand", name: "巧手 (Sleight of Hand)", ability: "DEX", desc: "顺手牵羊、隐藏物品、近战缴械" },
  { id: "stealth", name: "隐匿 (Stealth)", ability: "DEX", desc: "潜行、暗中移动、战术躲藏" },
  { id: "arcana", name: "奥秘 (Arcana)", ability: "INT", desc: "回忆魔法知识、法术流派、位面存在" },
  { id: "history", name: "历史 (History)", ability: "INT", desc: "历史事件、古老帝国、贵族家族" },
  { id: "investigation", name: "调查 (Investigation)", ability: "INT", desc: "搜寻隐秘线索、洞察机关破绽" },
  { id: "nature", name: "自然 (Nature)", ability: "INT", desc: "动植物知识、地形、天气与自然规律" },
  { id: "religion", name: "宗教 (Religion)", ability: "INT", desc: "神祇、教派仪式、神圣符号" },
  { id: "animal_handling", name: "驯兽 (Animal Handling)", ability: "WIS", desc: "安抚坐骑、理解动物意图" },
  { id: "insight", name: "洞悉 (Insight)", ability: "WIS", desc: "识破谎言、洞察战术假动作与意图" },
  { id: "medicine", name: "医疗 (Medicine)", ability: "WIS", desc: "战地急救、稳定濒死伤势 (DC 10)" },
  { id: "perception", name: "察觉 (Perception)", ability: "WIS", desc: "侦测周围细节、识破潜伏伏击" },
  { id: "survival", name: "生存 (Survival)", ability: "WIS", desc: "追踪足迹、野外辨位、预知危险" },
  { id: "deception", name: "欺瞒 (Deception)", ability: "CHA", desc: "声东击西、误导敌人、战术佯攻" },
  { id: "intimidation", name: "威吓 (Intimidation)", ability: "CHA", desc: "战吼威压、以气势逼退敌人" },
  { id: "performance", name: "表演 (Performance)", ability: "CHA", desc: "引人注目、分散注意力" },
  { id: "persuasion", name: "说服 (Persuasion)", ability: "CHA", desc: "战地谈判、劝降与调停" },
];

function combatantElevationFt(fighter: Combatant): number {
  const snap = fighter.snapshot_json as Record<string, unknown> | undefined;
  if (!snap) return 0;
  const pos = snap.grid_position as { elevation_ft?: number } | undefined;
  if (pos && typeof pos.elevation_ft === "number") return pos.elevation_ft;
  if (typeof snap.elevation_ft === "number") return snap.elevation_ft;
  if (typeof snap.elevation === "number") return snap.elevation;
  return 0;
}

function combatantGridPosition(fighter: Combatant): [number, number] | null {
  const snap = fighter.snapshot_json as Record<string, unknown> | undefined;
  if (!snap) return null;
  const pos = snap.grid_position as { row?: number; col?: number } | undefined;
  if (pos && typeof pos.row === "number" && typeof pos.col === "number") {
    return [pos.row, pos.col];
  }
  if (typeof snap.row === "number" && typeof snap.col === "number") {
    return [snap.row, snap.col];
  }
  return null;
}

// ---------------------------------------------------------------------------
// 45° 3D Isometric Tactical Grid Component with Elevation & 3D Spell Volume
// ---------------------------------------------------------------------------
function QuickBattleGrid({
  campaignId,
  combatId,
  fighters,
  activeFighterId,
  targeting,
  positions,
  onTargetSelect,
  selectedTargetId,
  vfxEvents,
  onSpawnVfx,
  interactionMode,
  onInteractionModeChange,
  aimPoint,
  onAimPointChange,
  areaKeys,
}: {
  campaignId: string;
  combatId: string;
  fighters: Combatant[];
  activeFighterId: string | null;
  targeting: CombatTargeting | null;
  positions: Record<string, [number, number]>;
  onTargetSelect: (targetId: string) => void;
  selectedTargetId: string;
  vfxEvents: VfxEvent[];
  onSpawnVfx: (event: Omit<VfxEvent, "id">) => void;
  interactionMode: "move" | "target";
  onInteractionModeChange: (mode: "move" | "target") => void;
  aimPoint: GridPoint | null;
  onAimPointChange: (point: GridPoint | null) => void;
  areaKeys: Set<string>;
}): ReactElement {
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const width = 12;
  const height = 10;
  const cellSizeFt = 5;

  const [viewPerspective, setViewPerspective] = useState<"iso-3d" | "high-3d" | "flat-2d">("iso-3d");
  const [selectedTokenId, setSelectedTokenId] = useState<string>(activeFighterId ?? "");
  const [showEnemyThreat, setShowEnemyThreat] = useState<boolean>(true);
  const [pings, setPings] = useState<Array<{ id: string; row: number; col: number }>>([]);

  const activeFighter = useMemo(() => fighters.find((f) => f.id === activeFighterId) ?? null, [fighters, activeFighterId]);
  const activePos = activeFighter ? positions[activeFighter.id] : null;
  const activePosition: GridPoint | null = activePos ? { row: activePos[0], col: activePos[1] } : null;

  const selectedFighter = useMemo(() => fighters.find((f) => f.id === selectedTokenId) ?? activeFighter, [fighters, selectedTokenId, activeFighter]);
  const selectedPos = selectedFighter ? positions[selectedFighter.id] : null;
  const selectedRemaining = selectedFighter?.movement_remaining_ft ?? selectedFighter?.speed_ft ?? 30;

  // Calculate Enemy Threat Ranges
  const enemyThreatCells = useMemo(() => {
    if (!showEnemyThreat) return { meleeKeys: new Set<string>(), rangedKeys: new Set<string>() };
    const meleeKeys = new Set<string>();
    const rangedKeys = new Set<string>();

    const enemies = fighters.filter((f) => f.entity_type === "monster" && (f.hp ?? 0) > 0);
    enemies.forEach((enemy) => {
      const pos = positions[enemy.id];
      if (!pos) return;

      for (let r = 1; r <= height; r++) {
        for (let c = 1; c <= width; c++) {
          const dist = gridDistanceFt({ row: pos[0], col: pos[1] }, { row: r, col: c }, cellSizeFt);
          if (dist <= 5) {
            meleeKeys.add(`${r}:${c}`);
          } else if (dist <= 30) {
            rangedKeys.add(`${r}:${c}`);
          }
        }
      }
    });

    return { meleeKeys, rangedKeys };
  }, [fighters, positions, showEnemyThreat, height, width, cellSizeFt]);

  // Adjust Elevation Mutation
  const adjustElevationMutation = useMutation({
    mutationFn: async ({ fighter, deltaFt }: { fighter: Combatant; deltaFt: number }) => {
      const curElev = combatantElevationFt(fighter);
      const nextElev = Math.max(0, curElev + deltaFt);
      const snapshot = {
        ...(fighter.snapshot_json as Record<string, unknown> | undefined),
        elevation_ft: nextElev,
        grid_position: {
          ...((fighter.snapshot_json as Record<string, unknown> | undefined)?.grid_position as Record<string, unknown> | undefined),
          elevation_ft: nextElev,
        },
      };
      return updateCombatant(
        campaignId,
        combatId,
        fighter.id,
        { snapshot_json: snapshot },
        fighter.version,
      );
    },
    onSuccess: (_data, vars) => {
      soundboard.playDiceRoll();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast(`🏔️ ${vars.fighter.display_name} 高度已调整！`, "success");
    },
  });

  // Move token mutation with movement dust VFX
  const moveMutation = useMutation({
    mutationFn: async ({ fighter, newRow, newCol, spentFt }: { fighter: Combatant; newRow: number; newCol: number; spentFt: number }) => {
      const nextRemaining = Math.max(0, (fighter.movement_remaining_ft ?? fighter.speed_ft ?? 30) - spentFt);
      const snapshot = {
        ...(fighter.snapshot_json as Record<string, unknown> | undefined),
        grid_position: {
          ...((fighter.snapshot_json as Record<string, unknown> | undefined)?.grid_position as Record<string, unknown> | undefined),
          row: newRow,
          col: newCol,
        },
        row: newRow,
        col: newCol,
      };

      onSpawnVfx({ row: newRow, col: newCol, type: "dust", text: `-${spentFt}尺` });

      return updateCombatant(
        campaignId,
        combatId,
        fighter.id,
        {
          movement_remaining_ft: nextRemaining,
          snapshot_json: snapshot,
        },
        fighter.version,
      );
    },
    onSuccess: () => {
      soundboard.playDiceRoll();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast("🏃 单位已移动并扣减移动力！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "移动失败", "error");
    },
  });

  const triggerPing = (row: number, col: number) => {
    soundboard.playPing();
    const id = `${Date.now()}-${Math.random()}`;
    setPings((prev) => [...prev, { id, row, col }]);
    showToast(`📍 战术信号已发送至 (${row}, ${col})`, "info");
    setTimeout(() => {
      setPings((prev) => prev.filter((p) => p.id !== id));
    }, 2400);
  };

  return (
    <div className="rounded-xl border border-ink-800 bg-ink-950/80 p-3 shadow-2xl">
      {/* Grid 3D Toolbar & Perspective Controls */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-2xs">
        <div className="flex flex-wrap items-center gap-2">
          <strong className="text-stone-200">⚔️ 3D 战术立体战场 ({width}×{height})</strong>
          <span className="text-stone-500">每格 5 尺</span>
          {interactionMode === "move" && selectedFighter ? (
            <span className="rounded bg-emerald-950/60 border border-emerald-700/50 px-2 py-0.5 text-emerald-300 font-medium animate-pulse">
              🏃 移动模式已就绪：剩余移动力 {selectedRemaining} 尺 (可移动 {Math.floor(selectedRemaining / 5)} 格)
            </span>
          ) : null}
          {targeting ? (
            <span className="rounded bg-fuchsia-950/60 border border-fuchsia-700/50 px-2 py-0.5 text-fuchsia-300 font-medium animate-pulse">
              🔮 3D 施法指示：{targeting.label} ({targeting.rangeFt}尺射程 · 形状: {targeting.shape}{targeting.sizeFt ? ` ${targeting.sizeFt}尺` : ""})
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          {/* 3D Perspective Switcher */}
          <div className="flex rounded-lg border border-ink-700 bg-ink-900 p-0.5">
            <button
              className={`rounded px-2 py-1 text-2xs transition ${viewPerspective === "iso-3d" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setViewPerspective("iso-3d")}
              type="button"
            >
              📐 45°等轴 3D
            </button>
            <button
              className={`rounded px-2 py-1 text-2xs transition ${viewPerspective === "high-3d" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setViewPerspective("high-3d")}
              type="button"
            >
              🦅 俯角 3D
            </button>
            <button
              className={`rounded px-2 py-1 text-2xs transition ${viewPerspective === "flat-2d" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setViewPerspective("flat-2d")}
              type="button"
            >
              🗺️ 2D 平面
            </button>
          </div>

          <button
            className={`rounded border px-2 py-1 text-2xs transition ${
              showEnemyThreat
                ? "border-rose-600 bg-rose-950/60 text-rose-200 font-bold"
                : "border-ink-700 bg-ink-900 text-stone-400 hover:text-stone-200"
            }`}
            onClick={() => setShowEnemyThreat(!showEnemyThreat)}
            type="button"
          >
            👹 敌方威胁: {showEnemyThreat ? "开" : "关"}
          </button>

          <div className="flex rounded-lg border border-ink-700 bg-ink-900 p-0.5">
            <button
              className={`rounded px-2.5 py-1 text-2xs transition ${interactionMode === "move" ? "bg-emerald-600 font-bold text-emerald-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => onInteractionModeChange("move")}
              type="button"
            >
              🏃 移动模式
            </button>
            <button
              className={`rounded px-2.5 py-1 text-2xs transition ${interactionMode === "target" ? "bg-fuchsia-600 font-bold text-fuchsia-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => onInteractionModeChange("target")}
              type="button"
            >
              🔮 施法瞄准
            </button>
          </div>
        </div>
      </div>

      {/* Selected Token Elevation Adjuster & High Ground Banner */}
      {selectedFighter ? (
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ink-700/60 bg-ink-900/80 px-3 py-1.5 text-2xs">
          <div className="flex items-center gap-2">
            <span className="text-stone-400">当前选定单位:</span>
            <strong className="text-parchment-100">{selectedFighter.display_name}</strong>
            <span className="rounded bg-ink-950 px-2 py-0.5 font-mono text-amber-300 font-bold border border-ink-800">
              🏔️ 拔高/飞行高度: {combatantElevationFt(selectedFighter)} 尺
            </span>
            {combatantElevationFt(selectedFighter) > 0 ? (
              <Badge tone="ok">高地优势 (+2远程命中/俯视射程)</Badge>
            ) : null}
          </div>

          <div className="flex items-center gap-1">
            <span className="text-stone-400">调整高度:</span>
            <button
              className="rounded border border-ink-700 bg-ink-950 px-2 py-0.5 text-2xs text-stone-300 hover:border-amber-500 hover:text-amber-200"
              onClick={() => adjustElevationMutation.mutate({ fighter: selectedFighter, deltaFt: -5 })}
              type="button"
            >
              ⬇️ -5尺
            </button>
            <button
              className="rounded border border-amber-600/70 bg-amber-950/40 px-2 py-0.5 text-2xs font-bold text-amber-200 hover:bg-amber-900/50"
              onClick={() => adjustElevationMutation.mutate({ fighter: selectedFighter, deltaFt: 5 })}
              type="button"
            >
              ⬆️ +5尺高地/飞行
            </button>
          </div>
        </div>
      ) : null}

      {/* 3D Perspective Stage Container */}
      <div className="perspective-stage overflow-hidden rounded-xl border border-ink-800 bg-gradient-to-b from-ink-950 via-[#07090d] to-ink-950 p-4 py-8">
        <div
          className={`grid gap-1 min-w-[560px] mx-auto ${
            viewPerspective === "iso-3d"
              ? "grid-3d-iso"
              : viewPerspective === "high-3d"
                ? "grid-3d-high"
                : "grid-2d-flat"
          }`}
          style={{ gridTemplateColumns: `repeat(${width}, minmax(40px, 1fr))` }}
        >
          {Array.from({ length: height }, (_, r) =>
            Array.from({ length: width }, (_, c) => {
              const row = r + 1;
              const col = c + 1;
              const point = { row, col };
              const cellKey = `${row}:${col}`;
              const fighter = fighters.find((f) => positions[f.id]?.[0] === row && positions[f.id]?.[1] === col);
              const isSelected = selectedTokenId === fighter?.id;
              const isActive = activeFighterId === fighter?.id;
              const isTarget = selectedTargetId === fighter?.id;

              // Enemy Threat Highlight
              const isEnemyMeleeThreat = enemyThreatCells.meleeKeys.has(cellKey);
              const isEnemyRangedThreat = enemyThreatCells.rangedKeys.has(cellKey);

              // Movement reachability
              const distFromSelected = selectedPos
                ? gridDistanceFt({ row: selectedPos[0], col: selectedPos[1] }, point, cellSizeFt)
                : null;
              const canMoveHere = interactionMode === "move" && selectedFighter && !fighter && distFromSelected !== null && distFromSelected <= selectedRemaining;

              // Targeting reachability
              const inCastRange = targeting && activePosition
                ? isAimPointInRange(activePosition, point, targeting.rangeFt, cellSizeFt)
                : false;
              const isAreaAffected = areaKeys.has(cellKey);
              const hasPing = pings.some((p) => p.row === row && p.col === col);
              const activeVfx = vfxEvents.filter((v) => v.row === row && v.col === col);

              const fighterElevFt = fighter ? combatantElevationFt(fighter) : 0;

              return (
                <button
                  className={`relative aspect-square rounded border p-0.5 text-2xs transition-all duration-200 ${
                    canMoveHere
                      ? "bg-emerald-950/60 border-emerald-500/70 shadow-[0_0_12px_rgba(16,185,129,0.3)] hover:bg-emerald-900/70 cursor-pointer"
                      : ""
                  } ${inCastRange && interactionMode === "target" ? "bg-sky-950/50 border-sky-500/50" : ""} ${
                    isAreaAffected && interactionMode === "target"
                      ? "!bg-fuchsia-950/80 !border-fuchsia-400 !shadow-[0_0_16px_rgba(217,70,239,0.6)]"
                      : ""
                  } ${
                    !canMoveHere && !inCastRange && isEnemyMeleeThreat
                      ? "bg-rose-950/40 border-rose-700/60 shadow-[inset_0_0_8px_rgba(225,29,72,0.4)]"
                      : ""
                  } ${
                    !canMoveHere && !inCastRange && !isEnemyMeleeThreat && isEnemyRangedThreat
                      ? "bg-amber-950/20 border-amber-800/30"
                      : "border-ink-800/80 bg-ink-900/70 hover:bg-ink-800/60"
                  } ${fighter ? "cursor-pointer" : ""}`}
                  key={`${row}-${col}`}
                  onClick={() => {
                    if (fighter) {
                      setSelectedTokenId(fighter.id);
                      onTargetSelect(fighter.id);
                    } else if (canMoveHere && selectedFighter && distFromSelected !== null) {
                      moveMutation.mutate({
                        fighter: selectedFighter,
                        newRow: row,
                        newCol: col,
                        spentFt: distFromSelected,
                      });
                    }
                    if (interactionMode === "target" && inCastRange) {
                      onAimPointChange(point);
                    }
                  }}
                  onDoubleClick={(e) => {
                    e.preventDefault();
                    triggerPing(row, col);
                  }}
                  style={{
                    transform: viewPerspective !== "flat-2d" && fighterElevFt > 0 ? `translateY(-${fighterElevFt * 1.8}px)` : undefined,
                  }}
                  title={
                    fighter
                      ? `${fighter.display_name} (HP: ${fighter.hp}/${fighter.max_hp}, 高度: ${fighterElevFt}尺)`
                      : canMoveHere
                        ? `坐标 (${row}, ${col}) · 移动距离: ${distFromSelected} 尺 (消耗 ${distFromSelected} 尺移动力)`
                        : isEnemyMeleeThreat
                          ? `坐标 (${row}, ${col}) · ⚠️ 敌方近战借机区 (5尺)`
                          : `坐标 (${row}, ${col})`
                  }
                  type="button"
                >
                  {/* 3D Volumetric Area of Effect (AoE) Extrusion Column */}
                  {isAreaAffected && interactionMode === "target" ? (
                    <div className="aoe-3d-volume flex items-center justify-center">
                      <span className="font-bold text-[8px] text-fuchsia-200 drop-shadow">3D AOE</span>
                    </div>
                  ) : null}

                  {/* Ping Animation Waves */}
                  {hasPing ? (
                    <span className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center">
                      <span className="absolute h-8 w-8 rounded-full border-2 border-amber-400 bg-amber-400/30 animate-ping" />
                      <span className="absolute h-3 w-3 rounded-full bg-amber-300 shadow-[0_0_8px_rgba(251,191,36,1)]" />
                    </span>
                  ) : null}

                  {/* Combat Visual Effects */}
                  {activeVfx.map((vfx) => (
                    <span className="pointer-events-none absolute inset-0 z-40 flex items-center justify-center overflow-visible" key={vfx.id}>
                      {vfx.type === "slash" ? (
                        <span className="absolute h-10 w-2.5 rounded-full bg-gradient-to-t from-red-600 via-amber-400 to-white animate-vfx-slash shadow-[0_0_15px_#f59e0b]" />
                      ) : null}

                      {vfx.type === "arcane" ? (
                        <span className="absolute h-8 w-8 rounded-full bg-gradient-to-r from-fuchsia-500 to-purple-600 animate-vfx-arcane-dart shadow-[0_0_20px_#d946ef]" />
                      ) : null}

                      {vfx.type === "shockwave" ? (
                        <span className="absolute h-12 w-12 rounded-full border-4 border-sky-400 bg-sky-500/20 animate-vfx-shockwave" />
                      ) : null}

                      {vfx.type === "smite" ? (
                        <span className="absolute h-16 w-3 rounded bg-gradient-to-b from-amber-200 via-yellow-400 to-amber-600 animate-vfx-smite shadow-[0_0_25px_#fef08a]" />
                      ) : null}

                      {vfx.type === "dust" ? (
                        <span className="absolute h-8 w-8 rounded-full border border-emerald-400/60 bg-emerald-400/20 animate-token-dust" />
                      ) : null}

                      {vfx.text ? (
                        <span
                          className={`absolute font-black font-mono text-xs drop-shadow-[0_2px_4px_rgba(0,0,0,1)] animate-float-combat-text ${
                            vfx.isCrit
                              ? "text-amber-300 text-sm scale-125"
                              : vfx.isMiss
                                ? "text-stone-400"
                                : "text-rose-400"
                          }`}
                        >
                          {vfx.text}
                        </span>
                      ) : null}
                    </span>
                  ))}

                  {/* Move Range Highlight Dot & Distance indicator */}
                  {canMoveHere && !fighter ? (
                    <span className="absolute inset-0 flex flex-col items-center justify-center">
                      <span className="h-2 w-2 rounded-full bg-emerald-400/80 shadow-[0_0_6px_#34d399]" />
                      <span className="text-[7px] font-mono text-emerald-300 font-bold">{distFromSelected}尺</span>
                    </span>
                  ) : null}

                  {/* 3D Elevated Token with Drop Shadow */}
                  {fighter ? (
                    <>
                      {fighterElevFt > 0 && viewPerspective !== "flat-2d" ? (
                        <div className="token-shadow" style={{ transform: `scale(${Math.max(0.4, 1 - fighterElevFt * 0.02)})` }} />
                      ) : null}

                      <div
                        className={`token-smooth-move relative flex h-full w-full flex-col items-center justify-center rounded-lg p-0.5 text-center leading-none shadow-lg transition-all ${
                          isActive
                            ? "ring-2 ring-amber-400 bg-gradient-to-br from-amber-500/40 to-ink-900"
                            : isTarget
                              ? "ring-2 ring-emerald-400 bg-emerald-950/70"
                              : isSelected
                                ? "ring-1 ring-sky-400 bg-sky-950/50"
                                : fighter.entity_type === "character"
                                  ? "bg-sky-950/70 border border-sky-600/60"
                                  : fighter.entity_type === "npc"
                                    ? "bg-violet-950/70 border border-violet-600/60"
                                    : "bg-red-950/70 border border-red-600/60"
                        }`}
                        style={{
                          transform: viewPerspective !== "flat-2d" && fighterElevFt > 0 ? `translateY(-${fighterElevFt * 1.5}px)` : undefined,
                        }}
                      >
                        <span className="truncate font-bold text-[10px] text-parchment-100 drop-shadow">
                          {fighter.display_name?.slice(0, 3)}
                        </span>
                        <span className="mt-0.5 text-[8px] font-mono text-stone-300">
                          {fighter.hp}/{fighter.max_hp}
                        </span>
                        {fighterElevFt > 0 ? (
                          <span className="mt-0.5 rounded bg-amber-400/90 px-1 text-[7px] font-black text-amber-950">
                            ▲{fighterElevFt}尺
                          </span>
                        ) : null}
                        {fighter.conditions && fighter.conditions.length > 0 ? (
                          <span className="mt-0.5 text-[7px] text-amber-300 font-bold">
                            {fighter.conditions[0].slice(0, 2)}
                          </span>
                        ) : null}
                      </div>
                    </>
                  ) : null}
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Quick Combat Cockpit Page
// ---------------------------------------------------------------------------
function QuickCombatCockpit({ campaignId }: { campaignId: string }): ReactElement {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { selectCampaign } = useCurrentCampaign();

  const [selectedCombatId, setSelectedCombatId] = useState<string>("");
  const [selectedMapTargetId, setSelectedMapTargetId] = useState<string>("");
  const [gridInteractionMode, setGridInteractionMode] = useState<"move" | "target">("move");
  const [aimPoint, setAimPoint] = useState<GridPoint | null>(null);

  const [targetingRange, setTargetingRange] = useState<CombatTargeting | null>(null);
  const [targetingActorId, setTargetingActorId] = useState<string | null>(null);
  const [autoEnemies, setAutoEnemies] = useState<boolean>(false);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [showAddCombatantModal, setShowAddCombatantModal] = useState<boolean>(false);

  // Visual Effects (VFX) Queue
  const [vfxEvents, setVfxEvents] = useState<VfxEvent[]>([]);

  const spawnVfx = useCallback((event: Omit<VfxEvent, "id">) => {
    const id = `${Date.now()}-${Math.random()}`;
    setVfxEvents((prev) => [...prev, { ...event, id }]);
    setTimeout(() => {
      setVfxEvents((prev) => prev.filter((e) => e.id !== id));
    }, 1200);
  }, []);

  // Active Tab for Quick Actions HUD
  const [activeHudTab, setActiveHudTab] = useState<"actions" | "spells" | "skills" | "features" | "conditions">("spells");

  // Spell Casting Engine States
  const [selectedSpell, setSelectedSpell] = useState<CombatSpellOption | null>(DND_TEST_SPELLS[0]);
  const [selectedSpellLevel, setSelectedSpellLevel] = useState<number>(0);
  const [spellLevelFilter, setSpellLevelFilter] = useState<"all" | 0 | 1 | 2 | 3>("all");
  const [spellSearchTerm, setSpellSearchTerm] = useState<string>("");

  // New combatant form
  const [newCombatantName, setNewCombatantName] = useState<string>("");
  const [newCombatantType, setNewCombatantType] = useState<"character" | "monster" | "npc">("monster");
  const [newCombatantHp, setNewCombatantHp] = useState<string>("12");
  const [newCombatantAc, setNewCombatantAc] = useState<string>("14");
  const [newCombatantInit, setNewCombatantInit] = useState<string>("10");

  // Interactive Dice Prompt / Action HUD States
  const [actionPromptOpen, setActionPromptOpen] = useState<boolean>(false);
  const [promptActionName, setPromptActionName] = useState<string>("近战武器攻击");
  const [promptTargetId, setPromptTargetId] = useState<string>("");
  const [promptAttackMod, setPromptAttackMod] = useState<string>("4");
  const [promptDamageDice, setPromptDamageDice] = useState<string>("1d8+2");
  const [promptDamageType, setPromptDamageType] = useState<string>("slashing");
  const [isMeleeAttack, setIsMeleeAttack] = useState<boolean>(true);
  const [manualAttackRoll, setManualAttackRoll] = useState<string>("");
  const [manualDamageRoll, setManualDamageRoll] = useState<string>("");
  const [isManualCrit, setIsManualCrit] = useState<boolean>(false);

  // Magic Missile Multi-Target Distribution state
  const [magicMissileModalOpen, setMagicMissileModalOpen] = useState<boolean>(false);
  const [dartAllocations, setDartAllocations] = useState<Record<string, number>>({});

  // Skill Check Modal state
  const [skillCheckMod, setSkillCheckMod] = useState<string>("3");
  const [skillCheckResult, setSkillCheckResult] = useState<string>("");

  // Dice Roller states
  const [diceHistory, setDiceHistory] = useState<Array<{ id: string; formula: string; result: number; rolls: number[]; isCrit?: boolean; isFumble?: boolean }>>([]);
  const [customDiceMod, setCustomDiceMod] = useState<string>("3");

  // AI Guidance states
  const [aiAnalysis, setAiAnalysis] = useState<string>("");
  const [aiNarrative, setAiNarrative] = useState<string>("");

  // Queries
  const campaignsQuery = useQuery({
    queryKey: ["campaigns"],
    queryFn: ({ signal }) => listCampaigns(signal),
  });

  const combatsQuery = useQuery({
    queryKey: ["combats", campaignId],
    queryFn: ({ signal }) => listCombats(campaignId, signal),
  });

  const activeCombat = useMemo(() => {
    const list = combatsQuery.data ?? [];
    if (selectedCombatId) return list.find((c) => c.id === selectedCombatId) ?? list[0] ?? null;
    return list.find((c) => c.status === "active") ?? list[0] ?? null;
  }, [combatsQuery.data, selectedCombatId]);

  const combatId = activeCombat?.id ?? "";

  const combatantsQuery = useQuery({
    queryKey: ["combatants", campaignId, combatId],
    queryFn: ({ signal }) => (combatId ? listCombatants(campaignId, combatId, signal) : Promise.resolve([])),
    enabled: Boolean(combatId),
    refetchInterval: 3000,
  });

  const actionsQuery = useQuery({
    queryKey: ["combat-actions", campaignId, combatId],
    queryFn: ({ signal }) => (combatId ? listCombatActions(campaignId, combatId, signal) : Promise.resolve([])),
    enabled: Boolean(combatId),
    refetchInterval: 3000,
  });

  const charactersQuery = useQuery({
    queryKey: ["characters", campaignId],
    queryFn: ({ signal }) => listCharacters(campaignId, signal),
  });

  // Ordered combatants
  const ordered = useMemo(() => {
    const items = [...(combatantsQuery.data ?? [])];
    return items.sort((a, b) => (b.initiative ?? 0) - (a.initiative ?? 0));
  }, [combatantsQuery.data]);

  // Positions map
  const positions = useMemo(() => {
    const map: Record<string, [number, number]> = {};
    ordered.forEach((f, i) => {
      const pos = combatantGridPosition(f);
      if (pos) {
        map[f.id] = pos;
      } else {
        const isPlayer = f.entity_type === "character";
        const row = isPlayer ? Math.floor(i / 3) + 2 : Math.floor(i / 3) + 2;
        const col = isPlayer ? (i % 3) + 2 : 11 - (i % 3);
        map[f.id] = [row, col];
      }
    });
    return map;
  }, [ordered]);

  // Active Fighter
  const activeFighter = useMemo(() => {
    if (!ordered.length) return null;
    const index = (activeCombat?.current_turn_index ?? activeCombat?.active_combatant_index ?? 0) % ordered.length;
    return ordered[index] ?? ordered[0] ?? null;
  }, [ordered, activeCombat?.current_turn_index, activeCombat?.active_combatant_index]);

  const activePos = activeFighter ? positions[activeFighter.id] : null;
  const activePosition: GridPoint | null = useMemo(() => (activePos ? { row: activePos[0], col: activePos[1] } : null), [activePos]);

  const activeCharacter = useMemo(() => {
    if (!activeFighter || activeFighter.entity_type !== "character") return undefined;
    return (charactersQuery.data ?? []).find((c) => c.id === activeFighter.entity_id);
  }, [activeFighter, charactersQuery.data]);

  // Target Combatant for Action Prompt
  const promptTargetCombatant = useMemo(() => {
    return ordered.find((f) => f.id === (promptTargetId || selectedMapTargetId)) ?? ordered.find((f) => f.id !== activeFighter?.id) ?? null;
  }, [ordered, promptTargetId, selectedMapTargetId, activeFighter]);

  // Calculate targeting area cells purely
  const areaCells = useMemo(() => {
    if (!targetingRange || !activePosition) return [];
    const tacticalGrid: SceneGrid = { width: 12, height: 10, cell_size_ft: 5, cells: [], spawn_zones: [], theme: "dungeon" };
    return getTargetingCells(tacticalGrid, activePosition, aimPoint ?? activePosition, targetingRange);
  }, [targetingRange, activePosition, aimPoint]);

  const areaKeys = useMemo(() => new Set(areaCells.map((c) => `${c.row}:${c.col}`)), [areaCells]);

  // Pure derived targeting validity - NO infinite useEffect loop!
  const targetingValidity = useMemo<CombatTargetingValidity>(() => {
    if (!targetingRange || !activePosition) {
      return {
        anchorPoint: null,
        horizontalTargetIds: new Set(),
        validTargetIds: new Set(),
        missingElevationTargetIds: new Set(),
      };
    }
    const horizontalTargetIds = new Set<string>();
    const validTargetIds = new Set<string>();
    const missingElevationTargetIds = new Set<string>();

    ordered.forEach((f) => {
      if (f.id === (targetingActorId ?? activeFighter?.id) || (f.hp ?? 0) <= 0) return;
      const pos = positions[f.id];
      if (!pos) return;
      const key = `${pos[0]}:${pos[1]}`;
      const inArea = targetingRange.shape === "single"
        ? isAimPointInRange(activePosition, { row: pos[0], col: pos[1] }, targetingRange.rangeFt, 5)
        : areaKeys.has(key);

      if (!inArea) return;
      horizontalTargetIds.add(f.id);
      validTargetIds.add(f.id);
    });

    return {
      anchorPoint: aimPoint ?? (targetingRange.originSelf ? activePosition : null),
      horizontalTargetIds,
      validTargetIds,
      missingElevationTargetIds,
    };
  }, [targetingRange, activePosition, aimPoint, ordered, positions, targetingActorId, activeFighter?.id, areaKeys]);

  const handleRangeChange = useCallback((range: CombatTargeting | null, actorId?: string | null) => {
    setTargetingRange((prev) => {
      if (!range && !prev) return prev;
      if (
        range &&
        prev &&
        range.label === prev.label &&
        range.rangeFt === prev.rangeFt &&
        range.shape === prev.shape &&
        range.sizeFt === prev.sizeFt &&
        range.originSelf === prev.originSelf
      ) {
        return prev;
      }
      return range;
    });
    setTargetingActorId((prev) => (prev === (actorId ?? null) ? prev : (actorId ?? null)));
  }, []);

  const handleTargetChange = useCallback((id: string) => {
    setSelectedMapTargetId((prev) => (prev === id ? prev : id));
    setPromptTargetId((prev) => (prev === id ? prev : id));
  }, []);

  // Filtered spells catalog
  const filteredSpells = useMemo(() => {
    return DND_TEST_SPELLS.filter((spell) => {
      const matchLevel = spellLevelFilter === "all" || spell.level === spellLevelFilter;
      const matchSearch = !spellSearchTerm.trim()
        || spell.name.includes(spellSearchTerm.trim())
        || spell.nameEn.toLowerCase().includes(spellSearchTerm.trim().toLowerCase())
        || spell.description.includes(spellSearchTerm.trim());
      return matchLevel && matchSearch;
    });
  }, [spellLevelFilter, spellSearchTerm]);

  // Derive Advantage / Disadvantage based on conditions
  const attackAdvantageState = useMemo(() => {
    if (!activeFighter || !promptTargetCombatant) return { hasAdvantage: false, hasDisadvantage: false, reasons: [] as string[] };
    const reasons: string[] = [];
    let hasAdv = false;
    let hasDis = false;

    const targetConds = promptTargetCombatant.conditions ?? [];
    const attackerConds = activeFighter.conditions ?? [];

    if (targetConds.includes("prone")) {
      if (isMeleeAttack) {
        hasAdv = true;
        reasons.push("目标倒地：近战攻击具有优势 (Advantage)");
      } else {
        hasDis = true;
        reasons.push("目标倒地：远程攻击具有劣势 (Disadvantage)");
      }
    }
    if (targetConds.some((c) => ["paralyzed", "unconscious", "stunned", "restrained"].includes(c))) {
      hasAdv = true;
      reasons.push("目标处于限制/失能状态：攻击具有优势");
    }
    if (attackerConds.includes("invisible")) {
      hasAdv = true;
      reasons.push("攻击者处于隐形/潜伏：攻击具有优势");
    }
    if (attackerConds.some((c) => ["poisoned", "blinded", "prone"].includes(c))) {
      hasDis = true;
      reasons.push("自身处于负面状态：攻击具有劣势");
    }

    return { hasAdvantage: hasAdv && !hasDis, hasDisadvantage: hasDis && !hasAdv, reasons };
  }, [activeFighter, promptTargetCombatant, isMeleeAttack]);

  // Advance Turn mutation
  const advanceTurnMutation = useMutation({
    mutationFn: async () => {
      if (!activeCombat) throw new Error("没有活跃的战斗");
      return advanceCombatTurn(campaignId, activeCombat.id, activeCombat.version);
    },
    onSuccess: () => {
      soundboard.playDiceRoll();
      void queryClient.invalidateQueries({ queryKey: ["combats", campaignId] });
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast("⏭️ 已进入下一战斗员回合！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "推进回合失败", "error");
    },
  });

  // Quick Roll All Initiatives
  const rollInitiativesMutation = useMutation({
    mutationFn: async () => {
      if (!ordered.length) return;
      for (const combatant of ordered) {
        const d20 = Math.floor(Math.random() * 20) + 1;
        const dexMod = Math.floor(((combatant.armor_class ?? 10) - 10) / 2);
        const total = d20 + dexMod;
        await updateCombatant(
          campaignId,
          combatId,
          combatant.id,
          { initiative: total },
          combatant.version,
        );
      }
    },
    onSuccess: () => {
      soundboard.playDiceRoll();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast("🎲 全员先攻已重新投掷并排序！", "success");
    },
  });

  // Toggle condition mutation
  const toggleConditionMutation = useMutation({
    mutationFn: async ({ combatant, conditionId }: { combatant: Combatant; conditionId: string }) => {
      const current = combatant.conditions ?? [];
      const hasIt = current.includes(conditionId);
      const nextConditions = hasIt ? current.filter((c) => c !== conditionId) : [...current, conditionId];
      return updateCombatant(
        campaignId,
        combatId,
        combatant.id,
        { conditions: nextConditions },
        combatant.version,
      );
    },
    onSuccess: (_data, vars) => {
      const current = vars.combatant.conditions ?? [];
      const isAdd = !current.includes(vars.conditionId);
      if (isAdd) soundboard.playHandout();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast(`🏷️ ${vars.combatant.display_name} 已${isAdd ? "获得状态" : "解除状态"}：${vars.conditionId}`, "info");
    },
  });

  // Quick HP adjust mutation
  const quickHpAdjustMutation = useMutation({
    mutationFn: async ({ combatant, delta }: { combatant: Combatant; delta: number }) => {
      const currentHp = combatant.hp ?? 0;
      const maxHp = combatant.max_hp ?? 10;
      const newHp = Math.max(0, Math.min(maxHp, currentHp + delta));
      const pos = combatantGridPosition(combatant) ?? [3, 3];

      spawnVfx({
        row: pos[0],
        col: pos[1],
        type: delta < 0 ? "slash" : "dust",
        text: delta > 0 ? `+${delta}` : `${delta}`,
      });

      return updateCombatant(
        campaignId,
        combatId,
        combatant.id,
        { hp: newHp },
        combatant.version,
      );
    },
    onSuccess: (_data, vars) => {
      if (vars.delta < 0) soundboard.playAttackHit();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast(`生命值已调整: ${vars.delta > 0 ? `+${vars.delta}` : vars.delta}`, "success");
    },
  });

  // Cast Selected Spell with Upcast Bonus & 3D AOE Resolution
  const castSelectedSpellMutation = useMutation({
    mutationFn: async () => {
      if (!selectedSpell || !activeFighter) throw new Error("请选定施法者与法术");

      const upcastDelta = Math.max(0, selectedSpellLevel - selectedSpell.level);
      const isAoE = selectedSpell.shape !== "single";
      const affectedTargets = isAoE
        ? ordered.filter((f) => targetingValidity.validTargetIds.has(f.id) && f.id !== activeFighter.id)
        : (promptTargetCombatant ? [promptTargetCombatant] : []);

      if (!affectedTargets.length && selectedSpell.shape === "single") {
        throw new Error("请在地图或列表中选定施法目标");
      }

      let baseDiceCount = 1;
      let dieSides = 8;
      if (selectedSpell.damageDiceBase.includes("8d6")) {
        baseDiceCount = 8 + upcastDelta;
        dieSides = 6;
      } else if (selectedSpell.damageDiceBase.includes("3d6")) {
        baseDiceCount = 3 + upcastDelta;
        dieSides = 6;
      } else if (selectedSpell.damageDiceBase.includes("2d8")) {
        baseDiceCount = 2 + upcastDelta;
        dieSides = 8;
      } else if (selectedSpell.damageDiceBase.includes("3d8")) {
        baseDiceCount = 3 + upcastDelta;
        dieSides = 8;
      } else if (selectedSpell.damageDiceBase.includes("1d10")) {
        baseDiceCount = 1;
        dieSides = 10;
      }

      let rollSum = 0;
      for (let i = 0; i < baseDiceCount; i++) {
        const r = Math.floor(Math.random() * dieSides) + 1;
        rollSum += r;
      }

      for (const target of affectedTargets) {
        const pos = combatantGridPosition(target) ?? [3, 5];
        let dmg = rollSum;
        if (selectedSpell.damageType === "healing") {
          const heal = rollSum + 3;
          const nextHp = Math.min(target.max_hp ?? 20, (target.hp ?? 0) + heal);
          spawnVfx({ row: pos[0], col: pos[1], type: "smite", text: `+${heal}` });
          await updateCombatant(campaignId, combatId, target.id, { hp: nextHp }, target.version);
        } else {
          if ((target.damage_immunities ?? []).includes(selectedSpell.damageType)) dmg = 0;
          else if ((target.damage_resistances ?? []).includes(selectedSpell.damageType)) dmg = Math.floor(dmg / 2);

          const nextHp = Math.max(0, (target.hp ?? 10) - dmg);
          spawnVfx({
            row: pos[0],
            col: pos[1],
            type: selectedSpell.vfx,
            text: `-${dmg} (${selectedSpell.damageType})`,
          });
          await updateCombatant(campaignId, combatId, target.id, { hp: nextHp }, target.version);
        }
      }

      const note = `${activeFighter.display_name} 施放【${selectedSpell.name}】(${selectedSpellLevel === 0 ? "戏法" : `${selectedSpellLevel}环`}) ➔ 覆盖 ${affectedTargets.length} 个目标，造成 ${rollSum} 点 ${selectedSpell.damageType} 效果！`;

      const command: CombatActionCommand = {
        action_type: "spell",
        actor_combatant_id: activeFighter.id,
        actor_version: activeFighter.version,
        action_cost: selectedSpell.castTime.includes("附赠") ? "bonus" : "action",
        action_name: `${selectedSpell.name} (${selectedSpellLevel}环)`,
        amount: rollSum,
        damage_type: selectedSpell.damageType,
        resolution_note: note,
      };

      return confirmCombatAction(campaignId, combatId, command);
    },
    onSuccess: () => {
      soundboard.playAttackHit();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      void queryClient.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
      showToast(`✨ 法术【${selectedSpell?.name}】已成功施展并对目标造成伤害！`, "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "施法失败", "error");
    },
  });

  // 1-Click Auto Resolve Action Mutation
  const autoResolveActionMutation = useMutation({
    mutationFn: async () => {
      if (!activeFighter || !promptTargetCombatant) throw new Error("请选定攻击者与受击目标");
      const attackMod = Number(promptAttackMod) || 0;

      const roll1 = Math.floor(Math.random() * 20) + 1;
      const roll2 = Math.floor(Math.random() * 20) + 1;
      let d20 = roll1;
      let rollDesc = `d20(${roll1})`;
      if (attackAdvantageState.hasAdvantage) {
        d20 = Math.max(roll1, roll2);
        rollDesc = `优势取高(${roll1}, ${roll2}) ➔ ${d20}`;
      } else if (attackAdvantageState.hasDisadvantage) {
        d20 = Math.min(roll1, roll2);
        rollDesc = `劣势取低(${roll1}, ${roll2}) ➔ ${d20}`;
      }

      const attackTotal = d20 + attackMod;
      const isCrit = d20 === 20 || (isMeleeAttack && (promptTargetCombatant.conditions ?? []).some((c) => ["paralyzed", "unconscious"].includes(c)));
      const targetAc = promptTargetCombatant.armor_class ?? 10;
      const isHit = isCrit || attackTotal >= targetAc;
      const targetPos = combatantGridPosition(promptTargetCombatant) ?? [3, 5];

      if (!isHit) {
        soundboard.playDiceRoll();
        spawnVfx({ row: targetPos[0], col: targetPos[1], type: "dust", text: "MISS!", isMiss: true });
        const command: CombatActionCommand = {
          action_type: "damage",
          target_combatant_id: promptTargetCombatant.id,
          target_version: promptTargetCombatant.version,
          actor_combatant_id: activeFighter.id,
          actor_version: activeFighter.version,
          action_cost: "action",
          action_name: promptActionName,
          amount: 0,
          is_attack: true,
          attack_roll_total: attackTotal,
          resolution_note: `${activeFighter.display_name} 发动「${promptActionName}」命中检定 ${rollDesc} + ${attackMod} = ${attackTotal} (vs AC ${targetAc}) ➔ ❌ 未命中！`,
        };
        return confirmCombatAction(campaignId, combatId, command);
      }

      const dieSides = promptDamageDice.includes("d12") ? 12 : promptDamageDice.includes("d10") ? 10 : promptDamageDice.includes("d6") ? 6 : promptDamageDice.includes("d4") ? 4 : 8;
      const baseDamage = Math.floor(Math.random() * dieSides) + 1 + (isCrit ? Math.floor(Math.random() * dieSides) + 1 : 0) + 2;

      const resistances = promptTargetCombatant.damage_resistances ?? [];
      const immunities = promptTargetCombatant.damage_immunities ?? [];
      const vulnerabilities = promptTargetCombatant.damage_vulnerabilities ?? [];
      let finalDamage = baseDamage;
      if (immunities.includes(promptDamageType)) finalDamage = 0;
      else if (resistances.includes(promptDamageType)) finalDamage = Math.floor(baseDamage / 2);
      else if (vulnerabilities.includes(promptDamageType)) finalDamage = baseDamage * 2;

      spawnVfx({
        row: targetPos[0],
        col: targetPos[1],
        type: promptDamageType === "fire" ? "fire" : "slash",
        text: isCrit ? `CRIT! -${finalDamage}` : `-${finalDamage}`,
        isCrit,
      });

      const command: CombatActionCommand = {
        action_type: "damage",
        target_combatant_id: promptTargetCombatant.id,
        target_version: promptTargetCombatant.version,
        actor_combatant_id: activeFighter.id,
        actor_version: activeFighter.version,
        action_cost: "action",
        action_name: promptActionName,
        amount: finalDamage,
        damage_type: promptDamageType,
        is_attack: true,
        attack_roll_total: attackTotal,
        critical_hit: isCrit,
        resolution_note: `${activeFighter.display_name} 发动「${promptActionName}」命中检定 ${rollDesc} + ${attackMod} = ${attackTotal} (vs AC ${targetAc}) ➔ ✅ 命中！造成 ${finalDamage} 点 ${promptDamageType} 伤害${isCrit ? "（💥暴击！）" : ""}${resistances.includes(promptDamageType) ? "（抗性减半）" : ""}`,
      };

      return confirmCombatAction(campaignId, combatId, command);
    },
    onSuccess: () => {
      soundboard.playAttackHit();
      setActionPromptOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      void queryClient.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
      showToast("⚔️ 动作已自动投骰并结算！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "自动结算失败", "error");
    },
  });

  // Magic Missile Multi-Target Split Execution with Arcane VFX
  const executeMagicMissileMutation = useMutation({
    mutationFn: async () => {
      if (!activeFighter) throw new Error("无有效施法者");
      const targetEntries = Object.entries(dartAllocations).filter(([, count]) => count > 0);
      if (!targetEntries.length) throw new Error("请为至少一个目标分配飞弹");

      for (const [targetId, dartCount] of targetEntries) {
        const target = ordered.find((f) => f.id === targetId);
        if (!target) continue;

        let targetTotalDamage = 0;
        const rolls: number[] = [];
        for (let i = 0; i < dartCount; i++) {
          const dmg = Math.floor(Math.random() * 4) + 1 + 1; // 1d4+1
          targetTotalDamage += dmg;
          rolls.push(dmg);
        }

        const nextHp = Math.max(0, (target.hp ?? 10) - targetTotalDamage);
        const pos = combatantGridPosition(target) ?? [3, 5];

        spawnVfx({ row: pos[0], col: pos[1], type: "arcane", text: `-${targetTotalDamage}` });

        await updateCombatant(
          campaignId,
          combatId,
          target.id,
          { hp: nextHp },
          target.version,
        );

        const command: CombatActionCommand = {
          action_type: "damage",
          target_combatant_id: target.id,
          target_version: target.version,
          actor_combatant_id: activeFighter.id,
          actor_version: activeFighter.version,
          action_cost: "action",
          action_name: "魔法飞弹 (Magic Missile)",
          amount: targetTotalDamage,
          damage_type: "force",
          resolution_note: `${activeFighter.display_name} 射出 ${dartCount} 枚「魔法飞弹」击中 ${target.display_name}（自动必中，各 ${rolls.join("+")} 点）➔ 造成 ${targetTotalDamage} 点力场伤害！`,
        };

        await confirmCombatAction(campaignId, combatId, command);
      }
    },
    onSuccess: () => {
      soundboard.playAttackHit();
      setMagicMissileModalOpen(false);
      setDartAllocations({});
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      void queryClient.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
      showToast("🚀 魔法飞弹已发射并分别对目标结算必中力场伤害！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "施法失败", "error");
    },
  });

  // Manual Dice Input Confirmation Mutation (Physical dice input)
  const confirmManualDiceActionMutation = useMutation({
    mutationFn: async () => {
      if (!activeFighter || !promptTargetCombatant) throw new Error("请选定攻击者与受击目标");
      const attackTotal = Number(manualAttackRoll) || 15;
      const targetAc = promptTargetCombatant.armor_class ?? 10;
      const isHit = isManualCrit || attackTotal >= targetAc;
      const dmg = Number(manualDamageRoll) || 0;
      const finalDmg = isHit ? dmg : 0;
      const targetPos = combatantGridPosition(promptTargetCombatant) ?? [3, 5];

      if (isHit) {
        spawnVfx({ row: targetPos[0], col: targetPos[1], type: "slash", text: isManualCrit ? `CRIT! -${finalDmg}` : `-${finalDmg}`, isCrit: isManualCrit });
      } else {
        spawnVfx({ row: targetPos[0], col: targetPos[1], type: "dust", text: "MISS!", isMiss: true });
      }

      const command: CombatActionCommand = {
        action_type: "damage",
        target_combatant_id: promptTargetCombatant.id,
        target_version: promptTargetCombatant.version,
        actor_combatant_id: activeFighter.id,
        actor_version: activeFighter.version,
        action_cost: "action",
        action_name: promptActionName,
        amount: finalDmg,
        damage_type: promptDamageType,
        is_attack: true,
        attack_roll_total: attackTotal,
        critical_hit: isManualCrit,
        resolution_note: `${activeFighter.display_name} 录入实体骰「${promptActionName}」命中检定 ${attackTotal} (vs AC ${targetAc}) ➔ ${isHit ? `✅ 命中！造成 ${finalDmg} 点伤害` : "❌ 未命中"}${isManualCrit ? "（💥暴击！）" : ""}`,
      };

      return confirmCombatAction(campaignId, combatId, command);
    },
    onSuccess: () => {
      soundboard.playAttackHit();
      setActionPromptOpen(false);
      setManualAttackRoll("");
      setManualDamageRoll("");
      setIsManualCrit(false);
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      void queryClient.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
      showToast("✍️ 玩家实体骰结果已应用并结算！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "实体骰应用失败", "error");
    },
  });

  // AI Guidance
  const aiTacticsMutation = useMutation({
    mutationFn: async () => {
      const summary = ordered
        .map((c) => `- ${c.display_name} (${c.entity_type}): HP ${c.hp}/${c.max_hp}, AC ${c.armor_class}, 先攻 ${c.initiative}`)
        .join("\n");
      const prompt = `当前战斗第 ${activeCombat?.round_number ?? 1} 轮，轮到 [${activeFighter?.display_name ?? "当前行动者"}] 行动。\n参战人员状态如下：\n${summary}\n\n请作为资深 D&D 5e 战术军师，给出简明扼要的战术决策建议（包括推荐攻击目标、走位、法术使用与附赠动作搭配，100字左右）。`;
      const res = await runAssistantTurn(campaignId, prompt, { mode: "combat" });
      return res.dm_hint?.text ?? "未能生成战术建议";
    },
    onSuccess: (text) => {
      setAiAnalysis(text);
      soundboard.playHandout();
      showToast("🤖 AI 战术建议已生成！", "success");
    },
  });

  const aiNarrativeMutation = useMutation({
    mutationFn: async () => {
      const recentActions = (actionsQuery.data ?? [])
        .slice(0, 5)
        .map((a: CombatAction) => `- ${a.action_name ?? a.action_type}: ${a.resolution_note ?? ""}`)
        .join("\n");
      const prompt = `请根据以下最近发生的战斗交锋，写一段充满张力、画面感极强的中文战斗旁白（150字左右，用于主持人口述描述）：\n${recentActions || "双方正在近身对峙，伺机发动致命一击"}`;
      const res = await runAssistantTurn(campaignId, prompt, { mode: "narrative" });
      return res.dm_hint?.text ?? "未能生成战斗描述";
    },
    onSuccess: (text) => {
      setAiNarrative(text);
      soundboard.playHandout();
      showToast("🎙️ 战斗生动旁白已生成！", "success");
    },
  });

  // Roll dice helper
  const rollDice = (sides: number, count = 1) => {
    soundboard.playDiceRoll();
    const mod = Number(customDiceMod) || 0;
    const rolls: number[] = [];
    let sum = 0;
    for (let i = 0; i < count; i++) {
      const r = Math.floor(Math.random() * sides) + 1;
      rolls.push(r);
      sum += r;
    }
    const total = sum + mod;
    const isCrit = sides === 20 && count === 1 && rolls[0] === 20;
    const isFumble = sides === 20 && count === 1 && rolls[0] === 1;

    if (isCrit) soundboard.playNat20();
    if (isFumble) soundboard.playNat1();

    const entry = {
      id: `${Date.now()}-${Math.random()}`,
      formula: `${count}d${sides}${mod !== 0 ? (mod > 0 ? `+${mod}` : `${mod}`) : ""}`,
      result: total,
      rolls,
      isCrit,
      isFumble,
    };
    setDiceHistory((prev) => [entry, ...prev.slice(0, 9)]);
  };

  // Perform a 5e Skill Check
  const executeSkillCheck = (skill: (typeof DND_SKILLS)[0]) => {
    soundboard.playDiceRoll();
    const d20 = Math.floor(Math.random() * 20) + 1;
    const mod = Number(skillCheckMod) || 0;
    const total = d20 + mod;
    const isCrit = d20 === 20;
    const isFumble = d20 === 1;
    const text = `${activeFighter?.display_name ?? "行动者"} 进行【${skill.name}】检定：d20(${d20}) + ${mod} = ${total}${isCrit ? "（💥天然20极佳表现！）" : ""}${isFumble ? "（💀天然1大失败！）" : ""}`;
    setSkillCheckResult(text);
    if (isCrit) soundboard.playNat20();
    if (isFumble) soundboard.playNat1();
    showToast(`🎲 ${skill.name} 检定总值: ${total}`, "info");
  };

  if (combatsQuery.isLoading) {
    return <LoadingBlock label="正在载入战役战斗数据…" />;
  }

  // 1-Click Starter Encounter Loader when no combat is active
  if (!activeCombat || (combatsQuery.data ?? []).length === 0) {
    return (
      <div className="mx-auto max-w-4xl p-6">
        <div className="rounded-2xl border border-amber-500/40 bg-gradient-to-b from-ink-900 via-ink-950 to-ink-950 p-8 shadow-2xl text-center">
          <span className="text-5xl">⚡</span>
          <h2 className="mt-4 font-display text-2xl font-bold text-parchment-100">当前战役尚无活跃战斗遭遇</h2>
          <p className="mt-2 text-sm text-stone-400">
            您可以一键快速发起标准新手遭遇，或手动新建一场遭遇战并导入玩家与怪物。
          </p>

          <div className="mt-8 flex flex-wrap justify-center gap-4">
            <button
              className="rounded-xl border border-amber-500/70 bg-gradient-to-r from-amber-600 to-amber-700 px-6 py-3 text-sm font-bold text-amber-950 shadow-lg shadow-amber-600/30 transition hover:brightness-110 active:scale-95"
              onClick={async () => {
                const combat = await createCombat(campaignId, { name: "红落避难所前厅突袭", round_number: 1, status: "active" });
                await createCombatant(campaignId, combat.id, { display_name: "圣骑士 瓦伦丁", entity_type: "character", hp: 28, max_hp: 28, armor_class: 18, initiative: 17, conditions: [], snapshot_json: { actions: [], row: 3, col: 3, elevation_ft: 0 } });
                await createCombatant(campaignId, combat.id, { display_name: "游侠 艾拉", entity_type: "character", hp: 20, max_hp: 20, armor_class: 15, initiative: 15, conditions: [], snapshot_json: { actions: [], row: 4, col: 2, elevation_ft: 10 } });
                await createCombatant(campaignId, combat.id, { display_name: "地精头目·裂齿", entity_type: "monster", hp: 21, max_hp: 21, armor_class: 15, initiative: 14, conditions: [], snapshot_json: { actions: [], row: 3, col: 7, elevation_ft: 0 } });
                await createCombatant(campaignId, combat.id, { display_name: "地精射手 A", entity_type: "monster", hp: 7, max_hp: 7, armor_class: 13, initiative: 11, conditions: [], snapshot_json: { actions: [], row: 2, col: 8, elevation_ft: 0 } });
                soundboard.playNat20();
                setSelectedCombatId(combat.id);
                void queryClient.invalidateQueries({ queryKey: ["combats", campaignId] });
                showToast("🚀 预设遭遇已创建并载入参战人员！", "success");
              }}
              type="button"
            >
              🚀 一键发起《红落避难所前厅突袭》（4名参战者）
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex flex-col bg-ink-950 text-stone-200 ${isFullscreen ? "fixed inset-0 z-50 overflow-y-auto p-4" : "p-3 lg:p-5"}`}>
      {/* Top Cockpit Header */}
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-ink-700/80 bg-ink-900/90 p-3 shadow-xl backdrop-blur-md">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-2xl">⚡</span>
            <div>
              <h1 className="font-display text-lg font-bold text-parchment-100">快捷战斗座舱 (Quick Combat)</h1>
              <p className="text-2xs text-stone-400">玩家移动与施法总控 · 45° 3D 战术范围可视化 · 环数选择与升环增效 · 高低差</p>
            </div>
          </div>

          {/* Campaign Selector */}
          <div className="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-950/80 px-2 py-1">
            <span className="text-2xs text-stone-400">战役:</span>
            <select
              className="bg-transparent text-xs text-parchment-100 outline-none"
              onChange={(e) => selectCampaign(e.target.value)}
              value={campaignId}
            >
              {(campaignsQuery.data ?? []).map((cp) => (
                <option className="bg-ink-900 text-stone-200" key={cp.id} value={cp.id}>
                  {cp.name}
                </option>
              ))}
            </select>
          </div>

          {/* Combat Selector */}
          <select
            className={`${selectCls} max-w-48 text-xs font-medium`}
            onChange={(e) => setSelectedCombatId(e.target.value)}
            value={combatId}
          >
            {(combatsQuery.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name || `遭遇战斗 #${c.id.slice(0, 6)}`} ({c.status === "active" ? "进行中" : "已结束"})
              </option>
            ))}
          </select>

          {activeCombat ? (
            <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-950/30 px-3 py-1 text-xs">
              <span className="font-bold text-amber-300">第 {activeCombat.round_number} 轮</span>
              <span className="text-stone-500">|</span>
              <span className="text-stone-300">当前回合:</span>
              <strong className="text-amber-200">{activeFighter?.display_name ?? "未指定"}</strong>
            </div>
          ) : null}
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="rounded-lg border border-ink-700 bg-ink-800 px-2.5 py-1.5 text-xs text-stone-300 transition hover:border-amber-500/50 hover:text-amber-200"
            onClick={() => setShowAddCombatantModal(true)}
            type="button"
          >
            👥 添加参战者
          </button>
          <button
            className="rounded-lg border border-ink-700 bg-ink-800 px-2.5 py-1.5 text-xs text-stone-300 transition hover:border-amber-500/50 hover:text-amber-200"
            onClick={() => rollInitiativesMutation.mutate()}
            type="button"
          >
            🎲 全员先攻
          </button>
          <button
            className="rounded-lg border border-emerald-600/70 bg-emerald-950/40 px-3 py-1.5 text-xs font-bold text-emerald-200 transition hover:bg-emerald-900/50"
            disabled={advanceTurnMutation.isPending}
            onClick={() => advanceTurnMutation.mutate()}
            type="button"
          >
            ⏭️ 推进下一回合
          </button>
          <button
            className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1.5 text-xs text-stone-400 hover:text-stone-200"
            onClick={() => setIsFullscreen(!isFullscreen)}
            type="button"
          >
            {isFullscreen ? "🗗 退出全屏" : "🗖 全景座舱"}
          </button>
        </div>
      </header>

      {/* Top Initiative Card Strip */}
      {ordered.length > 0 ? (
        <div className="mb-3">
          <InitiativeCardStrip
            currentIndex={activeCombat?.current_turn_index ?? activeCombat?.active_combatant_index ?? 0}
            fighters={ordered}
          />
        </div>
      ) : null}

      {/* Interactive Suite: Player Movement & Spellcasting Station */}
      <div className="mb-3 rounded-xl border border-ink-700 bg-gradient-to-r from-ink-900 via-ink-950 to-ink-900 p-3.5 shadow-xl">
        {/* Navigation Tabs for HUD */}
        <div className="flex flex-wrap items-center justify-between border-b border-ink-800 pb-2.5 gap-2">
          <div className="flex rounded-lg border border-ink-700 bg-ink-950/80 p-0.5">
            <button
              className={`rounded px-3 py-1 text-xs font-bold transition ${activeHudTab === "spells" ? "bg-fuchsia-600 text-fuchsia-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => {
                setActiveHudTab("spells");
                setGridInteractionMode("target");
              }}
              type="button"
            >
              🔮 玩家法术库与施法 (选法术/选环数/看范围)
            </button>
            <button
              className={`rounded px-3 py-1 text-xs font-bold transition ${activeHudTab === "actions" ? "bg-amber-600 text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setActiveHudTab("actions")}
              type="button"
            >
              ⚔️ 基础武器攻击
            </button>
            <button
              className={`rounded px-3 py-1 text-xs font-bold transition ${activeHudTab === "skills" ? "bg-sky-600 text-sky-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setActiveHudTab("skills")}
              type="button"
            >
              🎯 18项技能检定
            </button>
            <button
              className={`rounded px-3 py-1 text-xs font-bold transition ${activeHudTab === "features" ? "bg-purple-600 text-purple-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setActiveHudTab("features")}
              type="button"
            >
              🛡️ 职业战术特技
            </button>
            <button
              className={`rounded px-3 py-1 text-xs font-bold transition ${activeHudTab === "conditions" ? "bg-rose-600 text-rose-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setActiveHudTab("conditions")}
              type="button"
            >
              🏷️ 15核心状态
            </button>
          </div>

          <div className="flex items-center gap-2 text-2xs text-stone-400">
            <span>当前行动者: <strong className="text-amber-300">{activeFighter?.display_name ?? "未指定"}</strong></span>
            <span>|</span>
            <span>锁定目标: <strong className="text-emerald-300">{promptTargetCombatant?.display_name ?? "未选定"}</strong></span>
          </div>
        </div>

        {/* Tab 1: 🔮 玩家法术库与施法全流程 */}
        {activeHudTab === "spells" ? (
          <div className="mt-3 space-y-3">
            {/* Step 1: Spell Selector & Filters */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-2xs font-semibold text-fuchsia-300">① 选择法术:</span>
                <div className="flex rounded border border-ink-700 bg-ink-950 p-0.5 text-2xs">
                  <button
                    className={`rounded px-2 py-0.5 transition ${spellLevelFilter === "all" ? "bg-fuchsia-600 font-bold text-fuchsia-950" : "text-stone-400 hover:text-stone-200"}`}
                    onClick={() => setSpellLevelFilter("all")}
                    type="button"
                  >
                    全部
                  </button>
                  <button
                    className={`rounded px-2 py-0.5 transition ${spellLevelFilter === 0 ? "bg-fuchsia-600 font-bold text-fuchsia-950" : "text-stone-400 hover:text-stone-200"}`}
                    onClick={() => setSpellLevelFilter(0)}
                    type="button"
                  >
                    0环戏法
                  </button>
                  <button
                    className={`rounded px-2 py-0.5 transition ${spellLevelFilter === 1 ? "bg-fuchsia-600 font-bold text-fuchsia-950" : "text-stone-400 hover:text-stone-200"}`}
                    onClick={() => setSpellLevelFilter(1)}
                    type="button"
                  >
                    1环法术
                  </button>
                  <button
                    className={`rounded px-2 py-0.5 transition ${spellLevelFilter === 2 ? "bg-fuchsia-600 font-bold text-fuchsia-950" : "text-stone-400 hover:text-stone-200"}`}
                    onClick={() => setSpellLevelFilter(2)}
                    type="button"
                  >
                    2环法术
                  </button>
                  <button
                    className={`rounded px-2 py-0.5 transition ${spellLevelFilter === 3 ? "bg-fuchsia-600 font-bold text-fuchsia-950" : "text-stone-400 hover:text-stone-200"}`}
                    onClick={() => setSpellLevelFilter(3)}
                    type="button"
                  >
                    3环法术
                  </button>
                </div>
              </div>

              <input
                className="w-44 rounded-lg border border-ink-700 bg-ink-950 px-2.5 py-1 text-2xs text-stone-200 placeholder-stone-500 outline-none focus:border-fuchsia-500"
                onChange={(e) => setSpellSearchTerm(e.target.value)}
                placeholder="🔍 快速搜索法术…"
                value={spellSearchTerm}
              />
            </div>

            {/* Spells Grid Cards */}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 max-h-48 overflow-y-auto pr-1">
              {filteredSpells.map((spell) => {
                const isCurrent = selectedSpell?.id === spell.id;
                return (
                  <button
                    className={`flex flex-col items-start rounded-lg border p-2 text-left transition shadow-md ${
                      isCurrent
                        ? "border-fuchsia-400 bg-fuchsia-950/60 ring-2 ring-fuchsia-400"
                        : "border-ink-800 bg-ink-900/80 hover:border-fuchsia-500/60 hover:bg-ink-900"
                    }`}
                    key={spell.id}
                    onClick={() => handleSelectSpell(spell)}
                    type="button"
                  >
                    <div className="flex w-full items-center justify-between">
                      <strong className="text-xs font-bold text-parchment-100">{spell.name}</strong>
                      <span className="rounded bg-fuchsia-950 border border-fuchsia-800/80 px-1.5 py-0.2 text-[9px] font-mono text-fuchsia-300">
                        {spell.level === 0 ? "戏法" : `${spell.level}环`}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1 text-[9px] text-stone-400">
                      <span>{spell.castTime}</span>
                      <span>·</span>
                      <span>{spell.rangeFt}尺</span>
                      <span>·</span>
                      <span className="text-amber-300 font-mono">{spell.damageDiceBase} {spell.damageType}</span>
                    </div>
                    <p className="mt-1 line-clamp-1 text-[9px] text-stone-500">{spell.description}</p>
                  </button>
                );
              })}
            </div>

            {/* Step 2 & 3: Selected Spell Controls */}
            {selectedSpell ? (
              <div className="rounded-xl border border-fuchsia-500/60 bg-gradient-to-r from-fuchsia-950/40 via-ink-950 to-ink-950 p-3.5 shadow-xl">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 max-w-xl">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-lg">✨</span>
                      <strong className="text-sm font-bold text-fuchsia-200">
                        已选定法术：{selectedSpell.name} ({selectedSpell.nameEn})
                      </strong>
                      <Badge tone="ai">{selectedSpell.school}学派</Badge>
                      <Badge tone="warn">射程: {selectedSpell.rangeFt} 尺</Badge>
                      <Badge tone="neutral">形态: {selectedSpell.shape} {selectedSpell.sizeFt ? `${selectedSpell.sizeFt}尺` : ""}</Badge>
                    </div>
                    <p className="mt-1 text-2xs leading-relaxed text-stone-300">
                      {selectedSpell.description}
                    </p>
                    <div className="mt-1 text-2xs text-amber-300 font-medium">
                      💡 升环增效规则：{selectedSpell.upcastRule}
                    </div>
                  </div>

                  {/* Upcasting Level Selector */}
                  <div className="flex flex-col items-end gap-1.5">
                    <span className="text-2xs text-stone-400 font-semibold">② 选择施法环数:</span>
                    <div className="flex rounded-lg border border-fuchsia-700 bg-ink-950 p-0.5 text-xs font-bold">
                      {selectedSpell.level === 0 ? (
                        <span className="rounded bg-fuchsia-600 px-3 py-1 text-fuchsia-950">0环 (戏法不耗法术位)</span>
                      ) : (
                        Array.from({ length: 4 - selectedSpell.level }, (_, idx) => {
                          const slotLvl = selectedSpell.level + idx;
                          const isPicked = selectedSpellLevel === slotLvl;
                          return (
                            <button
                              className={`rounded px-2.5 py-1 transition ${
                                isPicked
                                  ? "bg-gradient-to-r from-fuchsia-600 to-purple-600 text-white shadow"
                                  : "text-stone-300 hover:text-white"
                              }`}
                              key={slotLvl}
                              onClick={() => setSelectedSpellLevel(slotLvl)}
                              type="button"
                            >
                              {slotLvl}环 {slotLvl > selectedSpell.level ? `(+${slotLvl - selectedSpell.level}级升环)` : "(基础)"}
                            </button>
                          );
                        })
                      )}
                    </div>
                  </div>
                </div>

                {/* Range & Target Area Live Feedback Bar */}
                <div className="mt-3 flex flex-wrap items-center justify-between border-t border-ink-800/80 pt-2.5 gap-2 text-2xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-sky-950/80 border border-sky-700/60 px-2 py-0.5 text-sky-300 font-mono font-medium">
                      🎯 3D 射程范围: {selectedSpell.rangeFt} 尺已在网格上实时高亮蓝圈
                    </span>
                    {selectedSpell.shape !== "single" ? (
                      <span className="rounded bg-fuchsia-950/80 border border-fuchsia-700/60 px-2 py-0.5 text-fuchsia-300 font-mono font-medium">
                        🔮 3D 作用体: {selectedSpell.shape} ({selectedSpell.sizeFt}尺) 立体光柱已投射
                      </span>
                    ) : null}
                    <span className="text-stone-400">
                      当前覆盖敌人: <strong className="text-emerald-300">{targetingValidity.validTargetIds.size || (promptTargetCombatant ? 1 : 0)} 名</strong>
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {selectedSpell.id === "magic_missile" ? (
                      <Button
                        onClick={() => {
                          const initAlloc: Record<string, number> = {};
                          if (promptTargetCombatant) initAlloc[promptTargetCombatant.id] = 3 + (selectedSpellLevel - 1);
                          else if (ordered[0]) initAlloc[ordered[0].id] = 3 + (selectedSpellLevel - 1);
                          setDartAllocations(initAlloc);
                          setMagicMissileModalOpen(true);
                        }}
                        variant="primary"
                      >
                        🚀 唤起魔法飞弹多目标分流面板
                      </Button>
                    ) : (
                      <button
                        className="rounded-lg border border-fuchsia-500 bg-gradient-to-r from-fuchsia-600 to-purple-600 px-5 py-2 text-xs font-bold text-white shadow-lg hover:brightness-110 disabled:opacity-50 transition active:scale-95"
                        disabled={castSelectedSpellMutation.isPending}
                        onClick={() => castSelectedSpellMutation.mutate()}
                        type="button"
                      >
                        {castSelectedSpellMutation.isPending ? "正在施法…" : `✨ 立即施放【${selectedSpell.name}】(${selectedSpellLevel === 0 ? "戏法" : `${selectedSpellLevel}环`})`}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {/* Tab 2: ⚔️ 基础武器攻击 */}
        {activeHudTab === "actions" ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              className="rounded-lg border border-amber-600/60 bg-amber-950/40 px-3 py-1.5 text-xs font-bold text-amber-200 hover:bg-amber-900/50 shadow-md"
              onClick={() => {
                setPromptActionName("近战武器重击 (Melee Attack)");
                setPromptAttackMod("5");
                setPromptDamageDice("1d8+3");
                setPromptDamageType("slashing");
                setIsMeleeAttack(true);
                setActionPromptOpen(true);
              }}
              type="button"
            >
              🗡️ 近战攻击
            </button>
            <button
              className="rounded-lg border border-sky-600/60 bg-sky-950/40 px-3 py-1.5 text-xs font-bold text-sky-200 hover:bg-sky-900/50 shadow-md"
              onClick={() => {
                setPromptActionName("远程射击 (Ranged Attack)");
                setPromptAttackMod("6");
                setPromptDamageDice("1d8+3");
                setPromptDamageType("piercing");
                setIsMeleeAttack(false);
                setActionPromptOpen(true);
              }}
              type="button"
            >
              🏹 远程射击
            </button>
            <button
              className="rounded-lg border border-rose-600/60 bg-rose-950/40 px-3 py-1.5 text-xs font-bold text-rose-200 hover:bg-rose-900/50 shadow-md"
              onClick={() => {
                setPromptActionName("借机攻击 (Opportunity Attack)");
                setPromptAttackMod("5");
                setPromptDamageDice("1d8+3");
                setPromptDamageType("slashing");
                setIsMeleeAttack(true);
                setActionPromptOpen(true);
              }}
              type="button"
            >
              ⚡ 借机攻击
            </button>
          </div>
        ) : null}

        {/* Tab 3: 🎯 18项技能与战术对决 */}
        {activeHudTab === "skills" ? (
          <div className="mt-3">
            {/* Quick Combat Maneuvers */}
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <button
                className="rounded-lg border border-amber-600/70 bg-amber-950/40 px-2.5 py-1 text-xs font-bold text-amber-200 hover:bg-amber-900/50"
                onClick={() => {
                  if (!promptTargetCombatant) return;
                  toggleConditionMutation.mutate({ combatant: promptTargetCombatant, conditionId: "prone" });
                  showToast(`🤼 ${activeFighter?.display_name} 发动推撞倒地对决！`, "info");
                }}
                type="button"
              >
                🤼 推撞倒地 (Shove Prone)
              </button>
              <button
                className="rounded-lg border border-amber-600/70 bg-amber-950/40 px-2.5 py-1 text-xs font-bold text-amber-200 hover:bg-amber-900/50"
                onClick={() => {
                  if (!promptTargetCombatant) return;
                  toggleConditionMutation.mutate({ combatant: promptTargetCombatant, conditionId: "grappled" });
                  showToast(`🤼 ${activeFighter?.display_name} 发动擒抱压制！`, "info");
                }}
                type="button"
              >
                🤼 擒抱控制 (Grapple)
              </button>
              <button
                className="rounded-lg border border-emerald-600/70 bg-emerald-950/40 px-2.5 py-1 text-xs font-bold text-emerald-200 hover:bg-emerald-900/50"
                onClick={() => {
                  if (!activeFighter) return;
                  toggleConditionMutation.mutate({ combatant: activeFighter, conditionId: "invisible" });
                  showToast(`🕵️ ${activeFighter.display_name} 进行战术躲藏并隐蔽！`, "info");
                }}
                type="button"
              >
                🕵️ 潜行与躲藏 (Hide)
              </button>
              <button
                className="rounded-lg border border-sky-600/70 bg-sky-950/40 px-2.5 py-1 text-xs font-bold text-sky-200 hover:bg-sky-900/50"
                onClick={() => {
                  if (!promptTargetCombatant) return;
                  if (promptTargetCombatant.hp <= 0) {
                    quickHpAdjustMutation.mutate({ combatant: promptTargetCombatant, delta: 1 });
                  }
                  showToast(`🩹 对 ${promptTargetCombatant.display_name} 执行战地急救 (DC 10 医疗检定)！`, "success");
                }}
                type="button"
              >
                🩹 急救与稳定伤势 (Stabilize)
              </button>
              <button
                className="rounded-lg border border-purple-600/70 bg-purple-950/40 px-2.5 py-1 text-xs font-bold text-purple-200 hover:bg-purple-900/50"
                onClick={() => {
                  showToast(`🤝 协助动作：为下一名队友针对 ${promptTargetCombatant?.display_name ?? "目标"} 的首击赋予优势！`, "success");
                }}
                type="button"
              >
                🤝 协助盟友 (Help)
              </button>
            </div>

            {/* 18 Skills Grid */}
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 md:grid-cols-6">
              {DND_SKILLS.map((skill) => (
                <button
                  className="flex flex-col items-start rounded-lg border border-ink-800 bg-ink-950/80 p-2 text-left hover:border-sky-500/60 hover:bg-sky-950/30 transition group"
                  key={skill.id}
                  onClick={() => executeSkillCheck(skill)}
                  title={skill.desc}
                  type="button"
                >
                  <div className="flex w-full items-center justify-between">
                    <strong className="text-2xs text-stone-200 group-hover:text-sky-200">{skill.name.split(" ")[0]}</strong>
                    <span className="rounded bg-ink-800 px-1 py-0.5 text-[8px] font-mono text-stone-400">{skill.ability}</span>
                  </div>
                  <span className="mt-0.5 truncate text-[9px] text-stone-500">{skill.desc.slice(0, 8)}…</span>
                </button>
              ))}
            </div>

            {skillCheckResult ? (
              <div className="mt-2 rounded-lg border border-sky-800/60 bg-sky-950/40 p-2 text-2xs text-sky-200 font-mono">
                {skillCheckResult}
              </div>
            ) : null}
          </div>
        ) : null}

        {/* Tab 4: 🛡️ 职业特技与战术爆发 */}
        {activeHudTab === "features" ? (
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-4">
            <button
              className="flex flex-col rounded-lg border border-emerald-700/60 bg-emerald-950/30 p-2.5 text-left hover:bg-emerald-900/40 transition"
              onClick={() => {
                if (!activeFighter) return;
                const heal = Math.floor(Math.random() * 10) + 1 + 3;
                quickHpAdjustMutation.mutate({ combatant: activeFighter, delta: heal });
                showToast(`🛡️ 战士回气：回复 ${heal} 点生命值！`, "success");
              }}
              type="button"
            >
              <strong className="text-xs font-bold text-emerald-200">🛡️ 回气 (Second Wind)</strong>
              <span className="text-2xs text-stone-400 mt-0.5">附赠动作 · 恢复 1d10 + 等级生命</span>
            </button>

            <button
              className="flex flex-col rounded-lg border border-amber-700/60 bg-amber-950/30 p-2.5 text-left hover:bg-amber-900/40 transition"
              onClick={() => {
                if (!promptTargetCombatant) return;
                const smiteDamage = Math.floor(Math.random() * 8) + 1 + Math.floor(Math.random() * 8) + 1;
                const pos = combatantGridPosition(promptTargetCombatant) ?? [3, 5];
                spawnVfx({ row: pos[0], col: pos[1], type: "smite", text: `-${smiteDamage} 光耀` });
                quickHpAdjustMutation.mutate({ combatant: promptTargetCombatant, delta: -smiteDamage });
                showToast(`⚖️ 圣负惩击：对 ${promptTargetCombatant.display_name} 造成 ${smiteDamage} 点额外光耀伤害！`, "success");
              }}
              type="button"
            >
              <strong className="text-xs font-bold text-amber-200">⚖️ 圣负惩击 (Divine Smite)</strong>
              <span className="text-2xs text-stone-400 mt-0.5">命中后消耗法术位 · 追加 2d8 光耀伤害</span>
            </button>

            <button
              className="flex flex-col rounded-lg border border-rose-700/60 bg-rose-950/30 p-2.5 text-left hover:bg-rose-900/40 transition"
              onClick={() => {
                if (!activeFighter) return;
                toggleConditionMutation.mutate({ combatant: activeFighter, conditionId: "rage" });
                showToast(`🪓 狂暴 (Rage)：近战伤害+2，获得钝击/穿刺/挥砍抗性！`, "success");
              }}
              type="button"
            >
              <strong className="text-xs font-bold text-rose-200">🪓 狂暴 (Rage)</strong>
              <span className="text-2xs text-stone-400 mt-0.5">附赠动作 · 伤害+2，物理伤害抗性</span>
            </button>

            <button
              className="flex flex-col rounded-lg border border-purple-700/60 bg-purple-950/30 p-2.5 text-left hover:bg-purple-900/40 transition"
              onClick={() => {
                showToast(`🔮 护盾术 (Shield)：反应激活，AC +5 并免疫魔法飞弹直至下回合！`, "success");
              }}
              type="button"
            >
              <strong className="text-xs font-bold text-purple-200">🔮 护盾术 (Shield)</strong>
              <span className="text-2xs text-stone-400 mt-0.5">反应触发 · AC +5 直至自身下回合开始</span>
            </button>
          </div>
        ) : null}

        {/* Tab 5: 🏷️ 15核心状态赋予/解除 */}
        {activeHudTab === "conditions" ? (
          <div className="mt-3">
            <div className="mb-2 text-2xs text-stone-400">
              为目标 <strong className="text-emerald-300">{promptTargetCombatant?.display_name ?? "未选定"}</strong> 一键赋予/解除 5e 核心状态：
            </div>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 md:grid-cols-5">
              {DND_CONDITIONS.map((cond) => {
                const isActive = (promptTargetCombatant?.conditions ?? []).includes(cond.id);
                return (
                  <button
                    className={`flex flex-col items-start rounded-lg border p-2 text-left transition ${
                      isActive
                        ? "border-rose-500 bg-rose-950/60 ring-1 ring-rose-400"
                        : "border-ink-800 bg-ink-950/80 hover:border-amber-500/50"
                    }`}
                    key={cond.id}
                    onClick={() => {
                      if (!promptTargetCombatant) return;
                      toggleConditionMutation.mutate({ combatant: promptTargetCombatant, conditionId: cond.id });
                    }}
                    title={cond.desc}
                    type="button"
                  >
                    <div className="flex w-full items-center justify-between">
                      <span className="text-xs">{cond.icon} {cond.name.split(" ")[0]}</span>
                      {isActive ? <Badge tone="danger">生效中</Badge> : null}
                    </div>
                    <span className="mt-1 line-clamp-1 text-[8px] text-stone-400">{cond.desc}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        {/* Magic Missile Multi-Target Allocation Modal */}
        {magicMissileModalOpen ? (
          <div className="mt-3.5 rounded-xl border border-fuchsia-500/70 bg-ink-950/90 p-4 shadow-2xl animate-fade-in">
            <div className="flex items-center justify-between border-b border-ink-800 pb-2.5">
              <div className="flex items-center gap-2">
                <span className="text-lg">🚀</span>
                <strong className="text-sm text-fuchsia-200">
                  魔法飞弹多目标分配（当前总数：{Object.values(dartAllocations).reduce((a, b) => a + b, 0)}/{3 + Math.max(0, selectedSpellLevel - 1)} 枚 · {selectedSpellLevel}环）
                </strong>
              </div>
              <button
                className="text-stone-400 hover:text-stone-200 text-xs"
                onClick={() => setMagicMissileModalOpen(false)}
                type="button"
              >
                ✕ 关闭
              </button>
            </div>

            <p className="mt-2 text-2xs text-stone-300">
              每枚飞弹造成 <strong>1d4+1 力场伤害</strong>（自动必中）。您可以将飞弹打向同一目标，或分散打向不同敌人：
            </p>

            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
              {ordered.map((f) => {
                const count = dartAllocations[f.id] ?? 0;
                return (
                  <div className="flex items-center justify-between rounded-lg border border-ink-800 bg-ink-900/80 p-2 text-2xs" key={f.id}>
                    <div className="min-w-0 pr-2">
                      <strong className="truncate block text-stone-200">{f.display_name}</strong>
                      <span className="text-stone-500 font-mono">HP: {f.hp}/{f.max_hp}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        className="h-6 w-6 rounded border border-ink-700 bg-ink-950 text-xs font-bold text-stone-300 hover:bg-ink-800"
                        onClick={() => setDartAllocations((prev) => ({ ...prev, [f.id]: Math.max(0, (prev[f.id] ?? 0) - 1) }))}
                        type="button"
                      >
                        -
                      </button>
                      <span className="w-5 text-center font-bold text-fuchsia-300 font-mono">{count}</span>
                      <button
                        className="h-6 w-6 rounded border border-fuchsia-700 bg-fuchsia-950/60 text-xs font-bold text-fuchsia-200 hover:bg-fuchsia-900"
                        onClick={() => {
                          const total = Object.values(dartAllocations).reduce((a, b) => a + b, 0);
                          const maxAllowed = 3 + Math.max(0, selectedSpellLevel - 1);
                          if (total >= maxAllowed) {
                            showToast(`${selectedSpellLevel}环魔法飞弹最多分配 ${maxAllowed} 枚飞弹`, "info");
                            return;
                          }
                          setDartAllocations((prev) => ({ ...prev, [f.id]: (prev[f.id] ?? 0) + 1 }));
                        }}
                        type="button"
                      >
                        +
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="mt-3.5 flex justify-end gap-2">
              <Button onClick={() => setMagicMissileModalOpen(false)} variant="ghost">取消</Button>
              <Button
                disabled={executeMagicMissileMutation.isPending || Object.values(dartAllocations).reduce((a, b) => a + b, 0) === 0}
                onClick={() => executeMagicMissileMutation.mutate()}
                variant="primary"
              >
                {executeMagicMissileMutation.isPending ? "正在发射…" : "🚀 全数发射并分别自动扣除伤害"}
              </Button>
            </div>
          </div>
        ) : null}

        {/* Action & Dice Prompt Interactive Modal / Card */}
        {actionPromptOpen ? (
          <div className="mt-3.5 rounded-xl border border-amber-500/70 bg-ink-950/90 p-4 shadow-2xl animate-fade-in">
            <div className="flex flex-wrap items-center justify-between border-b border-ink-800 pb-2.5">
              <div className="flex items-center gap-2">
                <span className="text-lg">🎲</span>
                <strong className="text-sm text-parchment-100">
                  动作判定：{promptActionName} ➔ 目标：
                  <span className="text-emerald-300">
                    {promptTargetCombatant?.display_name ?? "未选定"} (AC {promptTargetCombatant?.armor_class ?? 10} · HP {promptTargetCombatant?.hp}/{promptTargetCombatant?.max_hp})
                  </span>
                </strong>
              </div>
              <button
                className="text-stone-400 hover:text-stone-200 text-xs"
                onClick={() => setActionPromptOpen(false)}
                type="button"
              >
                ✕ 关闭
              </button>
            </div>

            {/* Advantage / Disadvantage Badge banner */}
            {attackAdvantageState.reasons.length > 0 ? (
              <div className="mt-2.5 rounded-lg border border-amber-800/60 bg-amber-950/30 p-2 text-2xs">
                {attackAdvantageState.hasAdvantage ? (
                  <span className="font-bold text-emerald-300">🟢 本次攻击具有优势 (Advantage - 自动掷 2 颗 d20 取高)</span>
                ) : attackAdvantageState.hasDisadvantage ? (
                  <span className="font-bold text-rose-300">🔴 本次攻击具有劣势 (Disadvantage - 自动掷 2 颗 d20 取低)</span>
                ) : null}
                <ul className="mt-1 list-disc pl-4 text-stone-400">
                  {attackAdvantageState.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
              {/* Option 1: Full Auto Resolve */}
              <div className="flex flex-col justify-between rounded-xl border border-emerald-800/60 bg-emerald-950/20 p-3.5 shadow-md">
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-emerald-400 font-bold text-xs uppercase tracking-wide">🤖 模式 A：智能代投与自动结算</span>
                    <Badge tone="ok">极速推荐</Badge>
                  </div>
                  <p className="mt-1.5 text-2xs leading-relaxed text-stone-300">
                    系统自动投掷 d20 命中检定（自动计算优势/劣势），比对目标 AC，计算暴击与抗性减免，扣减目标生命值并播放打击音效。
                  </p>
                </div>

                <button
                  className="mt-3 w-full rounded-lg border border-emerald-600 bg-emerald-600/30 py-2.5 text-xs font-bold text-emerald-200 shadow-lg hover:bg-emerald-600/50 disabled:opacity-50 transition active:scale-95"
                  disabled={autoResolveActionMutation.isPending || !promptTargetCombatant}
                  onClick={() => autoResolveActionMutation.mutate()}
                  type="button"
                >
                  {autoResolveActionMutation.isPending ? "正在自动结算…" : "🎲 一键自动投骰并扣除目标生命"}
                </button>
              </div>

              {/* Option 2: Manual Physical Dice Input */}
              <div className="rounded-xl border border-amber-800/60 bg-amber-950/20 p-3.5 shadow-md">
                <div className="flex items-center gap-1.5">
                  <span className="text-amber-400 font-bold text-xs uppercase tracking-wide">✍️ 模式 B：玩家/DM 实体骰结果录入</span>
                  <Badge tone="warn">真实跑团</Badge>
                </div>
                <p className="mt-1 text-2xs text-stone-300">
                  玩家或 DM 掷出真实骰子后，在此输入点数，系统将按真实点数精准写入规则：
                </p>

                <div className="mt-2.5 grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-2xs font-semibold text-stone-400">命中检定总值 (d20+加值)</label>
                    <input
                      className={`${inputCls} mt-1 font-mono text-xs`}
                      onChange={(e) => setManualAttackRoll(e.target.value)}
                      placeholder="如: 19 (vs AC 18)"
                      type="number"
                      value={manualAttackRoll}
                    />
                  </div>
                  <div>
                    <label className="text-2xs font-semibold text-stone-400">最终伤害点数</label>
                    <input
                      className={`${inputCls} mt-1 font-mono text-xs`}
                      onChange={(e) => setManualDamageRoll(e.target.value)}
                      placeholder="如: 8"
                      type="number"
                      value={manualDamageRoll}
                    />
                  </div>
                </div>

                <div className="mt-2.5 flex items-center justify-between">
                  <label className="flex items-center gap-1.5 text-2xs text-amber-300 cursor-pointer">
                    <input
                      checked={isManualCrit}
                      className="accent-amber-500"
                      onChange={(e) => setIsManualCrit(e.target.checked)}
                      type="checkbox"
                    />
                    <span>💥 致命一击 (暴击)</span>
                  </label>

                  <button
                    className="rounded-lg border border-amber-600 bg-amber-600/30 px-4 py-1.5 text-xs font-bold text-amber-200 hover:bg-amber-600/50 disabled:opacity-50 transition"
                    disabled={confirmManualDiceActionMutation.isPending || !promptTargetCombatant}
                    onClick={() => confirmManualDiceActionMutation.mutate()}
                    type="button"
                  >
                    {confirmManualDiceActionMutation.isPending ? "应用中…" : "✅ 确认应用实体骰"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {/* Main 2-Column Cockpit Layout: Tactical Map (Left) + Turn Console & AI (Right) */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Left Column: 🗺️ 3D 战术地图与移动距离范围 (6 Cols) */}
        <div className="flex flex-col gap-3 lg:col-span-6">
          <QuickBattleGrid
            activeFighterId={activeFighter?.id ?? null}
            aimPoint={aimPoint}
            areaKeys={areaKeys}
            campaignId={campaignId}
            combatId={combatId}
            fighters={ordered}
            interactionMode={gridInteractionMode}
            onAimPointChange={setAimPoint}
            onInteractionModeChange={setGridInteractionMode}
            onSpawnVfx={spawnVfx}
            onTargetSelect={(id) => {
              setSelectedMapTargetId(id);
              setPromptTargetId(id);
            }}
            positions={positions}
            selectedTargetId={selectedMapTargetId}
            targeting={targetingRange}
            vfxEvents={vfxEvents}
          />

          {/* Quick HP Adjustment Strip for All Fighters */}
          <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3 shadow-md">
            <span className="text-2xs font-semibold uppercase tracking-wider text-parchment-200">
              ⚡ 快速生命值微调器 (DM HP Adjuster)
            </span>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {ordered.slice(0, 6).map((f) => (
                <div className="flex items-center justify-between rounded-lg border border-ink-800 bg-ink-950/60 p-2 text-2xs" key={f.id}>
                  <div className="min-w-0 pr-2">
                    <strong className="truncate block text-stone-200">{f.display_name}</strong>
                    <span className="text-stone-400">HP: {f.hp}/{f.max_hp} · ▲{combatantElevationFt(f)}尺</span>
                  </div>
                  <div className="flex gap-1">
                    <button
                      className="rounded border border-rose-900 bg-rose-950/50 px-1.5 py-0.5 text-rose-300 hover:bg-rose-900"
                      onClick={() => quickHpAdjustMutation.mutate({ combatant: f, delta: -5 })}
                    >
                      -5
                    </button>
                    <button
                      className="rounded border border-rose-900 bg-rose-950/50 px-1.5 py-0.5 text-rose-300 hover:bg-rose-900"
                      onClick={() => quickHpAdjustMutation.mutate({ combatant: f, delta: -1 })}
                    >
                      -1
                    </button>
                    <button
                      className="rounded border border-emerald-900 bg-emerald-950/50 px-1.5 py-0.5 text-emerald-300 hover:bg-emerald-900"
                      onClick={() => quickHpAdjustMutation.mutate({ combatant: f, delta: 1 })}
                    >
                      +1
                    </button>
                    <button
                      className="rounded border border-emerald-900 bg-emerald-950/50 px-1.5 py-0.5 text-emerald-300 hover:bg-emerald-900"
                      onClick={() => quickHpAdjustMutation.mutate({ combatant: f, delta: 5 })}
                    >
                      +5
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Column: ⚔️ 规则积木指令台 & 法术位 & AI 战术副驾 (6 Cols) */}
        <div className="flex flex-col gap-3 lg:col-span-6">
          {/* Complete Rule Block Turn Command Console */}
          {activeFighter ? (
            <div className="rounded-xl border border-amber-600/50 bg-ink-900/90 p-3.5 shadow-xl">
              <TurnCommandConsole
                active={activeFighter}
                activeCharacter={activeCharacter}
                autoEnemies={autoEnemies}
                automationReady={true}
                campaignId={campaignId}
                combatActions={actionsQuery.data ?? []}
                combatId={combatId}
                fighters={ordered}
                key={`${combatId}:${activeFighter.id}`}
                onAutoEnemiesChange={setAutoEnemies}
                onEnemyTurnComplete={() => {
                  advanceTurnMutation.mutate();
                }}
                onRangeChange={handleRangeChange}
                onTargetChange={handleTargetChange}
                selectedTargetId={selectedMapTargetId}
                targetingValidity={targetingValidity}
                turnKey={`${activeCombat.round_number}:${activeCombat.current_turn_index ?? 0}:${activeFighter.id}`}
              />
            </div>
          ) : (
            <div className="rounded-xl border border-ink-800 bg-ink-900/40 p-6 text-center text-xs text-stone-500">
              当前回合无行动战斗员
            </div>
          )}

          {/* Player Rolls Queue */}
          <PlayerRollPanel
            actions={actionsQuery.data ?? []}
            activeEnemy={activeFighter?.entity_type === "monster" ? activeFighter : undefined}
            automationEnabled={autoEnemies}
            campaignId={campaignId}
            combatId={combatId}
            fighters={ordered}
            onResolved={() => {
              void queryClient.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
            }}
          />

          {/* Bottom Grid: 🎲 Dice Roller & 🤖 AI Tactical Copilot */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {/* Quick Dice Roller */}
            <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3 shadow-md">
              <div className="flex items-center justify-between border-b border-ink-800 pb-1.5">
                <span className="text-xs font-bold text-parchment-200">🎲 极速骰盘</span>
                <div className="flex items-center gap-1">
                  <span className="text-2xs text-stone-400">调整:</span>
                  <input
                    className="w-10 rounded border border-ink-700 bg-ink-950 px-1 py-0.5 text-center font-mono text-xs text-amber-200"
                    onChange={(e) => setCustomDiceMod(e.target.value)}
                    type="number"
                    value={customDiceMod}
                  />
                </div>
              </div>
              <div className="mt-2 grid grid-cols-4 gap-1">
                {[20, 12, 10, 8, 6, 4].map((d) => (
                  <button
                    className="rounded border border-ink-700 bg-ink-950/80 py-1 text-xs font-bold text-stone-300 hover:border-amber-500 hover:text-amber-200"
                    key={d}
                    onClick={() => rollDice(d)}
                    type="button"
                  >
                    d{d}
                  </button>
                ))}
                <button
                  className="col-span-2 rounded border border-amber-800/60 bg-amber-950/30 py-1 text-xs font-bold text-amber-300 hover:bg-amber-900/40"
                  onClick={() => rollDice(6, 2)}
                  type="button"
                >
                  2d6
                </button>
              </div>

              {diceHistory.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1 border-t border-ink-800/60 pt-1.5">
                  {diceHistory.slice(0, 3).map((r) => (
                    <span
                      className={`rounded border px-1.5 py-0.5 font-mono text-2xs ${
                        r.isCrit ? "border-amber-500 bg-amber-500/20 text-amber-200 font-bold" : "border-ink-800 bg-ink-950 text-stone-300"
                      }`}
                      key={r.id}
                    >
                      {r.formula}➔<strong>{r.result}</strong>
                    </span>
                  ))}
                </div>
              ) : null}
            </div>

            {/* AI Tactical Copilot */}
            <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3 shadow-md flex flex-col justify-between">
              <div className="flex items-center justify-between border-b border-ink-800 pb-1.5">
                <span className="text-xs font-bold text-parchment-200">🤖 AI 战术军师</span>
                <div className="flex gap-1">
                  <button
                    className="rounded border border-amber-700/60 bg-amber-950/30 px-1.5 py-0.5 text-2xs text-amber-300 hover:bg-amber-900/40 disabled:opacity-50"
                    disabled={aiTacticsMutation.isPending}
                    onClick={() => aiTacticsMutation.mutate()}
                    type="button"
                  >
                    {aiTacticsMutation.isPending ? "思考中…" : "战术建议"}
                  </button>
                  <button
                    className="rounded border border-sky-700/60 bg-sky-950/30 px-1.5 py-0.5 text-2xs text-sky-300 hover:bg-sky-900/40 disabled:opacity-50"
                    disabled={aiNarrativeMutation.isPending}
                    onClick={() => aiNarrativeMutation.mutate()}
                    type="button"
                  >
                    {aiNarrativeMutation.isPending ? "构思中…" : "战况朗读"}
                  </button>
                </div>
              </div>

              <div className="mt-1.5 min-h-[50px] max-h-28 overflow-y-auto text-2xs text-stone-300">
                {aiAnalysis ? <p className="text-amber-200/90 leading-relaxed">{aiAnalysis}</p> : null}
                {aiNarrative ? <p className="font-serif text-sky-200/90 italic leading-relaxed">{aiNarrative}</p> : null}
                {!aiAnalysis && !aiNarrative ? <p className="text-stone-500 py-2 text-center">点击按钮获取 AI 决策与旁白</p> : null}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Add Combatant Modal */}
      {showAddCombatantModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-ink-700 bg-ink-900 p-6 shadow-2xl">
            <h3 className="font-display text-base font-bold text-parchment-100">添加参战者 / 怪物</h3>
            <div className="mt-4 space-y-3">
              <div>
                <label className="text-xs text-stone-400">战斗员名称</label>
                <input
                  className={`${inputCls} mt-1`}
                  onChange={(e) => setNewCombatantName(e.target.value)}
                  placeholder="如：地精巫师 / 守卫长"
                  value={newCombatantName}
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-stone-400">阵营类型</label>
                  <select
                    className={`${selectCls} mt-1`}
                    onChange={(e) => setNewCombatantType(e.target.value as "character" | "monster" | "npc")}
                    value={newCombatantType}
                  >
                    <option value="monster">👹 怪物 (Monster)</option>
                    <option value="character">🛡️ 玩家角色 (PC)</option>
                    <option value="npc">👤 NPC / 友军</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-stone-400">初始先攻</label>
                  <input
                    className={`${inputCls} mt-1`}
                    onChange={(e) => setNewCombatantInit(e.target.value)}
                    type="number"
                    value={newCombatantInit}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-stone-400">生命上限 HP</label>
                  <input
                    className={`${inputCls} mt-1`}
                    onChange={(e) => setNewCombatantHp(e.target.value)}
                    type="number"
                    value={newCombatantHp}
                  />
                </div>
                <div>
                  <label className="text-xs text-stone-400">护甲等级 AC</label>
                  <input
                    className={`${inputCls} mt-1`}
                    onChange={(e) => setNewCombatantAc(e.target.value)}
                    type="number"
                    value={newCombatantAc}
                  />
                </div>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button onClick={() => setShowAddCombatantModal(false)} variant="ghost">取消</Button>
              <Button
                onClick={async () => {
                  if (!newCombatantName.trim()) return;
                  await createCombatant(campaignId, combatId, {
                    display_name: newCombatantName.trim(),
                    entity_type: newCombatantType,
                    hp: Number(newCombatantHp) || 10,
                    max_hp: Number(newCombatantHp) || 10,
                    armor_class: Number(newCombatantAc) || 10,
                    initiative: Number(newCombatantInit) || 10,
                    conditions: [],
                    snapshot_json: {
                      actions: [],
                      row: Math.floor(Math.random() * 5) + 2,
                      col: Math.floor(Math.random() * 8) + 2,
                      elevation_ft: 0,
                    },
                  });
                  setShowAddCombatantModal(false);
                  setNewCombatantName("");
                  void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
                  showToast("👥 战斗员已加入战场！", "success");
                }}
                variant="primary"
              >
                加入战场
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function QuickCombatPage(): ReactElement {
  return (
    <RequireCampaign>
      {(campaignId) => <QuickCombatCockpit campaignId={campaignId} />}
    </RequireCampaign>
  );
}
