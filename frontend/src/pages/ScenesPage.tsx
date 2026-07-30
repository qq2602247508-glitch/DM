import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactElement } from "react";
import { createClientId } from "../ui/id";

import { listCharacters, listLocations, listNpcs } from "../api/entities";
import type { Location, Scene, SceneCombatResult, SceneGrid } from "../api/types";
import {
  addSceneParticipant,
  createMonster,
  createPersistentGrid,
  createSceneObject,
  createSceneToken,
  createScene,
  confirmExploration,
  confirmTravel,
  listMonsters,
  listSceneParticipants,
  listScenes,
  getSceneGrid,
  previewExploration,
  previewTravel,
  removeSceneParticipant,
  startSceneCombat,
  type ExplorationInput,
  type TravelInput,
} from "../api/world";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { SceneGridPreview } from "../components/SceneGridPreview";
import { useToast } from "../hooks/toastContext";
import { navigate } from "../hooks/useHashRoute";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { xpForChallengeRating } from "../ui/progressionRules";
import { generateTacticalSceneGrid } from "../ui/sceneGridGenerator";
import { persistentGridAsSceneGrid } from "../ui/persistentSceneGrid";
import { buildSceneFlow, readSceneStoryOutline, sortScenesByOutline } from "../ui/sceneOutline";
import { inputCls, selectCls } from "../ui/styles";
import { HpBar } from "../ui/widgets";

function readSceneGrid(notes: string | null): SceneGrid | null {
  if (!notes) return null;
  try {
    const parsed = JSON.parse(notes) as { scene_grid?: SceneGrid };
    return parsed.scene_grid ?? null;
  } catch {
    return null;
  }
}

function requestGameTableScene(campaignId: string, sceneId: string): void {
  sessionStorage.setItem(`dnd-dm-requested-scene:${campaignId}`, sceneId);
  navigate("/game-table");
}

function SceneAtomLibrary({
  campaignId,
  scenes,
  locations,
  grids,
  expandedSceneId,
  onExpand,
  onEdit,
}: {
  campaignId: string;
  scenes: Scene[];
  locations: Location[];
  grids: Map<string, Awaited<ReturnType<typeof getSceneGrid>>>;
  expandedSceneId: string;
  onExpand: (sceneId: string) => void;
  onEdit: (sceneId: string) => void;
}): ReactElement {
  const ordered = sortScenesByOutline(scenes);
  const locationNames = new Map(locations.map((location) => [location.id, location.name]));
  const boundLocations = new Set(scenes.map((scene) => scene.location_id).filter(Boolean));
  return (
    <Panel
      eyebrow="推进台 Scene 的权威原子库"
      title="Scene 编排总览"
      action={<Badge tone="ok">{grids.size}/{scenes.length} 张持久地图</Badge>}
    >
      <p className="prose-block mt-0 text-sm text-stone-400">
        这里一次列出全部 Scene，不受当前推进位置影响。每个原子都能核对地点、网格、流程和 DM 细节；游戏推进台只负责运行当前选中的一个。
      </p>
      <div className="mb-4 grid gap-2 sm:grid-cols-4">
        {[
          ["Scene 原子", scenes.length],
          ["已绑定地点", boundLocations.size],
          ["持久地图", grids.size],
          ["尚无地图", Math.max(0, scenes.length - grids.size)],
        ].map(([label, value]) => (
          <div className="rounded-lg border border-ink-700 bg-ink-950/55 p-3" key={label}>
            <strong className="block text-xl text-parchment-100">{value}</strong>
            <span className="text-2xs text-stone-500">{label}</span>
          </div>
        ))}
      </div>
      {ordered.length === 0 ? <EmptyState title="还没有 Scene 原子" hint="在下方创建，或从备团草稿导入。" /> : null}
      <div className="space-y-3">
        {ordered.map((scene, index) => {
          const outline = readSceneStoryOutline(scene, index + 1);
          const flow = buildSceneFlow(scene, index + 1);
          const gridData = grids.get(scene.id);
          const isExpanded = expandedSceneId === scene.id;
          const locationName = scene.location_id ? locationNames.get(scene.location_id) : null;
          return (
            <article className="rounded-xl border border-ink-700 bg-ink-950/45 p-3" key={scene.id}>
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.72fr)]">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="ember">{outline.chapterTitle} · Scene {outline.sceneOrder}</Badge>
                    <Badge tone={scene.status === "active" ? "ok" : "neutral"}>{scene.status}</Badge>
                    <strong className="text-sm text-parchment-100">{scene.name}</strong>
                  </div>
                  <p className="mb-0 mt-2 text-xs text-stone-400">{scene.description || "暂无场景描述"}</p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <div className="rounded border border-ink-700/70 bg-ink-900/60 p-2 text-xs">
                      <span className="block text-2xs text-stone-600">绑定地点</span>
                      <strong className="text-parchment-100">{locationName ?? "未绑定地点"}</strong>
                    </div>
                    <div className="rounded border border-ink-700/70 bg-ink-900/60 p-2 text-xs">
                      <span className="block text-2xs text-stone-600">本场目标</span>
                      <strong className="text-parchment-100">{outline.objective}</strong>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button onClick={() => onExpand(isExpanded ? "" : scene.id)} size="sm">{isExpanded ? "收起完整细节" : `查看完整细节 · ${flow.length} 步`}</Button>
                    <Button onClick={() => onEdit(scene.id)} size="sm" variant="primary">编辑地图与参与者</Button>
                    <Button onClick={() => requestGameTableScene(campaignId, scene.id)} size="sm" variant="ai">在推进台打开</Button>
                  </div>
                </div>
                <div>
                  {gridData ? (
                    <>
                      <div className="flex flex-wrap gap-2 text-2xs text-stone-500">
                        <Badge tone="ok">持久地图</Badge>
                        <span>{gridData.grid.width}×{gridData.grid.height}</span>
                        <span>{gridData.objects.length} 个对象</span>
                        <span>{gridData.tokens.length} 个 Token</span>
                      </div>
                      <SceneGridPreview grid={persistentGridAsSceneGrid(gridData, scene.name)} tokens={gridData.tokens} compact />
                    </>
                  ) : (
                    <div className="rounded-lg border border-dashed border-amber-800/70 bg-amber-950/10 p-4 text-xs text-amber-200">尚无服务端持久地图。下方仍可显示旧兼容网格，但推进台和玩家端不会把它当作权威探索状态。</div>
                  )}
                </div>
              </div>
              {isExpanded ? (
                <div className="mt-4 border-t border-ink-700 pt-4">
                  <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {[
                      ["开场", outline.opening], ["发展", outline.development], ["转折", outline.twist],
                      ["收束", outline.climax], ["转场", outline.transition],
                    ].map(([label, text]) => (
                      <div className="rounded border border-ink-700 bg-ink-900/55 p-3" key={label}>
                        <strong className="text-xs text-amber-200">{label}</strong>
                        <p className="prose-block mb-0 mt-1 text-xs text-stone-400">{text}</p>
                      </div>
                    ))}
                  </div>
                  <ol className="mt-4 grid list-none gap-2 p-0 lg:grid-cols-2">
                    {flow.map((step) => (
                      <li className="rounded border border-ink-700/80 bg-ink-950/60 p-3" key={step.id}>
                        <div className="flex items-center gap-2"><Badge>{step.order}</Badge><strong className="text-xs text-parchment-100">{step.title}</strong></div>
                        <p className="prose-block mb-0 mt-2 text-xs text-stone-400">{step.instruction}</p>
                        <p className="mb-0 mt-2 text-2xs text-stone-600">DM：{step.dmNote}</p>
                      </li>
                    ))}
                  </ol>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </Panel>
  );
}

function ScenesContent({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [sceneId, setSceneId] = useState(() => sessionStorage.getItem(`dnd-dm-requested-scene:${campaignId}`) ?? "");
  const [expandedSceneId, setExpandedSceneId] = useState("");
  const [sceneName, setSceneName] = useState("");
  const [sceneDescription, setSceneDescription] = useState("");
  const [locationId, setLocationId] = useState("");
  const [entityKey, setEntityKey] = useState("");
  const [monsterName, setMonsterName] = useState("");
  const [monsterAc, setMonsterAc] = useState("12");
  const [monsterHp, setMonsterHp] = useState("10");
  const [monsterDex, setMonsterDex] = useState("10");
  const [monsterCr, setMonsterCr] = useState("1/4");
  const [combatResult, setCombatResult] = useState<SceneCombatResult | null>(null);
  const [objectKind, setObjectKind] = useState<"wall" | "door" | "cover" | "terrain" | "light" | "trap" | "treasure" | "furniture" | "portal">("cover");
  const [objectVisibility, setObjectVisibility] = useState<"public" | "dm" | "hidden">("public");
  const [tokenId, setTokenId] = useState("");
  const [explorationDraft, setExplorationDraft] = useState<{ input: ExplorationInput; preview: Record<string, unknown> } | null>(null);
  const [travelLocationId, setTravelLocationId] = useState("");
  const [travelDistance, setTravelDistance] = useState("1");
  const [travelDraft, setTravelDraft] = useState<{ input: TravelInput; preview: Record<string, unknown> } | null>(null);
  const scenes = useQuery({ queryKey: ["scenes", campaignId], queryFn: ({ signal }) => listScenes(campaignId, signal) });
  const locations = useQuery({ queryKey: ["locations", campaignId], queryFn: ({ signal }) => listLocations(campaignId, signal) });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const npcs = useQuery({ queryKey: ["npcs", campaignId], queryFn: ({ signal }) => listNpcs(campaignId, signal) });
  const monsters = useQuery({ queryKey: ["monsters", campaignId], queryFn: ({ signal }) => listMonsters(campaignId, signal) });
  const allGridQueries = useQueries({
    queries: (scenes.data ?? []).map((scene) => ({
      queryKey: ["persistent-scene-grid", campaignId, scene.id],
      queryFn: ({ signal }: { signal: AbortSignal }) => getSceneGrid(campaignId, scene.id, signal),
      retry: false,
    })),
  });
  const allGrids = useMemo(() => {
    const result = new Map<string, Awaited<ReturnType<typeof getSceneGrid>>>();
    (scenes.data ?? []).forEach((scene, index) => {
      const data = allGridQueries[index]?.data;
      if (data) result.set(scene.id, data);
    });
    return result;
  }, [allGridQueries, scenes.data]);
  useEffect(() => {
    const fallbackScene = scenes.data?.[0];
    if (!fallbackScene) return;
    if (!scenes.data?.some((scene) => scene.id === sceneId)) setSceneId(fallbackScene.id);
    sessionStorage.removeItem(`dnd-dm-requested-scene:${campaignId}`);
  }, [campaignId, sceneId, scenes.data]);
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
    mutationFn: async () => {
      const location = locations.data?.find((item) => item.id === locationId);
      const grid = generateTacticalSceneGrid(
        sceneName.trim(),
        sceneDescription.trim(),
        `${location?.name ?? ""} ${location?.description ?? ""}`,
      );
      const scene = await createScene(campaignId, {
        name: sceneName.trim(), location_id: locationId || null,
        description: sceneDescription.trim() || null,
        notes: JSON.stringify({ scene_grid: grid }),
      });
      await createPersistentGrid(campaignId, scene.id, {
        width: grid.width,
        height: grid.height,
        cell_size_ft: grid.cell_size_ft,
        mode: "exploration",
        public_description: grid.theme,
        dm_description: `由 Scene“${scene.name}”的名称、地点与描述自动生成，可继续调整。`,
        layers_json: { theme: grid.theme, cells: grid.cells },
      });
      return scene;
    },
    onSuccess: async (scene) => {
      setSceneName("");
      setSceneDescription("");
      await client.invalidateQueries({ queryKey: ["scenes", campaignId] });
      setSceneId(scene.id);
      await client.invalidateQueries({ queryKey: ["persistent-scene-grid", campaignId, scene.id] });
      showToast("场景已创建");
    },
    onError: () => showToast("场景创建失败", "error"),
  });
  const gridCreate = useMutation({
    mutationFn: () => {
      const location = locations.data?.find((item) => item.id === activeScene?.location_id);
      const grid = activeGrid ?? generateTacticalSceneGrid(
        activeScene?.name ?? "未命名场景",
        activeScene?.description ?? "",
        `${location?.name ?? ""} ${location?.description ?? ""}`,
      );
      return createPersistentGrid(campaignId, sceneId, {
        width: grid.width,
        height: grid.height,
        cell_size_ft: grid.cell_size_ft,
        mode: "exploration",
        public_description: grid.theme,
        dm_description: `由旧 Scene“${activeScene?.name ?? "未命名场景"}”补建。`,
        layers_json: { theme: grid.theme, cells: grid.cells },
      });
    },
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["persistent-scene-grid", campaignId, sceneId] }); showToast("持久探索网格已生成"); },
    onError: () => showToast("网格已存在或创建失败", "error"),
  });
  const objectCreate = useMutation({
    mutationFn: (position: { row: number; col: number }) => createSceneObject(campaignId, sceneId, { object_type: objectKind, label: objectKind === "terrain" ? "困难地形" : objectKind, row: position.row, col: position.col, visibility: objectVisibility, metadata_json: objectKind === "terrain" ? { difficult: true } : {} }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["persistent-scene-grid", campaignId, sceneId] }); },
    onError: () => showToast("对象放置失败", "error"),
  });
  const tokenCreate = useMutation({
    mutationFn: () => {
      const [entity_type, entity_id] = entityKey.split(":");
      const candidate = candidates.find((item) => item.key === entityKey);
      if (!candidate || !entity_type || !entity_id) throw new Error("请选择要放置的参与者");
      return createSceneToken(campaignId, sceneId, {
        entity_type: entity_type as "character" | "npc" | "monster",
        entity_id,
        label: candidate.label.replace(/^.+? · /, ""),
        row: 2,
        col: 2,
      });
    },
    onSuccess: (token) => {
      setTokenId(token.id);
      void client.invalidateQueries({ queryKey: ["persistent-scene-grid", campaignId, sceneId] });
      showToast("单位已放置到探索网格");
    },
    onError: () => showToast("单位放置失败", "error"),
  });
  const explorationPreview = useMutation({
    mutationFn: async (input: ExplorationInput) => ({
      input,
      preview: await previewExploration(campaignId, sceneId, input),
    }),
    onSuccess: setExplorationDraft,
    onError: () => showToast("探索操作无法预览", "error"),
  });
  const explorationConfirm = useMutation({
    mutationFn: () => {
      if (!explorationDraft) throw new Error("没有待确认的探索操作");
      return confirmExploration(campaignId, sceneId, {
        ...explorationDraft.input,
        preview_token: String(explorationDraft.preview.preview_token),
        idempotency_key: createClientId("exploration"),
      });
    },
    onSuccess: () => {
      setExplorationDraft(null);
      void client.invalidateQueries({ queryKey: ["persistent-scene-grid", campaignId, sceneId] });
      showToast("探索轮已确认，世界时间已推进");
    },
  });
  const travelPreview = useMutation({
    mutationFn: async (input: TravelInput) => ({
      input,
      preview: await previewTravel(campaignId, input),
    }),
    onSuccess: setTravelDraft,
    onError: () => showToast("旅行无法预览", "error"),
  });
  const travelConfirm = useMutation({
    mutationFn: () => {
      if (!travelDraft) throw new Error("没有待确认的旅行");
      return confirmTravel(campaignId, {
        ...travelDraft.input,
        preview_token: String(travelDraft.preview.preview_token),
        idempotency_key: createClientId("travel"),
      });
    },
    onSuccess: () => {
      setTravelDraft(null);
      showToast("旅行已确认，地点与世界时间已更新");
    },
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
      challenge_rating: monsterCr,
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
      <SceneAtomLibrary
        campaignId={campaignId}
        expandedSceneId={expandedSceneId}
        grids={allGrids}
        locations={locations.data ?? []}
        onEdit={(targetSceneId) => {
          setSceneId(targetSceneId);
          setCombatResult(null);
          requestAnimationFrame(() => document.getElementById("scene-editor")?.scrollIntoView({ behavior: "smooth", block: "start" }));
        }}
        onExpand={setExpandedSceneId}
        scenes={scenes.data ?? []}
      />
      <div className="mt-4 grid gap-4 xl:grid-cols-[0.85fr_1.15fr]" id="scene-editor">
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
          {persistentGrid.data ? <div className="mt-3"><div className="mb-2 flex flex-wrap gap-2"><select className={selectCls} onChange={(event) => setObjectKind(event.target.value as typeof objectKind)} value={objectKind}>{["wall","door","cover","terrain","light","trap","treasure","furniture","portal"].map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select><select className={selectCls} onChange={(event) => setObjectVisibility(event.target.value as typeof objectVisibility)} value={objectVisibility}><option value="public">公开层</option><option value="dm">DM 私密层</option><option value="hidden">隐藏层</option></select><span className="self-center text-2xs text-stone-500">点击格子放置对象；困难地形移动消耗翻倍。</span></div><div className="grid max-w-[600px] gap-px overflow-hidden rounded border border-ink-700 bg-ink-700" style={{ gridTemplateColumns: `repeat(${persistentGrid.data.grid.width}, minmax(0, 1fr))` }}>{Array.from({ length: persistentGrid.data.grid.width * persistentGrid.data.grid.height }, (_, index) => { const row = Math.floor(index / persistentGrid.data.grid.width) + 1; const col = index % persistentGrid.data.grid.width + 1; const obj = persistentGrid.data.objects.find((item) => item.row === row && item.col === col); const token = persistentGrid.data.tokens.find((item) => item.row === row && item.col === col); return <button className={`aspect-square min-h-6 ${token ? "bg-sky-900" : obj?.object_type === "wall" ? "bg-stone-700" : obj?.object_type === "terrain" ? "bg-amber-900" : obj?.visibility !== "public" ? "bg-violet-950" : obj ? "bg-emerald-900" : "bg-ink-950"}`} disabled={objectCreate.isPending} key={`${row}-${col}`} onClick={() => tokenId ? explorationPreview.mutate({ action: "move", minutes: 1, token_id: tokenId, path: [[persistentGrid.data.tokens.find((item) => item.id === tokenId)?.row ?? row, persistentGrid.data.tokens.find((item) => item.id === tokenId)?.col ?? col], [row, col]] }) : objectCreate.mutate({ row, col })} title={token ? token.label : obj ? `${obj.label} · ${obj.visibility}` : `${row},${col}`} type="button" />; })}</div><p className="mt-1 text-2xs text-stone-500">公开 {persistentGrid.data.objects.filter((item) => item.visibility === "public").length} · DM/隐藏 {persistentGrid.data.objects.filter((item) => item.visibility !== "public").length}</p><div className="mt-3 flex flex-wrap gap-2"><Button disabled={!entityKey} loading={tokenCreate.isPending} onClick={() => tokenCreate.mutate()}>将所选参与者放到 2,2</Button><select className={selectCls} onChange={(event) => setTokenId(event.target.value)} value={tokenId}><option value="">选择移动单位</option>{persistentGrid.data.tokens.map((token) => <option key={token.id} value={token.id}>{token.label}（{token.row},{token.col}）</option>)}</select><Button onClick={() => explorationPreview.mutate({ action: "search", minutes: 10, notes: "场景搜寻" })}>预览搜寻 10 分钟</Button></div>{explorationDraft ? <div className="mt-3 rounded border border-amber-700/50 p-3 text-xs"><pre className="max-h-32 overflow-auto whitespace-pre-wrap">{JSON.stringify(explorationDraft.preview, null, 2)}</pre><div className="mt-2 flex gap-2"><Button loading={explorationConfirm.isPending} onClick={() => explorationConfirm.mutate()} variant="primary">DM 确认探索</Button><Button onClick={() => setExplorationDraft(null)}>取消</Button></div></div> : null}</div> : null}
          <div className="mt-4 rounded border border-ink-700 p-3"><p className="m-0 text-xs font-medium text-parchment-100">地点旅行</p><div className="mt-2 flex flex-wrap gap-2"><select className={selectCls} onChange={(event) => setTravelLocationId(event.target.value)} value={travelLocationId}><option value="">目的地</option>{locations.data?.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select><input className={inputCls} min="0" onChange={(event) => setTravelDistance(event.target.value)} type="number" value={travelDistance} /><Button disabled={!travelLocationId} onClick={() => travelPreview.mutate({ to_location_id: travelLocationId, distance_miles: Number(travelDistance), pace: "normal" })}>预览旅行</Button></div>{travelDraft ? <div className="mt-2 text-xs text-stone-400">预计 {String(travelDraft.preview.duration_minutes)} 分钟 <Button className="ml-2" loading={travelConfirm.isPending} onClick={() => travelConfirm.mutate()} size="sm" variant="primary">DM 确认</Button></div> : null}</div>
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
            <label className="text-2xs text-stone-600 sm:col-span-2">挑战等级 CR（用于难度与经验）
              <select className={`${selectCls} mt-1`} onChange={(event) => setMonsterCr(event.target.value)} value={monsterCr}>
                {["0", "1/8", "1/4", "1/2", ...Array.from({ length: 30 }, (_, index) => String(index + 1))].map((cr) => <option key={cr} value={cr}>CR {cr} · {xpForChallengeRating(cr)} XP</option>)}
              </select>
            </label>
            <p className="m-0 self-end text-2xs text-stone-500">CR 是结算依据；AC、HP 不会自动反推 CR。</p>
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
                      {participant.role === "defeated" ? <Badge>已击败</Badge> : null}
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
