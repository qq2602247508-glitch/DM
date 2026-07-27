import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactElement } from "react";

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
  type PlayerRoomSnapshot,
  type SafePlayerCharacter,
} from "../api/playerRoom";
import { getCharacterOptions } from "../api/entities";
import {
  BACKGROUNDS_2024, CLASSES_2024, SPECIES_2024,
  classSkillSelection, spellChoiceCounts, spellChoicesComplete,
  spellIsAvailable, spellSelectionRule, spellToCharacterAction,
} from "../ui/characterRules";
import { Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";

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

function CharacterView({ character }: { character: SafePlayerCharacter }): ReactElement {
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
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className={cardCls}>
        <h2 className="mt-0 font-display text-2xl">{character.name}</h2>
        <p className="text-sm text-amber-200">{character.race} · {character.class_name} Lv{character.level} · {character.background}</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">{[["HP", `${character.hp}/${character.max_hp}`], ["AC", character.armor_class], ["速度", `${character.speed}尺`], ["经验", `${character.experience} XP`], ["金币", `${character.wallet?.gp ?? 0} GP`]].map(([label, value]) => <div className="rounded bg-ink-950 p-3 text-center" key={label}><span className="block text-2xs text-stone-500">{label}</span><strong className="font-mono text-lg">{value}</strong></div>)}</div>
        <div className="mt-3 grid grid-cols-3 gap-2">{Object.entries(ABILITIES).map(([key, label]) => <div className="rounded border border-ink-700 p-2 text-center" key={key}><span className="block text-2xs text-stone-500">{label}</span><strong>{character.ability_scores[key] ?? 10}</strong></div>)}</div>
      </section>
      <section className={cardCls}><h2 className="mt-0 font-display text-xl">动作与法术</h2>{spellcastingAbility ? <p className="text-xs text-amber-200">施法属性：{spellcastingAbility}</p> : null}{[...character.actions, ...character.spells].length ? [...character.actions, ...character.spells].map((item, index) => <details className="mb-2 rounded border border-ink-700 p-2" key={`${display(item)}-${index}`}><summary className="cursor-pointer text-sm text-parchment-100">{display(item)}</summary><pre className="whitespace-pre-wrap text-xs text-stone-400">{JSON.stringify(item, null, 2)}</pre></details>) : <p className="text-sm text-stone-500">暂无动作或法术。</p>}</section>
      <section className={cardCls}><h2 className="mt-0 font-display text-xl">背包与装备</h2>{[...character.inventory, ...character.equipment].length ? <ul className="pl-5 text-sm">{[...character.inventory, ...character.equipment].map((item, index) => <li className="mb-1" key={`${display(item)}-${index}`}>{display(item)}</li>)}</ul> : <p className="text-sm text-stone-500">背包为空。</p>}</section>
      <section className={cardCls}><h2 className="mt-0 font-display text-xl">特性、技能与资源</h2><div className="flex flex-wrap gap-2">{character.features.map((item, index) => <span className="rounded bg-violet-500/10 px-2 py-1 text-xs text-violet-200" key={`${display(item)}-${index}`} title={display(item)}>{display(item)}</span>)}</div><p className="mt-4 text-xs text-stone-400">熟练：{character.proficiencies.map(display).join("、") || "无"}</p><p className="text-xs text-stone-400">技能：{Object.keys(character.skills).join("、") || "无"}</p>{resources.map((resource) => <div className="mt-2 flex items-center gap-3 rounded border border-ink-700 p-3 text-xs" key={resource.key}><strong className="mr-auto text-parchment-100">{resource.label}</strong>{resource.current !== undefined && resource.max !== undefined ? <span className="font-mono text-base text-amber-200">{display(resource.current)}/{display(resource.max)}</span> : null}{resource.recovery ? <span className="text-stone-500">{resource.recovery}</span> : null}</div>)}</section>
    </div>
  );
}

function SceneGridView({ snapshot, onMove }: { snapshot: PlayerRoomSnapshot; onMove: (row: number, col: number) => void }): ReactElement {
  const scene = snapshot.table.scene;
  const combat = snapshot.combat;
  if (!scene?.grid) return <EmptyState hint="等待 DM 选择带网格的场景。" title="尚无公开地图" />;
  const { width, height } = scene.grid;
  const combatByCell = new Map(combat?.combatants.filter((item) => item.position).map((item) => [`${item.position?.row}:${item.position?.col}`, item]) ?? []);
  const sceneTokensByCell = new Map(scene.tokens.map((item) => [`${item.row}:${item.col}`, item]));
  const objectsByCell = new Map(scene.objects.map((item) => [`${item.row}:${item.col}`, item]));
  const cellsByCell = new Map((scene.grid.cells ?? []).map((item) => [`${item.row}:${item.col}`, item]));
  return (
    <div className="overflow-auto rounded border border-ink-700 bg-ink-950 p-1">
      <div className="grid min-w-[560px] gap-px" style={{ gridTemplateColumns: `repeat(${width}, minmax(28px, 1fr))` }}>
        {Array.from({ length: width * height }, (_, index) => {
          const row = Math.floor(index / width) + 1;
          const col = index % width + 1;
          const combatant = combatByCell.get(`${row}:${col}`);
          const sceneToken = sceneTokensByCell.get(`${row}:${col}`);
          const object = objectsByCell.get(`${row}:${col}`);
          const terrain = cellsByCell.get(`${row}:${col}`);
          const blocked = object?.object_type === "wall" || (object?.object_type === "door" && object.state !== "open");
          const token = combatant ? null : sceneToken;
          const terrainClass = terrain?.kind === "wall" ? "bg-stone-800" : terrain?.kind === "cover" ? "bg-amber-950/50" : terrain?.kind === "water" ? "bg-sky-950/60" : "bg-ink-900";
          const ownSceneToken = token?.entity_type === "character" && token.entity_id === snapshot.character?.id;
          return <button aria-label={`格子 ${row},${col}`} className={`relative aspect-square border border-ink-800 text-[9px] ${blocked ? "bg-stone-800" : combat?.is_my_turn ? `${terrainClass} hover:bg-emerald-950` : terrainClass} ${combatant?.is_own || ownSceneToken ? "ring-2 ring-amber-400" : ""}`} disabled={!combat?.is_my_turn || blocked} key={`${row}-${col}`} onClick={() => onMove(row, col)} title={object?.label ?? terrain?.label ?? token?.label ?? `${row},${col}`} type="button">
            {object ? <span className="absolute left-0 top-0 text-stone-500">{object.label.slice(0, 2)}</span> : null}
            {combatant ? <span className={`flex h-full items-center justify-center rounded-full px-1 text-center ${combatant.is_own ? "bg-amber-500/30 text-amber-100" : combatant.entity_type === "monster" ? "bg-red-500/25 text-red-100" : "bg-blue-500/20 text-blue-100"}`}>{combatant.name.slice(0, 4)}</span> : null}
            {token ? <span className={`flex h-full items-center justify-center rounded-full px-1 text-center ${ownSceneToken ? "bg-amber-500/30 text-amber-100" : token.entity_type === "monster" ? "bg-red-500/25 text-red-100" : token.entity_type === "npc" ? "bg-violet-500/25 text-violet-100" : "bg-blue-500/20 text-blue-100"}`}>{token.label.slice(0, 4)}</span> : null}
          </button>;
        })}
      </div>
    </div>
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

function CombatView({ snapshot, refresh }: { snapshot: PlayerRoomSnapshot; refresh: () => void }): ReactElement {
  const combat = snapshot.combat;
  const [actionName, setActionName] = useState("");
  const [targetId, setTargetId] = useState("");
  const [attackTotal, setAttackTotal] = useState("");
  const [damageTotal, setDamageTotal] = useState("");
  const [rolls, setRolls] = useState<Record<string, string>>({});
  const own = combat?.combatants.find((item) => item.is_own);
  const actions = (snapshot.character?.actions ?? []).filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null);
  const enemies = combat?.combatants.filter((item) => item.entity_type === "monster" && item.health_status !== "倒地") ?? [];
  const selectedAction = actions.find((item) => display(item.name) === actionName);
  const selectedTarget = enemies.find((item) => item.id === targetId);
  const attackBonus = typeof selectedAction?.attack_bonus === "number"
    ? selectedAction.attack_bonus
    : null;
  const damageFormula = display(selectedAction?.damage ?? selectedAction?.description ?? "角色卡所列伤害骰");
  const mutation = useMutation({ mutationFn: async (fn: () => Promise<unknown>) => fn(), onSuccess: refresh });
  if (!combat) return <EmptyState hint="DM 从当前 Scene 发起战斗后，这里会自动切换。" title="当前没有战斗" />;
  const ended = combat.status === "ended";
  return (
    <div className="grid gap-4 xl:grid-cols-[1.35fr_.65fr]">
      <section className={cardCls}>
        <div className="mb-3 flex flex-wrap items-center gap-2"><h2 className="m-0 mr-auto font-display text-2xl">{combat.name}</h2><span className="rounded bg-ink-950 px-2 py-1 text-xs">第 {combat.round_number} 轮</span><span className={`rounded px-2 py-1 text-xs ${ended ? "bg-amber-500/20 text-amber-200" : combat.is_my_turn ? "bg-emerald-500/20 text-emerald-200" : "bg-ink-800 text-stone-400"}`}>{ended ? "战斗已结束" : combat.is_my_turn ? "轮到你行动" : "等待其他单位"}</span></div>
        <div className="mb-3 flex gap-2 overflow-x-auto">{combat.combatants.map((item) => <div className={`min-w-32 rounded border p-2 text-xs ${item.id === combat.active_combatant_id ? "border-amber-400" : "border-ink-700"}`} key={item.id}><strong>{item.name}</strong><span className="block text-stone-500">{item.health_status} · 先攻 {item.initiative}</span></div>)}</div>
        <SceneGridView onMove={(row, col) => own && mutation.mutate(() => moveMyCombatant(row, col, own.version ?? 1))} snapshot={snapshot} />
        {own ? <p className="mb-0 mt-2 text-xs text-stone-400">剩余移动 {own.movement_remaining_ft ?? 0}尺 · 动作 {own.action_available ? "可用" : "已用"} · 附赠动作 {own.bonus_action_available ? "可用" : "已用"}</p> : null}
      </section>
      <aside className="space-y-4">
        <section className={cardCls}>
          <h2 className="mt-0 font-display text-xl">当前战斗面板</h2>
          {combat.pending_rolls.map((roll) => <div className="mb-3 rounded border border-violet-700 bg-violet-950/20 p-3" key={roll.id}><strong className="text-sm">{roll.action_name}</strong><p className="text-xs text-stone-400">请掷 {roll.roll_formula}，总值需达到 DC {roll.dc}（{roll.ability || roll.skill || roll.resolution_type}）</p><div className="flex gap-2"><input aria-label={`${roll.action_name}骰值`} className={inputCls} onChange={(event) => setRolls((current) => ({ ...current, [roll.id]: event.target.value }))} type="number" value={rolls[roll.id] ?? ""} /><Button disabled={!rolls[roll.id]} onClick={() => mutation.mutate(() => submitMyPlayerRoll(roll.id, roll.version, Number(rolls[roll.id])))} variant="primary">提交</Button></div></div>)}
          {ended ? <p className="rounded border border-amber-800/60 bg-amber-950/20 p-3 text-sm text-amber-100">战斗已由 DM 结束。你仍可查看地图和完整公开日志；奖励请到“我的角色”查看。</p> : null}
          <label className="block text-xs text-stone-400">攻击/技能<select className={`${inputCls} mt-1`} disabled={ended || !combat.is_my_turn} onChange={(event) => setActionName(event.target.value)} value={actionName}><option value="">选择角色卡动作</option>{actions.map((action) => <option key={display(action.name)} value={display(action.name)}>{display(action.name)} · {display(action.damage ?? action.description ?? "")}</option>)}</select></label>
          <label className="mt-2 block text-xs text-stone-400">目标<select className={`${inputCls} mt-1`} disabled={ended || !combat.is_my_turn} onChange={(event) => setTargetId(event.target.value)} value={targetId}><option value="">选择合法敌人</option>{enemies.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.health_status}</option>)}</select></label>
          <div className="mt-3 rounded border border-amber-800/60 bg-amber-950/20 p-3 text-xs leading-5 text-amber-100">
            {selectedAction && selectedTarget ? (
              <>
                <strong>{selectedAction.name as string} → {selectedTarget.name}</strong>
                <span className="mt-1 block">
                  请掷 d20{attackBonus === null ? "并加入角色卡命中调整值" : ` + ${attackBonus} 命中加值`}；
                  最终总值需要达到 AC {selectedTarget.armor_class}（≥ {selectedTarget.armor_class}）才命中。
                  命中后掷 {damageFormula}，再把最终伤害总值填到下方。
                </span>
              </>
            ) : (
              <span>先选择攻击/技能和目标；这里会明确显示命中所需 AC、命中加值与伤害骰。</span>
            )}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2"><label className="text-xs text-stone-400">d20命中总值<input className={`${inputCls} mt-1`} onChange={(event) => setAttackTotal(event.target.value)} type="number" value={attackTotal} /></label><label className="text-xs text-stone-400">伤害骰最终总值<input className={`${inputCls} mt-1`} onChange={(event) => setDamageTotal(event.target.value)} type="number" value={damageTotal} /></label></div>
          <Button className="mt-3 w-full" disabled={ended || !combat.is_my_turn || !actionName || !targetId || !attackTotal || !damageTotal || !own?.action_available} loading={mutation.isPending} onClick={() => mutation.mutate(() => attackWithMyCombatant(targetId, actionName, Number(attackTotal), Number(damageTotal)))} variant="primary">提交攻击并同步结算</Button>
          <Button className="mt-2 w-full" disabled={ended || !combat.is_my_turn} onClick={() => mutation.mutate(() => endMyTurn(combat.version))}>结束我的回合</Button>
          {mutation.isError ? <p className="text-sm text-red-300">{mutation.error.message}</p> : null}
        </section>
        <section className={cardCls}><h2 className="mt-0 font-display text-xl">公开战斗日志</h2><div className="max-h-72 space-y-2 overflow-auto">{combat.log.map((entry) => <p className="m-0 border-b border-ink-800 pb-2 text-xs text-stone-400" key={entry.id}><span className="text-amber-300">R{entry.round_number}</span> {entry.summary}</p>)}</div></section>
      </aside>
    </div>
  );
}

function PlayerDashboard({ snapshot, refresh }: { snapshot: PlayerRoomSnapshot; refresh: () => void }): ReactElement {
  const [tab, setTab] = useState<"table" | "character" | "combat" | "rules">(
    snapshot.combat?.status === "active" ? "combat" : "table",
  );
  const [intent, setIntent] = useState("");
  const [ruleText, setRuleText] = useState("");
  const [ruleHits, setRuleHits] = useState<Awaited<ReturnType<typeof searchPlayerRules>>>([]);
  const intentMutation = useMutation({ mutationFn: () => submitMyActionRequest("player_intent", intent), onSuccess: () => setIntent("") });
  const rulesMutation = useMutation({ mutationFn: () => searchPlayerRules(ruleText), onSuccess: setRuleHits });
  return (
    <main className="mx-auto min-h-screen max-w-[1500px] p-3 lg:p-6">
      <header className="mb-4 flex flex-wrap items-center gap-3 border-b border-ink-700 pb-4">
        <div className="mr-auto"><p className="m-0 text-xs uppercase tracking-[.18em] text-amber-300">玩家辅助台 · {snapshot.player.display_name}</p><h1 className="mb-0 mt-1 font-display text-2xl">{snapshot.campaign.name}</h1></div>
        <span className="text-xs text-stone-500">{snapshot.character?.name}</span>
        <Button onClick={() => void logoutPlayerRoom().then(() => window.location.reload())} size="sm">退出房间</Button>
      </header>
      <nav className="mb-4 flex gap-2 overflow-x-auto">{([["table", "游戏推进"], ["character", "我的角色"], ["combat", snapshot.combat?.status === "active" ? "战斗中" : "战斗"], ["rules", "规则搜索"]] as const).map(([key, label]) => <Button key={key} onClick={() => setTab(key)} variant={tab === key ? "primary" : "ghost"}>{label}</Button>)}</nav>
      {tab === "character" && snapshot.character ? <CharacterView character={snapshot.character} /> : null}
      {tab === "combat" ? <CombatView refresh={refresh} snapshot={snapshot} /> : null}
      {tab === "rules" ? <section className={cardCls}><h2 className="mt-0 font-display text-2xl">D&D 5e 本地规则搜索</h2><p className="text-sm text-stone-400">只做确定性关键词检索，不调用本地生成AI。</p><div className="flex gap-2"><input aria-label="规则关键词" className={inputCls} onChange={(event) => setRuleText(event.target.value)} placeholder="例如：擒抱、火球术、倒地" value={ruleText} /><Button disabled={!ruleText.trim()} loading={rulesMutation.isPending} onClick={() => rulesMutation.mutate()} variant="primary">搜索</Button></div><div className="mt-4 space-y-3">{ruleHits.map((hit, index) => <article className="rounded border border-ink-700 p-3" key={`${hit.name}-${index}`}><strong>{hit.name}</strong><span className="ml-2 text-2xs text-stone-500">{hit.edition} · {hit.content_type}</span><p className="mb-0 text-sm leading-6 text-stone-400">{hit.excerpt}</p></article>)}</div></section> : null}
      {tab === "table" ? <div className="grid gap-4 lg:grid-cols-[1.2fr_.8fr]">
        <div className="space-y-4">
          <section className={cardCls}><h2 className="mt-0 font-display text-2xl">{snapshot.table.scene?.name ?? "等待 DM 选择 Scene"}</h2><p className="whitespace-pre-wrap text-sm leading-6 text-stone-400">{snapshot.table.scene?.description}</p><SceneGridView onMove={() => undefined} snapshot={snapshot} /></section>
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
  const room = useQuery({
    queryKey: ["my-player-room"],
    queryFn: ({ signal }) => getMyPlayerRoom(signal),
    retry: false,
    // Keep the join form stable while the player is unauthenticated. Polling
    // the 401 response every few seconds can remount the gate while someone
    // is typing, which looks like the page refreshed and clears the room code.
    refetchInterval: (query) => {
      if (!query.state.data) return false;
      return query.state.data.combat?.status === "active" ? 1_000 : 2_500;
    },
  });
  const refresh = () => { void client.invalidateQueries({ queryKey: ["my-player-room"] }); };
  const missing = room.isError && isPlayerSessionMissing(room.error);
  const content = useMemo(() => room.data, [room.data]);
  if (room.isLoading) return <LoadingBlock label="正在连接玩家房间…" />;
  if (missing) return <JoinRoom onJoined={refresh} />;
  if (room.isError) return <main className="mx-auto max-w-xl p-6"><ErrorState error={room.error} onRetry={() => void room.refetch()} /></main>;
  if (!content) return <JoinRoom onJoined={refresh} />;
  if (!content.character) return <CharacterBuilder onDone={refresh} snapshot={content} />;
  return <PlayerDashboard refresh={refresh} snapshot={content} />;
}
