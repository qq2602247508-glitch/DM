import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactElement } from "react";

import {
  createCombat, createCombatant, deleteCombatant, listCombatants, listCombats,
  listEvents, updateCombat, updateCombatant,
} from "../api/entities";
import { listCharacters, listNpcs, updateCharacter } from "../api/entities";
import { listMonsters, listScenes } from "../api/world";
import type { Combat, Combatant, Character, Monster, Npc, SceneGrid } from "../api/types";
import { RequireCampaign } from "../components/RequireCampaign";
import { Panel } from "../components/Panel";
import { inputCls } from "../ui/styles";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { COMBAT_STATUS_LABELS } from "../ui/styles";
import { HpBar } from "../ui/widgets";
import { useToast } from "../hooks/toastContext";
import { navigate } from "../hooks/useHashRoute";
import {
  DIFFICULTY_LABELS, encounterDifficulty, shiftDifficulty, xpForChallengeRating,
  type Difficulty,
} from "../ui/progressionRules";

type CombatCandidate = {
  key: string;
  entityType: "character" | "npc" | "monster";
  entityId: string;
  name: string;
  armorClass: number;
  hp: number;
  maxHp: number;
  dexterity: number;
  speed: number;
  character?: Character;
  challengeRating?: string | null;
};

function readSceneGrid(notes: string | null): SceneGrid | null {
  if (!notes) return null;
  try {
    return (JSON.parse(notes) as { scene_grid?: SceneGrid }).scene_grid ?? null;
  } catch {
    return null;
  }
}

function CombatantRow({ campaignId, combat, fighter, current, character }: { campaignId: string; combat: Combat; fighter: Combatant; current: boolean; character?: Character }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [amount, setAmount] = useState("1");
  const [condition, setCondition] = useState("");
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["combatants", campaignId, combat.id] });
    void client.invalidateQueries({ queryKey: ["campaign-state", campaignId] });
  };
  const change = useMutation({
    mutationFn: (payload: { hp?: number; conditions?: unknown[] }) => updateCombatant(campaignId, combat.id, fighter.id, payload, fighter.version),
    onSuccess: () => { invalidate(); showToast("战斗状态已更新"); },
    onError: () => showToast("战斗状态更新失败", "error"),
  });
  const remove = useMutation({
    mutationFn: () => deleteCombatant(campaignId, combat.id, fighter.id, fighter.version),
    onSuccess: () => { invalidate(); showToast("参与者已移除"); },
    onError: () => showToast("参与者移除失败", "error"),
  });
  const spendResource = useMutation({
    mutationFn: (key: string) => {
      if (!character) throw new Error("没有关联角色");
      const resource = character.resources[key] as { current?: number; max?: number; label?: string; recovery?: string } | undefined;
      if (!resource || Number(resource.current ?? 0) <= 0) throw new Error("资源不足");
      return updateCharacter(campaignId, character.id, {
        resources: { ...character.resources, [key]: { ...resource, current: Number(resource.current ?? 0) - 1 } },
      }, character.version);
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      showToast("角色资源已消耗并同步到角色卡");
    },
    onError: () => showToast("资源消耗失败，请刷新角色状态", "error"),
  });
  return (
    <li className={`grid gap-2 rounded-md border px-3 py-2 md:grid-cols-[3rem_1fr_12rem_auto] md:items-center ${current ? "border-ember-500/50 bg-ember-500/5" : "border-ink-700 bg-ink-950/40"}`}>
      <span className="text-center"><strong className="block font-mono text-sm text-ember-300">{fighter.initiative}</strong><span className="block text-2xs text-stone-600">先攻</span></span>
      <div className="min-w-0">
        <p className="m-0 truncate text-sm text-parchment-100">{fighter.display_name}</p>
        <p className="mb-0 mt-0.5 text-2xs text-stone-600">护甲 AC {fighter.armor_class} · {fighter.entity_type === "character" ? "玩家" : fighter.entity_type === "npc" ? "NPC" : "其他"}{fighter.conditions.length > 0 ? ` · 状态：${fighter.conditions.join("、")}` : ""}</p>
      </div>
      <HpBar hp={fighter.hp} maxHp={fighter.max_hp} />
      <div className="flex flex-wrap justify-end gap-1">
        <input aria-label={`${fighter.display_name} 数值`} className="w-14 rounded border border-ink-600 bg-ink-950 px-1.5 py-1 text-xs text-parchment-100" min="1" onChange={(event) => setAmount(event.target.value)} type="number" value={amount} />
        <Button disabled={change.isPending || fighter.hp <= 0} onClick={() => change.mutate({ hp: Math.max(0, fighter.hp - Number(amount)) })} size="sm">伤害</Button>
        <Button disabled={change.isPending || fighter.hp >= fighter.max_hp} onClick={() => change.mutate({ hp: Math.min(fighter.max_hp, fighter.hp + Number(amount)) })} size="sm">治疗</Button>
        <input aria-label={`${fighter.display_name} 条件`} className="w-20 rounded border border-ink-600 bg-ink-950 px-1.5 py-1 text-xs text-parchment-100" onChange={(event) => setCondition(event.target.value)} placeholder="条件" value={condition} />
        <Button disabled={!condition.trim() || change.isPending} onClick={() => { change.mutate({ conditions: [...fighter.conditions, condition.trim()] }); setCondition(""); }} size="sm">加状态</Button>
        <Button disabled={remove.isPending} onClick={() => remove.mutate()} size="sm" variant="danger">移除</Button>
      </div>
      {character ? (
        <div className="border-t border-ink-700/70 pt-2 md:col-span-4">
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(character.resources).map(([key, raw]) => {
              const resource = raw as { label?: string; current?: number; max?: number };
              return <Button disabled={Number(resource.current ?? 0) <= 0 || spendResource.isPending} key={key} onClick={() => spendResource.mutate(key)} size="sm">{resource.label ?? key} {resource.current ?? 0}/{resource.max ?? 0} · 消耗1</Button>;
            })}
          </div>
          {character.actions.length > 0 ? <div className="mt-2 grid gap-1 sm:grid-cols-2">{character.actions.map((raw, index) => { const action = raw as { name?: string; damage?: string; range?: string; cost?: string; description?: string }; return <div className="rounded border border-ink-700 bg-ink-950/60 px-2 py-1.5 text-2xs text-stone-400" key={`${action.name ?? "动作"}-${index}`}><strong className="text-parchment-100">{action.name ?? "动作"}</strong>{action.damage ? ` · ${action.damage}` : ""}{action.range ? ` · ${action.range}` : ""}<br />{action.cost ?? "动作"} · {action.description ?? ""}</div>; })}</div> : null}
        </div>
      ) : null}
    </li>
  );
}

function BattleGrid({ fighters, grid, candidates }: { fighters: Combatant[]; grid: SceneGrid | null; candidates: CombatCandidate[] }): ReactElement {
  const width = grid?.width ?? 12;
  const height = grid?.height ?? 8;
  const [positions, setPositions] = useState<Record<string, [number, number]>>({});
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    setPositions((current) => {
      const next = { ...current };
      fighters.forEach((fighter, index) => {
        if (!next[fighter.id]) next[fighter.id] = [Math.floor(index / 4) + 1, (index % 4) + 1];
      });
      return next;
    });
  }, [fighters]);
  const selectedPosition = selected ? positions[selected] : null;
  const selectedFighter = fighters.find((fighter) => fighter.id === selected);
  const selectedSpeed = candidates.find((candidate) => candidate.entityId === selectedFighter?.entity_id)?.speed ?? 30;
  const distance = (row: number, col: number) => selectedPosition ? (Math.abs(row - selectedPosition[0]) + Math.abs(col - selectedPosition[1])) * 5 : null;
  const tokenAt = (row: number, col: number) => fighters.find((fighter) => {
    const position = positions[fighter.id];
    return position?.[0] === row && position[1] === col;
  });
  return (
    <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/50 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-parchment-100">战斗场景网格</span>
        <span className="text-2xs text-stone-500">每格 5 尺 · 绿色方块为掩体 · 点击单位后点击目标格移动</span>
        {selected ? <span className="ml-auto text-2xs text-ember-300">已选：{fighters.find((fighter) => fighter.id === selected)?.display_name}</span> : null}
      </div>
      <div className="grid max-w-[720px] gap-px overflow-hidden rounded border border-ink-700 bg-ink-700" style={{ gridTemplateColumns: `repeat(${width}, minmax(0, 1fr))` }}>
        {Array.from({ length: height }, (_, row) => Array.from({ length: width }, (_, col) => {
          const rowNumber = row + 1;
          const colNumber = col + 1;
          const fighter = tokenAt(rowNumber, colNumber);
          const sceneCell = grid?.cells.find((cell) => cell.row === rowNumber && cell.col === colNumber);
          const blocked = sceneCell?.kind === "wall";
          const moveDistance = distance(rowNumber, colNumber);
          const canMove = Boolean(selected && !fighter && !blocked && moveDistance !== null && moveDistance <= selectedSpeed);
          const terrainClass = sceneCell?.kind === "wall" ? "bg-stone-700" : sceneCell?.kind === "cover" ? "bg-emerald-900/80" : sceneCell?.kind === "door" ? "bg-amber-800/80" : sceneCell?.kind === "object" ? "bg-violet-900/80" : "bg-ink-950/80";
          return (
            <button
              className={`relative aspect-square min-h-8 text-2xs transition-colors ${terrainClass} ${canMove ? "hover:bg-ember-500/30" : ""}`}
              key={`${rowNumber}-${colNumber}`}
              onClick={() => {
                if (fighter) setSelected(fighter.id);
                else if (canMove && selected) setPositions((current) => ({ ...current, [selected]: [rowNumber, colNumber] }));
              }}
              title={sceneCell?.label ?? (moveDistance === null ? "选择一个单位" : `${moveDistance} 尺`)}
              type="button"
            >
              {fighter ? <span className={`mx-auto flex h-6 w-6 items-center justify-center rounded-full text-2xs font-bold ${selected === fighter.id ? "bg-ember-400 text-ink-950" : "bg-violet-500/80 text-white"}`}>{fighter.display_name.slice(0, 1)}</span> : null}
              {!fighter && sceneCell ? <span className="text-stone-200">{sceneCell.kind === "wall" ? "■" : sceneCell.kind === "door" ? "门" : sceneCell.kind === "cover" ? "▦" : "◆"}</span> : null}
            </button>
          );
        }))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-stone-500">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-violet-500/80" />单位</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-emerald-900" />掩体</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-stone-700" />墙体</span>
        <span>当前单位移动上限：{selected ? `${selectedSpeed}尺（${Math.floor(selectedSpeed / 5)}格）` : "选择单位后显示"}</span>
      </div>
    </div>
  );
}

function CombatCard({ campaignId, combat, candidates, grid, sceneName, sceneAdjustments }: { campaignId: string; combat: Combat; candidates: CombatCandidate[]; grid: SceneGrid | null; sceneName: string | null; sceneAdjustments: { shift: number; reason: string }[] }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [name, setName] = useState("");
  const [initiative, setInitiative] = useState("10");
  const [armorClass, setArmorClass] = useState("10");
  const [hp, setHp] = useState("10");
  const [selectedKey, setSelectedKey] = useState("");
  const [xpOverride, setXpOverride] = useState("");
  const fighters = useQuery({
    queryKey: ["combatants", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatants(campaignId, combat.id, signal),
  });
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["combats", campaignId] });
    void client.invalidateQueries({ queryKey: ["combatants", campaignId, combat.id] });
    void client.invalidateQueries({ queryKey: ["campaign-state", campaignId] });
  };
  const selectedCandidate = candidates.find((candidate) => candidate.key === selectedKey);
  const selectCandidate = (key: string) => {
    setSelectedKey(key);
    const candidate = candidates.find((item) => item.key === key);
    if (!candidate) return;
    setName(candidate.name);
    setArmorClass(String(candidate.armorClass));
    setHp(String(candidate.hp || candidate.maxHp));
    const dexterityModifier = Math.floor((candidate.dexterity - 10) / 2);
    setInitiative(String(Math.floor(Math.random() * 20) + 1 + dexterityModifier));
  };
  const add = useMutation({
    mutationFn: () => createCombatant(campaignId, combat.id, {
      display_name: name.trim(), entity_type: selectedCandidate?.entityType ?? "custom",
      entity_id: selectedCandidate?.entityId ?? null,
      initiative: Number(initiative), armor_class: Number(armorClass),
      hp: Number(hp), max_hp: Number(hp), is_active: true,
    }),
    onSuccess: () => { setName(""); invalidate(); showToast("参与者已加入战斗"); },
    onError: () => showToast("添加参与者失败", "error"),
  });
  const update = useMutation({
    mutationFn: (payload: { status?: string; round_number?: number; current_turn_index?: number; difficulty?: Difficulty; base_xp?: number; difficulty_adjustments?: unknown[] }) =>
      updateCombat(campaignId, combat.id, payload, combat.version),
    onSuccess: () => { invalidate(); showToast("战斗进度已保存"); },
    onError: () => showToast("战斗进度保存失败", "error"),
  });
  const ordered = [...(fighters.data ?? [])].sort((a, b) => b.initiative - a.initiative || a.display_name.localeCompare(b.display_name));
  const playerCharacters = ordered
    .filter((fighter) => fighter.entity_type === "character" && fighter.entity_id)
    .map((fighter) => candidates.find((candidate) => candidate.entityType === "character" && candidate.entityId === fighter.entity_id)?.character)
    .filter((character): character is Character => Boolean(character));
  const monsterXp = ordered
    .filter((fighter) => fighter.entity_type === "monster")
    .reduce((sum, fighter) => {
      const candidate = candidates.find((item) => item.entityType === "monster" && item.entityId === fighter.entity_id);
      return sum + xpForChallengeRating(candidate?.challengeRating);
    }, 0);
  const baseDifficulty = encounterDifficulty(playerCharacters.map((character) => character.level), monsterXp);
  const sceneShift = sceneAdjustments.reduce((sum, adjustment) => sum + adjustment.shift, 0);
  const manualShift = combat.difficulty_adjustments.reduce<number>((sum, raw) => {
    const adjustment = raw as { shift?: number };
    return sum + Number(adjustment.shift ?? 0);
  }, 0);
  const finalDifficulty = shiftDifficulty(baseDifficulty, sceneShift + manualShift);
  const distributableXp = Math.max(0, Number(xpOverride || combat.base_xp || monsterXp));
  const xpPerCharacter = playerCharacters.length > 0 ? Math.floor(distributableXp / playerCharacters.length) : 0;
  const manualAdjustment = useMutation({
    mutationFn: (shift: -1 | 1) => updateCombat(campaignId, combat.id, {
      difficulty: shiftDifficulty(finalDifficulty, shift),
      base_xp: combat.base_xp || monsterXp,
      difficulty_adjustments: [...combat.difficulty_adjustments, {
        shift,
        reason: shift < 0 ? "DM手动降低一级" : "DM手动提高一级",
        created_at: new Date().toISOString(),
      }],
    }, combat.version),
    onSuccess: () => { invalidate(); showToast("DM难度修正已保存"); },
    onError: () => showToast("难度修正保存失败，请刷新后重试", "error"),
  });
  const awardExperience = useMutation({
    mutationFn: async () => {
      if (combat.xp_awarded) throw new Error("该战斗已经发放经验");
      if (playerCharacters.length === 0 || xpPerCharacter <= 0) throw new Error("没有可发放的参与玩家或经验值");
      for (const character of playerCharacters) {
        await updateCharacter(campaignId, character.id, {
          experience: character.experience + xpPerCharacter,
        }, character.version);
      }
      return updateCombat(campaignId, combat.id, {
        xp_awarded: true,
        base_xp: distributableXp,
        difficulty: finalDifficulty,
      }, combat.version);
    },
    onSuccess: () => {
      invalidate();
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      showToast(`战斗经验已发放：每名参与玩家 ${xpPerCharacter} XP`);
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "经验发放失败", "error"),
  });
  const nextIndex = ordered.length === 0 ? 0 : (combat.current_turn_index + 1) % ordered.length;
  const nextRound = ordered.length > 0 && nextIndex === 0 ? combat.round_number + 1 : combat.round_number;
  return (
    <Panel eyebrow={`第 ${combat.round_number} 轮 · 回合 ${combat.current_turn_index + 1}`} title={combat.name}>
      <p className="mb-3 mt-0 text-2xs text-stone-500">战斗场景：{sceneName ?? "未绑定场景"}{grid ? ` · 已加载 ${grid.theme} 网格` : " · 使用临时通用网格"}</p>
      <div className="mb-3 grid gap-2 rounded-lg border border-ink-700 bg-ink-950/50 p-3 md:grid-cols-[1fr_auto]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <strong className="text-sm text-parchment-100">遭遇难度：{DIFFICULTY_LABELS[finalDifficulty]}</strong>
            <Badge tone={finalDifficulty === "high" ? "danger" : finalDifficulty === "moderate" ? "warn" : finalDifficulty === "low" || finalDifficulty === "trivial" ? "ok" : "neutral"}>{finalDifficulty}</Badge>
          </div>
          <p className="mb-0 mt-1 text-2xs text-stone-500">队伍：{playerCharacters.length ? playerCharacters.map((character) => `${character.name} Lv${character.level}`).join("、") : "尚无玩家"} · 怪物基础 XP：{monsterXp} · 基础判定：{DIFFICULTY_LABELS[baseDifficulty]}</p>
          {sceneAdjustments.length > 0 ? <ul className="mb-0 mt-2 pl-4 text-2xs text-emerald-300">{sceneAdjustments.map((item, index) => <li key={`${item.reason}-${index}`}>{item.shift < 0 ? "降低" : "提高"}一级：{item.reason}</li>)}</ul> : <p className="mb-0 mt-1 text-2xs text-stone-600">推进台没有记录玩家准备或敌方优势修正。</p>}
          <p className="mb-0 mt-1 text-2xs text-stone-600">难度估算综合角色等级、怪物 CR/XP 与情景修正；行动经济、地形和资源消耗仍由 DM 最终判断。</p>
        </div>
        <div className="flex gap-1.5 md:flex-col">
          <Button disabled={manualAdjustment.isPending} onClick={() => manualAdjustment.mutate(-1)} size="sm">DM 降一级</Button>
          <Button disabled={manualAdjustment.isPending} onClick={() => manualAdjustment.mutate(1)} size="sm">DM 升一级</Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Badge tone={combat.status === "active" ? "danger" : "neutral"}>{COMBAT_STATUS_LABELS[combat.status] ?? combat.status}</Badge>
        <div className="flex gap-2">
          <Button disabled={combat.status !== "active" || ordered.length === 0 || update.isPending} onClick={() => update.mutate({ round_number: nextRound, current_turn_index: nextIndex })} size="sm" variant="primary">下一回合</Button>
          <Button disabled={combat.status !== "active" || update.isPending} onClick={() => update.mutate({ status: "ended" })} size="sm">结束战斗</Button>
          {combat.status === "ended" && combat.scene_id ? <Button onClick={() => navigate("/game-table")} size="sm" variant="primary">返回游戏推进台</Button> : null}
        </div>
      </div>
      {combat.status === "active" ? (
        <>
          <p className="mb-2 mt-3 text-2xs text-stone-500">先攻 = d20 + 敏捷调整值；这里填写最终先攻结果。AC 是护甲等级，HP 是生命值。</p>
          <form className="grid gap-2 md:grid-cols-[1fr_6rem_6rem_6rem_auto]" onSubmit={(event: FormEvent) => { event.preventDefault(); if (name.trim()) add.mutate(); }}>
            <label className="text-2xs text-stone-500">从原子选择（自动填充）<select className={`${inputCls} mt-1`} onChange={(event) => selectCandidate(event.target.value)} value={selectedKey}><option value="">手动录入</option>{candidates.map((candidate) => <option key={candidate.key} value={candidate.key}>{candidate.entityType === "character" ? "玩家" : candidate.entityType === "npc" ? "NPC" : "怪物"} · {candidate.name}</option>)}</select></label>
            <label className="text-2xs text-stone-500">参与者名称<input className={`${inputCls} mt-1`} onChange={(event) => setName(event.target.value)} placeholder="例如：大妞 / 哥布林" value={name} /></label>
            <label className="text-2xs text-stone-500">先攻总值<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setInitiative(event.target.value)} type="number" value={initiative} /></label>
            <label className="text-2xs text-stone-500">护甲 AC<input className={`${inputCls} mt-1`} max="99" min="0" onChange={(event) => setArmorClass(event.target.value)} type="number" value={armorClass} /></label>
            <label className="text-2xs text-stone-500">生命 HP<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setHp(event.target.value)} type="number" value={hp} /></label>
            <Button disabled={!name.trim() || Number(hp) < 1} icon="plus" loading={add.isPending} type="submit">添加</Button>
          </form>
        </>
      ) : null}
      <div className="mt-3">
        {fighters.isLoading ? <LoadingBlock label="正在读取先攻列表…" /> : null}
        {fighters.isError ? <ErrorState error={fighters.error} onRetry={() => void fighters.refetch()} /> : null}
        {!fighters.isLoading && ordered.length === 0 ? <EmptyState title="尚无参与者" hint="录入先攻与 HP 后即可开始逐回合追踪。" /> : null}
        {ordered.length > 0 ? <ol className="m-0 flex list-none flex-col gap-1.5 p-0">{ordered.map((fighter, index) => <CombatantRow campaignId={campaignId} character={candidates.find((candidate) => candidate.entityId === fighter.entity_id)?.character} combat={combat} current={combat.status === "active" && index === combat.current_turn_index} fighter={fighter} key={fighter.id} />)}</ol> : null}
      </div>
      {ordered.length > 0 ? <BattleGrid candidates={candidates} fighters={ordered} grid={grid} /> : null}
      {combat.status === "ended" ? (
        <div className="mt-4 rounded-lg border border-amber-800/50 bg-amber-950/10 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-auto text-sm text-parchment-100">战斗经验结算</strong>
            <Badge tone={combat.xp_awarded ? "ok" : "warn"}>{combat.xp_awarded ? "已发放" : "等待 DM 确认"}</Badge>
          </div>
          <p className="mb-2 mt-2 text-xs text-stone-400">参与玩家：{playerCharacters.map((character) => character.name).join("、") || "无"}。总经验由怪物 CR 换算，可由 DM 修改；确认后平均分配且此战斗不能重复发放。</p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-2xs text-stone-500">总 XP<input className={`${inputCls} mt-1 w-32`} disabled={combat.xp_awarded} min="0" onChange={(event) => setXpOverride(event.target.value)} type="number" value={xpOverride || String(combat.base_xp || monsterXp)} /></label>
            <span className="pb-2 text-xs text-ember-300">每名玩家 {xpPerCharacter} XP</span>
            <Button disabled={combat.xp_awarded || playerCharacters.length === 0 || xpPerCharacter <= 0} loading={awardExperience.isPending} onClick={() => awardExperience.mutate()} variant="primary">DM 确认发放经验</Button>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

function CombatContent({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [name, setName] = useState("");
  const [sceneId, setSceneId] = useState("");
  const combats = useQuery({ queryKey: ["combats", campaignId], queryFn: ({ signal }) => listCombats(campaignId, signal) });
  const scenes = useQuery({ queryKey: ["scenes", campaignId], queryFn: ({ signal }) => listScenes(campaignId, signal) });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const npcs = useQuery({ queryKey: ["npcs", campaignId], queryFn: ({ signal }) => listNpcs(campaignId, signal) });
  const monsters = useQuery({ queryKey: ["monsters", campaignId], queryFn: ({ signal }) => listMonsters(campaignId, signal) });
  const events = useQuery({ queryKey: ["events", campaignId], queryFn: ({ signal }) => listEvents(campaignId, signal) });
  const candidates: CombatCandidate[] = [
    ...(characters.data ?? []).map((entity: Character) => ({ key: `character:${entity.id}`, entityType: "character" as const, entityId: entity.id, name: entity.name, armorClass: entity.armor_class, hp: entity.hp, maxHp: entity.max_hp, dexterity: entity.ability_scores.dexterity ?? 10, speed: entity.speed, character: entity })),
    ...(npcs.data ?? []).map((entity: Npc) => ({ key: `npc:${entity.id}`, entityType: "npc" as const, entityId: entity.id, name: entity.name, armorClass: entity.armor_class, hp: entity.hp, maxHp: entity.max_hp, dexterity: entity.ability_scores.dexterity ?? 10, speed: entity.speed, challengeRating: entity.challenge_rating })),
    ...(monsters.data ?? []).map((entity: Monster) => ({ key: `monster:${entity.id}`, entityType: "monster" as const, entityId: entity.id, name: entity.name, armorClass: entity.armor_class, hp: entity.hp, maxHp: entity.max_hp, dexterity: entity.ability_scores.dexterity ?? 10, speed: entity.speed, challengeRating: entity.challenge_rating })),
  ];
  const create = useMutation({
    mutationFn: () => createCombat(campaignId, { name: name.trim(), scene_id: sceneId || null, status: "active" }),
    onSuccess: () => { setName(""); void client.invalidateQueries({ queryKey: ["combats", campaignId] }); showToast("战斗已创建并加载场景网格"); },
    onError: () => showToast("创建战斗失败", "error"),
  });
  return (
    <div className="mx-auto max-w-[1100px] p-4 lg:p-6">
      <Panel eyebrow="遭遇" title="战斗辅助">
        <form className="grid gap-2 md:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => { event.preventDefault(); if (name.trim()) create.mutate(); }}>
          <input className={inputCls} onChange={(event) => setName(event.target.value)} placeholder="战斗名称，例如：城门伏击" value={name} />
          <select className={inputCls} onChange={(event) => setSceneId(event.target.value)} value={sceneId}><option value="">必须选择战斗场景</option>{scenes.data?.map((scene) => <option key={scene.id} value={scene.id}>{scene.name}{readSceneGrid(scene.notes) ? " · 有网格" : ""}</option>)}</select>
          <Button disabled={!name.trim() || !sceneId} loading={create.isPending} icon="plus" type="submit" variant="primary">创建战斗</Button>
        </form>
      </Panel>
      <div className="mt-4 flex flex-col gap-3">
        {combats.isLoading ? <Panel title="战斗"><LoadingBlock /></Panel> : null}
        {combats.isError ? <Panel title="战斗"><ErrorState error={combats.error} onRetry={() => void combats.refetch()} /></Panel> : null}
        {!combats.isLoading && !combats.isError && combats.data?.length === 0 ? <Panel title="战斗"><EmptyState title="暂无战斗" hint="创建战斗后可以追踪先攻、HP、轮次和当前回合。" /></Panel> : null}
        {combats.data?.map((combat) => {
          const scene = scenes.data?.find((item) => item.id === combat.scene_id);
          const sceneAdjustments = (events.data ?? [])
            .filter((event) => event.metadata_json.scene_id === combat.scene_id && Number(event.metadata_json.encounter_adjustment ?? 0) !== 0)
            .map((event) => {
              const rawReason = event.metadata_json.encounter_reason;
              return {
                shift: Number(event.metadata_json.encounter_adjustment ?? 0),
                reason: typeof rawReason === "string" ? rawReason : (event.description ?? event.title),
              };
            });
          return <CombatCard campaignId={campaignId} combat={combat} candidates={candidates} grid={scene ? readSceneGrid(scene.notes) : null} key={combat.id} sceneAdjustments={sceneAdjustments} sceneName={scene?.name ?? null} />;
        })}
      </div>
    </div>
  );
}

export function CombatPage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <CombatContent campaignId={campaignId} />}</RequireCampaign>;
}
