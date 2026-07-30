import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactElement } from "react";

import { runAssistantTurn } from "../api/assistant";
import { createCompendiumEntry } from "../api/compendium";
import { getRuleDocument, searchKnowledge } from "../api/knowledge";
import { confirmPrepImport, previewPrepImport, type PrepDraft, type PrepImportPreview } from "../api/prep";
import {
  createSessionCheckpoint, getSessionCheckpoint, listSessionCheckpoints,
  previewSessionCheckpointRestore, restoreSessionCheckpoint,
  type SessionCheckpointRestorePreview, type SessionCheckpointSummary,
} from "../api/sessionCheckpoints";
import {
  getDmNoncombatActions,
  planDmNoncombatAction,
  rollDmNoncombatAction,
  setPlayerRoomLiveState,
  type NoncombatActionOption,
  type NoncombatPendingAction,
} from "../api/playerRoom";
import {
  applyEncounterAdjustment, createEncounterAdjustment, createEquipmentInstance,
  createEvent, createKnownSpell, createNpc, getCharacterOptions,
  listCharacters, listEncounterAdjustments, listEvents, listLocations, listNpcs, updateCharacter,
  rejectEncounterAdjustment, revertEncounterAdjustment,
} from "../api/entities";
import type {
  AgentResponse, Character, EncounterAdjustment, EncounterOperation, Monster, Npc, Scene, SceneParticipant,
} from "../api/types";
import {
  addSceneParticipant, createMonster, createPersistentGrid, createScene, generateNpc, getSceneGrid,
  listMonsters, listSceneParticipants, listScenes,
  removeSceneParticipant, startSceneCombat,
} from "../api/world";
import { CharacterSheetDetail } from "../components/CharacterSheetDetail";
import { Panel } from "../components/Panel";
import { PlayerRoomPanel } from "../components/PlayerRoomPanel";
import { RestPanel } from "../components/RestPanel";
import { RequireCampaign } from "../components/RequireCampaign";
import { SceneOutlinePanel } from "../components/SceneOutlinePanel";
import { SceneEntityDetailDialog } from "../components/SceneEntityDetailDialog";
import { SceneMap } from "../components/SceneMap";
import { useToast } from "../hooks/toastContext";
import { navigate } from "../hooks/useHashRoute";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../ui/styles";
import { safeDndText } from "../ui/contentSafety";
import { splitAssistantRevealChunks } from "../ui/assistantReveal";
import { buildPlayerGuidance, type PlayerGuidanceReason } from "../ui/playerGuidance";
import { HpBar } from "../ui/widgets";
import { atomsToStrictPrepDraft, buildFallbackPrepDraft, parsePrepDraft, type DraftAtom } from "../ui/prepDraft";
import { generateTacticalSceneGrid } from "../ui/sceneGridGenerator";
import {
  buildSceneFlow, buildSceneNotes, chapterOrderFromTitle, readSceneStoryOutline,
  sortScenesByOutline, type SceneFlowStep, type SceneStoryOutline,
} from "../ui/sceneOutline";
import {
  campaignMonsterCandidates, compendiumMonsterCandidates, customMonsterDraft,
  detectArrivalKind, monsterDraftFromCandidate, parseMonsterStats, suggestedNpcName,
  requestedMonsterName,
  type ArrivalDraft, type ArrivalKind, type MonsterReferenceCandidate,
} from "../ui/dynamicEntityDraft";
import {
  buildFeatureGrantDraft, buildItemGrantDraft, buildSkillGrantDraft, buildSpellGrantDraft,
  detectCharacterGrantIntent, type CharacterGrantDraft, type CharacterGrantIntent,
} from "../ui/characterGrants";
import {
  describeEncounterOperation, difficultyShiftLabel,
} from "../ui/encounterAdjustments";
import {
  buildContextualQuickActions, type ScenePhase,
} from "../ui/contextualQuickActions";
import { createClientId } from "../ui/id";
import {
  assistantEntryLabel, gameTableAssistantContract, isUnwantedRepeatedReply,
  repairLegacyAssistantHistory,
  type GameTableAssistantIntent,
} from "../ui/gameTableAssistant";

type ProgressEntry = {
  id: string;
  kind: "dm" | "ai" | "system";
  intent?: GameTableAssistantIntent;
  text: string;
  createdAt: string;
};

type LiveAssistantEntry = {
  id: string;
  intent: GameTableAssistantIntent;
  label: string;
  status: "thinking" | "revealing";
  text: string;
};

function summaryCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function flowStepId(value: unknown): string {
  return typeof value === "string" ? value : "";
}

type LegacySessionCheckpoint = {
  id: string;
  label: string;
  createdAt: string;
  sceneId: string;
  entries: ProgressEntry[];
  participantKeys: string[];
};

function SessionStatusBar({ characters, npcs, events }: { characters: { name: string; hp: number; max_hp: number }[]; npcs: { name: string; attitude: string | null }[]; events: { title: string }[] }): ReactElement {
  return <Panel className="mb-4" eyebrow="统一状态栏 · 已确认事实" title="队伍、关系与未解决事项"><div className="grid gap-3 text-xs md:grid-cols-3"><div><strong>队伍</strong><p className="mb-0 mt-1 text-stone-500">{characters.map((c) => `${c.name} ${c.hp}/${c.max_hp}`).join("、") || "—"}</p></div><div><strong>NPC 态度</strong><p className="mb-0 mt-1 text-stone-500">{npcs.slice(0, 3).map((n) => `${n.name}·${n.attitude ?? "未定"}`).join("、") || "—"}</p></div><div><strong>未解决事项</strong><p className="mb-0 mt-1 text-stone-500">{events.slice(-3).map((e) => e.title).join("、") || "暂无"}</p></div></div></Panel>;
}

function SessionReadiness({
  characterCount,
  sceneCount,
  hasActiveScene,
  participantCount,
  hasGrid,
  onPrep,
}: {
  characterCount: number;
  sceneCount: number;
  hasActiveScene: boolean;
  participantCount: number;
  hasGrid: boolean;
  onPrep: () => void;
}): ReactElement {
  const steps = [
    {
      label: "玩家角色",
      ready: characterCount > 0,
      detail: characterCount > 0 ? `${characterCount} 名可用` : "还没有玩家角色",
      action: () => navigate("/characters"),
      actionLabel: "去创建角色",
    },
    {
      label: "章节与 Scene",
      ready: sceneCount > 0,
      detail: sceneCount > 0 ? `${sceneCount} 个 Scene` : "还没有冒险场景",
      action: onPrep,
      actionLabel: "开始备团",
    },
    {
      label: "当前 Scene",
      ready: hasActiveScene && hasGrid,
      detail: !hasActiveScene ? "请选择当前 Scene" : hasGrid ? "地图已就绪" : "地图尚未生成",
      action: onPrep,
      actionLabel: "检查 Scene",
    },
    {
      label: "在场成员",
      ready: participantCount > 0,
      detail: participantCount > 0 ? `${participantCount} 个单位在场` : "尚未将角色或 NPC 加入场景",
      action: () => {
        document.getElementById("scene-participant-workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
      },
      actionLabel: "添加在场成员",
    },
  ];
  const completed = steps.filter((step) => step.ready).length;
  if (completed === steps.length) return <></>;
  const next = steps.find((step) => !step.ready);
  return (
    <section className="mb-4 rounded-xl border border-amber-700/45 bg-amber-950/15 p-3" aria-label="开团准备度">
      <div className="flex flex-wrap items-center gap-2">
        <div className="mr-auto">
          <strong className="block text-sm text-amber-100">开团准备度 · {completed}/{steps.length}</strong>
          <span className="text-2xs text-stone-500">按顺序补齐即可开始；已经完成的内容不会被改动。</span>
        </div>
        {next ? <Button onClick={next.action} size="sm" variant="primary">{next.actionLabel}</Button> : null}
      </div>
      <ol className="mt-3 grid list-none gap-2 p-0 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map((step, index) => (
          <li className={`rounded border p-2 ${step.ready ? "border-emerald-800/55 bg-emerald-950/15" : index === completed ? "border-amber-700/55 bg-amber-950/20" : "border-ink-700 bg-ink-950/40"}`} key={step.label}>
            <span className={`text-2xs ${step.ready ? "text-emerald-300" : "text-stone-500"}`}>{step.ready ? "✓ 已完成" : `${index + 1} · 待完成`}</span>
            <strong className="mt-1 block text-xs text-parchment-100">{step.label}</strong>
            <span className="text-2xs text-stone-500">{step.detail}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function DmSceneActionPanel({
  campaignId,
  characters,
  gridData,
}: {
  campaignId: string;
  characters: Character[];
  gridData: Awaited<ReturnType<typeof getSceneGrid>> | undefined;
}): ReactElement {
  const client = useQueryClient();
  const [characterId, setCharacterId] = useState("");
  const [actionId, setActionId] = useState("");
  const [targetValue, setTargetValue] = useState("");
  const [message, setMessage] = useState("");
  const [rolls, setRolls] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!characterId && characters[0]) setCharacterId(characters[0].id);
  }, [characterId, characters]);
  const actions = useQuery({
    queryKey: ["dm-noncombat-actions", campaignId, characterId],
    queryFn: ({ signal }) => getDmNoncombatActions(campaignId, characterId, signal),
    enabled: Boolean(characterId),
    refetchInterval: 15_000,
  });
  const selected = actions.data?.available_actions.find((item) => item.id === actionId);
  const targets = selected && gridData ? [
    ...(selected.target_types.includes("self")
      ? [{ value: `self:${characterId}`, label: `自己 · ${characters.find((item) => item.id === characterId)?.name ?? "玩家"}` }]
      : []),
    ...(selected.target_types.includes("area")
      ? [{ value: "area:", label: "当前地点 / 区域" }]
      : []),
    ...gridData.tokens
      .filter((token) => token.entity_id && selected.target_types.includes(token.entity_type as "npc" | "monster"))
      .map((token) => ({
        value: `${token.entity_type}:${token.entity_id}`,
        label: `${token.entity_type === "npc" ? "NPC" : "怪物"} · ${token.label}`,
      })),
    ...gridData.objects
      .filter((object) => selected.target_types.includes("object")
        && (selected.kind !== "tool" || ["door", "trap", "treasure", "portal"].includes(object.object_type)))
      .map((object) => ({
        value: `object:${object.id}`,
        label: `物体 · ${object.label}（${object.state}）`,
      })),
  ] : [];
  const invalidate = () => client.invalidateQueries({
    queryKey: ["dm-noncombat-actions", campaignId, characterId],
  });
  const mutation = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => { setMessage(""); void invalidate(); },
  });
  const submit = () => {
    const [targetType, targetId] = targetValue.split(":");
    if (!selected || !targetType || !characterId) return;
    mutation.mutate(() => planDmNoncombatAction(campaignId, {
      character_id: characterId,
      action_id: selected.id,
      target_type: targetType as "self" | "npc" | "monster" | "object" | "area",
      target_id: targetId || null,
      message: message || `DM代${characters.find((item) => item.id === characterId)?.name ?? "玩家"}使用${selected.name}`,
    }));
  };
  const pending = actions.data?.pending_actions ?? [];
  const layers = gridData?.grid.layers_json as {
    theme?: string;
    cells?: Array<{ row: number; col: number; kind: string; label?: string }>;
  } | undefined;
  return (
    <Panel eyebrow="统一 Scene 操作台" title="DM 地图与代玩家操作">
      <p className="mt-0 text-xs leading-5 text-stone-500">
        DM 与玩家共用服务端持久化 Scene 网格。可以从列表选目标，也可以先选能力，再直接点击地图中的绿色目标。
      </p>
      {gridData ? (
        <SceneMap
          grid={{
            width: gridData.grid.width,
            height: gridData.grid.height,
            cell_size_ft: gridData.grid.cell_size_ft,
            theme: layers?.theme ?? gridData.grid.public_description,
            cells: layers?.cells ?? [],
          }}
          objects={gridData.objects.map((item) => ({ ...item, targetKey: `object:${item.id}` }))}
          onTargetSelect={setTargetValue}
          selectedTargetKey={targetValue}
          selectableTargetKeys={new Set(targets.map((target) => target.value))}
          tokens={gridData.tokens.map((item) => ({
            ...item,
            targetKey: item.entity_id ? `${item.entity_type}:${item.entity_id}` : undefined,
            isOwn: item.entity_type === "character" && item.entity_id === characterId,
          }))}
        />
      ) : <EmptyState hint="选择当前 Scene 后会读取服务端唯一网格。" title="尚未载入地图" />}
      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <label className="text-2xs text-stone-500">代操角色
          <select className={`${selectCls} mt-1`} onChange={(event) => { setCharacterId(event.target.value); setActionId(""); setTargetValue(""); }} value={characterId}>
            <option value="">选择场景玩家</option>
            {characters.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}
          </select>
        </label>
        <label className="text-2xs text-stone-500">技能 / 工具 / 非伤害法术
          <select className={`${selectCls} mt-1`} disabled={!characterId} onChange={(event) => { setActionId(event.target.value); setTargetValue(""); }} value={actionId}>
            <option value="">选择行动</option>
            {(actions.data?.available_actions ?? []).map((action: NoncombatActionOption) => <option key={action.id} value={action.id}>{action.kind === "spell" ? "法术" : action.kind === "tool" ? "工具" : "技能"} · {action.name}</option>)}
          </select>
        </label>
        <label className="text-2xs text-stone-500">目标
          <select className={`${selectCls} mt-1`} disabled={!selected} onChange={(event) => setTargetValue(event.target.value)} value={targetValue}>
            <option value="">列表选择，或点击地图绿色目标</option>
            {targets.map((target) => <option key={target.value} value={target.value}>{target.label}</option>)}
          </select>
        </label>
      </div>
      {selected ? <p className="mb-0 mt-2 rounded border border-sky-900/50 bg-sky-950/15 p-2 text-xs text-sky-100">{selected.description}{selected.range ? ` · 距离 ${selected.range}` : ""}</p> : null}
      <div className="mt-2 flex gap-2">
        <input className={inputCls} onChange={(event) => setMessage(event.target.value)} placeholder="补充玩家具体做法（可选）" value={message} />
        <Button disabled={!selected || !targetValue} loading={mutation.isPending} onClick={submit} variant="primary">DM代玩家执行</Button>
      </div>
      {mutation.isError ? <p className="text-xs text-red-300">{mutation.error.message}</p> : null}
      {pending.map((request: NoncombatPendingAction) => {
        const awaiting = request.payload.phase === "awaiting_player_roll";
        return (
          <div className="mt-2 rounded border border-violet-800/60 bg-violet-950/15 p-2" key={request.id}>
            <strong className="text-xs">{request.payload.action?.name} → {request.payload.target?.name}</strong>
            <p className="mb-0 mt-1 text-xs text-stone-400">{request.payload.resolution?.instruction ?? request.payload.proposal?.summary}</p>
            {awaiting ? <div className="mt-2 flex gap-2"><input className={inputCls} max={20} min={1} onChange={(event) => setRolls((current) => ({ ...current, [request.id]: event.target.value }))} placeholder="玩家 d20 裸骰" type="number" value={rolls[request.id] ?? ""} /><Button disabled={!rolls[request.id]} onClick={() => mutation.mutate(() => rollDmNoncombatAction(campaignId, characterId, request.id, request.version, Number(rolls[request.id])))} size="sm">提交骰值</Button></div> : <span className="mt-1 block text-2xs text-amber-200">规则已结算；在上方玩家房间面板接受或驳回。</span>}
          </div>
        );
      })}
    </Panel>
  );
}

function storageKey(campaignId: string, sceneId: string): string {
  return `dnd-game-table:${campaignId}:${sceneId}`;
}

function loadEntries(campaignId: string, sceneId: string): ProgressEntry[] {
  if (!sceneId) return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(campaignId, sceneId)) ?? "[]") as unknown;
    return Array.isArray(parsed)
      ? repairLegacyAssistantHistory(parsed as ProgressEntry[])
      : [];
  } catch {
    return [];
  }
}

function saveEntries(campaignId: string, sceneId: string, entries: ProgressEntry[]): void {
  localStorage.setItem(storageKey(campaignId, sceneId), JSON.stringify(entries));
}

function withoutSceneTransitionMarker(text: string): string {
  return text.replace(/\[\[(?:建议进入下一场景|继续当前场景)\]\]/g, "").trim();
}

function checkpointKey(campaignId: string): string {
  return `dnd-game-checkpoints:${campaignId}`;
}

function loadLegacyCheckpoints(campaignId: string): LegacySessionCheckpoint[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(checkpointKey(campaignId)) ?? "[]") as unknown;
    return Array.isArray(parsed) ? parsed as LegacySessionCheckpoint[] : [];
  } catch {
    return [];
  }
}

async function createSceneWithPersistentGrid(
  campaignId: string,
  input: { name: string; location_id?: string | null; description?: string | null; notes?: string | null },
  locationName = "",
): Promise<Scene> {
  const scene = await createScene(campaignId, input);
  const grid = generateTacticalSceneGrid(
    input.name,
    input.description ?? "",
    locationName,
  );
  await createPersistentGrid(campaignId, scene.id, {
    width: grid.width,
    height: grid.height,
    cell_size_ft: grid.cell_size_ft,
    mode: "combat",
    public_description: grid.theme,
    dm_description: `由 Scene“${input.name}”自动生成，可在场景页继续调整。`,
    layers_json: { theme: grid.theme, cells: grid.cells },
  });
  return scene;
}

async function ensureScenePersistentGrid(
  campaignId: string,
  scene: Scene,
  locationName = "",
): Promise<void> {
  try {
    await getSceneGrid(campaignId, scene.id);
    return;
  } catch {
    const grid = generateTacticalSceneGrid(
      scene.name,
      scene.description ?? "",
      locationName,
    );
    await createPersistentGrid(campaignId, scene.id, {
      width: grid.width,
      height: grid.height,
      cell_size_ft: grid.cell_size_ft,
      mode: "combat",
      public_description: grid.theme,
      dm_description: `由旧Scene“${scene.name}”补建并同步到玩家端。`,
      layers_json: { theme: grid.theme, cells: grid.cells },
    });
  }
}

function GameTableContent({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [sceneId, setSceneId] = useState(
    () => sessionStorage.getItem(`dnd-dm-requested-scene:${campaignId}`) ?? "",
  );
  const [playerCombatId, setPlayerCombatId] = useState<string | null>(
    () => sessionStorage.getItem(`dnd-dm-active-combat:${campaignId}`),
  );
  const [tableMode, setTableMode] = useState<"prep" | "play">("play");
  const [showEncounterTools, setShowEncounterTools] = useState(false);
  const [entityKey, setEntityKey] = useState("");
  const [detailParticipant, setDetailParticipant] = useState<SceneParticipant | null>(null);
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState<ProgressEntry[]>([]);
  const [liveAssistant, setLiveAssistant] = useState<LiveAssistantEntry | null>(null);
  const [lastResponse, setLastResponse] = useState<AgentResponse | null>(null);
  const conversationEndRef = useRef<HTMLDivElement>(null);
  const [legacyCheckpointCount] = useState(
    () => loadLegacyCheckpoints(campaignId).length,
  );
  const [checkpointPreview, setCheckpointPreview] = useState<{
    checkpoint: SessionCheckpointSummary;
    preview: SessionCheckpointRestorePreview;
  } | null>(null);
  const [prepBrief, setPrepBrief] = useState("");
  const [prepDraft, setPrepDraft] = useState("");
  const [draftAtoms, setDraftAtoms] = useState<DraftAtom[]>([]);
  const [selectedAtoms, setSelectedAtoms] = useState<Set<string>>(new Set());
  const [prepImportReview, setPrepImportReview] = useState<{
    draft: PrepDraft;
    preview: PrepImportPreview;
    omittedSites: number;
  } | null>(null);
  const [adjustmentTitle, setAdjustmentTitle] = useState("");
  const [adjustmentReason, setAdjustmentReason] = useState("");
  const [adjustmentShift, setAdjustmentShift] = useState<-1 | 0 | 1>(0);
  const [adjustmentTarget, setAdjustmentTarget] = useState("");
  const [adjustmentKind, setAdjustmentKind] = useState<EncounterOperation["kind"]>("set_entity_hp");
  const [adjustmentValue, setAdjustmentValue] = useState("");
  const [adjustmentRound, setAdjustmentRound] = useState("3");
  const [adjustmentQuantity, setAdjustmentQuantity] = useState("1");
  const [draftOperations, setDraftOperations] = useState<EncounterOperation[]>([]);
  const [arrivalDraft, setArrivalDraft] = useState<ArrivalDraft | null>(null);
  const [arrivalReferences, setArrivalReferences] = useState<MonsterReferenceCandidate[]>([]);
  const [grantDraft, setGrantDraft] = useState<CharacterGrantDraft | null>(null);
  const [startCombatAfterArrival, setStartCombatAfterArrival] = useState(false);
  const [suggestedSceneId, setSuggestedSceneId] = useState<string | null>(null);
  const [sceneChapter, setSceneChapter] = useState("第一章");
  const [sceneOrder, setSceneOrder] = useState("1");
  const [sceneName, setSceneName] = useState("");
  const [sceneLocationId, setSceneLocationId] = useState("");
  const [sceneObjective, setSceneObjective] = useState("");
  const [sceneOpening, setSceneOpening] = useState("");
  const [sceneDevelopment, setSceneDevelopment] = useState("");
  const [sceneTwist, setSceneTwist] = useState("");
  const [sceneClimax, setSceneClimax] = useState("");
  const [sceneTransition, setSceneTransition] = useState("");
  const [currentFlowStepId, setCurrentFlowStepId] = useState<string | null>(null);
  const scenes = useQuery({ queryKey: ["scenes", campaignId], queryFn: ({ signal }) => listScenes(campaignId, signal) });
  const locations = useQuery({ queryKey: ["locations", campaignId], queryFn: ({ signal }) => listLocations(campaignId, signal) });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const characterOptions = useQuery({ queryKey: ["character-options"], queryFn: ({ signal }) => getCharacterOptions(signal) });
  const npcs = useQuery({ queryKey: ["npcs", campaignId], queryFn: ({ signal }) => listNpcs(campaignId, signal) });
  const monsters = useQuery({ queryKey: ["monsters", campaignId], queryFn: ({ signal }) => listMonsters(campaignId, signal) });
  const events = useQuery({ queryKey: ["events", campaignId], queryFn: ({ signal }) => listEvents(campaignId, signal) });
  const participants = useQuery({
    queryKey: ["scene-participants", campaignId, sceneId],
    queryFn: ({ signal }) => listSceneParticipants(campaignId, sceneId, signal),
    enabled: Boolean(sceneId),
  });
  const sceneGrid = useQuery({
    queryKey: ["scene-grid", campaignId, sceneId],
    queryFn: ({ signal }) => getSceneGrid(campaignId, sceneId, signal),
    enabled: Boolean(sceneId),
  });
  const encounterAdjustments = useQuery({
    queryKey: ["encounter-adjustments", campaignId, sceneId],
    queryFn: ({ signal }) => listEncounterAdjustments(campaignId, sceneId, signal),
    enabled: Boolean(sceneId),
  });
  const checkpoints = useQuery({
    queryKey: ["session-checkpoints", campaignId],
    queryFn: ({ signal }) => listSessionCheckpoints(campaignId, signal),
  });
  useEffect(() => {
    const fallbackScene = scenes.data?.[0];
    if (!fallbackScene) return;
    if (!scenes.data?.some((scene) => scene.id === sceneId)) setSceneId(fallbackScene.id);
    sessionStorage.removeItem(`dnd-dm-requested-scene:${campaignId}`);
  }, [campaignId, sceneId, scenes.data]);
  useEffect(() => {
    setEntries(loadEntries(campaignId, sceneId));
    setLastResponse(null);
  }, [campaignId, sceneId]);
  useEffect(() => {
    if (sceneId) localStorage.setItem(storageKey(campaignId, sceneId), JSON.stringify(entries));
  }, [campaignId, entries, sceneId]);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      conversationEndRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "end",
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [entries, liveAssistant?.status, liveAssistant?.text]);
  useEffect(() => {
    if (!sceneId || entries.length > 0 || !events.data) return;
    const restored = events.data
      .filter((event) => event.metadata_json.scene_id === sceneId && event.metadata_json.game_table === true)
      .map((event): ProgressEntry => ({
        id: `event:${event.id}`,
        kind: event.metadata_json.entry_kind === "dm" ? "dm" : event.metadata_json.entry_kind === "ai" ? "ai" : "system",
        intent: event.metadata_json.assistant_intent === "ask"
          || event.metadata_json.assistant_intent === "advance"
          || event.metadata_json.assistant_intent === "execute"
          ? event.metadata_json.assistant_intent
          : undefined,
        text: event.description ?? event.title,
        createdAt: event.occurred_at,
      }));
    if (restored.length > 0) setEntries(repairLegacyAssistantHistory(restored));
  }, [entries.length, events.data, sceneId]);
  const activeScene = scenes.data?.find((scene) => scene.id === sceneId);
  const activeLocation = locations.data?.find((location) => location.id === activeScene?.location_id);
  const orderedScenes = useMemo(
    () => sortScenesByOutline(scenes.data ?? []),
    [scenes.data],
  );
  const activeSceneIndex = orderedScenes.findIndex((scene) => scene.id === sceneId);
  const nextScene = activeSceneIndex >= 0 ? orderedScenes[activeSceneIndex + 1] : undefined;
  const activeOutline = activeScene
    ? readSceneStoryOutline(activeScene, activeSceneIndex + 1)
    : null;
  const activeFlow = activeScene ? buildSceneFlow(activeScene, activeSceneIndex + 1) : [];
  const currentFlowStep = activeFlow.find((step) => step.id === currentFlowStepId) ?? activeFlow[0];
  const activePhase: ScenePhase = currentFlowStep?.sourcePhase ?? "opening";
  const sceneFlowEvents = (events.data ?? []).filter((event) => (
    event.metadata_json.scene_id === sceneId
    && event.metadata_json.action === "scene_flow_step"
  ));
  const skippedFlowStepIds = new Set(sceneFlowEvents
    .filter((event) => event.metadata_json.flow_step_status === "skipped")
    .map((event) => flowStepId(event.metadata_json.flow_step_id))
    .filter(Boolean));
  useEffect(() => {
    if (!activeScene) {
      setCurrentFlowStepId(null);
      return;
    }
    const latestCurrent = [...sceneFlowEvents].reverse().find(
      (event) => event.metadata_json.flow_step_status === "current",
    );
    const restoredId = flowStepId(latestCurrent?.metadata_json.flow_step_id);
    const fallbackId = buildSceneFlow(activeScene, activeSceneIndex + 1)[0]?.id ?? null;
    setCurrentFlowStepId(restoredId || fallbackId);
  // The event list is the server-side source of truth. Do not depend on the
  // derived array identity or this effect would reset after every render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeScene?.id, events.data, sceneId]);
  const findCompendiumMonsters = async (query: string): Promise<MonsterReferenceCandidate[]> => {
    const enrichHits = (hits: Awaited<ReturnType<typeof searchKnowledge>>) => Promise.all(hits.map(async (hit) => {
      try {
        const document = await getRuleDocument(hit.chunk.record_id);
        return { ...hit, chunk: { ...hit.chunk, text: document.content_plain_text } };
      } catch {
        return hit;
      }
    }));
    const currentHits = await searchKnowledge({
      text: query, top_k: 6, candidate_k: 24, min_score: 0.25,
      content_types: ["monsters"], editions: ["2024", "2025"],
      current_official: true,
    });
    const enrichedCurrent = await enrichHits(currentHits);
    let allHits = enrichedCurrent;
    if (
      enrichedCurrent.length === 0
      || enrichedCurrent.every((hit) => parseMonsterStats(hit).actions.length === 0)
    ) {
      const legacyHits = await searchKnowledge({
        text: query, top_k: 6, candidate_k: 24, min_score: 0.25,
        content_types: ["monsters"], editions: ["2014", "legacy"],
        current_official: false, allow_unknown: false, allow_third_party: false,
      });
      allHits = [...enrichedCurrent, ...await enrichHits(legacyHits)];
    }
    return compendiumMonsterCandidates(allHits, query);
  };
  const candidates = useMemo(() => [
    ...(characters.data ?? []).map((entity) => ({ key: `character:${entity.id}`, label: `玩家 · ${entity.name}` })),
    ...(npcs.data ?? []).map((entity) => ({ key: `npc:${entity.id}`, label: `NPC · ${entity.name}` })),
    ...(monsters.data ?? []).map((entity) => ({ key: `monster:${entity.id}`, label: `怪物 · ${entity.name}` })),
  ], [characters.data, monsters.data, npcs.data]);
  const presentKeys = new Set((participants.data ?? []).map((item) => `${item.entity_type}:${item.entity_id}`));
  const sanitizeSceneNarration = (
    text: string,
    outline: SceneStoryOutline,
    fallback: string,
    allowedEntityKeys = presentKeys,
  ): { text: string; contaminated: boolean } => {
    const allowedOutlineText = Object.values(outline).join(" ");
    const contaminated = [
      ...(npcs.data ?? []).map((entity) => ({ key: `npc:${entity.id}`, name: entity.name })),
      ...(monsters.data ?? []).map((entity) => ({ key: `monster:${entity.id}`, name: entity.name })),
    ].some((entity) => (
      entity.name.trim().length >= 2
      && !allowedEntityKeys.has(entity.key)
      && !allowedOutlineText.includes(entity.name)
      && text.includes(entity.name)
    ));
    return contaminated ? { text: fallback, contaminated: true } : { text, contaminated: false };
  };
  const availableCandidates = candidates.filter((candidate) => !presentKeys.has(candidate.key));
  const entityName = (entityType: string, entityId: string) =>
    candidates.find((candidate) => candidate.key === `${entityType}:${entityId}`)?.label.replace(/^.+ · /, "")
    ?? entityId;
  const quickActions = useMemo(() => buildContextualQuickActions({
    sceneName: activeScene?.name ?? "当前场景",
    outline: activeOutline,
    phase: activePhase,
    participants: (participants.data ?? []).map((item) => ({
      entity_type: item.entity_type,
      name: item.entity.name,
      defeated: item.role === "defeated",
    })),
    recentText: entries.at(-1)?.text,
  }), [activeOutline, activePhase, activeScene?.name, entries, participants.data]);
  const log = async (title: string, description: string, metadata: Record<string, unknown> = {}) => {
    await createEvent(campaignId, {
      title, description, event_type: "session_progress", visibility: "dm",
      location_id: activeScene?.location_id ?? null,
      metadata_json: { scene_id: sceneId, game_table: true, ...metadata },
    });
    await client.invalidateQueries({ queryKey: ["events", campaignId] });
  };
  const publishPlayerGuidance = async (input: {
    sceneName: string;
    sceneId: string;
    locationId?: string | null;
    phase: ScenePhase;
    reason: PlayerGuidanceReason;
  }) => {
    const guidance = buildPlayerGuidance(input);
    try {
      await createEvent(campaignId, {
        title: guidance.title,
        description: guidance.suggestions.join("\n"),
        event_type: "player_guidance",
        visibility: "players",
        location_id: input.locationId ?? null,
        metadata_json: {
          scene_id: input.sceneId,
          guidance_phase: input.phase,
          guidance_reason: input.reason,
        },
      });
    } catch {
      showToast("主机推进已完成，但玩家行动提示暂时没有同步", "error");
    }
  };
  const addEntry = (kind: ProgressEntry["kind"], text: string, intent?: GameTableAssistantIntent) => {
    setEntries((current) => [...current, { id: createClientId("progress"), kind, intent, text, createdAt: new Date().toISOString() }]);
  };
  const startAssistantActivity = (label: string, intent: GameTableAssistantIntent = "advance"): string => {
    const id = createClientId("assistant-live");
    setLiveAssistant({ id, intent, label, status: "thinking", text: "" });
    return id;
  };
  const revealAssistantText = async (activityId: string, text: string): Promise<void> => {
    const chunks = splitAssistantRevealChunks(text);
    let visible = "";
    for (const chunk of chunks) {
      visible = visible ? `${visible}\n\n${chunk}` : chunk;
      setLiveAssistant((current) => current?.id === activityId
        ? { ...current, status: "revealing", text: visible }
        : current);
      await new Promise((resolve) => window.setTimeout(resolve, 110));
    }
  };
  const finishAssistantActivity = (activityId: string) => {
    setLiveAssistant((current) => current?.id === activityId ? null : current);
  };
  const grantLookup = useMutation({
    mutationFn: async (intent: CharacterGrantIntent) => {
      const character = characters.data?.find((item) => item.id === intent.characterId);
      const catalog = characterOptions.data;
      if (!character || !catalog) throw new Error("角色或本地 2024 规则目录尚未载入");
      if (intent.kind === "spell") return buildSpellGrantDraft(intent, character, catalog);
      if (intent.kind === "skill_proficiency" || intent.kind === "skill_expertise") {
        return buildSkillGrantDraft(intent, character, catalog);
      }
      if (intent.kind === "class_feature") {
        return buildFeatureGrantDraft(intent, character, catalog);
      }
      const hits = await searchKnowledge({
        text: intent.kind === "item"
          ? `${intent.requestedName} 道具 物品 重量 价格`
          : `${intent.requestedName} 武器 护甲 装备 重量 价格`,
        top_k: 12,
        candidate_k: 64,
        min_score: 0.1,
        content_types: intent.kind === "item" ? ["items", "equipment"] : ["equipment"],
        editions: ["2024"],
        current_official: true,
        allow_unknown: false,
        allow_third_party: false,
      });
      const documents = await Promise.all(hits.slice(0, 12).map(async (hit) => {
        try {
          return await getRuleDocument(hit.chunk.record_id);
        } catch {
          return null;
        }
      }));
      const exact = documents.find((document) => (
        document?.content_type === "equipment"
        && document.content_plain_text.includes(intent.requestedName)
      ))
        ?? documents.find((document) => (
          document?.content_type === "items"
          && document.content_plain_text.includes(intent.requestedName)
        ))
        ?? documents.find((document) => document?.content_plain_text.includes(intent.requestedName))
        ?? documents.find((document) => document !== null)
        ?? null;
      return buildItemGrantDraft(intent, exact);
    },
    onSuccess: (draft) => {
      setGrantDraft(draft);
      setArrivalDraft(null);
      setArrivalReferences([]);
      showToast(draft.eligible ? "已生成规则校验后的玩家授予草案" : "授予请求未通过 2024 规则校验", draft.eligible ? "success" : "error");
    },
    onError: (error) => showToast(error.message, "error"),
  });
  const arrivalLookup = useMutation({
    mutationFn: async ({ kind, prompt, assistantText }: { kind: ArrivalKind; prompt: string; assistantText: string; startCombat?: boolean }) => {
      const sceneContext = `${activeScene?.name ?? ""} ${activeScene?.description ?? ""} ${activeLocation?.name ?? ""} ${activeLocation?.description ?? ""}`;
      if (kind === "npc") {
        try {
          const preview = await generateNpc(campaignId, {
            mode: "quick",
            brief: `${prompt}\n当前场景：${sceneContext}\n副DM建议：${assistantText}`,
            answers: {},
          });
          return {
            draft: {
              kind: "npc" as const, prompt, sourceKey: "generated-npc",
              name: preview.npc.name || suggestedNpcName(prompt),
              description: preview.npc.description || assistantText || prompt,
              armorClass: preview.npc.armor_class,
              hp: preview.npc.max_hp,
              speed: preview.npc.speed,
              challengeRating: preview.npc.challenge_rating ?? "0",
              templateSourceKey: null,
              abilityScores: preview.npc.ability_scores,
              actions: preview.npc.actions,
            },
            references: [] as MonsterReferenceCandidate[],
          };
        } catch {
          return {
            draft: {
              kind: "npc" as const, prompt, sourceKey: "generated-npc",
              name: suggestedNpcName(prompt), description: assistantText || prompt,
              armorClass: 10, hp: 10, speed: 30, challengeRating: "0",
              templateSourceKey: null,
              abilityScores: {
                strength: 10, dexterity: 10, constitution: 10,
                intelligence: 10, wisdom: 10, charisma: 10,
              },
              actions: [],
            },
            references: [] as MonsterReferenceCandidate[],
          };
        }
      }
      const availableMonsters = (monsters.data ?? []).filter(
        (monster) => !presentKeys.has(`monster:${monster.id}`),
      );
      const existing = campaignMonsterCandidates(availableMonsters, `${prompt} ${sceneContext}`);
      let compendium: MonsterReferenceCandidate[] = [];
      try {
        const requestedName = requestedMonsterName(prompt);
        compendium = await findCompendiumMonsters(
          `${requestedName} ${prompt} ${assistantText} ${sceneContext}`,
        );
      } catch {
        // The local index may be rebuilding. The DM still gets a clearly
        // labeled custom draft, and no state is written without confirmation.
      }
      const references = [...existing, ...compendium];
      return {
        draft: references[0]
          ? monsterDraftFromCandidate(references[0], prompt)
          : customMonsterDraft(prompt),
        references,
      };
    },
    onSuccess: ({ draft, references }, variables) => {
      setArrivalDraft(draft);
      setArrivalReferences(references);
      setStartCombatAfterArrival(Boolean(variables.startCombat));
      showToast(draft.kind === "monster"
        ? references.length > 0 ? `已找到 ${references.length} 个本地图鉴/战役候选，请 DM 复核` : "图鉴暂无可靠匹配，已生成明确标记的自制草案"
        : "NPC 草案已生成，请 DM 复核后加入场景");
    },
    onError: () => showToast("无法起草进入场景的人物，请稍后重试", "error"),
  });
  const assistant = useMutation({
    mutationFn: async ({ action, intent }: { action: string; activityId: string; intent: GameTableAssistantIntent }) => {
      const names = (participants.data ?? []).map((item) => `${item.entity_type}:${item.entity.name}${item.role === "defeated" ? "（已击败）" : ""}`).join("、") || "无人";
      const nextOutline = nextScene
        ? readSceneStoryOutline(nextScene, activeSceneIndex + 2)
        : null;
      const flowContext = currentFlowStep
        ? `当前流程步骤 ${currentFlowStep.order}/${activeFlow.length}「${currentFlowStep.title}」：${currentFlowStep.instruction}。这只是DM导航，玩家若采用其他合理方案，应响应玩家而不是强行拉回预设流程。`
        : "当前没有预设流程步骤，由DM自由推进。";
      const requestContract = gameTableAssistantContract(action, intent);
      const transitionContract = intent === "advance"
        ? "如果已确认的玩家行动使当前Scene目标完成、绕过或自然收束，并且确实存在下一个Scene，请在末尾单独输出[[建议进入下一场景]]；否则输出[[继续当前场景]]。"
        : "不要输出场景切换标记，也不要因为这次询问改变当前流程位置。";
      const recentEntries = entries.slice(-4).map((entry) => `${assistantEntryLabel(entry.kind, entry.intent)}：${entry.text}`).join("；");
      const context = `你是D&D 5e 2024副DM，本应用不是COC。不得使用克苏鲁、奈亚拉托提普、旧日支配者、深潜者、SAN或理智检定等其他系统内容。${requestContract}当前章节与场景：${activeOutline?.chapterTitle ?? "未编排"} / Scene ${activeOutline?.sceneOrder ?? "?"} ${activeScene?.name ?? "未选择"}。当前Scene目标：${activeOutline?.objective ?? "未填写"}。${flowContext}地点：${activeLocation?.name ?? "未绑定"}。当前在场：${names}。最近记录：${recentEntries || "无"}。DM本次输入：${action}。${nextScene && nextOutline ? `下一个候选是 Scene ${nextOutline.sceneOrder}「${nextScene.name}」，进入条件提示：${activeOutline?.transition ?? "由DM判断"}。` : "当前没有下一个已编排Scene。"}只用D&D 5e世界与机制，严格优先完成DM本次输入，不要复用上一条回答。本模式只输出叙事或建议草案，不给出未经规则证据逐条支持的DC、CR、伤害骰、加值、次数或持续时间，不要擅自修改数据库。${transitionContract}`;
      const previousReply = [...entries].reverse().find((entry) => entry.kind === "ai")?.text;
      let response = await runAssistantTurn(campaignId, context, { mode: "narrative" });
      let reply = withoutSceneTransitionMarker(response.dm_hint?.text ?? "");
      if (isUnwantedRepeatedReply(action, reply, previousReply)) {
        response = await runAssistantTurn(
          campaignId,
          `${context}\n纠错要求：刚才的候选回答与上一条副DM回答重复，不能使用。请重新理解“${action}”，从不同角度重新生成，并严格服从本次请求类型。`,
          { mode: "narrative" },
        );
        reply = withoutSceneTransitionMarker(response.dm_hint?.text ?? "");
        if (isUnwantedRepeatedReply(action, reply, previousReply)) {
          throw new Error("副 DM 连续返回了旧内容，已拦截重复回复");
        }
      }
      return response;
    },
    onSuccess: async (response, { action, activityId, intent }) => {
      const rawText = response.dm_hint?.text || (response.abstained ? "AI 暂时无法给出可靠建议，请由 DM 自由推进。" : "已读取当前战役状态，但没有生成新的提示。");
      const text = withoutSceneTransitionMarker(rawText);
      const dmRecordedTransition = intent === "advance" && /(?:决定|接受|完成|解决|离开|出发|前往|抵达|进入|打开|深入|转场)/.test(action);
      const suggestsTransition = intent === "advance" && Boolean(nextScene) && (
        rawText.includes("[[建议进入下一场景]]")
        || /(?:可以|建议|适合|准备).{0,8}(?:进入|切换|转入).{0,8}(?:下一|下个).{0,4}(?:场景|Scene)/i.test(rawText)
        || dmRecordedTransition
      );
      if (intent === "advance") {
        setSuggestedSceneId(suggestsTransition ? nextScene?.id ?? null : null);
      }
      setLastResponse(response);
      await revealAssistantText(activityId, text);
      addEntry("ai", text, intent);
      finishAssistantActivity(activityId);
      await log(intent === "ask" ? "副DM回答" : intent === "execute" ? "副DM执行建议" : "AI 推进建议", text, {
        dm_action: action, entry_kind: "ai", assistant_intent: intent,
      });
      if (intent === "advance") {
        await publishPlayerGuidance({
          sceneName: activeScene?.name ?? "当前 Scene",
          sceneId,
          locationId: activeScene?.location_id,
          phase: activePhase,
          reason: "dm_advanced",
        });
        const arrivalKind = detectArrivalKind(`${action}\n${text}`);
        if (arrivalKind && sceneId) {
          arrivalLookup.mutate({ kind: arrivalKind, prompt: action, assistantText: text });
        }
      }
    },
    onError: (error, { activityId }) => {
      finishAssistantActivity(activityId);
      showToast(error.message.includes("重复回复") ? error.message : "副 DM 暂时没有响应，请检查本地模型", "error");
    },
  });
  const askAssistant = (action: string) => {
    if (!action.trim() || !sceneId || assistant.isPending || liveAssistant) return;
    addEntry("dm", action.trim(), "ask");
    void log("DM 询问", action.trim(), { entry_kind: "dm", assistant_intent: "ask" });
    assistant.mutate({
      action: action.trim(),
      intent: "ask",
      activityId: startAssistantActivity("副 DM 正在理解问题并生成回答", "ask"),
    });
    setInput("");
  };
  const recordProgressAndAsk = (action: string) => {
    if (!action.trim() || !sceneId || assistant.isPending || liveAssistant) return;
    addEntry("dm", action.trim(), "advance");
    void log("DM 推进", action.trim(), { entry_kind: "dm", assistant_intent: "advance" });
    assistant.mutate({
      action: action.trim(),
      intent: "advance",
      activityId: startAssistantActivity("副 DM 正在承接已发生事实并生成推进建议", "advance"),
    });
    setInput("");
  };
  const retryAssistant = () => {
    const failed = assistant.variables;
    if (!failed || assistant.isPending || liveAssistant) return;
    assistant.reset();
    assistant.mutate({
      ...failed,
      activityId: startAssistantActivity(failed.intent === "ask" ? "副 DM 正在重新回答" : "副 DM 正在重新生成推进建议", failed.intent),
    });
  };
  const executeInput = () => {
    const action = input.trim();
    if (!action || !sceneId || arrivalLookup.isPending || grantLookup.isPending || liveAssistant) return;
    addEntry("dm", action, "execute");
    void log("DM 执行指令", action, { entry_kind: "dm", action: "execute_request", assistant_intent: "execute" });
    const grantIntent = detectCharacterGrantIntent(action, characters.data ?? []);
    if (grantIntent) {
      grantLookup.mutate(grantIntent);
      setInput("");
      return;
    }
    const kind = detectArrivalKind(action);
    if (kind) {
      const startsCombat = /攻击|战斗|突袭|伏击|开战|冲向|袭击/.test(action);
      arrivalLookup.mutate({
        kind,
        prompt: action,
        assistantText: "DM要求将描述转成当前场景中的真实D&D原子。",
        startCombat: startsCombat,
      });
      setInput("");
      return;
    }
    assistant.mutate({
      action: `DM要求立即落实以下场景变化，并给出可执行后果草案：${action}`,
      intent: "execute",
      activityId: startAssistantActivity("副 DM 正在分析这次场景变化", "execute"),
    });
    setInput("");
  };
  const grantConfirm = useMutation({
    mutationFn: async () => {
      if (!grantDraft?.eligible) throw new Error(grantDraft?.blockingReason ?? "授予草案未通过规则校验");
      const character = characters.data?.find((item) => item.id === grantDraft.characterId);
      if (!character) throw new Error("目标角色已不存在");
      if (grantDraft.kind === "spell") {
        await createKnownSpell(campaignId, {
          character_id: character.id,
          character_version: character.version,
          name: grantDraft.candidateName,
          spell_level: Number(grantDraft.metadata.spell_level ?? 0),
          prepared: false,
          source_reference: grantDraft.sourceLabel,
          metadata_json: {
            ...grantDraft.metadata,
            source_record_id: grantDraft.sourceRecordId,
            canonical_url: grantDraft.canonicalUrl,
            edition: grantDraft.edition,
            officiality: grantDraft.officiality,
          },
        });
      } else if (grantDraft.kind === "class_feature") {
        await updateCharacter(campaignId, character.id, {
          features: [
            ...character.features,
            {
              name: grantDraft.candidateName,
              description: grantDraft.description || grantDraft.ruleReason,
              source_record_id: grantDraft.sourceRecordId,
              source_label: grantDraft.sourceLabel,
              class_name: grantDraft.metadata.class_name,
              class_level: grantDraft.metadata.class_level,
              rule_year: 2024,
            },
          ],
        }, character.version);
      } else if (grantDraft.kind === "skill_proficiency" || grantDraft.kind === "skill_expertise") {
        const skillName = typeof grantDraft.metadata.skill_name === "string"
          ? grantDraft.metadata.skill_name
          : grantDraft.candidateName;
        const old = character.skills[skillName];
        const oldSetting = old && typeof old === "object" ? old as Record<string, unknown> : {};
        await updateCharacter(campaignId, character.id, {
          skills: {
            ...character.skills,
            [skillName]: {
              ...oldSetting,
              proficient: true,
              expertise: grantDraft.kind === "skill_expertise" || oldSetting.expertise === true,
              source_record_id: grantDraft.sourceRecordId,
              source_label: grantDraft.sourceLabel,
              rule_year: 2024,
            },
          },
        }, character.version);
      } else {
        await createEquipmentInstance(campaignId, {
          character_id: character.id,
          character_version: character.version,
          name: grantDraft.candidateName,
          category: typeof grantDraft.metadata.category === "string"
            ? grantDraft.metadata.category
            : grantDraft.kind === "item" ? "item" : "gear",
          quantity: grantDraft.quantity,
          armor_class: typeof grantDraft.metadata.armor_class === "number" ? grantDraft.metadata.armor_class : null,
          attunement_required: grantDraft.metadata.attunement_required === true,
          metadata_json: {
            ...grantDraft.metadata,
            source_record_id: grantDraft.sourceRecordId,
            canonical_url: grantDraft.canonicalUrl,
            edition: grantDraft.edition,
            officiality: grantDraft.officiality,
          },
        });
      }
      if (!grantDraft.sourceRecordId || grantDraft.officiality !== "official") {
        const entryType = grantDraft.kind === "spell"
          ? "spell"
          : grantDraft.kind === "class_feature"
            ? "feature"
            : grantDraft.kind === "item"
              ? "item"
              : "equipment";
        await createCompendiumEntry(campaignId, {
          entry_type: entryType,
          name: grantDraft.candidateName,
          description: grantDraft.description || grantDraft.ruleReason,
          source_kind: "ai_generated",
          tags: ["原创", "推进台确认"],
          filters_json: grantDraft.metadata,
          rules_json: grantDraft.metadata,
        });
      }
      await createEvent(campaignId, {
        title: `${grantDraft.characterName}获得${grantDraft.candidateName}`,
        description: `DM确认授予：${grantDraft.candidateName}${grantDraft.quantity > 1 ? ` × ${grantDraft.quantity}` : ""}。${grantDraft.ruleReason}`,
        event_type: "character_grant",
        visibility: "players",
        location_id: activeScene?.location_id ?? null,
        metadata_json: {
          action: "character_grant",
          grant_kind: grantDraft.kind,
          character_id: grantDraft.characterId,
          source_record_id: grantDraft.sourceRecordId,
          scene_id: sceneId,
          game_table: true,
        },
      });
      return grantDraft;
    },
    onSuccess: async (confirmed) => {
      addEntry("system", `${confirmed.characterName}获得${confirmed.candidateName}${confirmed.quantity > 1 ? ` × ${confirmed.quantity}` : ""}`);
      setGrantDraft(null);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["characters", campaignId] }),
        client.invalidateQueries({ queryKey: ["character-assets", campaignId, confirmed.characterId] }),
        client.invalidateQueries({ queryKey: ["dm-noncombat-actions", campaignId, confirmed.characterId] }),
        client.invalidateQueries({ queryKey: ["events", campaignId] }),
      ]);
      showToast("已按 2024 规则写入角色，并同步给玩家端");
    },
    onError: (error) => showToast(error.message, "error"),
  });
  const participantAdd = useMutation({
    mutationFn: async () => {
      const [entityType, entityId] = entityKey.split(":");
      if (!entityType || !entityId) throw new Error("请选择进入场景的人物");
      const created = await addSceneParticipant(campaignId, sceneId, { entity_type: entityType as "character" | "npc" | "monster", entity_id: entityId });
      await log(`${created.entity.name}进入场景`, `${created.entity.name}进入“${activeScene?.name ?? "当前场景"}”。`, { action: "enter", entry_kind: "system", entity_type: entityType, entity_id: entityId });
      return created;
    },
    onSuccess: (created) => {
      setEntityKey(""); addEntry("system", `${created.entity.name}进入当前场景`);
      void client.invalidateQueries({ queryKey: ["scene-participants", campaignId, sceneId] });
      showToast("人物已进入场景");
    },
    onError: () => showToast("加入场景失败", "error"),
  });
  const chooseArrivalReference = (key: string) => {
    const reference = arrivalReferences.find((item) => item.key === key);
    if (reference && arrivalDraft) setArrivalDraft(monsterDraftFromCandidate(reference, arrivalDraft.prompt));
    else if (arrivalDraft) setArrivalDraft(customMonsterDraft(arrivalDraft.prompt, arrivalReferences[0]));
  };
  const chooseCustomTemplate = (key: string) => {
    if (!arrivalDraft) return;
    const reference = arrivalReferences.find((item) => item.key === key);
    setArrivalDraft(customMonsterDraft(arrivalDraft.prompt, reference));
  };
  const arrivalConfirm = useMutation({
    mutationFn: async () => {
      if (!arrivalDraft || !sceneId) throw new Error("没有可确认的进入场景草案");
      let entityId: string;
      let entityType: "npc" | "monster";
      if (arrivalDraft.kind === "npc") {
        const npc = await createNpc(campaignId, {
          name: arrivalDraft.name,
          description: arrivalDraft.description,
          armor_class: arrivalDraft.armorClass,
          hp: arrivalDraft.hp,
          max_hp: arrivalDraft.hp,
          speed: arrivalDraft.speed,
          challenge_rating: arrivalDraft.challengeRating,
          ability_scores: {
            strength: 10, dexterity: 10, constitution: 10,
            intelligence: 10, wisdom: 10, charisma: 10,
          },
          known_information: `登场原因：${arrivalDraft.prompt}`,
          status: "active",
        });
        entityId = npc.id;
        entityType = "npc";
        await createCompendiumEntry(campaignId, {
          entry_type: "npc",
          name: arrivalDraft.name,
          description: arrivalDraft.description,
          source_kind: "ai_generated",
          tags: ["原创", "推进台确认"],
          filters_json: { challenge_rating: arrivalDraft.challengeRating },
          rules_json: {
            armor_class: arrivalDraft.armorClass,
            hp: arrivalDraft.hp,
            speed: arrivalDraft.speed,
            ability_scores: arrivalDraft.abilityScores,
            actions: arrivalDraft.actions,
          },
        });
      } else {
        const reference = arrivalReferences.find((item) => item.key === arrivalDraft.sourceKey);
        if (reference?.origin === "campaign") {
          entityId = reference.monster.id;
        } else {
          const templateReference = arrivalReferences.find(
            (item) => item.key === arrivalDraft.templateSourceKey,
          );
          const isOfficialReference = reference?.origin === "compendium";
          const templateLabel = templateReference?.label;
          const monster = await createMonster(campaignId, {
            name: arrivalDraft.name,
            source_record_id: isOfficialReference ? reference.hit.chunk.record_id : null,
            source_name: isOfficialReference
              ? `${reference.hit.chunk.source_book ?? reference.hit.chunk.source_title} · ${reference.hit.chunk.edition}`
              : templateLabel
                ? `DM自制怪物 · 规则模板参考 ${templateLabel}`
                : "DM自制模板（非图鉴）",
            armor_class: arrivalDraft.armorClass,
            hp: arrivalDraft.hp,
            max_hp: arrivalDraft.hp,
            speed: arrivalDraft.speed,
            challenge_rating: arrivalDraft.challengeRating,
            ability_scores: arrivalDraft.abilityScores,
            actions: arrivalDraft.actions,
            notes: `${arrivalDraft.description}\n登场原因：${arrivalDraft.prompt}${isOfficialReference ? "\n由本地图鉴条目创建，DM已确认。" : templateLabel ? `\n自制怪物，规则数值与动作绑定模板“${templateLabel}”，DM已确认。` : "\n自制模板，未绑定图鉴规则模板，DM应复核数值。"}`,
          });
          entityId = monster.id;
          if (!isOfficialReference) {
            await createCompendiumEntry(campaignId, {
              entry_type: "monster",
              name: arrivalDraft.name,
              description: arrivalDraft.description,
              source_kind: "ai_generated",
              tags: ["原创", "推进台确认"],
              filters_json: { challenge_rating: arrivalDraft.challengeRating },
              rules_json: {
                armor_class: arrivalDraft.armorClass,
                hp: arrivalDraft.hp,
                speed: arrivalDraft.speed,
                ability_scores: arrivalDraft.abilityScores,
                actions: arrivalDraft.actions,
              },
            });
          }
        }
        entityType = "monster";
      }
      const participant = await addSceneParticipant(campaignId, sceneId, {
        entity_type: entityType, entity_id: entityId,
      });
      await log(
        `${participant.entity.name}进入场景`,
        `${participant.entity.name}根据DM确认的动态原子草案进入“${activeScene?.name ?? "当前场景"}”。`,
        {
          action: "dynamic_arrival", entry_kind: "system",
          entity_type: entityType, entity_id: entityId,
          source: arrivalDraft.sourceKey,
        },
      );
      if (startCombatAfterArrival && activeScene) {
        await ensureScenePersistentGrid(campaignId, activeScene, activeLocation?.name ?? "");
      }
      const startedCombat = startCombatAfterArrival
        ? await startSceneCombat(campaignId, sceneId)
        : null;
      return { participant, startedCombat };
    },
    onSuccess: async ({ participant, startedCombat }) => {
      addEntry("system", `${participant.entity.name}已由 DM 确认并进入当前场景`);
      setArrivalDraft(null);
      setArrivalReferences([]);
      void client.invalidateQueries({ queryKey: ["scene-participants", campaignId, sceneId] });
      void client.invalidateQueries({ queryKey: ["npcs", campaignId] });
      void client.invalidateQueries({ queryKey: ["monsters", campaignId] });
      if (startedCombat) {
        sessionStorage.setItem(`dnd-dm-active-combat:${campaignId}`, startedCombat.combat.id);
        setPlayerCombatId(startedCombat.combat.id);
        await setPlayerRoomLiveState(campaignId, sceneId, startedCombat.combat.id);
        void client.invalidateQueries({ queryKey: ["combats", campaignId] });
        navigate("/combat");
      } else {
        showToast("原子已创建并加入当前场景");
      }
    },
    onError: () => showToast("确认加入失败；请检查是否已在场景中或字段是否有效", "error"),
  });
  const participantRemove = useMutation({
    mutationFn: async (participant: SceneParticipant) => {
      await removeSceneParticipant(campaignId, sceneId, participant.id, participant.version);
      await log(`${participant.entity.name}离开场景`, `${participant.entity.name}离开“${activeScene?.name ?? "当前场景"}”。`, { action: "leave", entry_kind: "system", entity_type: participant.entity_type, entity_id: participant.entity_id });
      return participant;
    },
    onSuccess: (participant) => {
      addEntry("system", `${participant.entity.name}离开当前场景`);
      void client.invalidateQueries({ queryKey: ["scene-participants", campaignId, sceneId] });
      showToast("离场状态已记录");
    },
  });
  const combat = useMutation({
    mutationFn: async () => {
      if (!activeScene) throw new Error("请先选择当前Scene");
      await ensureScenePersistentGrid(campaignId, activeScene, activeLocation?.name ?? "");
      return startSceneCombat(campaignId, sceneId);
    },
    onSuccess: async (result) => {
      void log("进入战斗", `“${activeScene?.name ?? "当前场景"}”进入战斗，已加载当前人物与场景网格。`);
      sessionStorage.setItem(`dnd-dm-active-combat:${campaignId}`, result.combat.id);
      setPlayerCombatId(result.combat.id);
      await setPlayerRoomLiveState(campaignId, sceneId, result.combat.id);
      void client.invalidateQueries({ queryKey: ["combats", campaignId] });
      navigate("/combat");
    },
    onError: () => showToast("无法发起战斗，请确认当前场景里至少有一名参与者", "error"),
  });
  const createManualScene = useMutation({
    mutationFn: async () => {
      const order = Math.max(1, Number(sceneOrder) || 1);
      const outline: SceneStoryOutline = {
        chapterTitle: sceneChapter.trim() || "未编排章节",
        chapterOrder: chapterOrderFromTitle(sceneChapter),
        sceneOrder: order,
        objective: sceneObjective.trim() || "由 DM 自由推进。",
        opening: sceneOpening.trim() || sceneObjective.trim() || "介绍环境与在场人物。",
        development: sceneDevelopment.trim() || "根据玩家行动推进。",
        twist: sceneTwist.trim() || "没有必要时可以跳过转折。",
        climax: sceneClimax.trim() || "确认当前 Scene 的目标是否完成。",
        transition: sceneTransition.trim() || "由 DM 决定是否进入下一个 Scene。",
      };
      return createSceneWithPersistentGrid(campaignId, {
        name: sceneName.trim(),
        location_id: sceneLocationId || null,
        description: outline.objective,
        notes: buildSceneNotes(
          generateTacticalSceneGrid(sceneName, `${outline.objective} ${outline.opening}`),
          outline,
        ),
      }, locations.data?.find((location) => location.id === sceneLocationId)?.name ?? "");
    },
    onSuccess: async (created) => {
      await client.invalidateQueries({ queryKey: ["scenes", campaignId] });
      setSceneId(created.id);
      setPlayerCombatId(null);
      setSceneName("");
      setSceneObjective("");
      setSceneOpening("");
      setSceneDevelopment("");
      setSceneTwist("");
      setSceneClimax("");
      setSceneTransition("");
      setSceneOrder(String(Math.max(1, Number(sceneOrder) || 1) + 1));
      showToast(`已创建 ${sceneChapter} · Scene ${sceneOrder}`);
    },
    onError: () => showToast("Scene 创建失败，请检查名称和地点", "error"),
  });
  const sceneTransitionNarration = useMutation({
    mutationFn: async ({ target, source, activityId }: { target: Scene; source: "manual" | "ai"; activityId: string }) => {
      const targetIndex = orderedScenes.findIndex((scene) => scene.id === target.id);
      const outline = readSceneStoryOutline(target, targetIndex + 1);
      await createEvent(campaignId, {
        title: `进入 Scene ${outline.sceneOrder} · ${target.name}`,
        description: `DM${source === "ai" ? "接受副DM建议并" : ""}切换到“${target.name}”。${outline.opening}`,
        event_type: "session_progress",
        visibility: "dm",
        location_id: target.location_id,
        metadata_json: {
          scene_id: target.id,
          from_scene_id: sceneId,
          game_table: true,
          entry_kind: "system",
          action: "scene_transition",
          source,
        },
      });
      const allowedNames = target.id === sceneId
        ? (participants.data ?? []).map((item) => item.entity.name).join("、") || "无"
        : "无";
      const prompt = `你是D&D 5e 2024副DM。现在正式进入${outline.chapterTitle}的 Scene ${outline.sceneOrder}「${target.name}」。目标：${outline.objective}。开场：${outline.opening}。发展：${outline.development}。转折：${outline.twist}。收束：${outline.climax}。当前Scene已确认在场人物仅有：${allowedNames}。只可使用大纲明确写到的人物或这份在场名单；严禁从同一战役的其他Scene、旧记录或模型记忆带入任何人物。请生成一段简洁的可朗读进入描述，然后另起一段给DM一个开场操作提示。不要擅自改变事实或写入数据库。`;
      const response = await runAssistantTurn(campaignId, prompt, { mode: "narrative" });
      const rawText = withoutSceneTransitionMarker(
        response.dm_hint?.text
        || "已进入新 Scene。请按右侧大纲介绍开场并询问玩家行动。",
      );
      const sanitized = sanitizeSceneNarration(
        rawText,
        outline,
        `${outline.opening}\n\nDM提示：只介绍当前Scene大纲与已在场人物，然后询问每名玩家要做什么。`,
        target.id === sceneId ? presentKeys : new Set<string>(),
      );
      return { activityId, response: sanitized.contaminated ? null : response, target, text: sanitized.text };
    },
    onSuccess: async ({ activityId, response, target, text }) => {
      await revealAssistantText(activityId, text);
      const aiEntry: ProgressEntry = {
        id: createClientId("progress"),
        kind: "ai",
        intent: "advance",
        text,
        createdAt: new Date().toISOString(),
      };
      const nextEntries = [...loadEntries(campaignId, target.id), aiEntry];
      saveEntries(campaignId, target.id, nextEntries);
      if (target.id === sceneId) setEntries(nextEntries);
      setLastResponse(response);
      finishAssistantActivity(activityId);
      await createEvent(campaignId, {
        title: "副DM Scene 开场",
        description: text,
        event_type: "session_progress",
        visibility: "dm",
        location_id: target.location_id,
        metadata_json: {
          scene_id: target.id,
          game_table: true,
          entry_kind: "ai",
          assistant_intent: "advance",
          action: "scene_opening",
        },
      });
      await publishPlayerGuidance({
        sceneName: target.name,
        sceneId: target.id,
        locationId: target.location_id,
        phase: "opening",
        reason: "scene_entered",
      });
      void client.invalidateQueries({ queryKey: ["events", campaignId] });
    },
    onError: (_error, { activityId }) => {
      finishAssistantActivity(activityId);
      showToast("Scene 已切换，但副DM开场描述暂时生成失败", "error");
    },
  });
  const enterScene = (target: Scene, source: "manual" | "ai") => {
    if (liveAssistant) return;
    const targetIndex = orderedScenes.findIndex((scene) => scene.id === target.id);
    const outline = readSceneStoryOutline(target, targetIndex + 1);
    const systemEntry: ProgressEntry = {
      id: createClientId("progress"),
      kind: "system",
      text: `进入 ${outline.chapterTitle} · Scene ${outline.sceneOrder}「${target.name}」。开场：${outline.opening}`,
      createdAt: new Date().toISOString(),
    };
    const nextEntries = [...loadEntries(campaignId, target.id), systemEntry];
    saveEntries(campaignId, target.id, nextEntries);
    setSceneId(target.id);
    setPlayerCombatId(null);
    setEntries(nextEntries);
    setLastResponse(null);
    setCurrentFlowStepId(buildSceneFlow(target, targetIndex + 1)[0]?.id ?? null);
    setSuggestedSceneId(null);
    sceneTransitionNarration.mutate({
      target,
      source,
      activityId: startAssistantActivity("副 DM 正在生成新 Scene 的进入描述"),
    });
  };
  const flowStepNarration = useMutation({
    mutationFn: async ({ target, step, activityId }: { target: Scene; step: SceneFlowStep; activityId: string }) => {
      const targetIndex = orderedScenes.findIndex((scene) => scene.id === target.id);
      const outline = readSceneStoryOutline(target, targetIndex + 1);
      const allowedNames = target.id === sceneId
        ? (participants.data ?? []).map((item) => item.entity.name).join("、") || "无"
        : "无";
      const prompt = `你是D&D 5e 2024副DM。DM明确把流程推进到${outline.chapterTitle} Scene ${outline.sceneOrder}「${target.name}」的第${step.order}步「${step.title}」。当前步骤：${step.instruction}。DM注意：${step.dmNote}。Scene目标：${outline.objective}。当前Scene已确认在场人物仅有：${allowedNames}。流程只是导航，若已记录的玩家行动采用其他合理方案，要承接玩家选择，不得强行照剧本；不得覆盖已经发生的事实。只可使用大纲明确写到的人物或这份在场名单；严禁从其他Scene、旧记录或模型记忆带入人物。请生成：1）一段简短可朗读内容；2）两到四个随当前局势变化的可选推进；3）一条DM私密注意事项。不要引入其他规则系统，不要修改数据库。`;
      try {
        const response = await runAssistantTurn(campaignId, prompt, { mode: "narrative" });
        const rawText = withoutSceneTransitionMarker(response.dm_hint?.text || `推进到：${step.instruction}`);
        const sanitized = sanitizeSceneNarration(
          rawText,
          outline,
          `当前流程：${step.instruction}\n\n让玩家根据现场事实自由选择调查、交涉、利用环境或采取行动。`,
          target.id === sceneId ? presentKeys : new Set<string>(),
        );
        return {
          activityId, target, step, response: sanitized.contaminated ? null : response,
          text: sanitized.text,
        };
      } catch {
        return {
          activityId, target, step, response: null,
          text: `当前流程：${step.instruction}\n\n请承接玩家已经采取的行动，并询问他们下一步具体怎么做。`,
        };
      }
    },
    onSuccess: async ({ activityId, target, step, response, text }) => {
      await revealAssistantText(activityId, text);
      const nextEntries = [
        ...loadEntries(campaignId, target.id),
        {
          id: createClientId("progress"),
          kind: "system" as const,
          intent: "advance" as const,
          text: `DM把流程推进到第 ${step.order} 步“${step.title}”。`,
          createdAt: new Date().toISOString(),
        },
        {
          id: createClientId("progress"),
          kind: "ai" as const,
          intent: "advance" as const,
          text,
          createdAt: new Date().toISOString(),
        },
      ];
      saveEntries(campaignId, target.id, nextEntries);
      setEntries(nextEntries);
      setCurrentFlowStepId(step.id);
      if (response) setLastResponse(response);
      finishAssistantActivity(activityId);
      await createEvent(campaignId, {
        title: `流程 ${step.order} · ${step.title}`,
        description: text,
        event_type: "session_progress",
        visibility: "dm",
        location_id: target.location_id,
        metadata_json: {
          scene_id: target.id,
          game_table: true,
          entry_kind: "ai",
          action: "scene_flow_step",
          flow_step_id: step.id,
          flow_step_order: step.order,
          flow_step_kind: step.kind,
          flow_step_status: "current",
        },
      });
      await publishPlayerGuidance({
        sceneName: target.name,
        sceneId: target.id,
        locationId: target.location_id,
        phase: step.sourcePhase,
        reason: "flow_advanced",
      });
      void client.invalidateQueries({ queryKey: ["events", campaignId] });
    },
  });
  const enterFlowStep = (target: Scene, step: SceneFlowStep) => {
    if (target.id !== sceneId || liveAssistant) return;
    flowStepNarration.mutate({
      target,
      step,
      activityId: startAssistantActivity(`副 DM 正在生成流程第 ${step.order} 步“${step.title}”`),
    });
  };
  const skipFlowStep = useMutation({
    mutationFn: async ({ target, step }: { target: Scene; step: SceneFlowStep; nextStep: SceneFlowStep | null }) => createEvent(campaignId, {
      title: `跳过流程 ${step.order} · ${step.title}`,
      description: `DM明确跳过“${step.title}”；不会调用AI，也不会改变当前流程位置。`,
      event_type: "session_progress",
      visibility: "dm",
      location_id: target.location_id,
      metadata_json: {
        scene_id: target.id, game_table: true, entry_kind: "system",
        action: "scene_flow_step", flow_step_id: step.id,
        flow_step_order: step.order, flow_step_kind: step.kind,
        flow_step_status: "skipped",
      },
    }),
    onSuccess: async (_, { step }) => {
      addEntry("system", `DM跳过流程第 ${step.order} 步“${step.title}”。`);
      await client.invalidateQueries({ queryKey: ["events", campaignId] });
    },
    onError: () => showToast("流程状态保存失败，请重试", "error"),
  });
  const prep = useMutation({
    mutationFn: () => runAssistantTurn(campaignId, `你是D&D 5e 2024备团副DM。用户可以只写一句简短概要；信息不足时请做保守、可编辑的D&D默认补全，不要拒绝生成，也不要把“博德之门、酒馆、地精、新手村”等D&D/奇幻内容误判成其他规则系统。本应用不是COC，严禁使用克苏鲁、奈亚拉托提普、旧日支配者、深潜者、SAN、理智检定等其他系统专有内容。根据冒险描述生成可审核草稿。必须严格使用以下Markdown结构，不要省略标题。\n## 地点\n- 地点名称｜地点描述、主要区域与可互动物\n场景必须按章节和跑团顺序生成。前五个剧情字段只是兼容摘要，不能把实际跑团锁死成起承转合。每行严格使用：章节｜Scene序号数字｜场景名｜目标｜开场摘要｜发展摘要｜可选变化｜收束摘要｜如何进入下一Scene｜完整推进流程。完整推进流程必须包含6到12个按实际情境安排的短步骤，用 >> 分隔；步骤应覆盖玩家自由行动、人物或环境反应、必要检定、失败后果、状态结算和转场，但不要机械套固定戏剧结构。例如：\n## 场景\n- 第一章｜1｜深水城集结｜让玩家相识并接受委托｜酒馆内分别介绍角色｜委托人说明失踪事件｜线人可能失踪｜玩家决定是否追查｜前往旧教堂｜描述酒馆可见事实 >> 请每名玩家介绍角色与此刻行动 >> 老板说明失踪事件 >> 玩家自由询问、调查或拒绝 >> 根据具体方法裁定是否需要检定 >> 描述成功、失败或代价造成的世界反应 >> 记录已获线索与NPC态度 >> 询问离场前行动 >> DM确认后前往旧教堂\n其他原子每条使用“名称｜描述”：\n## NPC\n- 名称｜描述\n## 怪物\n- 名称｜描述\n## 任务\n- 名称｜描述\n## 线索\n- 名称｜描述\n## 物品\n- 名称｜描述\n最后可以补充“## DM建议”，但不要直接修改数据库。每个Scene导入时会自动生成并绑定持久化5尺战斗网格。\n冒险描述：${prepBrief}`, { mode: "narrative" }),
    onSuccess: (response) => {
      const modelText = response.dm_hint?.text ?? "";
      const unsafeOrEmpty = !modelText.trim()
        || modelText.includes("混入非 D&D 内容已自动隔离")
        || parsePrepDraft(modelText).filter((atom) => atom.kind === "scene").length === 0;
      const text = unsafeOrEmpty ? buildFallbackPrepDraft(prepBrief) : modelText;
      setPrepDraft(text);
      const parsed = parsePrepDraft(text);
      setDraftAtoms(parsed);
      setSelectedAtoms(new Set(parsed.map((atom) => atom.id)));
      showToast(unsafeOrEmpty ? "已用D&D安全模板补全备团草稿" : "备团草稿已生成");
    },
    onError: () => showToast("备团草稿生成失败", "error"),
  });
  const parseDraft = () => {
    const parsed = parsePrepDraft(prepDraft);
    setDraftAtoms(parsed);
    setSelectedAtoms(new Set(parsed.map((atom) => atom.id)));
    showToast(parsed.length > 0 ? `已解析 ${parsed.length} 个可导入原子` : "没有识别到结构化条目，请按“名称｜描述”格式调整草稿", parsed.length > 0 ? "success" : "error");
  };
  const previewDraftImport = useMutation({
    mutationFn: async () => {
      const selected = draftAtoms.filter((atom) => selectedAtoms.has(atom.id));
      const omittedSites = selected.filter(
        (atom) => atom.kind === "building" || atom.kind === "dungeon",
      ).length;
      const draft = atomsToStrictPrepDraft(selected, prepBrief.trim() || "备团草稿");
      const preview = await previewPrepImport(campaignId, draft, "reuse");
      return { draft, preview, omittedSites };
    },
    onSuccess: (review) => {
      setPrepImportReview(review);
      showToast(review.preview.valid ? "原子导入预览已生成；确认前不会写入" : "草稿未通过严格校验", review.preview.valid ? "success" : "error");
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "备团草稿校验失败", "error"),
  });
  const importDraft = useMutation({
    mutationFn: async () => {
      if (!prepImportReview?.preview.valid) throw new Error("请先生成有效的原子导入预览");
      return confirmPrepImport(campaignId, {
        draft: prepImportReview.draft,
        duplicate_strategy: "reuse",
        preview_token: prepImportReview.preview.preview_token,
        idempotency_key: createClientId("prep-import"),
      });
    },
    onSuccess: (result) => {
      for (const key of ["locations", "scenes", "npcs", "monsters", "quests", "clues", "world-items", "region-maps", "adventure-sites"]) void client.invalidateQueries({ queryKey: [key, campaignId] });
      const count = Object.values(result.created).reduce((sum, value) => sum + value, 0);
      showToast(`已用单一事务导入 ${count} 个备团原子`);
      setPrepImportReview(null);
      void log("原子导入备团草稿", `严格 JSON 校验与引用重映射通过，共创建 ${count} 个原子；失败时整批回滚。`, { entry_kind: "system", prep_import_id: result.import_id });
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "备团事务导入失败；数据库未发生部分写入", "error"),
  });
  const saveCheckpoint = useMutation({
    mutationFn: () => {
      if (!sceneId) throw new Error("请先选择 Scene");
      return createSessionCheckpoint(campaignId, {
        name: `${activeScene?.name ?? "场景"} · ${new Date().toLocaleTimeString()}`,
        scene_id: sceneId,
        active_combat_id: playerCombatId,
        entries,
        notes: "由游戏推进台创建的服务端权威场次快照。",
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["session-checkpoints", campaignId] });
      showToast("服务端场次快照已保存");
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "保存检查点失败", "error"),
  });
  const previewCheckpointRestore = useMutation({
    mutationFn: async (checkpoint: SessionCheckpointSummary) => ({
      checkpoint,
      preview: await previewSessionCheckpointRestore(campaignId, checkpoint.id),
    }),
    onSuccess: setCheckpointPreview,
    onError: (error) => showToast(error instanceof Error ? error.message : "无法预览恢复", "error"),
  });
  const restoreCheckpoint = useMutation({
    mutationFn: async () => {
      if (!checkpointPreview) throw new Error("请先预览恢复内容");
      const { checkpoint, preview } = checkpointPreview;
      if (!preview.can_restore) throw new Error("当前状态存在冲突，不能直接恢复");
      const result = await restoreSessionCheckpoint(campaignId, checkpoint.id, {
        idempotency_key: createClientId("checkpoint-restore"),
      });
      const detail = await getSessionCheckpoint(campaignId, checkpoint.id);
      return { result, detail };
    },
    onSuccess: async ({ detail }) => {
      if (detail.scene_id) setSceneId(detail.scene_id);
      setEntries(detail.entries as unknown as ProgressEntry[]);
      setCheckpointPreview(null);
      await client.invalidateQueries();
      showToast("服务端场次快照已事务恢复");
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "恢复检查点失败", "error"),
  });
  const addDraftOperation = () => {
    const [entityType, entityId] = adjustmentTarget.split(":");
    if (!entityType || !entityId) {
      showToast("先选择要调整的角色、NPC 或怪物", "error");
      return;
    }
    const reason = adjustmentReason.trim() || "由 DM 在游戏推进台记录的情景后果。";
    const base = {
      entity_type: entityType as "character" | "npc" | "monster",
      entity_id: entityId,
      reason,
    };
    let operation: EncounterOperation;
    if (adjustmentKind === "set_entity_hp") {
      const hp = Number(adjustmentValue);
      if (!Number.isInteger(hp) || hp < 0) {
        showToast("请输入有效的目标 HP", "error");
        return;
      }
      operation = { ...base, kind: adjustmentKind, hp };
    } else if (adjustmentKind === "add_entity_condition") {
      if (!adjustmentValue.trim()) {
        showToast("请输入具体状态，例如“无法召唤阴影”", "error");
        return;
      }
      operation = { ...base, kind: adjustmentKind, condition: adjustmentValue.trim() };
    } else if (adjustmentKind === "schedule_reinforcement") {
      const round = Number(adjustmentRound);
      const quantity = Number(adjustmentQuantity);
      if (!Number.isInteger(round) || round < 1 || !Number.isInteger(quantity) || quantity < 1) {
        showToast("增援轮次和数量必须是正整数", "error");
        return;
      }
      operation = { ...base, kind: adjustmentKind, round, quantity };
    } else {
      operation = { ...base, kind: adjustmentKind };
    }
    setDraftOperations((current) => [...current, operation].slice(0, 8));
    setAdjustmentValue("");
  };
  const draftFromAssistant = (shift: -1 | 1) => {
    const monster = participants.data?.find((item) => item.entity_type === "monster" && item.role !== "defeated");
    if (!monster) {
      showToast("当前场景没有怪物，先加入怪物原子后再生成后果草案", "error");
      return;
    }
    const latestDmAction = [...entries].reverse().find((entry) => entry.kind === "dm")?.text
      ?? "当前推进记录";
    const hint = lastResponse?.dm_hint?.text;
    setAdjustmentTitle(shift < 0 ? "玩家准备产生的遭遇后果" : "敌方优势产生的遭遇后果");
    setAdjustmentReason(`${latestDmAction}${hint ? `。副 DM 判断：${hint}` : ""}`);
    setAdjustmentShift(shift);
    setDraftOperations(shift < 0
      ? [{
          kind: "set_entity_hp",
          entity_type: "monster",
          entity_id: monster.entity_id,
          hp: Math.max(0, Math.floor(monster.entity.hp * 0.75)),
          reason: `依据玩家行动：${latestDmAction}`,
        }]
      : [{
          kind: "schedule_reinforcement",
          entity_type: "monster",
          entity_id: monster.entity_id,
          round: 3,
          quantity: 1,
          reason: `依据敌方优势：${latestDmAction}`,
        }]);
    showToast("已生成可编辑草案，检查具体变化后再保存");
  };
  const createAdjustment = useMutation({
    mutationFn: () => createEncounterAdjustment(campaignId, {
      scene_id: sceneId,
      source_event_id: [...(events.data ?? [])].reverse()
        .find((event) => event.metadata_json.scene_id === sceneId && event.metadata_json.entry_kind === "dm")?.id,
      title: adjustmentTitle.trim(),
      reason: adjustmentReason.trim(),
      difficulty_shift: adjustmentShift,
      operations: draftOperations,
    }),
    onSuccess: async (created) => {
      setDraftOperations([]);
      setAdjustmentTitle("");
      setAdjustmentReason("");
      setAdjustmentShift(0);
      await client.invalidateQueries({ queryKey: ["encounter-adjustments", campaignId, sceneId] });
      addEntry("system", `已保存遭遇后果草案“${created.title}”，等待 DM 确认应用。`);
      showToast("草案已保存，尚未改变战斗事实");
    },
    onError: () => showToast("保存遭遇后果草案失败", "error"),
  });
  const changeAdjustment = useMutation({
    mutationFn: ({ proposal, action }: { proposal: EncounterAdjustment; action: "apply" | "reject" | "revert" }) => {
      if (action === "apply") return applyEncounterAdjustment(campaignId, proposal.id, proposal.version);
      if (action === "reject") return rejectEncounterAdjustment(campaignId, proposal.id, proposal.version);
      return revertEncounterAdjustment(campaignId, proposal.id, proposal.version);
    },
    onSuccess: async (proposal) => {
      await client.invalidateQueries({ queryKey: ["encounter-adjustments", campaignId, sceneId] });
      await client.invalidateQueries({ queryKey: ["combats", campaignId] });
      addEntry("system", `遭遇后果“${proposal.title}”状态变为 ${proposal.status}。`);
      showToast(proposal.status === "applied" ? "具体遭遇后果已应用" : proposal.status === "reverted" ? "遭遇后果已撤销" : "草案已拒绝");
    },
    onError: () => showToast("遭遇后果状态更新失败，请刷新后重试", "error"),
  });
  const recentEvents = (events.data ?? []).filter((event) => event.metadata_json.scene_id === sceneId).slice(-6).reverse();
  const activeAdjustment = (encounterAdjustments.data ?? [])
    .filter((proposal) => proposal.status === "applied")
    .reduce((sum, proposal) => sum + proposal.difficulty_shift, 0);
  const selectedArrivalReference = arrivalReferences.find(
    (reference) => reference.key === arrivalDraft?.sourceKey,
  );
  return (
    <div className="mx-auto max-w-[1500px] p-4 lg:p-6">
      <SessionReadiness
        characterCount={characters.data?.length ?? 0}
        hasActiveScene={Boolean(activeScene)}
        hasGrid={Boolean(sceneGrid.data)}
        onPrep={() => setTableMode("prep")}
        participantCount={participants.data?.length ?? 0}
        sceneCount={scenes.data?.length ?? 0}
      />
      <PlayerRoomPanel
        campaignId={campaignId}
        characters={characters.data ?? []}
        currentCombatId={playerCombatId}
        currentSceneId={sceneId || null}
        onSceneChange={(targetSceneId) => {
          const target = scenes.data?.find((item) => item.id === targetSceneId);
          if (target) enterScene(target, "manual");
          else setSceneId(targetSceneId);
        }}
      />
      <SessionStatusBar characters={characters.data ?? []} events={events.data ?? []} npcs={npcs.data ?? []} />
      <div className="mb-4 rounded-xl border border-ember-800/45 bg-ember-950/10 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <strong className="mr-auto text-sm text-parchment-100">现在要做什么？</strong>
          <Button onClick={() => setTableMode("prep")} size="sm" variant={tableMode === "prep" ? "primary" : "ghost"}>1 · 开团前备团</Button>
          <Button onClick={() => setTableMode("play")} size="sm" variant={tableMode === "play" ? "primary" : "ghost"}>2 · 开始 / 继续跑团</Button>
          <Button onClick={() => setShowEncounterTools((value) => !value)} size="sm">{showEncounterTools ? "收起高级遭遇工具" : "高级遭遇工具"}</Button>
        </div>
        <p className="mb-0 mt-2 text-2xs text-stone-500">
          {tableMode === "prep"
            ? "备团顺序：创建章节 Scene，或让 AI 从冒险概要生成章节大纲 → 审核导入 → 开始跑团。"
            : "推进顺序：在右侧章节大纲查看当前 Scene → 中间记录玩家行动 → DM 手动转场，或接受副 DM 的转场建议。"}
        </p>
      </div>
      <Panel eyebrow="副 DM · 实时场次" title="游戏推进台">
        <div className="grid gap-3 lg:grid-cols-[1fr_auto]">
          <select
            aria-label="快速切换当前 Scene"
            className={selectCls}
            disabled={sceneTransitionNarration.isPending || Boolean(liveAssistant)}
            onChange={(event) => {
              const target = orderedScenes.find((scene) => scene.id === event.target.value);
              if (target && target.id !== sceneId) enterScene(target, "manual");
            }}
            value={sceneId}
          >
            <option value="">选择当前 Scene</option>
            {orderedScenes.map((scene, index) => {
              const outline = readSceneStoryOutline(scene, index + 1);
              return <option key={scene.id} value={scene.id}>{outline.chapterTitle} · Scene {outline.sceneOrder} · {scene.name}</option>;
            })}
          </select>
          <Button disabled={!sceneId || !participants.data?.length} loading={combat.isPending} onClick={() => combat.mutate()} variant="danger" icon="sword">当前场景发起战斗</Button>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">当前场景</span><strong className="text-xs text-parchment-100">{activeScene?.name ?? "未选择"}</strong></div>
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">地点</span><strong className="text-xs text-parchment-100">{activeLocation?.name ?? "未绑定"}</strong></div>
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">玩家</span><strong className="text-xs text-emerald-300">{participants.data?.filter((item) => item.entity_type === "character").length ?? 0}</strong></div>
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">NPC</span><strong className="text-xs text-violet-300">{participants.data?.filter((item) => item.entity_type === "npc").length ?? 0}</strong></div>
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">怪物</span><strong className="text-xs text-red-300">{participants.data?.filter((item) => item.entity_type === "monster" && item.role !== "defeated").length ?? 0} 活动 · {participants.data?.filter((item) => item.entity_type === "monster" && item.role === "defeated").length ?? 0} 已击败</strong></div>
        </div>
      </Panel>
      {tableMode === "prep" ? <Panel className="mt-4" eyebrow="第 1 步 · 开团前准备" title="备团草稿">
        <div className="rounded-lg border border-ember-800/50 bg-ember-950/10 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="mr-auto">
              <strong className="block text-sm text-parchment-100">直接创建章节 Scene</strong>
              <span className="text-2xs text-stone-500">这里就是手工创建 Scene 的入口；会同时生成对应战斗网格。</span>
            </div>
            <Button
              disabled={!sceneName.trim()}
              loading={createManualScene.isPending}
              onClick={() => createManualScene.mutate()}
              variant="primary"
            >
              创建 Scene
            </Button>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            <label className="text-2xs text-stone-500">章节
              <input aria-label="Scene章节" className={`${inputCls} mt-1`} onChange={(event) => setSceneChapter(event.target.value)} placeholder="第一章" value={sceneChapter} />
            </label>
            <label className="text-2xs text-stone-500">Scene 序号
              <input aria-label="Scene序号" className={`${inputCls} mt-1`} min="1" onChange={(event) => setSceneOrder(event.target.value)} type="number" value={sceneOrder} />
            </label>
            <label className="text-2xs text-stone-500">Scene 名称
              <input aria-label="Scene名称" className={`${inputCls} mt-1`} onChange={(event) => setSceneName(event.target.value)} placeholder="深水城集结" value={sceneName} />
            </label>
            <label className="text-2xs text-stone-500">绑定地点（可选）
              <select aria-label="Scene绑定地点" className={`${selectCls} mt-1`} onChange={(event) => setSceneLocationId(event.target.value)} value={sceneLocationId}>
                <option value="">暂不绑定</option>
                {locations.data?.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
              </select>
            </label>
            <label className="text-2xs text-stone-500 md:col-span-2">Scene 目标
              <input aria-label="Scene目标" className={`${inputCls} mt-1`} onChange={(event) => setSceneObjective(event.target.value)} placeholder="让玩家彼此认识并接受委托" value={sceneObjective} />
            </label>
            <label className="text-2xs text-stone-500 md:col-span-2">开场摘要
              <input aria-label="Scene起" className={`${inputCls} mt-1`} onChange={(event) => setSceneOpening(event.target.value)} placeholder="DM怎样介绍环境与人物" value={sceneOpening} />
            </label>
            <label className="text-2xs text-stone-500 md:col-span-2">主要发展摘要
              <input aria-label="Scene承" className={`${inputCls} mt-1`} onChange={(event) => setSceneDevelopment(event.target.value)} placeholder="玩家可以调查、对话或做什么" value={sceneDevelopment} />
            </label>
            <label className="text-2xs text-stone-500 md:col-span-2">可选变化
              <input aria-label="Scene转" className={`${inputCls} mt-1`} onChange={(event) => setSceneTwist(event.target.value)} placeholder="可选转折、威胁或新信息" value={sceneTwist} />
            </label>
            <label className="text-2xs text-stone-500 md:col-span-2">完成 / 绕过条件
              <input aria-label="Scene合" className={`${inputCls} mt-1`} onChange={(event) => setSceneClimax(event.target.value)} placeholder="怎样算完成或绕过这个 Scene" value={sceneClimax} />
            </label>
            <label className="text-2xs text-stone-500 md:col-span-2">进入下一 Scene
              <input aria-label="Scene转场" className={`${inputCls} mt-1`} onChange={(event) => setSceneTransition(event.target.value)} placeholder="完成什么后适合转场" value={sceneTransition} />
            </label>
          </div>
        </div>
        <div className="my-4 flex items-center gap-3 text-2xs text-stone-600">
          <span className="h-px flex-1 bg-ink-700" />
          或让 AI 一次生成整章
          <span className="h-px flex-1 bg-ink-700" />
        </div>
        <div className="grid gap-2 lg:grid-cols-[1fr_auto]">
          <textarea className={textareaCls} onChange={(event) => setPrepBrief(event.target.value)} placeholder="描述本次冒险，或粘贴完整脚本。建议包含玩家等级、开场地点、目标和预计时长。" value={prepBrief} />
          <Button disabled={!prepBrief.trim()} loading={prep.isPending} onClick={() => prep.mutate()} variant="ai">AI 生成备团草稿</Button>
        </div>
        {prepDraft ? (
          <>
            <div className="prose-block mt-3 whitespace-pre-wrap rounded border border-violet-800/50 bg-violet-950/20 p-3 text-sm text-stone-300">{prepDraft}</div>
            <div className="mt-3 flex justify-end"><Button onClick={parseDraft} size="sm">重新解析草稿</Button></div>
          </>
        ) : null}
        {draftAtoms.length > 0 ? (
          <div className="mt-4 border-t border-ink-700 pt-3">
            <div className="mb-3 flex flex-wrap items-center gap-2"><strong className="mr-auto text-sm text-parchment-100">结构化草稿 · 已选 {selectedAtoms.size}/{draftAtoms.length}</strong><Button onClick={() => { setSelectedAtoms(new Set(draftAtoms.map((atom) => atom.id))); setPrepImportReview(null); }} size="sm">全选</Button><Button onClick={() => { setSelectedAtoms(new Set()); setPrepImportReview(null); }} size="sm">清空</Button><Button disabled={selectedAtoms.size === 0} loading={previewDraftImport.isPending} onClick={() => previewDraftImport.mutate()} variant="primary">严格校验并预览</Button></div>
            {prepImportReview ? <div className="mb-3 rounded border border-amber-500/30 bg-ink-900 p-3 text-xs text-stone-300"><strong className="text-amber-200">事务导入预览</strong><p className="mb-1 mt-1">计划 {prepImportReview.preview.operations.length} 项操作；确认后全部成功或全部回滚。引用和同名复用均由服务端校验。</p>{prepImportReview.omittedSites > 0 ? <p className="text-amber-300">有 {prepImportReview.omittedSites} 个建筑/地下城草案未进入本次原子事务；它们仍保留在草稿中，需使用地点页的站点生成器单独预览确认，不会被静默部分写入。</p> : null}{prepImportReview.preview.errors.map((issue) => <p className="text-red-300" key={`${issue.code}-${issue.path}`}>{issue.path}：{issue.message}</p>)}<div className="mt-2 flex gap-2"><Button onClick={() => setPrepImportReview(null)} size="sm">取消</Button><Button disabled={!prepImportReview.preview.valid} loading={importDraft.isPending} onClick={() => importDraft.mutate()} size="sm" variant="primary">DM 确认原子导入</Button></div></div> : null}
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {draftAtoms.map((atom) => (
                <label className={`rounded border p-3 ${selectedAtoms.has(atom.id) ? "border-ember-700/60 bg-ember-950/10" : "border-ink-700 bg-ink-950/40 opacity-60"}`} key={atom.id}>
                  <div className="flex items-center gap-2"><input checked={selectedAtoms.has(atom.id)} onChange={(event) => setSelectedAtoms((current) => { const next = new Set(current); if (event.target.checked) next.add(atom.id); else next.delete(atom.id); return next; })} type="checkbox" /><Badge>{({ location: "地点", building: "建筑", dungeon: "地下城", scene: "场景", npc: "NPC", monster: "怪物", quest: "任务", clue: "线索", item: "物品" } as const)[atom.kind]}</Badge></div>
                  {atom.sceneOutline ? (
                    <div className="mt-2 grid grid-cols-[1fr_5rem] gap-2">
                      <input
                        aria-label={`${atom.name}章节`}
                        className={selectCls}
                        onChange={(event) => setDraftAtoms((current) => current.map((item) => item.id === atom.id && item.sceneOutline ? { ...item, sceneOutline: { ...item.sceneOutline, chapterTitle: event.target.value } } : item))}
                        value={atom.sceneOutline.chapterTitle}
                      />
                      <input
                        aria-label={`${atom.name}Scene序号`}
                        className={selectCls}
                        min="1"
                        onChange={(event) => setDraftAtoms((current) => current.map((item) => item.id === atom.id && item.sceneOutline ? { ...item, sceneOutline: { ...item.sceneOutline, sceneOrder: Math.max(1, Number(event.target.value)) } } : item))}
                        type="number"
                        value={atom.sceneOutline.sceneOrder}
                      />
                    </div>
                  ) : null}
                  <input className={`${selectCls} mt-2`} onChange={(event) => setDraftAtoms((current) => current.map((item) => item.id === atom.id ? { ...item, name: event.target.value } : item))} value={atom.name} />
                  <textarea className={`${textareaCls} mt-2 min-h-20`} onChange={(event) => setDraftAtoms((current) => current.map((item) => item.id === atom.id ? { ...item, description: event.target.value } : item))} value={atom.description} />
                  {atom.sceneOutline ? (
                    <details className="mt-2 rounded border border-ink-700 bg-ink-950/50 p-2">
                      <summary className="cursor-pointer text-2xs text-stone-400">编辑 Scene 摘要与完整流程</summary>
                      <div className="mt-2 grid gap-2">
                        {([
                          ["opening", "开场摘要"],
                          ["development", "主要发展"],
                          ["twist", "可选变化"],
                          ["climax", "完成 / 绕过条件"],
                          ["transition", "进入下一 Scene"],
                        ] as const).map(([key, label]) => (
                          <label className="text-2xs text-stone-500" key={key}>{label}
                            <input
                              className={`${inputCls} mt-1`}
                              onChange={(event) => setDraftAtoms((current) => current.map((item) => item.id === atom.id && item.sceneOutline ? { ...item, sceneOutline: { ...item.sceneOutline, [key]: event.target.value } } : item))}
                              value={atom.sceneOutline?.[key] ?? ""}
                            />
                          </label>
                        ))}
                        <label className="text-2xs text-stone-500">完整推进流程 · 每行一步
                          <textarea
                            className={`${textareaCls} mt-1 min-h-40`}
                            onChange={(event) => setDraftAtoms((current) => current.map((item) => item.id === atom.id && item.sceneOutline ? { ...item, sceneOutline: { ...item.sceneOutline, flow: event.target.value.split("\n").map((step) => step.trim()).filter(Boolean) } } : item))}
                            value={(atom.sceneOutline.flow ?? []).join("\n")}
                          />
                        </label>
                      </div>
                    </details>
                  ) : null}
                </label>
              ))}
            </div>
          </div>
        ) : null}
      </Panel> : null}
      {showEncounterTools ? <Panel className="mt-4" eyebrow="高级工具 · 玩家行动 → 具体战斗变化" title="遭遇后果草案">
        <div className="mb-3 flex flex-wrap gap-2">
          <Button disabled={!sceneId || !participants.data?.some((item) => item.entity_type === "monster" && item.role !== "defeated")} onClick={() => draftFromAssistant(-1)} size="sm" variant="ai">从副 DM 建议生成玩家优势草案</Button>
          <Button disabled={!sceneId || !participants.data?.some((item) => item.entity_type === "monster" && item.role !== "defeated")} onClick={() => draftFromAssistant(1)} size="sm" variant="ai">从副 DM 建议生成敌方优势草案</Button>
          <span className="self-center text-2xs text-stone-600">AI 只填草案；保存后仍需 DM 再次确认才会改变战斗。</span>
        </div>
        <div className="grid gap-2 lg:grid-cols-[1fr_1.5fr_10rem]">
          <input className={selectCls} onChange={(event) => setAdjustmentTitle(event.target.value)} placeholder="草案标题，例如：玩家提前破坏仪式" value={adjustmentTitle} />
          <input className={selectCls} onChange={(event) => setAdjustmentReason(event.target.value)} placeholder="触发原因与事实依据" value={adjustmentReason} />
          <select className={selectCls} onChange={(event) => setAdjustmentShift(Number(event.target.value) as -1 | 0 | 1)} value={adjustmentShift}>
            <option value={-1}>难度降低一级</option>
            <option value={0}>难度不变</option>
            <option value={1}>难度提高一级</option>
          </select>
        </div>
        <div className="mt-2 grid gap-2 md:grid-cols-[1fr_12rem_1fr_auto]">
          <select className={selectCls} onChange={(event) => setAdjustmentTarget(event.target.value)} value={adjustmentTarget}>
            <option value="">选择受影响原子</option>
            {candidates.map((candidate) => <option key={candidate.key} value={candidate.key}>{candidate.label}</option>)}
          </select>
          <select className={selectCls} onChange={(event) => setAdjustmentKind(event.target.value as EncounterOperation["kind"])} value={adjustmentKind}>
            <option value="set_entity_hp">调整当前 HP</option>
            <option value="add_entity_condition">添加具体状态</option>
            <option value="remove_entity">移出本次战斗</option>
            <option value="add_scene_entity">加入本次战斗</option>
            <option value="schedule_reinforcement">安排增援</option>
          </select>
          {adjustmentKind === "set_entity_hp" ? <input className={selectCls} min="0" onChange={(event) => setAdjustmentValue(event.target.value)} placeholder="目标 HP" type="number" value={adjustmentValue} /> : null}
          {adjustmentKind === "add_entity_condition" ? <input className={selectCls} onChange={(event) => setAdjustmentValue(event.target.value)} placeholder="状态，例如：无法召唤阴影" value={adjustmentValue} /> : null}
          {adjustmentKind === "schedule_reinforcement" ? <div className="grid grid-cols-2 gap-2"><input className={selectCls} min="1" onChange={(event) => setAdjustmentRound(event.target.value)} placeholder="轮次" type="number" value={adjustmentRound} /><input className={selectCls} min="1" onChange={(event) => setAdjustmentQuantity(event.target.value)} placeholder="数量" type="number" value={adjustmentQuantity} /></div> : null}
          {adjustmentKind === "remove_entity" || adjustmentKind === "add_scene_entity" ? <p className="m-0 self-center text-2xs text-stone-500">此操作只影响本次战斗实例，不删除原子。</p> : null}
          <Button disabled={!adjustmentTarget || draftOperations.length >= 8} onClick={addDraftOperation} size="sm">加入变化</Button>
        </div>
        {draftOperations.length > 0 ? (
          <div className="mt-3 rounded border border-ink-700 bg-ink-950/40 p-3">
            <div className="mb-2 flex items-center gap-2"><strong className="mr-auto text-xs text-parchment-100">待保存具体变化 · {draftOperations.length}/8</strong><Button disabled={!sceneId || !adjustmentTitle.trim() || !adjustmentReason.trim()} loading={createAdjustment.isPending} onClick={() => createAdjustment.mutate()} size="sm" variant="primary">保存为待确认草案</Button></div>
            <ol className="m-0 space-y-1.5 pl-5 text-xs text-stone-300">
              {draftOperations.map((operation, index) => <li key={`${operation.kind}-${operation.entity_id}-${index}`}><span>{describeEncounterOperation(operation, entityName(operation.entity_type, operation.entity_id))}</span><button className="ml-2 text-red-300 hover:text-red-200" onClick={() => setDraftOperations((current) => current.filter((_, itemIndex) => itemIndex !== index))} type="button">删除</button><span className="block text-2xs text-stone-600">原因：{operation.reason}</span></li>)}
            </ol>
          </div>
        ) : null}
        <div className="mt-4 grid gap-2 lg:grid-cols-2">
          {encounterAdjustments.data?.map((proposal) => (
            <article className="rounded border border-ink-700 bg-ink-950/50 p-3" key={proposal.id}>
              <div className="flex flex-wrap items-center gap-2">
                <strong className="mr-auto text-sm text-parchment-100">{proposal.title}</strong>
                <Badge tone={proposal.status === "applied" ? "ok" : proposal.status === "pending" ? "warn" : "neutral"}>{({ pending: "待确认", applied: "已应用", rejected: "已拒绝", reverted: "已撤销", conflict: "冲突" } as const)[proposal.status]}</Badge>
                <Badge>{difficultyShiftLabel(proposal.difficulty_shift)}</Badge>
              </div>
              <p className="mb-2 mt-2 text-xs text-stone-400">{proposal.reason}</p>
              <ul className="m-0 space-y-1 pl-4 text-xs text-stone-300">{proposal.operations_json.map((operation, index) => <li key={`${operation.kind}-${operation.entity_id}-${index}`}>{describeEncounterOperation(operation, entityName(operation.entity_type, operation.entity_id))}<span className="block text-2xs text-stone-600">{operation.reason}</span></li>)}</ul>
              <div className="mt-3 flex justify-end gap-2">
                {proposal.status === "pending" ? <Button disabled={changeAdjustment.isPending} onClick={() => changeAdjustment.mutate({ proposal, action: "reject" })} size="sm">拒绝</Button> : null}
                {proposal.status === "pending" ? <Button disabled={changeAdjustment.isPending} onClick={() => changeAdjustment.mutate({ proposal, action: "apply" })} size="sm" variant="primary">DM 确认应用</Button> : null}
                {proposal.status === "applied" ? <Button disabled={changeAdjustment.isPending} onClick={() => changeAdjustment.mutate({ proposal, action: "revert" })} size="sm">撤销后果</Button> : null}
              </div>
            </article>
          ))}
          {!encounterAdjustments.isLoading && encounterAdjustments.data?.length === 0 ? <EmptyState title="暂无遭遇后果草案" hint="记录玩家行动后，可让副 DM 生成草案，或手工添加具体变化。" /> : null}
        </div>
      </Panel> : null}
      {tableMode === "play" ? <div className="mt-4 grid gap-4 xl:h-[calc(100vh-10rem)] xl:grid-cols-[0.8fr_1.4fr_0.8fr] xl:overflow-hidden">
        <div className="space-y-4 xl:min-h-0 xl:overflow-y-auto xl:pr-1">
        <div id="scene-participant-workspace">
        <Panel eyebrow="情景状态" title="当前在场">
          <div className="flex gap-2"><select className={selectCls} onChange={(event) => setEntityKey(event.target.value)} value={entityKey}><option value="">选择进入人物</option>{availableCandidates.map((candidate) => <option key={candidate.key} value={candidate.key}>{candidate.label}</option>)}</select><Button disabled={!entityKey} loading={participantAdd.isPending} onClick={() => participantAdd.mutate()} size="sm">进入</Button></div>
          <div className="mt-2"><RestPanel campaignId={campaignId} characters={characters.data ?? []} compact defaultCharacterIds={(participants.data ?? []).filter((item) => item.entity_type === "character").map((item) => item.entity_id)} /></div>
          {participants.isLoading ? <LoadingBlock /> : null}
          {participants.data?.length === 0 ? <EmptyState title="当前场景无人" hint="从上方选择玩家、NPC 或怪物进入。" /> : null}
          <p className="mb-0 mt-3 text-2xs text-stone-600">点击任意卡片查看完整原子详情；这里负责把角色、NPC、怪物汇合到当前 Scene。</p>
          <ul className="m-0 mt-2 space-y-2 p-0">{participants.data?.map((participant) => <li className="list-none" key={participant.id}><div aria-label={`查看${participant.entity.name}详情`} className="w-full cursor-pointer rounded border border-ink-700 bg-ink-950/50 p-2 text-left transition hover:border-violet-600 hover:bg-ink-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400" onClick={() => setDetailParticipant(participant)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setDetailParticipant(participant); } }} role="button" tabIndex={0}><div className="flex items-center gap-2"><Badge tone={participant.entity_type === "character" ? "ok" : participant.entity_type === "npc" ? "ai" : "danger"}>{participant.entity_type === "character" ? "玩家" : participant.entity_type === "npc" ? "NPC" : "怪物"}</Badge>{participant.role === "defeated" ? <Badge>已击败</Badge> : null}<strong className="min-w-0 flex-1 truncate text-xs text-parchment-100">{participant.entity.name}</strong><Button loading={participantRemove.isPending} onClick={(event) => { event.stopPropagation(); participantRemove.mutate(participant); }} size="sm">离开</Button></div><div className="mt-2"><HpBar hp={participant.entity.hp} maxHp={participant.entity.max_hp} /></div><p className="mb-0 mt-1 text-2xs text-stone-600">AC {participant.entity.armor_class} · 速度 {participant.entity.speed} · 点击查看详情</p></div></li>)}</ul>
        </Panel>
        </div>
          <Panel eyebrow="已确认事实 · 不重复 AI 对话" title="Scene 状态摘要">
            <dl className="m-0 grid gap-2 text-xs">
              <div className="rounded border border-ink-800 bg-ink-950/40 p-2"><dt className="text-stone-600">当前目标</dt><dd className="m-0 mt-1 text-parchment-100">{activeOutline?.objective ?? "未填写"}</dd></div>
              <div className="rounded border border-ink-800 bg-ink-950/40 p-2"><dt className="text-stone-600">当前位置</dt><dd className="m-0 mt-1 text-parchment-100">{activeLocation?.name ?? "未绑定地点"}</dd></div>
              <div className="rounded border border-ink-800 bg-ink-950/40 p-2"><dt className="text-stone-600">当前流程</dt><dd className="m-0 mt-1 text-parchment-100">{currentFlowStep ? `${currentFlowStep.order}/${activeFlow.length} · ${currentFlowStep.title}` : "自由推进"}</dd></div>
            </dl>
            <div className="mt-3 rounded border border-ink-700 bg-ink-950/50 p-2">
              <p className="m-0 text-2xs text-stone-500">当前场景遭遇修正：<strong className={activeAdjustment < 0 ? "text-emerald-300" : activeAdjustment > 0 ? "text-red-300" : "text-stone-300"}>{activeAdjustment > 0 ? `提高 ${activeAdjustment} 级` : activeAdjustment < 0 ? `降低 ${Math.abs(activeAdjustment)} 级` : "无"}</strong></p>
              <div className="mt-2 grid gap-1.5"><Button disabled={!sceneId} onClick={() => draftFromAssistant(-1)} size="sm">起草玩家准备后果</Button><Button disabled={!sceneId} onClick={() => draftFromAssistant(1)} size="sm">起草敌方优势后果</Button></div>
            </div>
          </Panel>
        </div>
        <div className="xl:min-h-0 xl:overflow-y-auto xl:px-1">
        <DmSceneActionPanel
          campaignId={campaignId}
          characters={(characters.data ?? []).filter((character) => presentKeys.has(`character:${character.id}`))}
          gridData={sceneGrid.data}
        />
        <Panel eyebrow="自由推进 / 快速推进" title="游戏推进对话">
          {!sceneId ? <EmptyState title="先选择场景" hint="选择当前场景后，副 DM 才能读取正确的情景状态。" /> : null}
          <div className="max-h-[52vh] space-y-3 overflow-y-auto pr-1">
            {entries.map((entry) => <div className={`rounded-lg border px-3 py-2 ${entry.kind === "dm" ? "ml-10 border-ember-800/50 bg-ember-950/20" : entry.kind === "ai" ? "mr-10 border-violet-800/50 bg-violet-950/20" : "border-ink-700 bg-ink-950/50"}`} key={entry.id}><span className="block text-2xs text-stone-600">{assistantEntryLabel(entry.kind, entry.intent)}</span><p className="prose-block mb-0 mt-1 text-sm text-stone-300">{entry.kind === "ai" ? safeDndText(entry.text) : entry.text}</p></div>)}
            {liveAssistant ? (
              <div
                aria-busy={liveAssistant.status === "thinking"}
                aria-live="polite"
                className="mr-10 rounded-lg border border-violet-700/60 bg-violet-950/25 px-3 py-2 shadow-[0_0_24px_rgba(124,58,237,0.08)]"
                role="status"
              >
                <span className="block text-2xs text-violet-300">{assistantEntryLabel("ai", liveAssistant.intent)} · 实时生成</span>
                {liveAssistant.status === "thinking" ? (
                  <div className="mt-2 flex items-center gap-2 text-sm text-stone-300">
                    <span className="flex gap-1" aria-hidden="true">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-300" />
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-300 [animation-delay:150ms]" />
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-300 [animation-delay:300ms]" />
                    </span>
                    <span>{liveAssistant.label}……</span>
                  </div>
                ) : (
                  <p className="prose-block mb-0 mt-1 whitespace-pre-wrap text-sm text-stone-300">
                    {safeDndText(liveAssistant.text)}
                    <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-violet-300 align-text-bottom" aria-hidden="true" />
                  </p>
                )}
              </div>
            ) : null}
            {entries.length === 0 && sceneId && !liveAssistant ? <EmptyState title="等待游戏开始" hint="输入开场、玩家行动或现场变化，副 DM 会读取当前人物与场景后给出建议。" /> : null}
            <div ref={conversationEndRef} />
          </div>
          {suggestedSceneId && nextScene?.id === suggestedSceneId ? (
            <div className="mt-3 rounded-lg border-2 border-violet-600/60 bg-violet-950/20 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="ai">副 DM 转场建议</Badge>
                <strong className="mr-auto text-xs text-parchment-100">
                  当前进展可能已经适合进入「{nextScene.name}」
                </strong>
                <Button
                  onClick={() => enterScene(nextScene, "ai")}
                  size="sm"
                  variant="ai"
                >
                  接受并进入下一 Scene
                </Button>
                <Button onClick={() => setSuggestedSceneId(null)} size="sm">继续当前 Scene</Button>
              </div>
              <p className="mb-0 mt-2 text-2xs text-stone-500">
                这只是提示，不会自动跳转；DM确认后才会切换并生成进入描述。
              </p>
            </div>
          ) : null}
          <div className="mt-4 grid gap-2">{quickActions.map((action) => <Button disabled={!sceneId || assistant.isPending || Boolean(liveAssistant)} key={action} onClick={() => askAssistant(action)} size="sm">{action}</Button>)}</div>
          <form className="mt-3" onSubmit={(event: FormEvent) => { event.preventDefault(); askAssistant(input); }}><textarea aria-label="副 DM 输入" className={textareaCls} onChange={(event) => setInput(event.target.value)} placeholder="问建议、要一段可朗读文案，或记录已经发生的玩家行动……" value={input} /><div className="mt-2 flex flex-wrap justify-end gap-2"><Button disabled={!sceneId || !input.trim() || Boolean(liveAssistant)} loading={arrivalLookup.isPending || grantLookup.isPending} onClick={executeInput} type="button" variant="primary">执行并生成草案</Button><Button disabled={!sceneId || !input.trim() || Boolean(liveAssistant)} loading={assistant.isPending && assistant.variables?.intent === "advance"} onClick={() => recordProgressAndAsk(input)} type="button">记录为推进并询问</Button><Button disabled={!sceneId || !input.trim() || Boolean(liveAssistant)} loading={assistant.isPending && assistant.variables?.intent === "ask"} type="submit" variant="ai">只询问副 DM</Button></div><p className="mb-0 mt-2 text-2xs text-stone-600">“只询问”不会推进流程、同步玩家提示或触发转场；只有“记录为推进”代表事情已经发生。“执行”只生成待确认的实体、奖励或后果草案。</p></form>
          {assistant.isError ? <div className="mt-3"><ErrorState error={assistant.error} onRetry={retryAssistant} /></div> : null}
        </Panel>
        </div>
        <div className="space-y-4 xl:min-h-0 xl:overflow-y-auto xl:pl-1">
          <Panel eyebrow="完整流程 · 查看不会推进" title="DM 流程导航">
            <SceneOutlinePanel
              currentSceneId={sceneId}
              currentStepId={currentFlowStepId}
              entering={sceneTransitionNarration.isPending || flowStepNarration.isPending || Boolean(liveAssistant)}
              onAdvanceStep={enterFlowStep}
              onEnter={enterScene}
              onSkipStep={(target, step, nextStep) => skipFlowStep.mutate({ target, step, nextStep })}
              scenes={orderedScenes}
              skippedStepIds={skippedFlowStepIds}
              suggestedSceneId={suggestedSceneId}
            />
          </Panel>
          {arrivalLookup.isPending ? (
            <Panel eyebrow="动态原子 · 只读检索" title="正在查找合适的登场者">
              <LoadingBlock label="优先检索战役原子与本地 D&D 怪物图鉴…" />
            </Panel>
          ) : null}
          {grantLookup.isPending ? (
            <Panel eyebrow="玩家授予 · 只读检索" title="正在核对 D&D 5e 2024 规则">
              <LoadingBlock label="正在定位官方条目并校验职业、等级、环阶与既有角色数据…" />
            </Panel>
          ) : null}
          {grantDraft ? (
            <Panel eyebrow="玩家授予草案 · 等待 DM 确认" title={`${grantDraft.characterName} ← ${grantDraft.candidateName}`}>
              <div className="flex flex-wrap gap-2">
                <Badge tone={grantDraft.eligible ? "ok" : "warn"}>{grantDraft.eligible ? "规则校验通过" : "已阻止写入"}</Badge>
                <Badge tone="ai">D&D 5e · {grantDraft.edition}</Badge>
                <Badge>{grantDraft.kind === "spell" ? "法术" : grantDraft.kind === "class_feature" ? "职业特性" : grantDraft.kind === "skill_expertise" ? "技能专精" : grantDraft.kind === "skill_proficiency" ? "技能熟练" : grantDraft.kind === "item" ? "道具" : "装备"}</Badge>
                {grantDraft.quantity > 1 ? <Badge>数量 × {grantDraft.quantity}</Badge> : null}
              </div>
              <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                <div className="rounded border border-ink-800 bg-ink-950/40 p-2"><dt className="text-stone-600">目标角色</dt><dd className="m-0 mt-1 text-parchment-100">{grantDraft.characterName}</dd></div>
                <div className="rounded border border-ink-800 bg-ink-950/40 p-2"><dt className="text-stone-600">规则来源</dt><dd className="m-0 mt-1 text-parchment-100">{grantDraft.sourceLabel}</dd></div>
                {typeof grantDraft.metadata.unit_weight_lb === "number" ? <div className="rounded border border-ink-800 bg-ink-950/40 p-2"><dt className="text-stone-600">单位重量</dt><dd className="m-0 mt-1 text-parchment-100">{grantDraft.metadata.unit_weight_lb} 磅</dd></div> : null}
                {typeof grantDraft.metadata.price_cp === "number" ? <div className="rounded border border-ink-800 bg-ink-950/40 p-2"><dt className="text-stone-600">规则价格</dt><dd className="m-0 mt-1 text-parchment-100">{(grantDraft.metadata.price_cp / 100).toFixed(2)} GP</dd></div> : null}
              </dl>
              <p className={`rounded border p-2 text-xs leading-5 ${grantDraft.eligible ? "border-emerald-900/60 bg-emerald-950/15 text-emerald-100" : "border-red-900/70 bg-red-950/20 text-red-200"}`}>
                {grantDraft.blockingReason ?? grantDraft.ruleReason}
              </p>
              {grantDraft.description ? <details className="rounded border border-ink-800 p-2 text-xs text-stone-400"><summary className="cursor-pointer text-parchment-100">查看规则摘录与限制</summary><p className="mb-0 whitespace-pre-wrap leading-5">{grantDraft.description}</p></details> : null}
              {grantDraft.canonicalUrl ? <a className="mt-2 block text-2xs text-ember-300 hover:text-ember-200" href={grantDraft.canonicalUrl} rel="noreferrer" target="_blank">打开本地条目对应来源</a> : null}
              <p className="mb-0 mt-2 text-2xs text-stone-600">模型不能改写来源、职业、环阶、价格或重量；确认后才会原子化写入角色，并公开同步到玩家日志。</p>
              <div className="mt-3 flex justify-end gap-2">
                <Button disabled={grantConfirm.isPending} onClick={() => setGrantDraft(null)} size="sm">放弃草案</Button>
                <Button disabled={!grantDraft.eligible} loading={grantConfirm.isPending} onClick={() => grantConfirm.mutate()} size="sm" variant="primary">DM 确认授予</Button>
              </div>
            </Panel>
          ) : null}
          {arrivalDraft ? (
            <Panel eyebrow="动态原子 · 等待 DM 确认" title={arrivalDraft.kind === "monster" ? "怪物进入场景草案" : "NPC 进入场景草案"}>
              <p className="mt-0 text-xs leading-5 text-stone-500">副 DM 只起草并检索，不会自动写入。核对来源与数值后，点击底部确认才会创建原子并加入当前场景。</p>
              {arrivalDraft.kind === "monster" ? (
                <div className="mb-3 space-y-2">
                  {arrivalReferences.map((reference) => (
                    <label className={`block cursor-pointer rounded border p-2 text-xs ${arrivalDraft.sourceKey === reference.key ? "border-ember-600/70 bg-ember-950/20" : "border-ink-700 bg-ink-950/40"}`} key={reference.key}>
                      <span className="flex items-center gap-2">
                        <input checked={arrivalDraft.sourceKey === reference.key} name="arrival-source" onChange={() => chooseArrivalReference(reference.key)} type="radio" />
                        <strong className="text-parchment-100">{reference.label}</strong>
                        <Badge tone={reference.origin === "compendium" ? "ok" : "ai"}>{reference.origin === "compendium" ? "本地图鉴" : "已有原子"}</Badge>
                      </span>
                      <span className="mt-1 block text-stone-500">{reference.sourceLabel}</span>
                      <span className="mt-1 block text-stone-600">{reference.matchReason}</span>
                    </label>
                  ))}
                  <label className={`block cursor-pointer rounded border p-2 text-xs ${arrivalDraft.sourceKey === "custom" ? "border-amber-700/70 bg-amber-950/20" : "border-ink-700 bg-ink-950/40"}`}>
                    <span className="flex items-center gap-2"><input checked={arrivalDraft.sourceKey === "custom"} name="arrival-source" onChange={() => chooseArrivalReference("custom")} type="radio" /><strong className="text-parchment-100">使用自制模板</strong><Badge tone="warn">非图鉴</Badge></span>
                    <span className="mt-1 block text-stone-600">保留自定义名称和设定，同时可以绑定一个真实 D&D 怪物作为 AC、HP、属性与动作模板。</span>
                  </label>
                  {arrivalDraft.sourceKey === "custom" ? (
                    <label className="block rounded border border-amber-900/50 bg-ink-950/50 p-2 text-2xs text-stone-400">
                      绑定规则模板
                      <select
                        aria-label="自制怪物规则模板"
                        className={`${selectCls} mt-1`}
                        onChange={(event) => chooseCustomTemplate(event.target.value)}
                        value={arrivalDraft.templateSourceKey ?? ""}
                      >
                        <option value="">不绑定（DM自行填写数值和动作）</option>
                        {arrivalReferences.map((reference) => (
                          <option key={`template-${reference.key}`} value={reference.key}>
                            {reference.label} · {reference.origin === "compendium" ? "本地图鉴" : "已有原子"}
                          </option>
                        ))}
                      </select>
                      <span className="mt-1 block">
                        {arrivalDraft.templateSourceKey
                          ? `已绑定模板；将继承 ${arrivalDraft.actions.length} 个动作，但数据库中仍保存为“${arrivalDraft.name}”这个自制怪物。`
                          : "未绑定时只会使用临时基础攻击。"}
                      </span>
                    </label>
                  ) : null}
                </div>
              ) : (
                <div className="mb-3 flex flex-wrap gap-2"><Badge tone="ai">AI 可编辑草案</Badge><span className="text-2xs text-stone-600">NPC 不会在确认前进入数据库。</span></div>
              )}
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="text-2xs text-stone-500 sm:col-span-2">名称<input className={`${inputCls} mt-1`} onChange={(event) => setArrivalDraft((current) => current ? { ...current, name: event.target.value } : current)} value={arrivalDraft.name} /></label>
                <label className="text-2xs text-stone-500">AC<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setArrivalDraft((current) => current ? { ...current, armorClass: Number(event.target.value) } : current)} type="number" value={arrivalDraft.armorClass} /></label>
                <label className="text-2xs text-stone-500">生命值<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setArrivalDraft((current) => current ? { ...current, hp: Number(event.target.value) } : current)} type="number" value={arrivalDraft.hp} /></label>
                <label className="text-2xs text-stone-500">速度（尺）<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setArrivalDraft((current) => current ? { ...current, speed: Number(event.target.value) } : current)} type="number" value={arrivalDraft.speed} /></label>
                <label className="text-2xs text-stone-500">CR<input className={`${inputCls} mt-1`} onChange={(event) => setArrivalDraft((current) => current ? { ...current, challengeRating: event.target.value } : current)} value={arrivalDraft.challengeRating} /></label>
                <label className="text-2xs text-stone-500 sm:col-span-2">登场说明<textarea className={`${textareaCls} mt-1`} onChange={(event) => setArrivalDraft((current) => current ? { ...current, description: event.target.value } : current)} value={arrivalDraft.description} /></label>
              </div>
              {selectedArrivalReference?.origin === "compendium" ? (
                <a className="mt-2 block text-2xs text-ember-300 hover:text-ember-200" href={selectedArrivalReference.hit.chunk.canonical_url} rel="noreferrer" target="_blank">查看图鉴来源：{selectedArrivalReference.sourceLabel}</a>
              ) : null}
              <label className="mt-3 flex items-center gap-2 text-xs text-stone-300"><input checked={startCombatAfterArrival} onChange={(event) => setStartCombatAfterArrival(event.target.checked)} type="checkbox" />确认加入后立即用当前场景发起战斗</label>
              <div className="mt-3 flex justify-end gap-2">
                <Button disabled={arrivalConfirm.isPending} onClick={() => { setArrivalDraft(null); setArrivalReferences([]); }} size="sm">放弃草案</Button>
                <Button disabled={!arrivalDraft.name.trim() || arrivalDraft.hp < 1 || !sceneId} loading={arrivalConfirm.isPending} onClick={() => arrivalConfirm.mutate()} size="sm" variant="primary">DM 确认创建并加入</Button>
              </div>
            </Panel>
          ) : null}
          <Panel eyebrow="进入 / 离开 / 推进" title="最近情景记录">
            {recentEvents.length === 0 ? <p className="m-0 text-xs text-stone-600">还没有当前场景记录。</p> : <ul className="m-0 space-y-2 p-0">{recentEvents.map((event) => <li className="list-none border-b border-ink-800 pb-2 text-xs last:border-0" key={event.id}><strong className="block text-parchment-100">{event.title}</strong><span className="text-stone-600">{event.metadata_json.entry_kind === "ai" ? safeDndText(event.description) : event.description}</span></li>)}</ul>}
          </Panel>
          <Panel eyebrow="服务端权威快照 · HP / 资源 / 战斗 / 场景" title="场次检查点">
            <Button disabled={!sceneId} loading={saveCheckpoint.isPending} onClick={() => saveCheckpoint.mutate()} size="sm" variant="primary">保存当前检查点</Button>
            <ul className="m-0 mt-3 space-y-2 p-0">
              {(checkpoints.data ?? []).filter((checkpoint) => checkpoint.scene_id === sceneId).slice(0, 5).map((checkpoint) => <li className="flex list-none items-center gap-2 text-xs" key={checkpoint.id}><span className="min-w-0 flex-1 truncate text-stone-500">{checkpoint.name}</span><Button loading={previewCheckpointRestore.isPending} onClick={() => previewCheckpointRestore.mutate(checkpoint)} size="sm">预览恢复</Button></li>)}
            </ul>
            {checkpointPreview ? <div className="mt-3 rounded border border-amber-500/30 bg-ink-900 p-3 text-xs text-stone-300"><strong className="text-amber-200">恢复预览 · {checkpointPreview.checkpoint.name}</strong><p className="mb-2 mt-1">将恢复 {summaryCount(checkpointPreview.preview.change_summary.character_count)} 名角色、{summaryCount(checkpointPreview.preview.change_summary.npc_count)} 名 NPC、{summaryCount(checkpointPreview.preview.change_summary.monster_count)} 只怪物及关联战斗状态。</p>{checkpointPreview.preview.conflicts.length ? <p className="text-red-300">发现 {checkpointPreview.preview.conflicts.length} 个版本或依赖冲突，已阻止直接恢复。</p> : null}<div className="flex gap-2"><Button onClick={() => setCheckpointPreview(null)} size="sm">取消</Button><Button disabled={!checkpointPreview.preview.can_restore} loading={restoreCheckpoint.isPending} onClick={() => restoreCheckpoint.mutate()} size="sm" variant="primary">DM 确认事务恢复</Button></div></div> : null}
            {!(checkpoints.data ?? []).some((checkpoint) => checkpoint.scene_id === sceneId) ? <p className="mb-0 mt-2 text-2xs text-stone-600">尚无当前场景的服务端检查点。</p> : null}
            {legacyCheckpointCount > 0 ? <p className="mb-0 mt-2 text-2xs text-stone-600">检测到 {legacyCheckpointCount} 个旧版本地界面检查点；它们不包含 HP、资源和战斗事实，因此不会冒充可恢复存档。</p> : null}
          </Panel>
        </div>
      </div> : null}
      {detailParticipant?.entity_type === "character" ? <CharacterSheetDetail campaignId={campaignId} character={detailParticipant.entity as Character} onClose={() => setDetailParticipant(null)} /> : null}
      {detailParticipant?.entity_type === "npc" || detailParticipant?.entity_type === "monster" ? <SceneEntityDetailDialog entity={detailParticipant.entity as Npc | Monster} entityType={detailParticipant.entity_type} onClose={() => setDetailParticipant(null)} /> : null}
    </div>
  );
}

export function GameTablePage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <GameTableContent campaignId={campaignId} />}</RequireCampaign>;
}
