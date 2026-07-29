import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import {
  attackWithMyCombatant,
  bindMyCharacter,
  createMyCharacter,
  endMyTurn,
  getMyPlayerRoom,
  isPlayerSessionMissing,
  joinPlayerRoom,
  logoutPlayerRoom,
  moveMyCombatant,
  planMyNoncombatAction,
  rollMyNoncombatAction,
  searchPlayerRules,
  submitMyActionRequest,
  submitMyPlayerRoll,
  switchPlayerRoom,
  type PlayerRoomSnapshot,
  type PlayerCombatant,
  type PlayerCombatSnapshot,
  type SafePlayerCharacter,
} from "../api/playerRoom";
import { getCharacterOptions } from "../api/entities";
import {
  BACKGROUNDS_2024, CLASSES_2024, SPECIES_2024,
  classSkillSelection, spellChoiceCounts, spellChoicesComplete,
  spellIsAvailable, spellSelectionRule, spellToCharacterAction,
} from "../ui/characterRules";
import { Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { SceneMap } from "../components/SceneMap";
import { PlayerEquipmentPanel } from "../components/player/PlayerEquipmentPanel";
import { useOffline } from "../hooks/useOffline";
import { usePlayerRealtime } from "../hooks/useRealtimeInvalidation";
import {
  getTargetingCells,
  gridDistanceFt,
  hasLineOfSight,
  type TargetingTemplate,
} from "../ui/gridTargeting";
import { targetingFromRulePlan } from "../ui/ruleBlocks";

const ABILITIES: Record<string, string> = {
  strength: "力量",
  dexterity: "敏捷",
  constitution: "体质",
  intelligence: "智力",
  wisdom: "感知",
  charisma: "魅力",
};
const inputCls = "w-full rounded border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-parchment-100 outline-none focus:border-amber-500";
const cardCls = "rounded-xl border border-ink-700 bg-ink-900/70 p-4";

function display(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value && typeof value === "object" && "name" in value) {
    const name = (value as { name?: unknown }).name;
    if (typeof name === "string" || typeof name === "number") return String(name);
  }
  return JSON.stringify(value);
}

function gridLine(
  start: { row: number; col: number },
  end: { row: number; col: number },
): Array<{ row: number; col: number }> {
  let { row, col } = start;
  const result = [{ row, col }];
  while (row !== end.row || col !== end.col) {
    if (row !== end.row) row += end.row > row ? 1 : -1;
    if (col !== end.col) col += end.col > col ? 1 : -1;
    result.push({ row, col });
  }
  return result;
}

function targetingForAction(action: Record<string, unknown> | undefined): TargetingTemplate | null {
  if (!action) return null;
  const compiled = targetingFromRulePlan(action);
  if (compiled) return compiled;
  const text = [
    display(action.range ?? ""),
    display(action.description ?? ""),
    display(action.area ?? ""),
  ].join(" ");
  const numbers = [...text.matchAll(/(\d+)\s*尺/g)].map((match) => Number(match[1]));
  const shape = /锥形|锥状|锥体/.test(text)
    ? "cone"
    : /直线|束/.test(text)
      ? "line"
      : /半径|球形|爆发|圆形/.test(text)
        ? "circle"
        : "single";
  return {
    shape,
    rangeFt: numbers[0] ?? 5,
    sizeFt: shape === "circle"
      ? numbers[1] ?? 20
      : shape === "line" || shape === "cone"
        ? numbers[0] ?? 5
        : undefined,
    widthFt: shape === "line" ? numbers[1] ?? 5 : undefined,
  };
}

function JoinRoom({ onJoined }: { onJoined: () => void }): ReactElement {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const join = useMutation({
    mutationFn: () => joinPlayerRoom(code, name),
    onSuccess: onJoined,
  });
  return (
    <main className="flex min-h-screen items-center justify-center bg-ink-950 p-4">
      <section className="w-full max-w-md rounded-2xl border border-amber-900/60 bg-ink-900 p-6 shadow-2xl">
        <p className="m-0 text-xs uppercase tracking-[.22em] text-amber-300">D&D 5e 玩家入口</p>
        <h1 className="mb-2 mt-3 font-display text-3xl text-parchment-100">加入跑团房间</h1>
        <p className="text-sm leading-6 text-stone-400">请连接到 DM 的同一局域网，输入主控台显示的 6 位房间码。</p>
        <label className="mt-5 block text-xs text-stone-400">房间码
          <input aria-label="房间码" autoCapitalize="characters" className={`${inputCls} mt-1 text-center font-mono text-2xl tracking-[.28em]`} maxLength={8} onChange={(event) => setCode(event.target.value.toUpperCase())} value={code} />
        </label>
        <label className="mt-3 block text-xs text-stone-400">玩家称呼
          <input aria-label="玩家称呼" className={`${inputCls} mt-1`} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder="例如：小林" value={name} />
        </label>
        <Button className="mt-5 w-full" disabled={code.trim().length < 6 || !name.trim()} loading={join.isPending} onClick={() => join.mutate()} variant="primary">进入房间</Button>
        {join.isError ? <p className="mb-0 mt-3 text-sm text-red-300">{join.error.message}</p> : null}
      </section>
    </main>
  );
}

function CharacterBuilder({ snapshot, onDone }: { snapshot: PlayerRoomSnapshot; onDone: () => void }): ReactElement {
  const [mode, setMode] = useState<"choose" | "create">(
    snapshot.available_characters?.length ? "choose" : "create",
  );
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [race, setRace] = useState("");
  const [className, setClassName] = useState("");
  const [background, setBackground] = useState("");
  const [spellSearch, setSpellSearch] = useState("");
  const [selectedSpells, setSelectedSpells] = useState<string[]>([]);
  const [preparedSpellIds, setPreparedSpellIds] = useState<string[]>([]);
  const [selectedClassSkills, setSelectedClassSkills] = useState<string[]>([]);
  const [scores, setScores] = useState<Record<string, number>>({
    strength: 15, dexterity: 14, constitution: 13,
    intelligence: 12, wisdom: 10, charisma: 8,
  });
  const bind = useMutation({ mutationFn: () => bindMyCharacter(selected), onSuccess: onDone });
  const characterOptions = useQuery({
    queryKey: ["character-options"],
    queryFn: ({ signal }) => getCharacterOptions(signal),
    staleTime: 60 * 60 * 1000,
  });
  const selectedClass = CLASSES_2024.find((item) => item.name === className);
  const selectedBackground = BACKGROUNDS_2024.find((item) => item.name === background);
  const skillRule = classSkillSelection(className, selectedBackground?.skills);
  const spellLimits = spellSelectionRule(className);
  const availableSpells = (characterOptions.data?.spells ?? [])
    .filter((spell) => spellIsAvailable(spell, className));
  const spellCounts = spellChoiceCounts(selectedSpells, availableSpells);
  const preparedRequired = spellLimits.preparedLeveled ?? 0;
  const preparedCount = preparedSpellIds.filter((id) => selectedSpells.includes(id)).length;
  const preparedComplete = preparedRequired === 0 || preparedCount === preparedRequired;
  const choicesComplete = selectedClassSkills.length === skillRule.count
    && spellChoicesComplete(className, selectedSpells, availableSpells)
    && preparedComplete;
  const create = useMutation({
    mutationFn: () => {
      const abilityKey = {
        力量: "strength", 敏捷: "dexterity", 体质: "constitution",
        智力: "intelligence", 感知: "wisdom", 魅力: "charisma",
      }[selectedClass?.spellcasting?.ability ?? "智力"] ?? "intelligence";
      const spellSaveDc = 10 + Math.floor(((scores[abilityKey] ?? 10) - 10) / 2);
      return createMyCharacter({
        name, race, class_name: className, background, ability_scores: scores, equipment: [],
        skill_proficiencies: selectedClassSkills,
        spells: availableSpells
          .filter((spell) => selectedSpells.includes(spell.source_record_id))
          .map((spell) => spellToCharacterAction(
            spell,
            spellSaveDc,
            className !== "法师" || preparedSpellIds.includes(spell.source_record_id),
          )),
      });
    },
    onSuccess: onDone,
  });
  const validArray = [...Object.values(scores)].sort((a, b) => a - b).join(",") === "8,10,12,13,14,15";
  const toggleSpell = (id: string, level: number, checked: boolean) => {
    if (!checked) {
      setSelectedSpells((current) => current.filter((item) => item !== id));
      setPreparedSpellIds((current) => current.filter((item) => item !== id));
      return;
    }
    const limit = level === 0 ? spellLimits.cantrips : spellLimits.leveled;
    const count = level === 0 ? spellCounts.cantrips : spellCounts.leveled;
    if (count >= limit) return;
    setSelectedSpells((current) => [...current, id]);
  };
  return (
    <main className="mx-auto min-h-screen max-w-4xl p-4 lg:p-8">
      <header className="mb-5">
        <p className="m-0 text-xs uppercase tracking-[.2em] text-amber-300">已加入 · {snapshot.campaign.name}</p>
        <h1 className="mb-1 mt-2 font-display text-3xl text-parchment-100">选择或创建你的角色</h1>
        <p className="text-sm text-stone-400">角色与这个跑团房间绑定；其他玩家无法查看或占用你的完整角色卡。</p>
      </header>
      <div className="mb-4 flex gap-2">
        <Button onClick={() => setMode("choose")} variant={mode === "choose" ? "primary" : "ghost"}>选择已有角色</Button>
        <Button onClick={() => setMode("create")} variant={mode === "create" ? "primary" : "ghost"}>按规则车卡</Button>
      </div>
      {mode === "choose" ? (
        <section className={cardCls}>
          <h2 className="mt-0 font-display text-xl">未被认领的角色</h2>
          {!snapshot.available_characters?.length ? <EmptyState hint="可以切换到“按规则车卡”创建新角色。" title="暂无可选角色" /> : (
            <div className="grid gap-3 md:grid-cols-2">
              {snapshot.available_characters.map((character) => (
                <button className={`rounded-lg border p-3 text-left ${selected === character.id ? "border-amber-400 bg-amber-500/10" : "border-ink-700 bg-ink-950/40"}`} key={character.id} onClick={() => setSelected(character.id)} type="button">
                  <strong>{character.name}</strong><span className="mt-1 block text-xs text-stone-400">{character.race || "未知种族"} · {character.class_name || "未知职业"} Lv{character.level}</span>
                </button>
              ))}
            </div>
          )}
          <Button className="mt-4" disabled={!selected} loading={bind.isPending} onClick={() => bind.mutate()} variant="primary">绑定所选角色</Button>
          {bind.isError ? <p className="text-sm text-red-300">{bind.error.message}</p> : null}
        </section>
      ) : (
        <section className={cardCls}>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-xs text-stone-400">角色名<input className={`${inputCls} mt-1`} onChange={(event) => setName(event.target.value)} value={name} /></label>
            <label className="text-xs text-stone-400">种族（2024核心）
              <select className={`${inputCls} mt-1`} onChange={(event) => setRace(event.target.value)} value={race}><option value="">请选择</option>{SPECIES_2024.map((item) => <option key={item.name}>{item.name}</option>)}</select>
            </label>
            <label className="text-xs text-stone-400">职业（全部12个核心职业）
              <select className={`${inputCls} mt-1`} onChange={(event) => { setClassName(event.target.value); setSelectedClassSkills([]); setSelectedSpells([]); setPreparedSpellIds([]); }} value={className}><option value="">请选择</option>{CLASSES_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · d{item.hitDie}</option>)}</select>
            </label>
            <label className="text-xs text-stone-400">背景（2024核心）
              <select className={`${inputCls} mt-1`} onChange={(event) => { setBackground(event.target.value); setSelectedClassSkills([]); }} value={background}><option value="">请选择</option>{BACKGROUNDS_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.skills.join("、")}</option>)}</select>
            </label>
          </div>
          <h3 className="mb-2 mt-5 text-sm text-parchment-100">分配标准数组（每个数值只能使用一次）</h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-6">
            {Object.entries(ABILITIES).map(([key, label]) => <label className="text-xs text-stone-400" key={key}>{label}<select className={`${inputCls} mt-1`} onChange={(event) => setScores((current) => ({ ...current, [key]: Number(event.target.value) }))} value={scores[key]}>{[15, 14, 13, 12, 10, 8].map((value) => <option key={value}>{value}</option>)}</select></label>)}
          </div>
          {!validArray ? <p className="text-sm text-red-300">标准数组的每个数值必须恰好使用一次。</p> : null}
          <div className="mt-5 rounded border border-ink-700 bg-ink-950/40 p-3">
            <h3 className="m-0 text-sm text-parchment-100">职业选项</h3>
            <p className="mb-2 mt-1 text-xs text-stone-500">当前创建1级角色；子职通常在3级解锁，升级时再从该职业完整子职库中选择。</p>
            <div className="mb-3 rounded border border-ink-700 p-2">
              <p className="mb-2 mt-0 text-xs text-stone-400">职业技能：已选 <strong className={selectedClassSkills.length === skillRule.count ? "text-emerald-300" : "text-amber-300"}>{selectedClassSkills.length}/{skillRule.count}</strong>；背景固定提供 {selectedBackground?.skills.join("、") || "无"}。</p>
              <div className="flex flex-wrap gap-2">
                {skillRule.choices.map((skill) => <label className={`rounded border px-2 py-1 text-xs ${selectedClassSkills.includes(skill) ? "border-emerald-500 text-emerald-200" : "border-ink-700 text-stone-400"}`} key={skill}><input checked={selectedClassSkills.includes(skill)} className="mr-1" onChange={(event) => { if (!event.target.checked) setSelectedClassSkills((current) => current.filter((item) => item !== skill)); else if (selectedClassSkills.length < skillRule.count) setSelectedClassSkills((current) => [...current, skill]); }} type="checkbox" />{skill}</label>)}
              </div>
            </div>
            {selectedClass?.spellcasting ? (
              <>
                <input aria-label="玩家搜索法术" className={inputCls} onChange={(event) => setSpellSearch(event.target.value)} placeholder="搜索并选择初始法术" value={spellSearch} />
                <div className="mt-2 max-h-56 overflow-y-auto rounded border border-ink-700 p-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    {availableSpells.filter((spell) => !spellSearch.trim() || `${spell.name} ${spell.source_path}`.toLowerCase().includes(spellSearch.trim().toLowerCase())).map((spell) => <label className={`flex gap-2 rounded border p-2 text-xs ${selectedSpells.includes(spell.source_record_id) ? "border-amber-500 bg-amber-950/20" : "border-ink-700"}`} key={spell.source_record_id}><input checked={selectedSpells.includes(spell.source_record_id)} onChange={(event) => toggleSpell(spell.source_record_id, spell.level, event.target.checked)} type="checkbox" /><span><strong className="block">{spell.name} · {spell.level === 0 ? "戏法" : "1环"}</strong><span className="text-2xs text-stone-600">{spell.casting_time || "施法时间未记录"} · {spell.range || "距离未记录"} · {spell.damage_expression || "叙事/辅助效果"}</span></span></label>)}
                  </div>
                </div>
                <p className={`mb-0 mt-2 text-xs ${spellCounts.cantrips === spellLimits.cantrips && spellCounts.leveled === spellLimits.leveled ? "text-emerald-300" : "text-amber-200"}`}>必须选择：戏法 {spellCounts.cantrips}/{spellLimits.cantrips} · {spellLimits.leveledLabel} {spellCounts.leveled}/{spellLimits.leveled}。</p>
                {preparedRequired > 0 ? <div className="mt-3 rounded border border-sky-800/60 p-2"><p className="mb-2 mt-0 text-xs text-sky-200">再从法术书中准备 {preparedRequired} 个1环法术（{preparedCount}/{preparedRequired}）；只有已准备法术能在战斗中施放。</p><div className="flex flex-wrap gap-2">{availableSpells.filter((spell) => spell.level === 1 && selectedSpells.includes(spell.source_record_id)).map((spell) => <label className={`rounded border px-2 py-1 text-xs ${preparedSpellIds.includes(spell.source_record_id) ? "border-sky-500 text-sky-200" : "border-ink-700 text-stone-500"}`} key={`prepared-${spell.source_record_id}`}><input checked={preparedSpellIds.includes(spell.source_record_id)} className="mr-1" onChange={(event) => { if (!event.target.checked) setPreparedSpellIds((current) => current.filter((id) => id !== spell.source_record_id)); else if (preparedCount < preparedRequired) setPreparedSpellIds((current) => [...current, spell.source_record_id]); }} type="checkbox" />准备 · {spell.name}</label>)}</div></div> : null}
              </>
            ) : <p className="mb-0 text-xs text-stone-600">该职业1级没有法术选择。</p>}
          </div>
          <Button className="mt-5" disabled={!name.trim() || !race || !className || !background || !validArray || !choicesComplete} loading={create.isPending} onClick={() => create.mutate()} variant="primary">创建并绑定角色</Button>
          {create.isError ? <p className="text-sm text-red-300">{create.error.message}</p> : null}
        </section>
      )}
    </main>
  );
}

function CharacterView({
  character,
  onChanged,
}: {
  character: SafePlayerCharacter;
  onChanged: () => void;
}): ReactElement {
  const resources = Object.entries(character.resources ?? {}).map(([key, value]) => {
    const resource = typeof value === "object" && value !== null
      ? value as Record<string, unknown>
      : {};
    return {
      key,
      label: display(resource.label ?? key),
      current: resource.current,
      max: resource.max,
      recovery: resource.recovery === "short_rest"
        ? "短休恢复"
        : resource.recovery === "long_rest"
          ? "长休恢复"
          : display(resource.recovery ?? ""),
    };
  });
  const spellcastingAbility = display(character.spellcasting?.ability ?? "");
  const atomicEquipmentNames = new Set(
    (character.equipment_assets ?? []).map((item) => item.name),
  );
  const ordinaryInventory = character.inventory.filter(
    (item) => !atomicEquipmentNames.has(display(item)),
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className={cardCls}>
        <h2 className="mt-0 font-display text-2xl">{character.name}</h2>
        <p className="text-sm text-amber-200">{character.race} · {character.class_name} Lv{character.level} · {character.background}</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">{[["HP", `${character.hp}/${character.max_hp}`], ["AC", character.armor_class], ["速度", `${character.speed}尺`], ["经验", `${character.experience} XP`], ["金币", `${character.wallet?.gp ?? 0} GP`]].map(([label, value]) => <div className="rounded bg-ink-950 p-3 text-center" key={label}><span className="block text-2xs text-stone-500">{label}</span><strong className="font-mono text-lg">{value}</strong></div>)}</div>
        <div className="mt-3 grid grid-cols-3 gap-2">{Object.entries(ABILITIES).map(([key, label]) => <div className="rounded border border-ink-700 p-2 text-center" key={key}><span className="block text-2xs text-stone-500">{label}</span><strong>{character.ability_scores[key] ?? 10}</strong></div>)}</div>
      </section>
      <section className={cardCls}><h2 className="mt-0 font-display text-xl">动作与法术</h2>{spellcastingAbility ? <p className="text-xs text-amber-200">施法属性：{spellcastingAbility}</p> : null}{[...character.actions, ...character.spells].length ? [...character.actions, ...character.spells].map((item, index) => <details className="mb-2 rounded border border-ink-700 p-2" key={`${display(item)}-${index}`}><summary className="cursor-pointer text-sm text-parchment-100">{display(item)}</summary><pre className="whitespace-pre-wrap text-xs text-stone-400">{JSON.stringify(item, null, 2)}</pre></details>) : <p className="text-sm text-stone-500">暂无动作或法术。</p>}</section>
      <PlayerEquipmentPanel character={character} onChanged={onChanged} />
      <section className={cardCls}><h2 className="mt-0 font-display text-xl">背包与普通道具</h2>{ordinaryInventory.length ? <ul className="pl-5 text-sm">{ordinaryInventory.map((item, index) => <li className="mb-1" key={`${display(item)}-${index}`}>{display(item)}</li>)}</ul> : <p className="text-sm text-stone-500">背包里暂无普通道具。</p>}</section>
      <section className={cardCls}><h2 className="mt-0 font-display text-xl">特性、技能与资源</h2><div className="flex flex-wrap gap-2">{character.features.map((item, index) => <span className="rounded bg-violet-500/10 px-2 py-1 text-xs text-violet-200" key={`${display(item)}-${index}`} title={display(item)}>{display(item)}</span>)}</div><p className="mt-4 text-xs text-stone-400">熟练：{character.proficiencies.map(display).join("、") || "无"}</p><p className="text-xs text-stone-400">技能：{Object.keys(character.skills).join("、") || "无"}</p>{resources.map((resource) => <div className="mt-2 flex items-center gap-3 rounded border border-ink-700 p-3 text-xs" key={resource.key}><strong className="mr-auto text-parchment-100">{resource.label}</strong>{resource.current !== undefined && resource.max !== undefined ? <span className="font-mono text-base text-amber-200">{display(resource.current)}/{display(resource.max)}</span> : null}{resource.recovery ? <span className="text-stone-500">{resource.recovery}</span> : null}</div>)}</section>
    </div>
  );
}

function SceneGridView({
  snapshot,
  onMove,
  selectedTargetKey,
  selectableTargetKeys,
  onTargetSelect,
  selectedTargetKeys,
  affectedCellKeys,
  movementCellKeys,
  rangeCellKeys,
  dangerCellKeys,
  positionOverrides,
}: {
  snapshot: PlayerRoomSnapshot;
  onMove: (row: number, col: number) => void;
  selectedTargetKey?: string;
  selectableTargetKeys?: ReadonlySet<string>;
  onTargetSelect?: (targetKey: string) => void;
  selectedTargetKeys?: ReadonlySet<string>;
  affectedCellKeys?: ReadonlySet<string>;
  movementCellKeys?: ReadonlySet<string>;
  rangeCellKeys?: ReadonlySet<string>;
  dangerCellKeys?: ReadonlySet<string>;
  positionOverrides?: Record<string, { row: number; col: number }>;
}): ReactElement {
  const scene = snapshot.table.scene;
  const combat = snapshot.combat;
  if (!scene?.grid) return <EmptyState hint="等待 DM 选择带网格的场景。" title="尚无公开地图" />;
  const own = combat?.combatants.find((item) => item.is_own);
  const tokens = combat
    ? combat.combatants.flatMap((item) => {
        const position = positionOverrides?.[item.id] ?? item.position;
        return position ? [{
          id: item.id,
          entity_id: item.id,
          entity_type: item.entity_type,
          label: item.name,
          row: position.row,
          col: position.col,
          targetKey: `combatant:${item.id}`,
          isOwn: item.is_own,
        }] : [];
      })
    : scene.tokens.map((item) => ({
        ...item,
        targetKey: item.entity_id ? `${item.entity_type}:${item.entity_id}` : undefined,
        isOwn: item.entity_type === "character" && item.entity_id === snapshot.character?.id,
      }));
  return (
    <SceneMap
      canSelectCell={(row, col) => Boolean(
        combat?.is_my_turn
        && own
        && movementCellKeys?.has(`${row}:${col}`),
      )}
      compactCells={Boolean(combat)}
      grid={scene.grid}
      objects={scene.objects.map((item) => ({ ...item, targetKey: `object:${item.id}` }))}
      onCellSelect={onMove}
      onTargetSelect={onTargetSelect}
      affectedCellKeys={affectedCellKeys}
      dangerCellKeys={dangerCellKeys}
      movementCellKeys={movementCellKeys}
      rangeCellKeys={rangeCellKeys}
      selectedTargetKey={selectedTargetKey}
      selectedTargetKeys={selectedTargetKeys}
      selectableTargetKeys={selectableTargetKeys}
      title={combat ? "玩家战斗地图 · 与 DM 共用当前 Scene" : "玩家场景地图 · 点击绿色目标"}
      tokens={tokens}
    />
  );
}

function NoncombatActionPanel({
  snapshot,
  refresh,
}: {
  snapshot: PlayerRoomSnapshot;
  refresh: () => void;
}): ReactElement {
  const actions = snapshot.table.noncombat?.available_actions ?? [];
  const pending = snapshot.table.noncombat?.pending_actions ?? [];
  const [actionId, setActionId] = useState("");
  const [targetValue, setTargetValue] = useState("");
  const [message, setMessage] = useState("");
  const [rolls, setRolls] = useState<Record<string, string>>({});
  const selected = actions.find((item) => item.id === actionId);
  const targets = selected ? [
    ...(selected.target_types.includes("self") ? [{ value: `self:${snapshot.character?.id ?? ""}`, label: `自己 · ${snapshot.character?.name}` }] : []),
    ...(selected.target_types.includes("area") ? [{ value: "area:", label: "当前地点 / 区域" }] : []),
    ...snapshot.table.scene!.tokens
      .filter((token) => token.entity_id && selected.target_types.includes(token.entity_type as "npc" | "monster"))
      .map((token) => ({ value: `${token.entity_type}:${token.entity_id}`, label: `${token.entity_type === "npc" ? "NPC" : "怪物"} · ${token.label}` })),
    ...snapshot.table.scene!.objects
      .filter((object) => selected.target_types.includes("object")
        && (selected.kind !== "tool" || ["door", "trap", "treasure", "portal"].includes(object.object_type)))
      .map((object) => ({ value: `object:${object.id}`, label: `物体 · ${object.label}（${object.state}）` })),
  ] : [];
  const mutation = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => {
      setMessage("");
      refresh();
    },
  });
  const submit = () => {
    const [targetType, targetId] = targetValue.split(":");
    if (!selected || !targetType) return;
    mutation.mutate(() => planMyNoncombatAction(
      selected.id,
      targetType as "self" | "npc" | "monster" | "object" | "area",
      targetId || null,
      message || `${snapshot.character?.name}尝试使用${selected.name}`,
    ));
  };
  return (
    <section className={cardCls}>
      <h2 className="mt-0 font-display text-xl">场景行动与非伤害能力</h2>
      <p className="text-xs leading-5 text-stone-400">选择角色真实拥有的能力和公开目标。系统校验目标、距离、资源和投骰；世界状态仍由 DM 最终确认。</p>
      <label className="block text-xs text-stone-400">技能 / 工具 / 已准备法术
        <select className={`${inputCls} mt-1`} onChange={(event) => { setActionId(event.target.value); setTargetValue(""); }} value={actionId}>
          <option value="">请选择行动</option>
          {actions.map((action) => <option key={action.id} value={action.id}>{action.kind === "spell" ? "法术" : action.kind === "tool" ? "工具" : "技能"} · {action.name}</option>)}
        </select>
      </label>
      {selected ? <div className="mt-2 rounded border border-sky-900/60 bg-sky-950/20 p-3 text-xs leading-5 text-sky-100">
        <strong>{selected.name}</strong>
        <span className="block text-stone-400">{selected.description}</span>
        <span className="block">{selected.ability_label ? `检定属性：${selected.ability_label}` : "按法术规则处理"}{selected.range ? ` · 距离 ${selected.range}` : ""}{selected.concentration ? " · 需要专注" : ""}</span>
      </div> : null}
      <label className="mt-2 block text-xs text-stone-400">目标
        <select className={`${inputCls} mt-1`} disabled={!selected} onChange={(event) => setTargetValue(event.target.value)} value={targetValue}>
          <option value="">请选择合法目标</option>
          {targets.map((target) => <option key={target.value} value={target.value}>{target.label}</option>)}
        </select>
      </label>
      <div className="mt-3">
        <SceneGridView
          onMove={() => undefined}
          onTargetSelect={setTargetValue}
          selectedTargetKey={targetValue}
          selectableTargetKeys={new Set(targets.map((target) => target.value))}
          snapshot={snapshot}
        />
      </div>
      <textarea className={`${inputCls} mt-2`} onChange={(event) => setMessage(event.target.value)} placeholder="补充你具体想怎么做；例如：低声命令守卫“离开”。" rows={2} value={message} />
      <Button className="mt-2 w-full" disabled={!selected || !targetValue} loading={mutation.isPending} onClick={submit} variant="primary">按规则生成行动计划</Button>
      {mutation.isError ? <p className="text-sm text-red-300">{mutation.error.message}</p> : null}
      {pending.length ? <div className="mt-4 border-t border-ink-700 pt-3">
        <strong className="text-sm">待完成 / 待 DM 确认</strong>
        {pending.map((request) => {
          const resolution = request.payload.resolution;
          const awaiting = request.payload.phase === "awaiting_player_roll";
          return <article className="mt-2 rounded border border-violet-800/70 bg-violet-950/20 p-3" key={request.id}>
            <strong className="text-sm">{request.payload.action?.name ?? "非战斗行动"} → {request.payload.target?.name ?? "当前区域"}</strong>
            <p className="mb-1 mt-2 text-xs leading-5 text-stone-300">{resolution?.instruction ?? request.payload.proposal?.summary ?? "规则计划已完成，等待 DM 确认。"}</p>
            {resolution?.save ? <p className="my-1 text-xs text-violet-200">目标豁免已由系统计算：{display(resolution.save.total)} vs DC {display(resolution.save.dc)} · {resolution.save.success ? "成功" : "失败"}</p> : null}
            {awaiting ? <div className="mt-2 flex gap-2"><input aria-label={`${request.id}裸骰`} className={inputCls} max={20} min={1} onChange={(event) => setRolls((current) => ({ ...current, [request.id]: event.target.value }))} placeholder="输入 d20 裸骰" type="number" value={rolls[request.id] ?? ""} /><Button disabled={!rolls[request.id]} onClick={() => mutation.mutate(() => rollMyNoncombatAction(request.id, request.version, Number(rolls[request.id])))} variant="primary">提交裸骰</Button></div> : <span className="mt-2 block text-2xs text-amber-200">已完成规则结算，等待 DM 接受或驳回。</span>}
          </article>;
        })}
      </div> : null}
    </section>
  );
}

function PlayerCombatantStrip({
  activeId,
  combatants,
}: {
  activeId: string | null;
  combatants: PlayerCombatant[];
}): ReactElement {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const expanded = combatants.find((item) => item.id === expandedId);
  return (
    <section className="mb-3 rounded-lg border border-ink-700 bg-ink-950/45 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs">
        <strong>先攻轨道</strong>
        <span className="text-stone-500">当前单位有橙色描边；点击卡片查看公开战斗属性</span>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {combatants.map((item, index) => (
          <button
            aria-expanded={expandedId === item.id}
            className={`min-w-48 rounded-lg border p-3 text-left text-xs transition ${
              item.id === activeId
                ? "border-amber-400 bg-amber-950/25 ring-2 ring-amber-500/40"
                : expandedId === item.id
                  ? "border-sky-600 bg-sky-950/15"
                  : "border-ink-700 bg-ink-900 hover:border-ink-500"
            }`}
            key={item.id}
            onClick={() => setExpandedId((current) => current === item.id ? null : item.id)}
            type="button"
          >
            <span className="flex items-center gap-2">
              <b className="flex size-8 items-center justify-center rounded-full bg-ink-950 font-mono text-amber-200">{item.initiative}</b>
              <span><strong className="block">{item.name}</strong><span className="text-stone-500">{item.entity_type === "character" ? "玩家" : item.entity_type === "npc" ? "NPC" : "怪物"} · 第 {index + 1} 位</span></span>
            </span>
            <span className="mt-2 grid grid-cols-3 gap-1 text-center text-2xs">
              <span className="rounded bg-ink-950 py-1"><b className="block">AC {item.armor_class}</b>护甲</span>
              <span className="rounded bg-ink-950 py-1"><b className="block">{item.hp === undefined ? item.health_status : `${item.hp}/${item.max_hp}`}</b>生命</span>
              <span className="rounded bg-ink-950 py-1"><b className="block">{item.speed_ft}尺</b>速度</span>
            </span>
          </button>
        ))}
      </div>
      {expanded ? (
        <div className="mt-2 rounded border border-sky-800/50 bg-sky-950/10 p-3" data-testid="player-combatant-detail">
          <div className="flex flex-wrap gap-2"><strong className="text-sky-100">{expanded.name} · 详细战斗卡</strong><span className="text-xs text-stone-500">状态：{expanded.conditions?.map(display).join("、") || expanded.health_status}</span></div>
          <div className="mt-2 grid grid-cols-3 gap-1 sm:grid-cols-6">
            {Object.entries(ABILITIES).map(([key, label]) => {
              const score = expanded.ability_scores[key] ?? 10;
              const modifier = Math.floor((score - 10) / 2);
              return <span className="rounded border border-ink-700 p-2 text-center text-2xs text-stone-500" key={key}>{label}<b className="block text-sm text-parchment-100">{score}（{modifier >= 0 ? "+" : ""}{modifier}）</b></span>;
            })}
          </div>
          <p className="mb-0 mt-2 text-xs text-stone-400">
            AC {expanded.armor_class} · 速度 {expanded.speed_ft}尺
            {expanded.damage_resistances?.length ? ` · 抗性 ${expanded.damage_resistances.join("、")}` : ""}
            {expanded.damage_immunities?.length ? ` · 免疫 ${expanded.damage_immunities.join("、")}` : ""}
          </p>
          {expanded.actions?.length ? <div className="mt-2 flex flex-wrap gap-1">{expanded.actions.map((action, index) => <span className="rounded border border-violet-800/50 bg-violet-950/20 px-2 py-1 text-2xs text-violet-200" key={`${display(action)}-${index}`}>{typeof action === "string" ? action : [display(action.name ?? `动作 ${index + 1}`), display(action.damage ?? ""), display(action.range ?? ""), display(action.cost ?? "")].filter(Boolean).join(" · ")}</span>)}</div> : <p className="mb-0 mt-2 text-xs text-stone-500">没有可公开的动作资料。</p>}
        </div>
      ) : null}
    </section>
  );
}

type PlayerCombatLogEntry = PlayerCombatSnapshot["log"][number];

function combatLogKey(entry: PlayerCombatLogEntry): string {
  return `${entry.id}:${entry.status}`;
}

function CombatView({ snapshot, refresh }: { snapshot: PlayerRoomSnapshot; refresh: () => void }): ReactElement {
  const combat = snapshot.combat;
  const [actionName, setActionName] = useState("");
  const [targetId, setTargetId] = useState("");
  const [attackTotal, setAttackTotal] = useState("");
  const [damageTotal, setDamageTotal] = useState("");
  const [criticalHit, setCriticalHit] = useState(false);
  const [rolls, setRolls] = useState<Record<string, string>>({});
  const [endTurnAfterAttack, setEndTurnAfterAttack] = useState(true);
  const [lastResolution, setLastResolution] = useState("");
  const [actionQueue, setActionQueue] = useState<PlayerCombatLogEntry[]>([]);
  const [presentation, setPresentation] = useState<PlayerCombatLogEntry | null>(null);
  const [positionOverrides, setPositionOverrides] = useState<Record<string, { row: number; col: number }>>({});
  const seenCombatLogKeys = useRef<Set<string>>(new Set());
  const replayCombatId = useRef<string | null>(null);
  useEffect(() => {
    if (!combat) return;
    if (replayCombatId.current !== combat.id) {
      replayCombatId.current = combat.id;
      seenCombatLogKeys.current = new Set(combat.log.map(combatLogKey));
      setActionQueue([]);
      setPresentation(null);
      setPositionOverrides({});
      return;
    }
    const unseen = combat.log
      .filter((entry) => !seenCombatLogKeys.current.has(combatLogKey(entry)))
      .reverse();
    if (!unseen.length) return;
    for (const entry of unseen) seenCombatLogKeys.current.add(combatLogKey(entry));
    const visibleEnemyEvents = unseen.filter((entry) => {
      const actor = combat.combatants.find((item) => item.id === entry.actor_combatant_id);
      return actor?.entity_type === "monster"
        || actor?.entity_type === "npc"
        || entry.action_type === "advance_turn";
    });
    if (visibleEnemyEvents.length) {
      setActionQueue((current) => [...current, ...visibleEnemyEvents]);
    }
  }, [combat]);
  useEffect(() => {
    if (presentation || !actionQueue.length) return;
    const nextPresentation = actionQueue[0];
    if (!nextPresentation) return;
    setPresentation(nextPresentation);
    setActionQueue((current) => current.slice(1));
  }, [actionQueue, presentation]);
  useEffect(() => {
    if (!presentation) return;
    let cancelled = false;
    const wait = (milliseconds: number) => new Promise<void>((resolve) => {
      window.setTimeout(resolve, milliseconds);
    });
    const replay = async () => {
      const actorId = presentation.actor_combatant_id;
      const from = presentation.from_position;
      const to = presentation.to_position;
      if (presentation.action_type === "move" && actorId && from && to) {
        setPositionOverrides((current) => ({ ...current, [actorId]: from }));
        for (const point of gridLine(from, to).slice(1)) {
          await wait(240);
          if (cancelled) return;
          setPositionOverrides((current) => ({ ...current, [actorId]: point }));
        }
        await wait(700);
        if (cancelled) return;
        setPositionOverrides((current) => {
          const next = { ...current };
          delete next[actorId];
          return next;
        });
      } else {
        await wait(presentation.action_type === "advance_turn" ? 850 : 1500);
      }
      if (!cancelled) setPresentation(null);
    };
    void replay();
    return () => {
      cancelled = true;
    };
  }, [presentation]);
  const own = combat?.combatants.find((item) => item.is_own);
  const actions = (snapshot.character?.actions ?? []).filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null);
  const enemies = combat?.combatants.filter((item) => item.entity_type === "monster" && item.health_status !== "倒地") ?? [];
  const selectedAction = actions.find((item) => display(item.name) === actionName);
  const selectedTarget = enemies.find((item) => item.id === targetId);
  const attackBonus = typeof selectedAction?.attack_bonus === "number"
    ? selectedAction.attack_bonus
    : null;
  const damageFormula = display(selectedAction?.damage ?? selectedAction?.description ?? "角色卡所列伤害骰");
  const targeting = targetingForAction(selectedAction);
  const actorPosition = own?.position;
  const grid = snapshot.table.scene?.grid;
  const aimPosition = selectedTarget?.position;
  const rangeCellKeys = new Set<string>();
  if (grid && actorPosition && targeting) {
    for (let row = 1; row <= grid.height; row += 1) {
      for (let col = 1; col <= grid.width; col += 1) {
        if (gridDistanceFt(actorPosition, { row, col }, grid.cell_size_ft) <= targeting.rangeFt) {
          if (hasLineOfSight(grid, actorPosition, { row, col })) {
            rangeCellKeys.add(`${row}:${col}`);
          }
        }
      }
    }
  }
  const affectedCells = grid && actorPosition && aimPosition && targeting
      ? getTargetingCells(
        {
          width: grid.width,
          height: grid.height,
          cell_size_ft: grid.cell_size_ft,
          cells: grid.cells,
        },
        actorPosition,
        aimPosition,
        targeting,
      )
    : [];
  const affectedCellKeys = new Set(affectedCells.map((cell) => `${cell.row}:${cell.col}`));
  const affectedEnemies = selectedTarget && targeting
    ? (targeting.shape === "single"
        ? [selectedTarget]
        : enemies.filter((enemy) => enemy.position && affectedCellKeys.has(`${enemy.position.row}:${enemy.position.col}`)))
    : [];
  const targetableEnemies = enemies.filter((enemy) => (
    enemy.position
    && rangeCellKeys.has(`${enemy.position.row}:${enemy.position.col}`)
  ));
  const presentationActor = combat?.combatants.find(
    (item) => item.id === presentation?.actor_combatant_id,
  );
  const presentationTargets = (presentation?.target_combatant_ids ?? [])
    .map((id) => combat?.combatants.find((item) => item.id === id))
    .filter((item): item is PlayerCombatant => Boolean(item));
  const replayTargetCellKeys = new Set(
    presentationTargets
      .filter((item) => item.position)
      .map((item) => `${item.position?.row}:${item.position?.col}`),
  );
  const displayAffectedCellKeys = new Set([...affectedCellKeys, ...replayTargetCellKeys]);
  const activeCombatant = combat?.combatants.find(
    (item) => item.id === combat.active_combatant_id,
  );
  const pendingRoll = combat?.pending_rolls[0];
  const pendingActor = combat?.combatants.find(
    (item) => item.id === pendingRoll?.actor_combatant_id,
  );
  const pendingAction = pendingActor?.actions.find(
    (item): item is Record<string, unknown> => (
      typeof item === "object"
      && item !== null
      && display(item.name) === pendingRoll?.action_name
    ),
  );
  const pendingTargeting = targetingForAction(pendingAction);
  const dangerCellKeys = new Set(
    grid
    && pendingActor?.position
    && own?.position
    && pendingTargeting
      ? getTargetingCells(
        {
          width: grid.width,
          height: grid.height,
          cell_size_ft: grid.cell_size_ft,
          cells: grid.cells,
        },
        pendingActor.position,
        own.position,
        pendingTargeting,
      ).map((cell) => `${cell.row}:${cell.col}`)
      : [],
  );
  const movementCellKeys = new Set<string>();
  if (combat?.is_my_turn && grid && actorPosition && (own?.movement_remaining_ft ?? 0) > 0) {
    const occupied = new Set(
      (combat?.combatants ?? [])
        .filter((item) => item.id !== own?.id && item.position)
        .map((item) => `${item.position?.row}:${item.position?.col}`),
    );
    const blocked = new Set<string>();
    const difficult = new Set<string>();
    for (const object of snapshot.table.scene?.objects ?? []) {
      for (let row = object.row; row < object.row + object.height_cells; row += 1) {
        for (let col = object.col; col < object.col + object.width_cells; col += 1) {
          const key = `${row}:${col}`;
          if (object.object_type === "terrain" && object.state === "active") difficult.add(key);
          if (
            object.object_type === "wall"
            || (object.object_type === "door" && ["active", "closed"].includes(object.state))
            || (["cover", "furniture"].includes(object.object_type) && object.state === "active")
          ) blocked.add(key);
        }
      }
    }
    for (let row = 1; row <= grid.height; row += 1) {
      for (let col = 1; col <= grid.width; col += 1) {
        const key = `${row}:${col}`;
        if (occupied.has(key) || blocked.has(key)) continue;
        const path = gridLine(actorPosition, { row, col });
        if (path.slice(1).some((cell) => blocked.has(`${cell.row}:${cell.col}`))) continue;
        const spent = path.slice(1).reduce(
          (total, cell) => total + grid.cell_size_ft * (difficult.has(`${cell.row}:${cell.col}`) ? 2 : 1),
          0,
        );
        if (spent <= (own?.movement_remaining_ft ?? 0)) movementCellKeys.add(key);
      }
    }
  }
  const isSavingThrowAction = Boolean(selectedAction?.save_dc && selectedAction?.save_ability);
  const mutation = useMutation({ mutationFn: async (fn: () => Promise<unknown>) => fn(), onSuccess: refresh });
  if (!combat) return <EmptyState hint="DM 从当前 Scene 发起战斗后，这里会自动切换。" title="当前没有战斗" />;
  const ended = combat.status === "ended";
  return (
    <div
      className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]"
      data-testid="player-combat-layout"
    >
      <section className={`${cardCls} min-w-0`}>
        <div className="mb-3 flex flex-wrap items-center gap-2"><h2 className="m-0 mr-auto font-display text-2xl">{combat.name}</h2><span className="rounded bg-ink-950 px-2 py-1 text-xs">第 {combat.round_number} 轮</span><span className={`rounded px-2 py-1 text-xs ${ended ? "bg-amber-500/20 text-amber-200" : combat.is_my_turn ? "bg-emerald-500/20 text-emerald-200" : "bg-ink-800 text-stone-400"}`}>{ended ? "战斗已结束" : presentation ? "正在展示敌方行动" : combat.is_my_turn ? "轮到你行动" : `${activeCombatant?.name ?? "其他单位"}行动中`}</span></div>
        <PlayerCombatantStrip activeId={combat.active_combatant_id} combatants={combat.combatants} />
        <div className="mb-3 min-h-[5.75rem]">
        {presentation ? (
          <div className="h-full rounded-lg border-2 border-red-700/60 bg-red-950/20 p-3" data-testid="player-enemy-action-banner">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-red-500/20 px-2 py-1 text-2xs text-red-200">
                {presentation.action_type === "move" ? "敌方移动" : presentation.action_type === "advance_turn" ? "回合切换" : "敌方动作"}
              </span>
              <strong className="text-sm text-parchment-100">{presentationActor?.name ?? presentation.actor_name ?? "战斗单位"}</strong>
              {presentation.action_name ? <span className="text-xs text-red-200">使用「{presentation.action_name}」</span> : null}
            </div>
            <p className="mb-0 mt-2 text-xs leading-5 text-stone-300">{presentation.summary}</p>
            {presentationTargets.length ? <p className="mb-0 mt-1 text-2xs text-amber-200">目标：{presentationTargets.map((item) => item.name).join("、")}</p> : null}
          </div>
        ) : <div aria-hidden="true" className="h-[5.75rem] rounded-lg border border-transparent" />}
        </div>
        <div data-testid="player-combat-map">
          <SceneGridView
            onMove={(row, col) => own && mutation.mutate(() => moveMyCombatant(row, col, own.version ?? 1))}
            onTargetSelect={(value) => setTargetId(value.replace(/^combatant:/, ""))}
            selectedTargetKey={targetId ? `combatant:${targetId}` : undefined}
            selectedTargetKeys={new Set(affectedEnemies.map((item) => `combatant:${item.id}`))}
            selectableTargetKeys={new Set(targetableEnemies.map((item) => `combatant:${item.id}`))}
            affectedCellKeys={displayAffectedCellKeys}
            dangerCellKeys={dangerCellKeys}
            movementCellKeys={movementCellKeys}
            positionOverrides={positionOverrides}
            rangeCellKeys={rangeCellKeys}
            snapshot={snapshot}
          />
        </div>
        {own ? <p className="mb-0 mt-2 text-xs text-stone-400">剩余移动 {own.movement_remaining_ft ?? 0}尺 · 动作 {own.action_available ? "可用" : "已用"} · 附赠动作 {own.bonus_action_available ? "可用" : "已用"}</p> : null}
      </section>
      <aside className="min-w-0 space-y-4" data-testid="player-combat-sidebar">
        <section className={cardCls}>
          <h2 className="mt-0 font-display text-xl">当前战斗面板</h2>
          <div className="mb-3 min-h-[6.75rem]">
          {!combat.is_my_turn && activeCombatant ? (
            <div className="h-full rounded border border-red-900/60 bg-red-950/15 p-3" data-testid="player-active-enemy-panel">
              <strong className="text-sm text-red-100">{activeCombatant.name} · 当前行动单位</strong>
              <p className="mb-0 mt-1 text-xs leading-5 text-stone-300">
                {activeCombatant.entity_type === "monster"
                  ? `怪物正在由战斗 AI 移动并选择攻击。AC ${activeCombatant.armor_class} · HP ${activeCombatant.hp}/${activeCombatant.max_hp} · 剩余移动 ${activeCombatant.movement_remaining_ft ?? 0}尺。`
                  : "NPC 正在按当前战斗状态行动。"}
              </p>
              {(activeCombatant.actions ?? []).length ? <p className="mb-0 mt-1 text-2xs text-stone-500">可见动作：{activeCombatant.actions.map(display).join("、")}</p> : null}
            </div>
          ) : <div aria-hidden="true" className="h-[6.75rem] rounded border border-transparent" />}
          </div>
          {combat.pending_rolls.map((roll) => <div className="mb-3 rounded border border-violet-700 bg-violet-950/20 p-3" data-testid="player-pending-roll" key={roll.id}><strong className="text-sm text-violet-100">{roll.actor_name ?? "敌方单位"} 对你使用「{roll.action_name}」</strong>{roll.description ? <p className="mb-0 mt-1 text-xs leading-5 text-stone-300">{roll.description}</p> : null}<p className="text-xs text-stone-400">请掷 {roll.roll_formula}，总值需达到 DC {roll.dc}（{roll.ability || roll.skill || roll.resolution_type}）。{roll.damage_on_failure ? `失败将承受 ${roll.damage_on_failure} 点${roll.damage_type ?? ""}伤害` : ""}{roll.damage_on_success ? `；成功仍承受 ${roll.damage_on_success} 点${roll.damage_type ?? ""}伤害` : ""}</p>{dangerCellKeys.size ? <p className="text-2xs text-red-300">地图上的红色描边为「{roll.action_name}」当前影响范围。</p> : null}<div className="flex gap-2"><input aria-label={`${roll.action_name}骰值`} className={inputCls} onChange={(event) => setRolls((current) => ({ ...current, [roll.id]: event.target.value }))} type="number" value={rolls[roll.id] ?? ""} /><Button disabled={!rolls[roll.id]} onClick={() => mutation.mutate(async () => { const result = await submitMyPlayerRoll(roll.id, roll.version, Number(rolls[roll.id])); const next = (result as { turn_advance?: { active_combatant?: { display_name?: string } } }).turn_advance?.active_combatant?.display_name; setLastResolution(`你对「${roll.action_name}」的豁免已结算${next ? `；现在轮到 ${next}` : "；战斗状态已更新"}。`); return result; })} variant="primary">提交并继续战斗</Button></div></div>)}
          {ended ? <p className="rounded border border-amber-800/60 bg-amber-950/20 p-3 text-sm text-amber-100">战斗已由 DM 结束。你仍可查看地图和完整公开日志；奖励请到“我的角色”查看。</p> : null}
          <label className="block text-xs text-stone-400">攻击/技能<select className={`${inputCls} mt-1`} disabled={ended || !combat.is_my_turn} onChange={(event) => setActionName(event.target.value)} value={actionName}><option value="">选择角色卡动作</option>{actions.map((action) => <option key={display(action.name)} value={display(action.name)}>{display(action.name)} · {display(action.damage ?? action.description ?? "")}</option>)}</select></label>
          <label className="mt-2 block text-xs text-stone-400">目标<select className={`${inputCls} mt-1`} disabled={ended || !combat.is_my_turn} onChange={(event) => setTargetId(event.target.value)} value={targetId}><option value="">选择合法敌人</option>{enemies.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.health_status}</option>)}</select></label>
          <div className="mt-3 rounded border border-amber-800/60 bg-amber-950/20 p-3 text-xs leading-5 text-amber-100">
            {selectedAction && selectedTarget ? (
              <>
                <strong>{selectedAction.name as string} → {selectedTarget.name}</strong>
                <span className="mt-1 block">
                  {isSavingThrowAction
                    ? <>该能力不需要玩家掷命中；请玩家掷一次 {damageFormula} 并输入最终伤害总值。系统会让范围内的每个目标分别进行 {display(selectedAction?.save_ability)} 豁免（DC {display(selectedAction?.save_dc)}）。</>
                    : <>请掷 d20{attackBonus === null ? "并加入角色卡命中调整值" : ` + ${attackBonus} 命中加值`}；最终总值需要达到 AC {selectedTarget.armor_class}（≥ {selectedTarget.armor_class}）才命中。命中后掷 {damageFormula}，再把最终伤害总值填到下方。</>}
                </span>
              </>
            ) : (
              <span>先选择攻击/技能和目标；这里会明确显示命中所需 AC、命中加值与伤害骰。</span>
            )}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2"><label className="text-xs text-stone-400">d20命中总值<input className={`${inputCls} mt-1`} disabled={isSavingThrowAction} onChange={(event) => setAttackTotal(event.target.value)} placeholder={isSavingThrowAction ? "豁免法术无需命中" : ""} type="number" value={attackTotal} /></label><label className="text-xs text-stone-400">伤害骰最终总值<input className={`${inputCls} mt-1`} onChange={(event) => setDamageTotal(event.target.value)} type="number" value={damageTotal} /></label></div>{!isSavingThrowAction ? <label className="mt-2 flex items-center gap-2 text-xs text-amber-200"><input checked={criticalHit} onChange={(event) => setCriticalHit(event.target.checked)} type="checkbox" />天然 20 暴击（伤害总值请使用暴击骰）</label> : null}
          <label className="mt-2 flex items-start gap-2 rounded border border-ink-700 p-2 text-xs text-stone-400"><input checked={endTurnAfterAttack} onChange={(event) => setEndTurnAfterAttack(event.target.checked)} type="checkbox" /><span>攻击结算后自动结束回合并切到下一位。取消勾选可在攻击后继续使用剩余移动或附赠动作。</span></label>
          <Button className="mt-3 w-full" disabled={ended || !combat.is_my_turn || !actionName || !targetId || (!isSavingThrowAction && !attackTotal) || !damageTotal || !own?.action_available} loading={mutation.isPending} onClick={() => mutation.mutate(async () => { const result = await attackWithMyCombatant(targetId, affectedEnemies.map((item) => item.id), actionName, Number(attackTotal || 0), Number(damageTotal), criticalHit, endTurnAfterAttack) as { target_count?: number; results?: Array<{ action?: { summary?: string } }>; turn_advance?: { active_combatant?: { display_name?: string } } }; setAttackTotal(""); setDamageTotal(""); setCriticalHit(false); const summaries = (result.results ?? []).map((item) => item.action?.summary).filter((item): item is string => Boolean(item)); const next = result.turn_advance?.active_combatant?.display_name; setLastResolution([`${actionName}已完成全部 ${result.target_count ?? affectedEnemies.length} 个目标的结算。`, ...summaries, endTurnAfterAttack ? (next ? `回合已切换至 ${next}。` : "回合已经结束并完成同步。") : "你仍可移动、使用附赠动作或手动结束回合。"].join("\n")); return result; })} variant="primary">{isSavingThrowAction ? `提交玩家伤害骰并结算 ${affectedEnemies.length} 个目标` : endTurnAfterAttack ? "提交攻击并结束回合" : "提交攻击并同步结算"}</Button>
          <Button className="mt-2 w-full" disabled={ended || !combat.is_my_turn} onClick={() => mutation.mutate(() => endMyTurn(combat.version))}>结束我的回合</Button>
          {lastResolution ? <p className="mb-0 mt-2 whitespace-pre-line rounded border border-emerald-800/60 bg-emerald-950/20 p-2 text-xs text-emerald-200" data-testid="player-last-resolution">{lastResolution}</p> : null}
          {mutation.isError ? <p className="text-sm text-red-300">{mutation.error.message}</p> : null}
        </section>
        <section className={cardCls}><h2 className="mt-0 font-display text-xl">公开战斗日志</h2><div className="max-h-72 space-y-2 overflow-auto">{combat.log.map((entry) => <p className="m-0 border-b border-ink-800 pb-2 text-xs text-stone-400" key={entry.id}><span className="text-amber-300">R{entry.round_number}</span> {entry.summary}</p>)}</div></section>
      </aside>
    </div>
  );
}

function PlayerDashboard({
  snapshot,
  refresh,
  syncing,
  updatedAt,
  offline,
  degraded,
}: {
  snapshot: PlayerRoomSnapshot;
  refresh: () => void;
  syncing: boolean;
  updatedAt: number;
  offline: boolean;
  degraded: boolean;
}): ReactElement {
  const [tab, setTab] = useState<"table" | "character" | "combat" | "rules">(
    snapshot.combat?.status === "active" ? "combat" : "table",
  );
  const [intent, setIntent] = useState("");
  const [ruleText, setRuleText] = useState("");
  const [ruleHits, setRuleHits] = useState<Awaited<ReturnType<typeof searchPlayerRules>>>([]);
  const [showRoomSwitch, setShowRoomSwitch] = useState(false);
  const [switchCode, setSwitchCode] = useState("");
  const intentMutation = useMutation({ mutationFn: () => submitMyActionRequest("player_intent", intent), onSuccess: () => setIntent("") });
  const rulesMutation = useMutation({ mutationFn: () => searchPlayerRules(ruleText), onSuccess: setRuleHits });
  const roomSwitchMutation = useMutation({
    mutationFn: () => switchPlayerRoom(switchCode, snapshot.player.display_name),
    onSuccess: () => window.location.reload(),
  });
  useEffect(() => {
    if (snapshot.combat?.status === "active") setTab("combat");
  }, [snapshot.combat?.id, snapshot.combat?.status]);
  return (
    <main className="mx-auto min-h-screen max-w-[1500px] p-3 lg:p-6">
      <header className="mb-4 flex flex-wrap items-center gap-3 border-b border-ink-700 pb-4">
        <div className="mr-auto"><p className="m-0 text-xs uppercase tracking-[.18em] text-amber-300">玩家辅助台 · {snapshot.player.display_name}</p><h1 className="mb-0 mt-1 font-display text-2xl">{snapshot.campaign.name}</h1></div>
        <span className="text-xs text-stone-500">{snapshot.character?.name}</span>
        <span
          className={`rounded border px-2 py-1 text-2xs ${offline || degraded ? "border-red-800/60 bg-red-950/30 text-red-200" : syncing ? "border-amber-800/60 bg-amber-950/30 text-amber-200" : "border-emerald-800/60 bg-emerald-950/25 text-emerald-300"}`}
          title={updatedAt ? `最后同步：${new Date(updatedAt).toLocaleTimeString()}` : "尚未完成同步"}
        >
          {offline ? "网络已断开" : degraded ? "服务器连接中断 · 保留当前画面" : syncing ? "正在同步…" : "已同步"}
        </span>
        <Button onClick={() => setShowRoomSwitch((current) => !current)} size="sm" variant="primary">切换跑团</Button>
        <Button onClick={() => void logoutPlayerRoom().then(() => window.location.reload())} size="sm">退出房间</Button>
      </header>
      {showRoomSwitch ? (
        <section className="mb-4 rounded-xl border border-amber-700/70 bg-amber-950/20 p-4">
          <strong className="text-sm text-amber-100">切换到 DM 当前发布的新团</strong>
          <p className="mb-3 mt-1 text-xs leading-5 text-stone-400">
            输入新团房间码。验证成功后才会离开“{snapshot.campaign.name}”；错误房间码不会影响当前会话。
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="新团房间码"
              autoCapitalize="characters"
              className={`${inputCls} max-w-56 text-center font-mono tracking-[.2em]`}
              maxLength={8}
              onChange={(event) => setSwitchCode(event.target.value.toUpperCase())}
              placeholder="6位房间码"
              value={switchCode}
            />
            <Button
              disabled={switchCode.trim().length < 6}
              loading={roomSwitchMutation.isPending}
              onClick={() => roomSwitchMutation.mutate()}
              variant="primary"
            >
              确认切换
            </Button>
            <Button onClick={() => setShowRoomSwitch(false)}>取消</Button>
          </div>
          {roomSwitchMutation.isError ? <p className="mb-0 mt-2 text-sm text-red-300">{roomSwitchMutation.error.message}</p> : null}
        </section>
      ) : null}
      <nav className="mb-4 flex gap-2 overflow-x-auto">{([["table", "游戏推进"], ["character", "我的角色"], ["combat", snapshot.combat?.status === "active" ? "战斗中" : "战斗"], ["rules", "规则搜索"]] as const).map(([key, label]) => <Button key={key} onClick={() => setTab(key)} variant={tab === key ? "primary" : "ghost"}>{label}</Button>)}</nav>
      {tab === "character" && snapshot.character ? <CharacterView character={snapshot.character} onChanged={refresh} /> : null}
      {tab === "combat" ? <CombatView refresh={refresh} snapshot={snapshot} /> : null}
      {tab === "rules" ? <section className={cardCls}><h2 className="mt-0 font-display text-2xl">D&D 5e 本地规则搜索</h2><p className="text-sm text-stone-400">只做确定性关键词检索，不调用本地生成AI。</p><div className="flex gap-2"><input aria-label="规则关键词" className={inputCls} onChange={(event) => setRuleText(event.target.value)} placeholder="例如：擒抱、火球术、倒地" value={ruleText} /><Button disabled={!ruleText.trim()} loading={rulesMutation.isPending} onClick={() => rulesMutation.mutate()} variant="primary">搜索</Button></div><div className="mt-4 space-y-3">{ruleHits.map((hit, index) => <article className="rounded border border-ink-700 p-3" key={`${hit.name}-${index}`}><strong>{hit.name}</strong><span className="ml-2 text-2xs text-stone-500">{hit.edition} · {hit.content_type}</span><p className="mb-0 text-sm leading-6 text-stone-400">{hit.excerpt}</p></article>)}</div></section> : null}
      {tab === "table" ? <div className="grid gap-4 lg:grid-cols-[1.2fr_.8fr]">
        <div className="space-y-4">
          <section className={cardCls}><h2 className="mt-0 font-display text-2xl">{snapshot.table.scene?.name ?? "等待 DM 选择 Scene"}</h2><p className="whitespace-pre-wrap text-sm leading-6 text-stone-400">{snapshot.table.scene?.description}</p></section>
          {snapshot.table.scene ? <NoncombatActionPanel refresh={refresh} snapshot={snapshot} /> : null}
        </div>
        <aside className="space-y-4">
          <section className={cardCls}><h2 className="mt-0 font-display text-xl">公开游戏日志</h2>{snapshot.table.shared_log.length ? snapshot.table.shared_log.map((event) => <article className="mb-3 border-l-2 border-amber-700 pl-3" key={event.id}><strong className="text-sm">{event.title}</strong><p className="mb-0 mt-1 text-xs text-stone-400">{event.description}</p></article>) : <p className="text-sm text-stone-500">等待 DM 推进。</p>}</section>
          <section className={cardCls}><h2 className="mt-0 font-display text-xl">公开讲义</h2>{snapshot.table.handouts.map((handout) => <details className="mb-2 rounded border border-ink-700 p-2" key={handout.id}><summary>{handout.title}</summary><p className="whitespace-pre-wrap text-sm text-stone-400">{handout.body}</p></details>)}</section>
          <section className={cardCls}><h2 className="mt-0 font-display text-xl">自由行动</h2><p className="text-xs text-stone-500">规则列表没有覆盖时，仍可用自然语言告诉 DM。</p><textarea className={inputCls} onChange={(event) => setIntent(event.target.value)} placeholder="例如：我把耳朵贴在门上听里面的声音。" rows={3} value={intent} /><Button className="mt-2" disabled={!intent.trim()} loading={intentMutation.isPending} onClick={() => intentMutation.mutate()} variant="primary">提交给 DM 裁定</Button></section>
        </aside>
      </div> : null}
    </main>
  );
}

export function PlayerPage(): ReactElement {
  const client = useQueryClient();
  const offline = useOffline();
  const room = useQuery({
    queryKey: ["my-player-room"],
    queryFn: ({ signal }) => getMyPlayerRoom(signal),
    retry: false,
    // Keep the join form stable while the player is unauthenticated. Polling
    // the 401 response every few seconds can remount the gate while someone
    // is typing, which looks like the page refreshed and clears the room code.
    refetchInterval: false,
  });
  usePlayerRealtime(Boolean(room.data));
  const refresh = () => { void client.invalidateQueries({ queryKey: ["my-player-room"] }); };
  const missing = room.isError && isPlayerSessionMissing(room.error);
  const content = useMemo(() => room.data, [room.data]);
  if (room.isLoading) return <LoadingBlock label="正在连接玩家房间…" />;
  if (missing && !content) return <JoinRoom onJoined={refresh} />;
  if (room.isError && !content) return <main className="mx-auto max-w-xl p-6"><ErrorState error={room.error} onRetry={() => void room.refetch()} /></main>;
  if (!content) return <JoinRoom onJoined={refresh} />;
  if (!content.character) return <CharacterBuilder onDone={refresh} snapshot={content} />;
  return (
    <PlayerDashboard
      offline={offline}
      degraded={room.isError}
      refresh={refresh}
      snapshot={content}
      syncing={room.isFetching}
      updatedAt={room.dataUpdatedAt}
    />
  );
}
