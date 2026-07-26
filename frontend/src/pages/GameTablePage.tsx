import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent, type ReactElement } from "react";

import { runAssistantTurn } from "../api/assistant";
import {
  applyEncounterAdjustment, createClue, createEncounterAdjustment, createEvent, createNpc,
  createQuest, listCharacters, listEncounterAdjustments, listEvents, listLocations, listNpcs,
  rejectEncounterAdjustment, revertEncounterAdjustment,
} from "../api/entities";
import type {
  AgentResponse, EncounterAdjustment, EncounterOperation, SceneParticipant,
} from "../api/types";
import {
  addSceneParticipant, createMonster, createScene, createWorldItem,
  listMonsters, listSceneParticipants, listScenes,
  removeSceneParticipant, startSceneCombat,
} from "../api/world";
import { Panel } from "../components/Panel";
import { RestPanel } from "../components/RestPanel";
import { RequireCampaign } from "../components/RequireCampaign";
import { useToast } from "../hooks/toastContext";
import { navigate } from "../hooks/useHashRoute";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { selectCls, textareaCls } from "../ui/styles";
import { HpBar } from "../ui/widgets";
import { parsePrepDraft, type DraftAtom } from "../ui/prepDraft";
import {
  describeEncounterOperation, difficultyShiftLabel,
} from "../ui/encounterAdjustments";

type ProgressEntry = {
  id: string;
  kind: "dm" | "ai" | "system";
  text: string;
  createdAt: string;
};

type SessionCheckpoint = {
  id: string;
  label: string;
  createdAt: string;
  sceneId: string;
  entries: ProgressEntry[];
  participantKeys: string[];
};

function storageKey(campaignId: string, sceneId: string): string {
  return `dnd-game-table:${campaignId}:${sceneId}`;
}

function loadEntries(campaignId: string, sceneId: string): ProgressEntry[] {
  if (!sceneId) return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(campaignId, sceneId)) ?? "[]") as unknown;
    return Array.isArray(parsed) ? parsed as ProgressEntry[] : [];
  } catch {
    return [];
  }
}

function checkpointKey(campaignId: string): string {
  return `dnd-game-checkpoints:${campaignId}`;
}

function loadCheckpoints(campaignId: string): SessionCheckpoint[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(checkpointKey(campaignId)) ?? "[]") as unknown;
    return Array.isArray(parsed) ? parsed as SessionCheckpoint[] : [];
  } catch {
    return [];
  }
}

function draftSceneGrid(name: string, description: string): string {
  const church = /教堂|神殿|祭坛|神祇/.test(`${name} ${description}`);
  const cells: { row: number; col: number; kind: "wall" | "cover" | "door" | "object"; label: string }[] = [];
  for (let col = 1; col <= 12; col += 1) cells.push({ row: 1, col, kind: "wall", label: "墙" }, { row: 8, col, kind: "wall", label: "墙" });
  for (let row = 2; row <= 7; row += 1) cells.push({ row, col: 1, kind: "wall", label: "墙" }, { row, col: 12, kind: "wall", label: "墙" });
  cells.push({ row: 8, col: 6, kind: "door", label: "入口" });
  if (church) cells.push({ row: 2, col: 6, kind: "object", label: "祭坛" }, { row: 4, col: 4, kind: "cover", label: "长椅" }, { row: 4, col: 9, kind: "cover", label: "长椅" });
  else cells.push({ row: 3, col: 7, kind: "cover", label: "掩体" }, { row: 5, col: 10, kind: "object", label: "可互动物" });
  return JSON.stringify({ scene_grid: { width: 12, height: 8, cell_size_ft: 5, theme: church ? "旧教堂" : name, cells } });
}

function GameTableContent({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [sceneId, setSceneId] = useState("");
  const [entityKey, setEntityKey] = useState("");
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState<ProgressEntry[]>([]);
  const [lastResponse, setLastResponse] = useState<AgentResponse | null>(null);
  const [checkpoints, setCheckpoints] = useState<SessionCheckpoint[]>(() => loadCheckpoints(campaignId));
  const [prepBrief, setPrepBrief] = useState("");
  const [prepDraft, setPrepDraft] = useState("");
  const [draftAtoms, setDraftAtoms] = useState<DraftAtom[]>([]);
  const [selectedAtoms, setSelectedAtoms] = useState<Set<string>>(new Set());
  const [adjustmentTitle, setAdjustmentTitle] = useState("");
  const [adjustmentReason, setAdjustmentReason] = useState("");
  const [adjustmentShift, setAdjustmentShift] = useState<-1 | 0 | 1>(0);
  const [adjustmentTarget, setAdjustmentTarget] = useState("");
  const [adjustmentKind, setAdjustmentKind] = useState<EncounterOperation["kind"]>("set_entity_hp");
  const [adjustmentValue, setAdjustmentValue] = useState("");
  const [adjustmentRound, setAdjustmentRound] = useState("3");
  const [adjustmentQuantity, setAdjustmentQuantity] = useState("1");
  const [draftOperations, setDraftOperations] = useState<EncounterOperation[]>([]);
  const scenes = useQuery({ queryKey: ["scenes", campaignId], queryFn: ({ signal }) => listScenes(campaignId, signal) });
  const locations = useQuery({ queryKey: ["locations", campaignId], queryFn: ({ signal }) => listLocations(campaignId, signal) });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const npcs = useQuery({ queryKey: ["npcs", campaignId], queryFn: ({ signal }) => listNpcs(campaignId, signal) });
  const monsters = useQuery({ queryKey: ["monsters", campaignId], queryFn: ({ signal }) => listMonsters(campaignId, signal) });
  const events = useQuery({ queryKey: ["events", campaignId], queryFn: ({ signal }) => listEvents(campaignId, signal) });
  const participants = useQuery({
    queryKey: ["scene-participants", campaignId, sceneId],
    queryFn: ({ signal }) => listSceneParticipants(campaignId, sceneId, signal),
    enabled: Boolean(sceneId),
  });
  const encounterAdjustments = useQuery({
    queryKey: ["encounter-adjustments", campaignId, sceneId],
    queryFn: ({ signal }) => listEncounterAdjustments(campaignId, sceneId, signal),
    enabled: Boolean(sceneId),
  });
  useEffect(() => {
    if (!sceneId && scenes.data?.[0]) setSceneId(scenes.data[0].id);
  }, [sceneId, scenes.data]);
  useEffect(() => {
    setEntries(loadEntries(campaignId, sceneId));
    setLastResponse(null);
  }, [campaignId, sceneId]);
  useEffect(() => {
    if (sceneId) localStorage.setItem(storageKey(campaignId, sceneId), JSON.stringify(entries));
  }, [campaignId, entries, sceneId]);
  useEffect(() => {
    if (!sceneId || entries.length > 0 || !events.data) return;
    const restored = events.data
      .filter((event) => event.metadata_json.scene_id === sceneId && event.metadata_json.game_table === true)
      .map((event): ProgressEntry => ({
        id: `event:${event.id}`,
        kind: event.metadata_json.entry_kind === "dm" ? "dm" : event.metadata_json.entry_kind === "ai" ? "ai" : "system",
        text: event.description ?? event.title,
        createdAt: event.occurred_at,
      }));
    if (restored.length > 0) setEntries(restored);
  }, [entries.length, events.data, sceneId]);
  useEffect(() => {
    localStorage.setItem(checkpointKey(campaignId), JSON.stringify(checkpoints.slice(-20)));
  }, [campaignId, checkpoints]);
  const activeScene = scenes.data?.find((scene) => scene.id === sceneId);
  const activeLocation = locations.data?.find((location) => location.id === activeScene?.location_id);
  const candidates = useMemo(() => [
    ...(characters.data ?? []).map((entity) => ({ key: `character:${entity.id}`, label: `玩家 · ${entity.name}` })),
    ...(npcs.data ?? []).map((entity) => ({ key: `npc:${entity.id}`, label: `NPC · ${entity.name}` })),
    ...(monsters.data ?? []).map((entity) => ({ key: `monster:${entity.id}`, label: `怪物 · ${entity.name}` })),
  ], [characters.data, monsters.data, npcs.data]);
  const presentKeys = new Set((participants.data ?? []).map((item) => `${item.entity_type}:${item.entity_id}`));
  const availableCandidates = candidates.filter((candidate) => !presentKeys.has(candidate.key));
  const entityName = (entityType: string, entityId: string) =>
    candidates.find((candidate) => candidate.key === `${entityType}:${entityId}`)?.label.replace(/^.+ · /, "")
    ?? entityId;
  const quickActions = useMemo(() => {
    const npc = participants.data?.find((item) => item.entity_type === "npc");
    const monster = participants.data?.find((item) => item.entity_type === "monster");
    return [
      npc ? `推进与 ${npc.entity.name} 的对话，根据其目标、态度和秘密给出具体反应` : "让一名与当前剧情相关的 NPC 进入场景并说明来意",
      `推进对“${activeScene?.name ?? "当前场景"}”的探索，给出检定、DC、线索和可互动内容`,
      monster ? `根据 ${monster.entity.name} 的存在制造紧张升级，并判断是否应该进入战斗` : "制造具体局势变化：人物进入、离开、暴露秘密或出现新的威胁",
    ];
  }, [activeScene?.name, participants.data]);
  const log = async (title: string, description: string, metadata: Record<string, unknown> = {}) => {
    await createEvent(campaignId, {
      title, description, event_type: "session_progress", visibility: "dm",
      location_id: activeScene?.location_id ?? null,
      metadata_json: { scene_id: sceneId, game_table: true, ...metadata },
    });
    await client.invalidateQueries({ queryKey: ["events", campaignId] });
  };
  const addEntry = (kind: ProgressEntry["kind"], text: string) => {
    setEntries((current) => [...current, { id: crypto.randomUUID(), kind, text, createdAt: new Date().toISOString() }]);
  };
  const assistant = useMutation({
    mutationFn: async (action: string) => {
      const names = (participants.data ?? []).map((item) => `${item.entity_type}:${item.entity.name}`).join("、") || "无人";
      const context = `你是副DM。当前场景：${activeScene?.name ?? "未选择"}。地点：${activeLocation?.name ?? "未绑定"}。当前在场：${names}。最近推进：${entries.slice(-5).map((entry) => entry.text).join("；")}。DM输入：${action}。请给DM私密推进建议、NPC可能反应、下一步引导和风险；不要擅自改数据库。`;
      return runAssistantTurn(campaignId, context);
    },
    onSuccess: async (response, action) => {
      const text = response.dm_hint?.text || (response.abstained ? "AI 暂时无法给出可靠建议，请由 DM 自由推进。" : "已读取当前战役状态，但没有生成新的提示。");
      setLastResponse(response);
      addEntry("ai", text);
      await log("AI 推进建议", text, { dm_action: action, entry_kind: "ai" });
    },
    onError: () => showToast("副 DM 暂时没有响应，请检查本地模型", "error"),
  });
  const advance = (action: string) => {
    if (!action.trim() || !sceneId || assistant.isPending) return;
    addEntry("dm", action.trim());
    void log("DM 推进", action.trim(), { entry_kind: "dm" });
    assistant.mutate(action.trim());
    setInput("");
  };
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
    mutationFn: () => startSceneCombat(campaignId, sceneId),
    onSuccess: () => {
      void log("进入战斗", `“${activeScene?.name ?? "当前场景"}”进入战斗，已加载当前人物与场景网格。`);
      void client.invalidateQueries({ queryKey: ["combats", campaignId] });
      navigate("/combat");
    },
    onError: () => showToast("无法发起战斗，请确认当前场景里至少有一名参与者", "error"),
  });
  const prep = useMutation({
    mutationFn: () => runAssistantTurn(campaignId, `你是D&D 5e 2024备团副DM。根据冒险描述生成可审核草稿。必须严格使用以下Markdown结构，每条使用“名称｜描述”，不要省略标题：\n## 场景\n- 名称｜描述\n## NPC\n- 名称｜描述\n## 怪物\n- 名称｜描述\n## 任务\n- 名称｜描述\n## 线索\n- 名称｜描述\n## 物品\n- 名称｜描述\n最后可以补充“## DM建议”，但不要直接修改数据库。\n冒险描述：${prepBrief}`),
    onSuccess: (response) => {
      const text = response.dm_hint?.text ?? "模型没有生成完整草稿，请补充冒险目标、玩家等级和预计时长。";
      setPrepDraft(text);
      const parsed = parsePrepDraft(text);
      setDraftAtoms(parsed);
      setSelectedAtoms(new Set(parsed.map((atom) => atom.id)));
      showToast("备团草稿已生成");
    },
    onError: () => showToast("备团草稿生成失败", "error"),
  });
  const parseDraft = () => {
    const parsed = parsePrepDraft(prepDraft);
    setDraftAtoms(parsed);
    setSelectedAtoms(new Set(parsed.map((atom) => atom.id)));
    showToast(parsed.length > 0 ? `已解析 ${parsed.length} 个可导入原子` : "没有识别到结构化条目，请按“名称｜描述”格式调整草稿", parsed.length > 0 ? "success" : "error");
  };
  const importDraft = useMutation({
    mutationFn: async () => {
      const selected = draftAtoms.filter((atom) => selectedAtoms.has(atom.id));
      for (const atom of selected) {
        if (atom.kind === "scene") await createScene(campaignId, { name: atom.name, description: atom.description, notes: draftSceneGrid(atom.name, atom.description) });
        if (atom.kind === "npc") await createNpc(campaignId, { name: atom.name, description: atom.description, armor_class: 10, hp: 10, max_hp: 10, speed: 30, ability_scores: { strength: 10, dexterity: 10, constitution: 10, intelligence: 10, wisdom: 10, charisma: 10 } });
        if (atom.kind === "monster") await createMonster(campaignId, { name: atom.name, notes: atom.description, armor_class: 12, hp: 8, max_hp: 8, speed: 30, ability_scores: { strength: 10, dexterity: 10, constitution: 10, intelligence: 8, wisdom: 10, charisma: 8 } });
        if (atom.kind === "quest") await createQuest(campaignId, { name: atom.name, description: atom.description, quest_type: "side", status: "open" });
        if (atom.kind === "clue") await createClue(campaignId, { name: atom.name, description: atom.description, player_text: atom.description, verified: false, discovered: false });
        if (atom.kind === "item") await createWorldItem(campaignId, { name: atom.name, description: atom.description, category: "adventure", quantity: 1, unit_weight_lb: 0, price_cp: 0, source_label: "ai_generated" });
      }
      return selected.length;
    },
    onSuccess: (count) => {
      for (const key of ["scenes", "npcs", "monsters", "quests", "clues", "world-items"]) void client.invalidateQueries({ queryKey: [key, campaignId] });
      showToast(`已确认导入 ${count} 个备团原子`);
      void log("导入备团草稿", `从备团草稿导入了 ${count} 个场景、人物、任务或物品原子。`, { entry_kind: "system" });
    },
    onError: () => showToast("备团导入失败；已成功写入的条目会保留，请检查是否存在同名或无效数据", "error"),
  });
  const saveCheckpoint = () => {
    if (!sceneId) return;
    const checkpoint: SessionCheckpoint = {
      id: crypto.randomUUID(), label: `${activeScene?.name ?? "场景"} · ${new Date().toLocaleTimeString()}`,
      createdAt: new Date().toISOString(), sceneId, entries,
      participantKeys: (participants.data ?? []).map((item) => `${item.entity_type}:${item.entity_id}`),
    };
    setCheckpoints((current) => [...current, checkpoint].slice(-20));
    showToast("场次检查点已保存");
  };
  const restoreCheckpoint = useMutation({
    mutationFn: async (checkpoint: SessionCheckpoint) => {
      if (checkpoint.sceneId !== sceneId) throw new Error("请先切换到检查点所属场景");
      const current = participants.data ?? [];
      const target = new Set(checkpoint.participantKeys);
      await Promise.all(current.filter((item) => !target.has(`${item.entity_type}:${item.entity_id}`)).map((item) => removeSceneParticipant(campaignId, sceneId, item.id, item.version)));
      const currentKeys = new Set(current.map((item) => `${item.entity_type}:${item.entity_id}`));
      await Promise.all(checkpoint.participantKeys.filter((key) => !currentKeys.has(key)).map((key) => {
        const [entityType, entityId] = key.split(":");
        if (!entityType || !entityId) throw new Error("检查点人物数据无效");
        return addSceneParticipant(campaignId, checkpoint.sceneId, { entity_type: entityType as "character" | "npc" | "monster", entity_id: entityId });
      }));
      setEntries(checkpoint.entries);
      await log("恢复场次检查点", `已恢复到检查点“${checkpoint.label}”。`, { entry_kind: "system", checkpoint_id: checkpoint.id });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["scene-participants", campaignId] });
      showToast("检查点已恢复");
    },
    onError: () => showToast("恢复检查点失败", "error"),
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
    const monster = participants.data?.find((item) => item.entity_type === "monster");
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
  return (
    <div className="mx-auto max-w-[1500px] p-4 lg:p-6">
      <Panel eyebrow="副 DM · 实时场次" title="游戏推进台">
        <div className="grid gap-3 lg:grid-cols-[1fr_auto]">
          <select className={selectCls} onChange={(event) => setSceneId(event.target.value)} value={sceneId}><option value="">选择当前场景</option>{scenes.data?.map((scene) => <option key={scene.id} value={scene.id}>{scene.name}</option>)}</select>
          <Button disabled={!sceneId || !participants.data?.length} loading={combat.isPending} onClick={() => combat.mutate()} variant="danger" icon="sword">当前场景发起战斗</Button>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">当前场景</span><strong className="text-xs text-parchment-100">{activeScene?.name ?? "未选择"}</strong></div>
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">地点</span><strong className="text-xs text-parchment-100">{activeLocation?.name ?? "未绑定"}</strong></div>
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">玩家</span><strong className="text-xs text-emerald-300">{participants.data?.filter((item) => item.entity_type === "character").length ?? 0}</strong></div>
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">NPC</span><strong className="text-xs text-violet-300">{participants.data?.filter((item) => item.entity_type === "npc").length ?? 0}</strong></div>
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">怪物</span><strong className="text-xs text-red-300">{participants.data?.filter((item) => item.entity_type === "monster").length ?? 0}</strong></div>
        </div>
      </Panel>
      <Panel className="mt-4" eyebrow="开团前准备" title="备团草稿">
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
            <div className="mb-3 flex flex-wrap items-center gap-2"><strong className="mr-auto text-sm text-parchment-100">结构化导入预览 · 已选 {selectedAtoms.size}/{draftAtoms.length}</strong><Button onClick={() => setSelectedAtoms(new Set(draftAtoms.map((atom) => atom.id)))} size="sm">全选</Button><Button onClick={() => setSelectedAtoms(new Set())} size="sm">清空</Button><Button disabled={selectedAtoms.size === 0} loading={importDraft.isPending} onClick={() => importDraft.mutate()} variant="primary">确认导入所选内容</Button></div>
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {draftAtoms.map((atom) => (
                <label className={`rounded border p-3 ${selectedAtoms.has(atom.id) ? "border-ember-700/60 bg-ember-950/10" : "border-ink-700 bg-ink-950/40 opacity-60"}`} key={atom.id}>
                  <div className="flex items-center gap-2"><input checked={selectedAtoms.has(atom.id)} onChange={(event) => setSelectedAtoms((current) => { const next = new Set(current); if (event.target.checked) next.add(atom.id); else next.delete(atom.id); return next; })} type="checkbox" /><Badge>{({ scene: "场景", npc: "NPC", monster: "怪物", quest: "任务", clue: "线索", item: "物品" } as const)[atom.kind]}</Badge></div>
                  <input className={`${selectCls} mt-2`} onChange={(event) => setDraftAtoms((current) => current.map((item) => item.id === atom.id ? { ...item, name: event.target.value } : item))} value={atom.name} />
                  <textarea className={`${textareaCls} mt-2 min-h-20`} onChange={(event) => setDraftAtoms((current) => current.map((item) => item.id === atom.id ? { ...item, description: event.target.value } : item))} value={atom.description} />
                </label>
              ))}
            </div>
          </div>
        ) : null}
      </Panel>
      <Panel className="mt-4" eyebrow="玩家行动 → 具体战斗变化" title="遭遇后果草案">
        <div className="mb-3 flex flex-wrap gap-2">
          <Button disabled={!sceneId || !participants.data?.some((item) => item.entity_type === "monster")} onClick={() => draftFromAssistant(-1)} size="sm" variant="ai">从副 DM 建议生成玩家优势草案</Button>
          <Button disabled={!sceneId || !participants.data?.some((item) => item.entity_type === "monster")} onClick={() => draftFromAssistant(1)} size="sm" variant="ai">从副 DM 建议生成敌方优势草案</Button>
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
      </Panel>
      <div className="mt-4 grid gap-4 xl:grid-cols-[0.8fr_1.4fr_0.8fr]">
        <Panel eyebrow="情景状态" title="当前在场">
          <div className="flex gap-2"><select className={selectCls} onChange={(event) => setEntityKey(event.target.value)} value={entityKey}><option value="">选择进入人物</option>{availableCandidates.map((candidate) => <option key={candidate.key} value={candidate.key}>{candidate.label}</option>)}</select><Button disabled={!entityKey} loading={participantAdd.isPending} onClick={() => participantAdd.mutate()} size="sm">进入</Button></div>
          <div className="mt-2"><RestPanel campaignId={campaignId} characters={characters.data ?? []} compact defaultCharacterIds={(participants.data ?? []).filter((item) => item.entity_type === "character").map((item) => item.entity_id)} /></div>
          {participants.isLoading ? <LoadingBlock /> : null}
          {participants.data?.length === 0 ? <EmptyState title="当前场景无人" hint="从上方选择玩家、NPC 或怪物进入。" /> : null}
          <ul className="m-0 mt-3 space-y-2 p-0">{participants.data?.map((participant) => <li className="list-none rounded border border-ink-700 bg-ink-950/50 p-2" key={participant.id}><div className="flex items-center gap-2"><Badge tone={participant.entity_type === "character" ? "ok" : participant.entity_type === "npc" ? "ai" : "danger"}>{participant.entity_type === "character" ? "玩家" : participant.entity_type === "npc" ? "NPC" : "怪物"}</Badge><strong className="min-w-0 flex-1 truncate text-xs text-parchment-100">{participant.entity.name}</strong><Button loading={participantRemove.isPending} onClick={() => participantRemove.mutate(participant)} size="sm">离开</Button></div><div className="mt-2"><HpBar hp={participant.entity.hp} maxHp={participant.entity.max_hp} /></div><p className="mb-0 mt-1 text-2xs text-stone-600">AC {participant.entity.armor_class} · 速度 {participant.entity.speed}</p></li>)}</ul>
        </Panel>
        <Panel eyebrow="自由推进 / 快速推进" title="游戏推进对话">
          {!sceneId ? <EmptyState title="先选择场景" hint="选择当前场景后，副 DM 才能读取正确的情景状态。" /> : null}
          <div className="max-h-[52vh] space-y-3 overflow-y-auto pr-1">
            {entries.map((entry) => <div className={`rounded-lg border px-3 py-2 ${entry.kind === "dm" ? "ml-10 border-ember-800/50 bg-ember-950/20" : entry.kind === "ai" ? "mr-10 border-violet-800/50 bg-violet-950/20" : "border-ink-700 bg-ink-950/50"}`} key={entry.id}><span className="block text-2xs text-stone-600">{entry.kind === "dm" ? "DM 推进" : entry.kind === "ai" ? "副 DM 私密提示" : "情景变化"}</span><p className="prose-block mb-0 mt-1 text-sm text-stone-300">{entry.text}</p></div>)}
            {entries.length === 0 && sceneId ? <EmptyState title="等待游戏开始" hint="输入开场、玩家行动或现场变化，副 DM 会读取当前人物与场景后给出建议。" /> : null}
          </div>
          <div className="mt-4 grid gap-2">{quickActions.map((action) => <Button disabled={!sceneId || assistant.isPending} key={action} onClick={() => advance(action)} size="sm">{action}</Button>)}</div>
          <form className="mt-3" onSubmit={(event: FormEvent) => { event.preventDefault(); advance(input); }}><textarea className={textareaCls} onChange={(event) => setInput(event.target.value)} placeholder="记录玩家行动、NPC 对话或现场变化……" value={input} /><div className="mt-2 flex justify-end"><Button disabled={!sceneId || !input.trim()} loading={assistant.isPending} type="submit" variant="ai">记录并询问副 DM</Button></div></form>
          {assistant.isError ? <div className="mt-3"><ErrorState error={assistant.error} onRetry={() => advance(input)} /></div> : null}
        </Panel>
        <div className="space-y-4">
          <Panel eyebrow="DM 帷幕" title="当前提示">
            <p className="prose-block m-0 text-sm text-stone-300">{lastResponse?.dm_hint?.text ?? "副 DM 的推进建议、NPC 反应和风险会显示在这里。"}</p>
            {lastResponse?.dm_hint?.uncertainties.length ? <ul className="mb-0 mt-3 pl-4 text-xs text-amber-300">{lastResponse.dm_hint.uncertainties.map((item) => <li key={item}>{item}</li>)}</ul> : null}
            <div className="mt-3 rounded border border-ink-700 bg-ink-950/50 p-2">
              <p className="m-0 text-2xs text-stone-500">当前场景遭遇修正：<strong className={activeAdjustment < 0 ? "text-emerald-300" : activeAdjustment > 0 ? "text-red-300" : "text-stone-300"}>{activeAdjustment > 0 ? `提高 ${activeAdjustment} 级` : activeAdjustment < 0 ? `降低 ${Math.abs(activeAdjustment)} 级` : "无"}</strong></p>
              <div className="mt-2 grid gap-1.5">
                <Button disabled={!sceneId} onClick={() => draftFromAssistant(-1)} size="sm">起草玩家准备后果</Button>
                <Button disabled={!sceneId} onClick={() => draftFromAssistant(1)} size="sm">起草敌方优势后果</Button>
              </div>
              <p className="mb-0 mt-2 text-2xs text-stone-600">这里只生成可编辑草案；到上方核对 HP、状态、参战者或增援后，再由 DM 确认。</p>
            </div>
          </Panel>
          <Panel eyebrow="进入 / 离开 / 推进" title="最近情景记录">
            {recentEvents.length === 0 ? <p className="m-0 text-xs text-stone-600">还没有当前场景记录。</p> : <ul className="m-0 space-y-2 p-0">{recentEvents.map((event) => <li className="list-none border-b border-ink-800 pb-2 text-xs last:border-0" key={event.id}><strong className="block text-parchment-100">{event.title}</strong><span className="text-stone-600">{event.description}</span></li>)}</ul>}
          </Panel>
          <Panel eyebrow="本地快照 · 最近 20 个" title="场次检查点">
            <Button disabled={!sceneId} onClick={saveCheckpoint} size="sm" variant="primary">保存当前检查点</Button>
            <ul className="m-0 mt-3 space-y-2 p-0">
              {checkpoints.filter((checkpoint) => checkpoint.sceneId === sceneId).slice(-5).reverse().map((checkpoint) => <li className="flex list-none items-center gap-2 text-xs" key={checkpoint.id}><span className="min-w-0 flex-1 truncate text-stone-500">{checkpoint.label}</span><Button loading={restoreCheckpoint.isPending} onClick={() => restoreCheckpoint.mutate(checkpoint)} size="sm">恢复</Button></li>)}
            </ul>
            {!checkpoints.some((checkpoint) => checkpoint.sceneId === sceneId) ? <p className="mb-0 mt-2 text-2xs text-stone-600">尚无当前场景检查点。</p> : null}
          </Panel>
        </div>
      </div>
    </div>
  );
}

export function GameTablePage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <GameTableContent campaignId={campaignId} />}</RequireCampaign>;
}
