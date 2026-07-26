import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent, type ReactElement } from "react";

import { runAssistantTurn } from "../api/assistant";
import { getRuleDocument, searchKnowledge } from "../api/knowledge";
import {
  applyEncounterAdjustment, createClue, createEncounterAdjustment, createEvent, createNpc,
  createQuest, listCharacters, listEncounterAdjustments, listEvents, listLocations, listNpcs,
  rejectEncounterAdjustment, revertEncounterAdjustment,
} from "../api/entities";
import type {
  AgentResponse, EncounterAdjustment, EncounterOperation, SceneParticipant,
} from "../api/types";
import {
  addSceneParticipant, createMonster, createScene, createWorldItem, generateNpc,
  listMonsters, listSceneParticipants, listScenes,
  removeSceneParticipant, startSceneCombat,
} from "../api/world";
import { Panel } from "../components/Panel";
import { RestPanel } from "../components/RestPanel";
import { RequireCampaign } from "../components/RequireCampaign";
import { useToast } from "../hooks/toastContext";
import { navigate } from "../hooks/useHashRoute";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../ui/styles";
import { safeDndText } from "../ui/contentSafety";
import { HpBar } from "../ui/widgets";
import { parsePrepDraft, type DraftAtom } from "../ui/prepDraft";
import { generateTacticalSceneGrid } from "../ui/sceneGridGenerator";
import {
  campaignMonsterCandidates, compendiumMonsterCandidates, customMonsterDraft,
  detectArrivalKind, monsterDraftFromCandidate, parseMonsterStats, suggestedNpcName,
  type ArrivalDraft, type ArrivalKind, type MonsterReferenceCandidate,
} from "../ui/dynamicEntityDraft";
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

function SessionStatusBar({ characters, npcs, events }: { characters: { name: string; hp: number; max_hp: number }[]; npcs: { name: string; attitude: string | null }[]; events: { title: string }[] }): ReactElement {
  return <Panel className="mb-4" eyebrow="统一状态栏 · 已确认事实" title="队伍、关系与未解决事项"><div className="grid gap-3 text-xs md:grid-cols-3"><div><strong>队伍</strong><p className="mb-0 mt-1 text-stone-500">{characters.map((c) => `${c.name} ${c.hp}/${c.max_hp}`).join("、") || "—"}</p></div><div><strong>NPC 态度</strong><p className="mb-0 mt-1 text-stone-500">{npcs.slice(0, 3).map((n) => `${n.name}·${n.attitude ?? "未定"}`).join("、") || "—"}</p></div><div><strong>未解决事项</strong><p className="mb-0 mt-1 text-stone-500">{events.slice(-3).map((e) => e.title).join("、") || "暂无"}</p></div></div></Panel>;
}

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

function GameTableContent({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [sceneId, setSceneId] = useState("");
  const [tableMode, setTableMode] = useState<"prep" | "play">("play");
  const [showEncounterTools, setShowEncounterTools] = useState(false);
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
  const [arrivalDraft, setArrivalDraft] = useState<ArrivalDraft | null>(null);
  const [arrivalReferences, setArrivalReferences] = useState<MonsterReferenceCandidate[]>([]);
  const [startCombatAfterArrival, setStartCombatAfterArrival] = useState(false);
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
  const findCompendiumMonsters = async (query: string): Promise<MonsterReferenceCandidate[]> => {
    let hits = await searchKnowledge({
      text: query, top_k: 6, candidate_k: 24, min_score: 0.25,
      content_types: ["monsters"], editions: ["2024", "2025"],
      current_official: true,
    });
    if (hits.length === 0) {
      hits = await searchKnowledge({
        text: query, top_k: 6, candidate_k: 24, min_score: 0.25,
        content_types: ["monsters"], editions: ["2014", "legacy"],
        current_official: false, allow_unknown: false, allow_third_party: false,
      });
    }
    const enriched = await Promise.all(hits.map(async (hit) => {
      try {
        const document = await getRuleDocument(hit.chunk.record_id);
        return { ...hit, chunk: { ...hit.chunk, text: document.content_plain_text } };
      } catch {
        return hit;
      }
    }));
    return compendiumMonsterCandidates(enriched);
  };
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
    const monster = participants.data?.find((item) => item.entity_type === "monster" && item.role !== "defeated");
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
  const arrivalLookup = useMutation({
    mutationFn: async ({ kind, prompt, assistantText }: { kind: ArrivalKind; prompt: string; assistantText: string }) => {
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
            },
            references: [] as MonsterReferenceCandidate[],
          };
        } catch {
          return {
            draft: {
              kind: "npc" as const, prompt, sourceKey: "generated-npc",
              name: suggestedNpcName(prompt), description: assistantText || prompt,
              armorClass: 10, hp: 10, speed: 30, challengeRating: "0",
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
        compendium = await findCompendiumMonsters(`${prompt} ${assistantText} ${sceneContext}`);
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
    onSuccess: ({ draft, references }) => {
      setArrivalDraft(draft);
      setArrivalReferences(references);
      setStartCombatAfterArrival(false);
      showToast(draft.kind === "monster"
        ? references.length > 0 ? `已找到 ${references.length} 个本地图鉴/战役候选，请 DM 复核` : "图鉴暂无可靠匹配，已生成明确标记的自制草案"
        : "NPC 草案已生成，请 DM 复核后加入场景");
    },
    onError: () => showToast("无法起草进入场景的人物，请稍后重试", "error"),
  });
  const assistant = useMutation({
    mutationFn: async (action: string) => {
      const names = (participants.data ?? []).map((item) => `${item.entity_type}:${item.entity.name}${item.role === "defeated" ? "（已击败）" : ""}`).join("、") || "无人";
      const context = `你是D&D 5e 2024副DM，本应用不是COC。不得使用克苏鲁、奈亚拉托提普、旧日支配者、深潜者、SAN或理智检定等其他系统内容。当前场景：${activeScene?.name ?? "未选择"}。地点：${activeLocation?.name ?? "未绑定"}。当前在场：${names}。最近推进：${entries.slice(-5).map((entry) => entry.text).join("；")}。DM输入：${action}。请只用D&D 5e世界与机制，给DM私密推进建议、NPC可能反应、下一步引导和风险；本模式只输出叙事草案，不给出未经规则证据逐条支持的DC、CR、伤害骰、加值、次数或持续时间，不要擅自改数据库。`;
      return runAssistantTurn(campaignId, context, { mode: "narrative" });
    },
    onSuccess: async (response, action) => {
      const text = response.dm_hint?.text || (response.abstained ? "AI 暂时无法给出可靠建议，请由 DM 自由推进。" : "已读取当前战役状态，但没有生成新的提示。");
      setLastResponse(response);
      addEntry("ai", text);
      await log("AI 推进建议", text, { dm_action: action, entry_kind: "ai" });
      const arrivalKind = detectArrivalKind(`${action}\n${text}`);
      if (arrivalKind && sceneId) {
        arrivalLookup.mutate({ kind: arrivalKind, prompt: action, assistantText: text });
      }
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
  const chooseArrivalReference = (key: string) => {
    const reference = arrivalReferences.find((item) => item.key === key);
    if (reference && arrivalDraft) setArrivalDraft(monsterDraftFromCandidate(reference, arrivalDraft.prompt));
    else if (arrivalDraft) setArrivalDraft(customMonsterDraft(arrivalDraft.prompt));
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
      } else {
        const reference = arrivalReferences.find((item) => item.key === arrivalDraft.sourceKey);
        if (reference?.origin === "campaign") {
          entityId = reference.monster.id;
        } else {
          const parsed = reference?.origin === "compendium"
            ? parseMonsterStats(reference.hit)
            : null;
          const monster = await createMonster(campaignId, {
            name: arrivalDraft.name,
            source_record_id: reference?.origin === "compendium" ? reference.hit.chunk.record_id : null,
            source_name: reference?.origin === "compendium"
              ? `${reference.hit.chunk.source_book ?? reference.hit.chunk.source_title} · ${reference.hit.chunk.edition}`
              : "DM自制模板（非图鉴）",
            armor_class: arrivalDraft.armorClass,
            hp: arrivalDraft.hp,
            max_hp: arrivalDraft.hp,
            speed: arrivalDraft.speed,
            challenge_rating: arrivalDraft.challengeRating,
            ability_scores: parsed?.abilityScores ?? {
              strength: 10, dexterity: 10, constitution: 10,
              intelligence: 8, wisdom: 10, charisma: 8,
            },
            notes: `${arrivalDraft.description}\n登场原因：${arrivalDraft.prompt}${reference?.origin === "compendium" ? "\n由本地图鉴条目创建，DM已确认。" : "\n自制模板，未匹配到可靠图鉴条目，DM应复核数值。"}`,
          });
          entityId = monster.id;
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
      const startedCombat = startCombatAfterArrival
        ? await startSceneCombat(campaignId, sceneId)
        : null;
      return { participant, startedCombat };
    },
    onSuccess: ({ participant, startedCombat }) => {
      addEntry("system", `${participant.entity.name}已由 DM 确认并进入当前场景`);
      setArrivalDraft(null);
      setArrivalReferences([]);
      void client.invalidateQueries({ queryKey: ["scene-participants", campaignId, sceneId] });
      void client.invalidateQueries({ queryKey: ["npcs", campaignId] });
      void client.invalidateQueries({ queryKey: ["monsters", campaignId] });
      if (startedCombat) {
        sessionStorage.setItem(`dnd-dm-active-combat:${campaignId}`, startedCombat.combat.id);
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
    mutationFn: () => startSceneCombat(campaignId, sceneId),
    onSuccess: (result) => {
      void log("进入战斗", `“${activeScene?.name ?? "当前场景"}”进入战斗，已加载当前人物与场景网格。`);
      sessionStorage.setItem(`dnd-dm-active-combat:${campaignId}`, result.combat.id);
      void client.invalidateQueries({ queryKey: ["combats", campaignId] });
      navigate("/combat");
    },
    onError: () => showToast("无法发起战斗，请确认当前场景里至少有一名参与者", "error"),
  });
  const prep = useMutation({
    mutationFn: () => runAssistantTurn(campaignId, `你是D&D 5e 2024备团副DM，本应用不是COC。严禁使用克苏鲁、奈亚拉托提普、旧日支配者、深潜者、SAN、理智检定等其他系统专有内容；诡异主题必须使用D&D 5e的神祇、异怪、法术、豁免与状态。根据冒险描述生成可审核草稿。必须严格使用以下Markdown结构，每条使用“名称｜描述”，不要省略标题：\n## 场景\n- 名称｜描述\n## NPC\n- 名称｜描述\n## 怪物\n- 名称｜描述\n## 任务\n- 名称｜描述\n## 线索\n- 名称｜描述\n## 物品\n- 名称｜描述\n最后可以补充“## DM建议”，但不要直接修改数据库。\n冒险描述：${prepBrief}`),
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
        if (atom.kind === "scene") await createScene(campaignId, { name: atom.name, description: atom.description, notes: JSON.stringify({ scene_grid: generateTacticalSceneGrid(atom.name, atom.description) }) });
        if (atom.kind === "npc") await createNpc(campaignId, { name: atom.name, description: atom.description, armor_class: 10, hp: 10, max_hp: 10, speed: 30, ability_scores: { strength: 10, dexterity: 10, constitution: 10, intelligence: 10, wisdom: 10, charisma: 10 } });
        if (atom.kind === "monster") {
          const existing = (monsters.data ?? []).find(
            (monster) => monster.name.trim().toLowerCase() === atom.name.trim().toLowerCase(),
          );
          if (existing) continue;
          let matched: MonsterReferenceCandidate | undefined;
          try {
            const references = await findCompendiumMonsters(`${atom.name} ${atom.description}`);
            matched = references.find((reference) => reference.origin === "compendium" && (
              reference.label.trim().toLowerCase() === atom.name.trim().toLowerCase()
              || reference.hit.chunk.aliases.some((alias) => alias.trim().toLowerCase() === atom.name.trim().toLowerCase())
              || reference.hit.score >= 0.72
            ));
          } catch {
            // A missing local index never turns into an implicit write. The
            // fallback remains visibly custom and awaits this explicit import.
          }
          if (matched?.origin === "compendium") {
            const stats = parseMonsterStats(matched.hit);
            await createMonster(campaignId, {
              name: stats.name,
              source_record_id: matched.hit.chunk.record_id,
              source_name: `${matched.hit.chunk.source_book ?? matched.hit.chunk.source_title} · ${matched.hit.chunk.edition}`,
              notes: `${atom.description}\n由备团草稿匹配本地图鉴并经DM确认导入。`,
              armor_class: stats.armorClass,
              hp: stats.hp,
              max_hp: stats.hp,
              speed: stats.speed,
              challenge_rating: stats.challengeRating,
              ability_scores: stats.abilityScores,
            });
          } else {
            await createMonster(campaignId, {
              name: atom.name,
              source_name: "DM自制模板（非图鉴）",
              notes: `${atom.description}\n未找到足够可靠的本地图鉴匹配；这是自制模板，CR 1/4，DM应在使用前复核。`,
              armor_class: 12, hp: 8, max_hp: 8, speed: 30, challenge_rating: "1/4",
              ability_scores: { strength: 10, dexterity: 10, constitution: 10, intelligence: 8, wisdom: 10, charisma: 8 },
            });
          }
        }
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
            ? "备团顺序：写冒险概要 → AI 生成草稿 → 勾选并导入 → 切到“开始跑团”。"
            : "推进顺序：选场景 → 添加当前在场人物 → 记录玩家行动 / 选择快捷推进 → 需要时发起战斗。"}
        </p>
      </div>
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
          <div className="rounded border border-ink-700 bg-ink-950/60 p-2"><span className="block text-2xs text-stone-600">怪物</span><strong className="text-xs text-red-300">{participants.data?.filter((item) => item.entity_type === "monster" && item.role !== "defeated").length ?? 0} 活动 · {participants.data?.filter((item) => item.entity_type === "monster" && item.role === "defeated").length ?? 0} 已击败</strong></div>
        </div>
      </Panel>
      {tableMode === "prep" ? <Panel className="mt-4" eyebrow="第 1 步 · 开团前准备" title="备团草稿">
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
      {tableMode === "play" ? <div className="mt-4 grid gap-4 xl:grid-cols-[0.8fr_1.4fr_0.8fr]">
        <Panel eyebrow="情景状态" title="当前在场">
          <div className="flex gap-2"><select className={selectCls} onChange={(event) => setEntityKey(event.target.value)} value={entityKey}><option value="">选择进入人物</option>{availableCandidates.map((candidate) => <option key={candidate.key} value={candidate.key}>{candidate.label}</option>)}</select><Button disabled={!entityKey} loading={participantAdd.isPending} onClick={() => participantAdd.mutate()} size="sm">进入</Button></div>
          <div className="mt-2"><RestPanel campaignId={campaignId} characters={characters.data ?? []} compact defaultCharacterIds={(participants.data ?? []).filter((item) => item.entity_type === "character").map((item) => item.entity_id)} /></div>
          {participants.isLoading ? <LoadingBlock /> : null}
          {participants.data?.length === 0 ? <EmptyState title="当前场景无人" hint="从上方选择玩家、NPC 或怪物进入。" /> : null}
          <ul className="m-0 mt-3 space-y-2 p-0">{participants.data?.map((participant) => <li className="list-none rounded border border-ink-700 bg-ink-950/50 p-2" key={participant.id}><div className="flex items-center gap-2"><Badge tone={participant.entity_type === "character" ? "ok" : participant.entity_type === "npc" ? "ai" : "danger"}>{participant.entity_type === "character" ? "玩家" : participant.entity_type === "npc" ? "NPC" : "怪物"}</Badge>{participant.role === "defeated" ? <Badge>已击败</Badge> : null}<strong className="min-w-0 flex-1 truncate text-xs text-parchment-100">{participant.entity.name}</strong><Button loading={participantRemove.isPending} onClick={() => participantRemove.mutate(participant)} size="sm">离开</Button></div><div className="mt-2"><HpBar hp={participant.entity.hp} maxHp={participant.entity.max_hp} /></div><p className="mb-0 mt-1 text-2xs text-stone-600">AC {participant.entity.armor_class} · 速度 {participant.entity.speed}</p></li>)}</ul>
        </Panel>
        <Panel eyebrow="自由推进 / 快速推进" title="游戏推进对话">
          {!sceneId ? <EmptyState title="先选择场景" hint="选择当前场景后，副 DM 才能读取正确的情景状态。" /> : null}
          <div className="max-h-[52vh] space-y-3 overflow-y-auto pr-1">
            {entries.map((entry) => <div className={`rounded-lg border px-3 py-2 ${entry.kind === "dm" ? "ml-10 border-ember-800/50 bg-ember-950/20" : entry.kind === "ai" ? "mr-10 border-violet-800/50 bg-violet-950/20" : "border-ink-700 bg-ink-950/50"}`} key={entry.id}><span className="block text-2xs text-stone-600">{entry.kind === "dm" ? "DM 推进" : entry.kind === "ai" ? "副 DM 私密提示" : "情景变化"}</span><p className="prose-block mb-0 mt-1 text-sm text-stone-300">{entry.kind === "ai" ? safeDndText(entry.text) : entry.text}</p></div>)}
            {entries.length === 0 && sceneId ? <EmptyState title="等待游戏开始" hint="输入开场、玩家行动或现场变化，副 DM 会读取当前人物与场景后给出建议。" /> : null}
          </div>
          <div className="mt-4 grid gap-2">{quickActions.map((action) => <Button disabled={!sceneId || assistant.isPending} key={action} onClick={() => advance(action)} size="sm">{action}</Button>)}</div>
          <form className="mt-3" onSubmit={(event: FormEvent) => { event.preventDefault(); advance(input); }}><textarea className={textareaCls} onChange={(event) => setInput(event.target.value)} placeholder="记录玩家行动、NPC 对话或现场变化……" value={input} /><div className="mt-2 flex justify-end"><Button disabled={!sceneId || !input.trim()} loading={assistant.isPending} type="submit" variant="ai">记录并询问副 DM</Button></div></form>
          {assistant.isError ? <div className="mt-3"><ErrorState error={assistant.error} onRetry={() => advance(input)} /></div> : null}
        </Panel>
        <div className="space-y-4">
          <Panel eyebrow="DM 帷幕" title="当前提示">
            <p className="prose-block m-0 text-sm text-stone-300">{lastResponse?.dm_hint?.text ? safeDndText(lastResponse.dm_hint.text) : "副 DM 的推进建议、NPC 反应和风险会显示在这里。"}</p>
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
          {arrivalLookup.isPending ? (
            <Panel eyebrow="动态原子 · 只读检索" title="正在查找合适的登场者">
              <LoadingBlock label="优先检索战役原子与本地 D&D 怪物图鉴…" />
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
                    <span className="mt-1 block text-stone-600">仅在图鉴没有合适条目时使用；数值需要 DM 自行复核。</span>
                  </label>
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
          <Panel eyebrow="本地快照 · 最近 20 个" title="场次检查点">
            <Button disabled={!sceneId} onClick={saveCheckpoint} size="sm" variant="primary">保存当前检查点</Button>
            <ul className="m-0 mt-3 space-y-2 p-0">
              {checkpoints.filter((checkpoint) => checkpoint.sceneId === sceneId).slice(-5).reverse().map((checkpoint) => <li className="flex list-none items-center gap-2 text-xs" key={checkpoint.id}><span className="min-w-0 flex-1 truncate text-stone-500">{checkpoint.label}</span><Button loading={restoreCheckpoint.isPending} onClick={() => restoreCheckpoint.mutate(checkpoint)} size="sm">恢复</Button></li>)}
            </ul>
            {!checkpoints.some((checkpoint) => checkpoint.sceneId === sceneId) ? <p className="mb-0 mt-2 text-2xs text-stone-600">尚无当前场景检查点。</p> : null}
          </Panel>
        </div>
      </div> : null}
    </div>
  );
}

export function GameTablePage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <GameTableContent campaignId={campaignId} />}</RequireCampaign>;
}
