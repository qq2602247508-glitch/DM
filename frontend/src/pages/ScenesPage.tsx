import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactElement } from "react";

import { listCharacters, listLocations, listNpcs } from "../api/entities";
import type { SceneCombatResult, SceneGrid } from "../api/types";
import {
  addSceneParticipant,
  createMonster,
  createPersistentGrid,
  createSceneObject,
  createScene,
  listMonsters,
  listSceneParticipants,
  listScenes,
  getSceneGrid,
  removeSceneParticipant,
  startSceneCombat,
} from "../api/world";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { useToast } from "../hooks/toastContext";
import { navigate } from "../hooks/useHashRoute";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls } from "../ui/styles";
import { HpBar } from "../ui/widgets";

function generateSceneGrid(name: string, description: string): SceneGrid {
  const text = `${name} ${description}`;
  const church = /教堂|神殿|祭坛|神祇/.test(text);
  const cells: SceneGrid["cells"] = [];
  for (let col = 1; col <= 12; col += 1) {
    cells.push({ row: 1, col, kind: "wall", label: "墙" }, { row: 8, col, kind: "wall", label: "墙" });
  }
  for (let row = 2; row <= 7; row += 1) {
    cells.push({ row, col: 1, kind: "wall", label: "墙" }, { row, col: 12, kind: "wall", label: "墙" });
  }
  cells.push({ row: 8, col: 6, kind: "door", label: "入口" });
  if (church) {
    cells.push(
      { row: 2, col: 6, kind: "object", label: "祭坛" },
      { row: 2, col: 7, kind: "object", label: "祭坛" },
      { row: 4, col: 4, kind: "cover", label: "长椅" },
      { row: 4, col: 9, kind: "cover", label: "长椅" },
      { row: 6, col: 4, kind: "cover", label: "长椅" },
      { row: 6, col: 9, kind: "cover", label: "长椅" },
      { row: 3, col: 10, kind: "object", label: "烛台" },
    );
  } else {
    cells.push(
      { row: 3, col: 7, kind: "cover", label: "掩体" },
      { row: 6, col: 4, kind: "cover", label: "掩体" },
      { row: 5, col: 10, kind: "object", label: "可互动物" },
    );
  }
  return { width: 12, height: 8, cell_size_ft: 5, theme: church ? "旧教堂" : "通用场景", cells };
}

function readSceneGrid(notes: string | null): SceneGrid | null {
  if (!notes) return null;
  try {
    const parsed = JSON.parse(notes) as { scene_grid?: SceneGrid };
    return parsed.scene_grid ?? null;
  } catch {
    return null;
  }
}

function SceneGridPreview({ grid }: { grid: SceneGrid }): ReactElement {
  return (
    <div className="mt-3">
      <p className="mb-2 text-2xs text-stone-500">{grid.theme} · {grid.width}×{grid.height} · 每格 {grid.cell_size_ft} 尺</p>
      <div className="grid max-w-[600px] gap-px overflow-hidden rounded border border-ink-700 bg-ink-700" style={{ gridTemplateColumns: `repeat(${grid.width}, minmax(0, 1fr))` }}>
        {Array.from({ length: grid.width * grid.height }, (_, index) => {
          const row = Math.floor(index / grid.width) + 1;
          const col = (index % grid.width) + 1;
          const cell = grid.cells.find((item) => item.row === row && item.col === col);
          const color = cell?.kind === "wall" ? "bg-stone-700" : cell?.kind === "cover" ? "bg-emerald-900" : cell?.kind === "door" ? "bg-amber-800" : cell?.kind === "object" ? "bg-violet-900" : "bg-ink-950";
          return <div className={`aspect-square min-h-6 ${color}`} key={`${row}-${col}`} title={cell?.label ?? "地面"} />;
        })}
      </div>
    </div>
  );
}

function ScenesContent({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [sceneId, setSceneId] = useState("");
  const [sceneName, setSceneName] = useState("");
  const [sceneDescription, setSceneDescription] = useState("");
  const [locationId, setLocationId] = useState("");
  const [entityKey, setEntityKey] = useState("");
  const [monsterName, setMonsterName] = useState("");
  const [monsterAc, setMonsterAc] = useState("12");
  const [monsterHp, setMonsterHp] = useState("10");
  const [monsterDex, setMonsterDex] = useState("10");
  const [combatResult, setCombatResult] = useState<SceneCombatResult | null>(null);
  const [objectKind, setObjectKind] = useState<"wall" | "door" | "cover" | "terrain" | "light" | "trap" | "treasure" | "furniture" | "portal">("cover");
  const [objectVisibility, setObjectVisibility] = useState<"public" | "dm" | "hidden">("public");
  const scenes = useQuery({ queryKey: ["scenes", campaignId], queryFn: ({ signal }) => listScenes(campaignId, signal) });
  const locations = useQuery({ queryKey: ["locations", campaignId], queryFn: ({ signal }) => listLocations(campaignId, signal) });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const npcs = useQuery({ queryKey: ["npcs", campaignId], queryFn: ({ signal }) => listNpcs(campaignId, signal) });
  const monsters = useQuery({ queryKey: ["monsters", campaignId], queryFn: ({ signal }) => listMonsters(campaignId, signal) });
  useEffect(() => {
    if (!sceneId && scenes.data?.[0]) setSceneId(scenes.data[0].id);
  }, [sceneId, scenes.data]);
  const participants = useQuery({
    queryKey: ["scene-participants", campaignId, sceneId],
    queryFn: ({ signal }) => listSceneParticipants(campaignId, sceneId, signal),
    enabled: Boolean(sceneId),
  });
  const persistentGrid = useQuery({ queryKey: ["persistent-scene-grid", campaignId, sceneId], queryFn: ({ signal }) => getSceneGrid(campaignId, sceneId, signal), enabled: Boolean(sceneId), retry: false });
  const candidates = useMemo(() => [
    ...(characters.data ?? []).map((entity) => ({ key: `character:${entity.id}`, label: `玩家 · ${entity.name}` })),
    ...(npcs.data ?? []).map((entity) => ({ key: `npc:${entity.id}`, label: `NPC · ${entity.name}` })),
    ...(monsters.data ?? []).map((entity) => ({ key: `monster:${entity.id}`, label: `怪物 · ${entity.name}` })),
  ], [characters.data, monsters.data, npcs.data]);
  const sceneCreate = useMutation({
    mutationFn: () => {
      const grid = generateSceneGrid(sceneName.trim(), sceneDescription.trim());
      return createScene(campaignId, {
        name: sceneName.trim(), location_id: locationId || null,
        description: sceneDescription.trim() || null,
        notes: JSON.stringify({ scene_grid: grid }),
      });
    },
    onSuccess: (scene) => {
      setSceneName("");
      setSceneDescription("");
      setSceneId(scene.id);
      void client.invalidateQueries({ queryKey: ["scenes", campaignId] });
      showToast("场景已创建");
    },
    onError: () => showToast("场景创建失败", "error"),
  });
  const gridCreate = useMutation({
    mutationFn: () => createPersistentGrid(campaignId, sceneId, { width: activeGrid?.width ?? 12, height: activeGrid?.height ?? 8, cell_size_ft: 5, mode: "exploration", public_description: activeScene?.description ?? null }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["persistent-scene-grid", campaignId, sceneId] }); showToast("持久探索网格已生成"); },
    onError: () => showToast("网格已存在或创建失败", "error"),
  });
  const objectCreate = useMutation({
    mutationFn: (position: { row: number; col: number }) => createSceneObject(campaignId, sceneId, { object_type: objectKind, label: objectKind === "terrain" ? "困难地形" : objectKind, row: position.row, col: position.col, visibility: objectVisibility, metadata_json: objectKind === "terrain" ? { difficult: true } : {} }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["persistent-scene-grid", campaignId, sceneId] }); },
    onError: () => showToast("对象放置失败", "error"),
  });
  const participantAdd = useMutation({
    mutationFn: () => {
      const [entity_type, entity_id] = entityKey.split(":");
      if (!entity_type || !entity_id) throw new Error("请选择参与者");
      return addSceneParticipant(campaignId, sceneId, {
        entity_type: entity_type as "character" | "npc" | "monster",
        entity_id,
      });
    },
    onSuccess: () => {
      setEntityKey("");
      void client.invalidateQueries({ queryKey: ["scene-participants", campaignId, sceneId] });
      showToast("已加入场景");
    },
    onError: () => showToast("加入失败，该角色可能已在场景中", "error"),
  });
  const participantRemove = useMutation({
    mutationFn: (input: { id: string; version: number }) => removeSceneParticipant(campaignId, sceneId, input.id, input.version),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["scene-participants", campaignId, sceneId] });
      showToast("已移出场景");
    },
  });
  const monsterCreate = useMutation({
    mutationFn: () => createMonster(campaignId, {
      name: monsterName.trim(),
      armor_class: Number(monsterAc),
      hp: Number(monsterHp),
      max_hp: Number(monsterHp),
      speed: 30,
      ability_scores: { strength: 10, dexterity: Number(monsterDex), constitution: 10, intelligence: 10, wisdom: 10, charisma: 10 },
      source_name: "DM 自定义",
    }),
    onSuccess: () => {
      setMonsterName("");
      void client.invalidateQueries({ queryKey: ["monsters", campaignId] });
      showToast("怪物实例已创建，可加入任意场景");
    },
    onError: () => showToast("怪物创建失败", "error"),
  });
  const combatStart = useMutation({
    mutationFn: () => startSceneCombat(campaignId, sceneId),
    onSuccess: (result) => {
      setCombatResult(result);
      void client.invalidateQueries({ queryKey: ["combats", campaignId] });
      showToast("已按敏捷自动掷先攻并创建战斗");
    },
    onError: () => showToast("发起战斗失败，请确保场景中至少有一名参与者", "error"),
  });
  const activeScene = scenes.data?.find((scene) => scene.id === sceneId);
  const activeGrid = activeScene ? readSceneGrid(activeScene.notes) : null;
  return (
    <div className="mx-auto max-w-[1200px] p-4 lg:p-6">
      <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
        <Panel eyebrow="地点的当前可玩快照" title="场景">
          <form className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => { event.preventDefault(); sceneCreate.mutate(); }}>
            <input className={inputCls} onChange={(event) => setSceneName(event.target.value)} placeholder="场景名称" value={sceneName} />
            <select className={selectCls} onChange={(event) => setLocationId(event.target.value)} value={locationId}>
              <option value="">不绑定地点</option>
              {locations.data?.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
            </select>
            <input className={`${inputCls} sm:col-span-2`} onChange={(event) => setSceneDescription(event.target.value)} placeholder="场景描述，例如：被异端神祇信徒占领的旧教堂" value={sceneDescription} />
            <Button disabled={!sceneName.trim()} loading={sceneCreate.isPending} type="submit" variant="primary">创建场景</Button>
          </form>
          <div className="mt-4">
            <label className="mb-1.5 block text-xs text-stone-500">当前场景</label>
            <select className={selectCls} onChange={(event) => { setSceneId(event.target.value); setCombatResult(null); }} value={sceneId}>
              <option value="">选择场景</option>
              {scenes.data?.map((scene) => <option key={scene.id} value={scene.id}>{scene.name}</option>)}
            </select>
          </div>
          {activeScene ? <p className="mb-0 mt-3 text-xs text-stone-500">{activeScene.description || "这个场景尚未添加描述。"} · {participants.data?.length ?? 0} 名参与者</p> : null}
          {activeGrid ? <SceneGridPreview grid={activeGrid} /> : null}
          {sceneId ? <div className="mt-3 flex flex-wrap gap-2"><Button loading={gridCreate.isPending} onClick={() => gridCreate.mutate()} variant="ghost">生成持久探索网格</Button><span className="self-center text-2xs text-stone-500">网格、对象与位置会写入场景事实；战斗将复用它。</span></div> : null}
          {persistentGrid.data ? <div className="mt-3"><div className="mb-2 flex flex-wrap gap-2"><select className={selectCls} onChange={(event) => setObjectKind(event.target.value as typeof objectKind)} value={objectKind}>{["wall","door","cover","terrain","light","trap","treasure","furniture","portal"].map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select><select className={selectCls} onChange={(event) => setObjectVisibility(event.target.value as typeof objectVisibility)} value={objectVisibility}><option value="public">公开层</option><option value="dm">DM 私密层</option><option value="hidden">隐藏层</option></select><span className="self-center text-2xs text-stone-500">点击格子放置对象；困难地形移动消耗翻倍。</span></div><div className="grid max-w-[600px] gap-px overflow-hidden rounded border border-ink-700 bg-ink-700" style={{ gridTemplateColumns: `repeat(${persistentGrid.data.grid.width}, minmax(0, 1fr))` }}>{Array.from({ length: persistentGrid.data.grid.width * persistentGrid.data.grid.height }, (_, index) => { const row = Math.floor(index / persistentGrid.data.grid.width) + 1; const col = index % persistentGrid.data.grid.width + 1; const obj = persistentGrid.data.objects.find((item) => item.row === row && item.col === col); return <button className={`aspect-square min-h-6 ${obj?.object_type === "wall" ? "bg-stone-700" : obj?.object_type === "terrain" ? "bg-amber-900" : obj?.visibility !== "public" ? "bg-violet-950" : obj ? "bg-emerald-900" : "bg-ink-950"}`} disabled={objectCreate.isPending} key={`${row}-${col}`} onClick={() => objectCreate.mutate({ row, col })} title={obj ? `${obj.label} · ${obj.visibility}` : `${row},${col}`} type="button" />; })}</div><p className="mt-1 text-2xs text-stone-500">公开 {persistentGrid.data.objects.filter((item) => item.visibility === "public").length} · DM/隐藏 {persistentGrid.data.objects.filter((item) => item.visibility !== "public").length}</p></div> : null}
        </Panel>
        <Panel eyebrow="可复用原子" title="快速创建怪物实例">
          <form className="grid gap-2 sm:grid-cols-5" onSubmit={(event) => { event.preventDefault(); monsterCreate.mutate(); }}>
            <input className={`${inputCls} sm:col-span-2`} onChange={(event) => setMonsterName(event.target.value)} placeholder="怪物名称" value={monsterName} />
            <input className={inputCls} min="0" onChange={(event) => setMonsterAc(event.target.value)} placeholder="AC" type="number" value={monsterAc} />
            <input className={inputCls} min="0" onChange={(event) => setMonsterHp(event.target.value)} placeholder="HP" type="number" value={monsterHp} />
            <Button disabled={!monsterName.trim()} loading={monsterCreate.isPending} type="submit">创建</Button>
            <label className="text-2xs text-stone-600 sm:col-span-2">敏捷值（用于先攻）
              <input className={`${inputCls} mt-1`} max="30" min="1" onChange={(event) => setMonsterDex(event.target.value)} type="number" value={monsterDex} />
            </label>
          </form>
        </Panel>
      </div>
      <Panel
        action={<Button disabled={!sceneId || !participants.data?.length} loading={combatStart.isPending} onClick={() => combatStart.mutate()} variant="danger" icon="sword">从场景发起战斗</Button>}
        className="mt-4"
        eyebrow="玩家 / NPC / 怪物均为引用，不复制"
        title="场景参与者"
      >
        {!sceneId ? <EmptyState hint="先创建或选择一个场景。" title="尚未选择场景" /> : (
          <>
            <div className="flex gap-2">
              <select className={selectCls} onChange={(event) => setEntityKey(event.target.value)} value={entityKey}>
                <option value="">选择玩家、NPC 或怪物</option>
                {candidates.map((candidate) => <option key={candidate.key} value={candidate.key}>{candidate.label}</option>)}
              </select>
              <Button disabled={!entityKey} loading={participantAdd.isPending} onClick={() => participantAdd.mutate()} variant="primary">加入场景</Button>
            </div>
            {participants.isLoading ? <LoadingBlock /> : null}
            {participants.isError ? <div className="mt-3"><ErrorState error={participants.error} onRetry={() => void participants.refetch()} /></div> : null}
            {participants.data?.length === 0 ? <EmptyState hint="选择上方原子角色加入；同一 NPC 可以在不同场景中复用。" title="场景里还没有角色" /> : null}
            {participants.data?.length ? (
              <ul className="m-0 mt-4 grid gap-2 p-0 md:grid-cols-2">
                {participants.data.map((participant) => (
                  <li className="list-none rounded-md border border-ink-700 bg-ink-950/50 p-3" key={participant.id}>
                    <div className="flex items-center gap-2">
                      <Badge tone={participant.entity_type === "character" ? "ok" : participant.entity_type === "npc" ? "ai" : "danger"}>{participant.entity_type}</Badge>
                      <strong className="text-sm text-parchment-100">{participant.entity.name}</strong>
                      <Button className="ml-auto" loading={participantRemove.isPending} onClick={() => participantRemove.mutate({ id: participant.id, version: participant.version })} size="sm">移出</Button>
                    </div>
                    <div className="mt-2"><HpBar hp={participant.entity.hp} maxHp={participant.entity.max_hp} /></div>
                    <p className="mb-0 mt-2 text-2xs text-stone-600">AC {participant.entity.armor_class} · 敏捷 {participant.entity.ability_scores.dexterity ?? 10}</p>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        )}
      </Panel>
      {combatResult ? (
        <Panel
          action={<Button onClick={() => navigate("/combat")} variant="primary" icon="sword">进入战斗辅助</Button>}
          className="mt-4"
          eyebrow="公开掷骰过程"
          title={`先攻结果 · ${combatResult.combat.name}`}
        >
          <ol className="m-0 space-y-2 p-0">
            {[...combatResult.initiative_rolls].sort((a, b) => b.total - a.total).map((roll) => (
              <li className="flex items-center gap-3 rounded border border-ink-700 px-3 py-2 text-sm" key={`${roll.entity_type}-${roll.entity_id}`}>
                <strong className="min-w-0 flex-1 text-parchment-100">{roll.name}</strong>
                <span className="font-mono text-xs text-stone-500">d20({roll.die}) + 敏捷({roll.dexterity_modifier >= 0 ? "+" : ""}{roll.dexterity_modifier})</span>
                <Badge tone="ember">先攻 {roll.total}</Badge>
              </li>
            ))}
          </ol>
        </Panel>
      ) : null}
    </div>
  );
}

export function ScenesPage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <ScenesContent campaignId={campaignId} />}</RequireCampaign>;
}
