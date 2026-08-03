import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type ChangeEvent, type FormEvent, type ReactElement } from "react";

import { createCampaign, deleteCampaign, listCampaigns, updateCampaign } from "../api/campaigns";
import { listContentPacks, type ContentPack } from "../api/contentPacks";
import { listRuleExtensions, type RuleExtension } from "../api/ruleExtensions";
import {
  createCharacter, createClue, createEvent, createLocation, createNpc, createQuest,
  deleteCharacter, deleteClue, deleteEvent, deleteLocation, deleteNpc, deleteQuest,
  listCharacters, listClues, listEvents, listLocations, listNpcs, listQuests,
  getCharacterOptions, recognizeCharacterSheet,
  updateCharacter, updateClue, updateEvent, updateLocation, updateNpc, updateQuest,
  type CharacterInput, type CharacterOcrResult, type ClueInput, type EventInput, type LocationInput, type NpcInput, type QuestInput,
} from "../api/entities";
import type { Campaign, CampaignEvent, Character, Clue, Location, Npc, Quest } from "../api/types";
import { Panel } from "../components/Panel";
import { CharacterSheetDetail } from "../components/CharacterSheetDetail";
import { CompanionPanel } from "../components/CompanionPanel";
import { RestPanel } from "../components/RestPanel";
import { RequireCampaign } from "../components/RequireCampaign";
import { inputCls } from "../ui/styles";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { formatDateTime } from "../ui/format";
import { ConfirmDialog } from "../ui/widgets";
import { useToast } from "../hooks/toastContext";
import {
  BACKGROUNDS_2024, CLASSES_2024, SPECIES_2024,
  classSkillSelection, spellChoiceCounts, spellChoicesComplete,
  spellIsAvailable, spellSelectionRule, spellToCharacterAction,
} from "../ui/characterRules";

const ABILITY_LABELS: Record<string, string> = {
  strength: "力量", dexterity: "敏捷", constitution: "体质",
  intelligence: "智力", wisdom: "感知", charisma: "魅力",
};

function modifier(score: number): string {
  const value = Math.floor((score - 10) / 2);
  return value >= 0 ? `+${value}` : String(value);
}

function resourceSummary(resources: Record<string, unknown>): string {
  return Object.values(resources).map((value) => {
    if (typeof value !== "object" || value === null) return "";
    const resource = value as { label?: unknown; current?: unknown; max?: unknown };
    const label = typeof resource.label === "string" ? resource.label : "资源";
    const current = typeof resource.current === "number" ? resource.current : 0;
    const max = typeof resource.max === "number" ? resource.max : 0;
    return `${label} ${current}/${max}`;
  }).filter(Boolean).join("、");
}

function characterStatus(character: Character): { label: string; tone: string } {
  if (character.hp <= 0) {
    if (character.death_saves.failures >= 3) return { label: "死亡", tone: "border-red-700/60 bg-red-950/40 text-red-200" };
    if (character.death_saves.successes >= 3) return { label: "稳定", tone: "border-sky-700/60 bg-sky-950/40 text-sky-200" };
    return {
      label: `倒地 · 豁免 ${character.death_saves.successes}成/${character.death_saves.failures}败`,
      tone: "border-red-700/60 bg-red-950/40 text-red-200",
    };
  }
  if (character.max_hp_reduction > 0) {
    return { label: `最大HP −${character.max_hp_reduction}`, tone: "border-violet-700/60 bg-violet-950/35 text-violet-200" };
  }
  if (character.hp <= character.max_hp / 2) {
    return { label: "重伤", tone: "border-amber-700/60 bg-amber-950/35 text-amber-200" };
  }
  return { label: "状态正常", tone: "border-emerald-800/60 bg-emerald-950/30 text-emerald-300" };
}

function downloadFile(filename: string, content: string, type: string): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

type CharacterWorkspaceTab = "list" | "create" | "tools";

function CharacterToolkit({
  campaignId,
  mode,
  onCreate,
}: {
  campaignId: string;
  mode: "list" | "tools";
  onCreate?: () => void;
}): ReactElement {
  const { showToast } = useToast();
  const client = useQueryClient();
  const characters = useQuery({
    queryKey: ["characters", campaignId],
    queryFn: ({ signal }) => listCharacters(campaignId, signal),
  });
  const fileRef = useRef<HTMLInputElement>(null);
  const ocrFileRef = useRef<HTMLInputElement>(null);
  const [ocrResult, setOcrResult] = useState<CharacterOcrResult | null>(null);
  const [selectedCharacter, setSelectedCharacter] = useState<Character | null>(null);
  const importCharacters = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const text = await file.text();
      const parsed: unknown = file.name.toLowerCase().endsWith(".csv")
        ? parseCharacterCsv(text)
        : JSON.parse(text);
      const rows = Array.isArray(parsed) ? parsed : [parsed];
      const valid = rows.filter((row): row is CharacterInput & { name: string } =>
        typeof row === "object" && row !== null && typeof (row as { name?: unknown }).name === "string",
      );
      if (valid.length === 0) throw new Error("文件中没有找到角色名称");
      await Promise.all(valid.map(({ name, ...input }) => createCharacter(campaignId, { ...input, name })));
      await client.invalidateQueries({ queryKey: ["characters", campaignId] });
      showToast(`已导入 ${valid.length} 张角色卡`);
    } catch (error) {
      showToast(error instanceof Error ? `导入失败：${error.message}` : "导入失败，请检查 JSON/CSV 格式", "error");
    }
  };
  const exportCharacters = (format: "json" | "csv") => {
    const rows = characters.data ?? [];
    if (format === "json") {
      downloadFile("dnd5e-characters.json", JSON.stringify(rows, null, 2), "application/json");
    } else {
      const header = "name,race,class_name,level,armor_class,speed,hp,max_hp,strength,dexterity,constitution,intelligence,wisdom,charisma,notes";
      const csvRows = rows.map((character) => {
        const scores = character.ability_scores;
        return [
          character.name, character.race ?? "", character.class_name ?? "", character.level,
          character.armor_class, character.speed, character.hp, character.max_hp,
          ...Object.keys(ABILITY_LABELS).map((key) => scores[key] ?? 10), character.notes ?? "",
        ].map((value) => `"${String(value).replaceAll("\"", "\"\"")}"`).join(",");
      });
      downloadFile("dnd5e-characters.csv", [header, ...csvRows].join("\n"), "text/csv;charset=utf-8");
    }
  };
  const ocrMutation = useMutation({
    mutationFn: async (file: File) => {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(reader.error ?? new Error("图片读取失败"));
        reader.onload = () => {
          if (typeof reader.result !== "string") {
            reject(new Error("图片读取结果无效"));
            return;
          }
          resolve(reader.result);
        };
        reader.readAsDataURL(file);
      });
      return recognizeCharacterSheet(file.name, dataUrl.split(",", 2)[1] ?? "");
    },
    onSuccess: (result) => {
      setOcrResult(result);
      showToast("本机 OCR 草稿已生成，请审核后确认");
    },
    onError: (error) => {
      showToast(error instanceof Error ? `图片识别失败：${error.message}` : "图片识别失败", "error");
    },
  });
  const confirmOcr = useMutation({
    mutationFn: () => {
      if (!ocrResult) throw new Error("没有 OCR 草稿");
      return createCharacter(campaignId, ocrResult.draft);
    },
    onSuccess: async () => {
      setOcrResult(null);
      await client.invalidateQueries({ queryKey: ["characters", campaignId] });
      showToast("OCR 角色草稿已由 DM 确认并创建");
    },
  });
  if (mode === "list") {
    return (
      <>
        <Panel eyebrow="队伍状态" title="角色列表">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-auto text-xs text-stone-500">
              外层只显示跑团时最常用的数值；点击任意角色查看背包、技能、特性、动作、法术与资源。
            </span>
            <RestPanel campaignId={campaignId} characters={characters.data ?? []} />
            <Button onClick={onCreate} size="sm" variant="primary">创建角色</Button>
          </div>
          {characters.isLoading ? <LoadingBlock label="读取角色列表…" /> : null}
          {characters.isError ? <ErrorState error={characters.error} onRetry={() => void characters.refetch()} /> : null}
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {(characters.data ?? []).map((character) => {
              const status = characterStatus(character);
              return (
                  <button
                    aria-label={`打开${character.name}的详细角色卡`}
                    className="rounded-xl border border-ink-700 bg-ink-950/45 p-4 text-left transition hover:border-ember-700/60 hover:bg-ink-950/75 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ember-400"
                    key={character.id}
                    onClick={() => setSelectedCharacter(character)}
                    type="button"
                  >
                    <div className="flex items-start gap-3">
                      <div className="mr-auto"><strong className="block text-base text-parchment-100">{character.name}</strong><span className="mt-1 block text-2xs text-stone-500">{character.race || "未选种族"} · {character.class_name || "未选职业"} Lv {character.level}</span></div>
                      <div className="flex flex-col items-end gap-1"><span className="rounded bg-ember-500/10 px-2 py-1 text-2xs text-ember-300">详细角色卡</span><span className={`rounded border px-2 py-0.5 text-[10px] ${status.tone}`}>{status.label}</span></div>
                    </div>
                    <div className="mt-4 grid grid-cols-3 gap-2 text-center">{[["AC", character.armor_class, "text-amber-300"], ["HP", `${character.hp}/${character.max_hp}`, "text-red-300"], ["速度", `${character.speed}尺`, "text-sky-300"]].map(([label, value, tone]) => <div className="rounded border border-ink-700 bg-ink-900/70 p-2" key={label}><span className="block text-2xs text-stone-600">{label}</span><strong className={`font-mono text-sm ${tone}`}>{value}</strong></div>)}</div>
                    <div className="mt-3 grid grid-cols-6 gap-1">{Object.entries(ABILITY_LABELS).map(([key, label]) => { const score = character.ability_scores[key] ?? 10; return <div className="rounded bg-ink-900 p-1.5 text-center" key={key}><span className="block text-[9px] text-stone-600">{label}</span><strong className="font-mono text-xs text-parchment-100">{score}</strong><span className="block text-[9px] text-violet-300">{modifier(score)}</span></div>; })}</div>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-2xs text-stone-500"><span>{character.experience.toLocaleString()} XP</span><span>·</span><span>{character.actions.length} 个动作</span><span>·</span><span>{resourceSummary(character.resources) || "无职业资源"}</span></div>
                  </button>
              );
            })}
          </div>
          {!characters.isLoading && characters.data?.length === 0 ? <EmptyState title="这个团还没有角色" hint="切换到“创建角色”，按 D&D 5e 2024 向导完成车卡。" /> : null}
          {selectedCharacter ? <CharacterSheetDetail campaignId={campaignId} character={selectedCharacter} onClose={() => setSelectedCharacter(null)} /> : null}
        </Panel>
        <CompanionPanel campaignId={campaignId} characters={characters.data ?? []} />
      </>
    );
  }

  return (
    <Panel eyebrow="本地角色卡工具" title="导入、导出与 OCR">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-auto text-xs text-stone-500">批量导入或导出 JSON、CSV；图片识别只在本机生成待审核草稿。</span>
        <input accept=".json,.csv,application/json,text/csv" className="hidden" onChange={(event) => { void importCharacters(event); }} ref={fileRef} type="file" />
        <input accept="image/png,image/jpeg,image/heic,image/tiff,image/webp" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) ocrMutation.mutate(file); }} ref={ocrFileRef} type="file" />
        <Button onClick={() => fileRef.current?.click()} size="sm">导入角色卡</Button>
        <Button loading={ocrMutation.isPending} onClick={() => ocrFileRef.current?.click()} size="sm">图片 OCR 草稿</Button>
        <Button disabled={!characters.data?.length} onClick={() => exportCharacters("json")} size="sm">导出 JSON</Button>
        <Button disabled={!characters.data?.length} onClick={() => exportCharacters("csv")} size="sm">导出表格</Button>
      </div>
      {ocrResult ? (
        <div className="mt-3 rounded-lg border border-violet-800/60 bg-violet-950/20 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><strong className="text-sm text-parchment-100">本机 Vision OCR 待审核草稿</strong><p className="mb-0 mt-1 text-2xs text-stone-500">未上传云端；只有点击确认后才写入角色事实。</p></div>
            <div className="flex gap-2"><Button loading={confirmOcr.isPending} onClick={() => confirmOcr.mutate()} size="sm" variant="primary">DM 确认创建</Button><Button onClick={() => setOcrResult(null)} size="sm">取消</Button></div>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {(["name", "race", "class_name", "background", "level", "armor_class", "hp", "max_hp", "speed"] as const).map((field) => (
              <label className="text-2xs text-stone-500" key={field}>{field}
                <input className={`${inputCls} mt-1 w-full`} onChange={(event) => setOcrResult({ ...ocrResult, draft: { ...ocrResult.draft, [field]: ["level", "armor_class", "hp", "max_hp", "speed"].includes(field) ? Number(event.target.value) : event.target.value } })} type={["level", "armor_class", "hp", "max_hp", "speed"].includes(field) ? "number" : "text"} value={String(ocrResult.draft[field] ?? "")} />
              </label>
            ))}
          </div>
          <details className="mt-3"><summary className="cursor-pointer text-xs text-violet-300">查看 OCR 原文</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-xs text-stone-400">{ocrResult.recognized_text}</pre></details>
        </div>
      ) : null}
      <p className="mb-0 mt-3 text-2xs text-stone-600">图片角色卡使用 macOS Vision 在本机识别为可编辑草稿；不会上传云端，确认后才创建角色。</p>
    </Panel>
  );
}

function CharacterWorkspace({ campaignId }: { campaignId: string }): ReactElement {
  const [tab, setTab] = useState<CharacterWorkspaceTab>("list");
  const tabs: { id: CharacterWorkspaceTab; label: string; hint: string }[] = [
    { id: "list", label: "角色列表", hint: "关键属性、状态与详细角色卡" },
    { id: "create", label: "创建角色", hint: "按 2024 规则逐步车卡" },
    { id: "tools", label: "导入 / 导出", hint: "JSON、CSV 与本机图片 OCR" },
  ];

  return (
    <div className="mx-auto max-w-[1200px] p-4 lg:p-6">
      <Panel eyebrow="D&D 5e · 2024" title="角色工作区">
        <p className="mt-0 text-xs text-stone-500">
          角色、背包与成长集中在这里。选择一个子界面，避免创建、工具和角色数据同时挤在一页。
        </p>
        <div aria-label="角色工作区导航" className="grid gap-2 sm:grid-cols-3" role="tablist">
          {tabs.map((item) => (
            <button
              aria-selected={tab === item.id}
              className={`rounded-lg border px-4 py-3 text-left transition ${
                tab === item.id
                  ? "border-ember-500/60 bg-ember-500/10 text-ember-200"
                  : "border-ink-700 bg-ink-950/35 text-stone-400 hover:border-ink-500 hover:text-parchment-100"
              }`}
              key={item.id}
              onClick={() => setTab(item.id)}
              role="tab"
              type="button"
            >
              <strong className="block text-sm">{item.label}</strong>
              <span className="mt-1 block text-2xs text-stone-600">{item.hint}</span>
            </button>
          ))}
        </div>
      </Panel>
      <div className="mt-4" role="tabpanel">
        {tab === "list" ? <CharacterToolkit campaignId={campaignId} mode="list" onCreate={() => setTab("create")} /> : null}
        {tab === "create" ? <CharacterCreateWizard campaignId={campaignId} onDone={() => setTab("list")} /> : null}
        {tab === "tools" ? <CharacterToolkit campaignId={campaignId} mode="tools" /> : null}
      </div>
    </div>
  );
}

function parseCharacterCsv(text: string): CharacterInput[] {
  const [headerLine, ...lines] = text.trim().split(/\r?\n/);
  if (!headerLine) return [];
  const headers = headerLine.split(",").map((value) => value.trim().replace(/^"|"$/g, ""));
  return lines.filter(Boolean).map((line) => {
    const values = line.split(",").map((value) => value.trim().replace(/^"|"$/g, ""));
    const row = Object.fromEntries(headers.map((key, index) => [key, values[index] ?? ""]));
    return {
      name: row.name,
      race: row.race || null,
      class_name: row.class_name || null,
      level: Number(row.level || 1), armor_class: Number(row.armor_class || 10),
      speed: Number(row.speed || 30), hp: Number(row.hp || 0), max_hp: Number(row.max_hp || 0),
      ability_scores: Object.fromEntries(Object.keys(ABILITY_LABELS).map((key) => [key, Number(row[key] || 10)])),
      notes: row.notes || null,
    };
  });
}

type EntityKind = "campaigns" | "characters" | "npcs" | "quests" | "clues" | "locations" | "events";
type Row = Campaign | Character | Npc | Quest | Clue | Location | CampaignEvent;

const META: Record<EntityKind, { title: string; eyebrow: string; name: string; description: string }> = {
  campaigns: { title: "跑团档案", eyebrow: "A团 / B团 · 数据完全独立", name: "团名（例如 A团）", description: "本团世界观与冒险说明" },
  characters: { title: "玩家角色", eyebrow: "队伍", name: "角色名称", description: "角色备注" },
  npcs: { title: "NPC", eyebrow: "登场人物", name: "NPC 名称", description: "公开描述" },
  quests: { title: "任务", eyebrow: "故事线", name: "任务名称", description: "任务描述" },
  clues: { title: "线索", eyebrow: "调查", name: "线索名称", description: "线索描述" },
  locations: { title: "地点", eyebrow: "世界地图", name: "地点名称", description: "地点描述" },
  events: { title: "事件", eyebrow: "编年史", name: "事件标题", description: "事件描述" },
};

function asRows(items: Row[]): Record<string, unknown>[] {
  return items.map((item) => Object.fromEntries(Object.entries(item)));
}

function display(value: unknown, fallback: string): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : fallback;
}

function useRows(kind: EntityKind, campaignId: string | null) {
  return useQuery({
    queryKey: [kind, campaignId],
    enabled: kind === "campaigns" || campaignId !== null,
    queryFn: async ({ signal }) => {
      if (kind === "campaigns") return asRows(await listCampaigns(signal));
      if (!campaignId) return [];
      if (kind === "characters") return asRows(await listCharacters(campaignId, signal));
      if (kind === "npcs") return asRows(await listNpcs(campaignId, signal));
      if (kind === "quests") return asRows(await listQuests(campaignId, signal));
      if (kind === "clues") return asRows(await listClues(campaignId, signal));
      if (kind === "locations") return asRows(await listLocations(campaignId, signal));
      return asRows(await listEvents(campaignId, signal));
    },
  });
}

function CharacterCreateWizard({ campaignId, onDone }: { campaignId: string; onDone: () => void }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [race, setRace] = useState("");
  const [className, setClassName] = useState("");
  const [background, setBackground] = useState("");
  const [abilities, setAbilities] = useState<Record<string, string>>({
    strength: "15", dexterity: "14", constitution: "13",
    intelligence: "12", wisdom: "10", charisma: "8",
  });
  const [armorClass, setArmorClass] = useState("10");
  const [speed, setSpeed] = useState("30");
  const [hp, setHp] = useState("10");
  const [equipment, setEquipment] = useState("");
  const [spellSearch, setSpellSearch] = useState("");
  const [selectedSpells, setSelectedSpells] = useState<string[]>([]);
  const [preparedSpellIds, setPreparedSpellIds] = useState<string[]>([]);
  const [selectedClassSkills, setSelectedClassSkills] = useState<string[]>([]);
  const characterOptions = useQuery({
    queryKey: ["character-options", campaignId],
    queryFn: ({ signal }) => getCharacterOptions(signal, campaignId),
    staleTime: 60 * 60 * 1000,
  });
  const mutation = useMutation({
    mutationFn: () => {
      if (!name.trim()) throw new Error("角色名称不能为空");
      const speciesRule = SPECIES_2024.find((item) => item.name === race);
      const backgroundRule = BACKGROUNDS_2024.find((item) => item.name === background);
      const classRule = CLASSES_2024.find((item) => item.name === className);
      const classResources = classRule ? structuredClone(classRule.resources) : {};
      if (classRule?.spellcasting) {
        classResources.spell_slots_1 = {
          label: "1环法术位", current: classRule.spellcasting.level1Slots,
          max: classRule.spellcasting.level1Slots, recovery: "long_rest",
        };
      }
      const initialEquipment = [
        ...(classRule?.equipment ?? []), ...(backgroundRule?.equipment ?? []),
        ...equipment.split(/\n|、|,/).map((item) => item.trim()).filter(Boolean),
      ];
      const spellAbilityKey = {
        力量: "strength", 敏捷: "dexterity", 体质: "constitution",
        智力: "intelligence", 感知: "wisdom", 魅力: "charisma",
      }[classRule?.spellcasting?.ability ?? "智力"] ?? "intelligence";
      const spellSaveDc = 10 + Math.floor((Number(abilities[spellAbilityKey]) - 10) / 2);
      const availableSpells = (characterOptions.data?.spells ?? [])
        .filter((spell) => spellIsAvailable(spell, className));
      if (selectedClassSkills.length !== classSkillSelection(className, backgroundRule?.skills).count) {
        throw new Error("请按职业规则选满技能熟练项");
      }
      if (!spellChoicesComplete(className, selectedSpells, availableSpells)) {
        throw new Error("请按职业规则选满戏法与1环法术");
      }
      if (className === "法师" && preparedSpellIds.length !== 4) {
        throw new Error("1级法师必须从法术书中准备4个1环法术");
      }
      return createCharacter(campaignId, {
        name: name.trim(), race: race || null, class_name: className || null,
        background: background || null,
        level: 1, armor_class: Number(armorClass), speed: Number(speed),
        ability_scores: Object.fromEntries(Object.entries(abilities).map(([key, value]) => [key, Number(value)])),
        hp: Number(hp), max_hp: Number(hp), equipment: initialEquipment,
        proficiencies: [...(classRule?.proficiencies ?? []), ...(classRule?.saves.map((item) => `${item}豁免`) ?? [])],
        skills: Object.fromEntries([...selectedClassSkills, ...(backgroundRule?.skills ?? [])].map((skill) => [skill, { proficient: true }])),
        features: [...(speciesRule?.features ?? []), ...(backgroundRule ? [`背景专长：${backgroundRule.feat}`] : [])],
        actions: classRule?.actions ?? [],
        resources: classResources,
        spells: availableSpells
          .filter((spell) => selectedSpells.includes(spell.source_record_id))
          .map((spell) => spellToCharacterAction(
            spell,
            spellSaveDc,
            className !== "法师" || preparedSpellIds.includes(spell.source_record_id),
          )),
        spellcasting: classRule?.spellcasting ?? {},
        class_levels: className ? { [className === "邪术师" ? "魔契师" : className]: 1 } : {},
        subclass_choices: {},
        notes: `D&D 5e 2024规则角色${background ? ` · 背景：${background}` : ""}`,
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      setStep(1); setName(""); setRace(""); setClassName(""); setBackground(""); setEquipment(""); setSelectedSpells([]); setPreparedSpellIds([]); setSelectedClassSkills([]);
      showToast("角色卡已创建"); onDone();
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "角色创建失败", "error"),
  });
  const setAbility = (key: string, value: string) => setAbilities((current) => ({ ...current, [key]: value }));
  const standardArray = () => setAbilities({ strength: "15", dexterity: "14", constitution: "13", intelligence: "12", wisdom: "10", charisma: "8" });
  const selectedSpecies = SPECIES_2024.find((item) => item.name === race);
  const selectedBackground = BACKGROUNDS_2024.find((item) => item.name === background);
  const selectedClass = CLASSES_2024.find((item) => item.name === className);
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
  const toggleSpell = (id: string, level: number, checked: boolean) => {
    if (!checked) {
      setSelectedSpells((current) => current.filter((item) => item !== id));
      setPreparedSpellIds((current) => current.filter((item) => item !== id));
      return;
    }
    const limit = level === 0 ? spellLimits.cantrips : spellLimits.leveled;
    const count = level === 0 ? spellCounts.cantrips : spellCounts.leveled;
    if (count >= limit) {
      showToast(`该职业1级最多选择 ${limit} 个${level === 0 ? "戏法" : spellLimits.leveledLabel}`, "error");
      return;
    }
    setSelectedSpells((current) => [...current, id]);
  };
  const applyDerivedStats = () => {
    const constitutionModifier = Math.floor((Number(abilities.constitution) - 10) / 2);
    setSpeed(String(selectedSpecies?.speed ?? 30));
    setHp(String(Math.max(1, (selectedClass?.hitDie ?? 8) + constitutionModifier)));
    setArmorClass(className === "武僧" ? String(10 + Math.floor((Number(abilities.dexterity) - 10) / 2) + Math.floor((Number(abilities.wisdom) - 10) / 2)) : "10");
    setStep(3);
  };
  return (
    <Panel eyebrow="D&D 5e · 2024" title="按规则创建角色">
      <div className="mb-4 flex items-center gap-2">
        {[["1", "身份"], ["2", "属性"], ["3", "职业选项"], ["4", "战斗与装备"]].map(([number, label]) => <div className={`flex items-center gap-2 text-xs ${step === Number(number) ? "text-ember-300" : "text-stone-600"}`} key={number}><span className={`flex h-6 w-6 items-center justify-center rounded-full border ${step === Number(number) ? "border-ember-400 bg-ember-500/15" : "border-ink-600"}`}>{number}</span>{label}</div>)}
      </div>
      {characterOptions.data?.rule_extensions?.length ? <div className="mb-4 rounded border border-violet-800/60 bg-violet-950/20 p-3 text-xs text-violet-100"><strong>本团已启用规则扩展：</strong>{characterOptions.data.rule_extensions.map((item) => <span className="ml-2 inline-flex rounded bg-violet-500/15 px-2 py-1 text-2xs" key={item.key}>{item.label} · {item.automation_status === "partial" ? "部分自动" : item.automation_status === "dm_only" ? "DM裁定" : "自动"}</span>)}<p className="mb-0 mt-2 text-2xs text-violet-200/70">车卡与升级会保留这些规则的来源；需要数值或前置条件的扩展仍需 DM 最终确认。</p></div> : null}
      {(characterOptions.data?.extension_character_options?.length ?? 0) > 0 ? <div className="mb-4 rounded border border-amber-800/60 bg-amber-950/20 p-3 text-xs text-amber-100"><strong>已启用扩展角色资料：</strong>{characterOptions.data?.extension_character_options?.length} 项。当前均标记为“DM 裁定”，不会混入 2024 核心职业、子职或专长自动选择器。</div> : null}
      {step === 1 ? (
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-xs text-stone-400">角色名称<input className={`${inputCls} mt-1`} onChange={(event) => setName(event.target.value)} placeholder="例如：艾拉" value={name} /></label>
          <label className="text-xs text-stone-400">种族（2024核心）<select className={`${inputCls} mt-1`} onChange={(event) => setRace(event.target.value)} value={race}><option value="">选择种族</option>{SPECIES_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.speed}尺</option>)}</select></label>
          <label className="text-xs text-stone-400">职业（全部12个核心职业）<select className={`${inputCls} mt-1`} onChange={(event) => { setClassName(event.target.value); setSelectedSpells([]); setPreparedSpellIds([]); setSelectedClassSkills([]); }} value={className}><option value="">选择职业</option>{CLASSES_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · d{item.hitDie} · {item.primary}</option>)}</select></label>
          <label className="text-xs text-stone-400">背景（2024核心）<select className={`${inputCls} mt-1`} onChange={(event) => { setBackground(event.target.value); setSelectedClassSkills([]); }} value={background}><option value="">选择背景</option>{BACKGROUNDS_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.skills.join("、")}</option>)}</select></label>
          {selectedSpecies ? <div className="rounded border border-ink-700 bg-ink-950/50 p-2 text-xs text-stone-400"><strong className="text-parchment-100">{selectedSpecies.name}</strong> · 速度 {selectedSpecies.speed}尺 · {selectedSpecies.size}<br />{selectedSpecies.features.join("、")}</div> : null}
          {selectedClass ? <div className="rounded border border-ink-700 bg-ink-950/50 p-2 text-xs text-stone-400"><strong className="text-parchment-100">{selectedClass.name}</strong> · d{selectedClass.hitDie}生命骰 · 豁免 {selectedClass.saves.join("、")}<br />{selectedClass.proficiencies.join("、")}</div> : null}
          {selectedBackground ? <div className="rounded border border-ink-700 bg-ink-950/50 p-2 text-xs text-stone-400"><strong className="text-parchment-100">{selectedBackground.name}</strong> · 技能 {selectedBackground.skills.join("、")} · {selectedBackground.feat}</div> : null}
          <p className="m-0 text-2xs leading-5 text-stone-600 md:col-span-2">先创建 1 级角色。种族、职业和背景会写入角色卡，后续可以继续扩展熟练项、法术和职业特性。</p>
        </div>
      ) : null}
      {step === 2 ? (
        <div>
          <div className="mb-3 flex items-center justify-between"><p className="m-0 text-xs text-stone-400">分配六项属性</p><Button onClick={standardArray} size="sm">使用标准数组 15/14/13/12/10/8</Button></div>
          <div className="overflow-x-auto rounded border border-ink-700"><table className="w-full min-w-[620px] text-xs"><thead className="bg-ink-950 text-stone-500"><tr><th className="px-3 py-2 text-left">属性</th><th className="px-3 py-2 text-left">数值</th><th className="px-3 py-2 text-left">调整值</th><th className="px-3 py-2 text-left">用途提示</th></tr></thead><tbody>{Object.entries(ABILITY_LABELS).map(([key, label]) => { const score = Number(abilities[key]); return <tr className="border-t border-ink-800" key={key}><td className="px-3 py-2 text-parchment-100">{label}</td><td className="px-3 py-2"><input aria-label={`${label}数值`} className={`${inputCls} w-24`} max="30" min="1" onChange={(event) => setAbility(key, event.target.value)} type="number" value={abilities[key]} /></td><td className="px-3 py-2 font-mono text-violet-300">{modifier(score)}</td><td className="px-3 py-2 text-stone-500">{key === "dexterity" ? "先攻、敏捷技能、AC" : key === "constitution" ? "生命值与体质豁免" : "相关技能与豁免"}</td></tr>; })}</tbody></table></div>
        </div>
      ) : null}
      {step === 3 ? (
        <div>
          <div className="rounded border border-ink-700 bg-ink-950/50 p-3 text-xs text-stone-400">
            <strong className="text-parchment-100">子职</strong>
            <p className="mb-0 mt-1">当前创建的是1级角色。D&D 5e 2024核心职业通常在3级选择子职，因此现在不会强制选择；达到解锁等级时，升级界面会展示 {characterOptions.data?.classes.find((item) => item.name === className)?.subclasses.filter((item) => !item.name.includes("法术列表")).map((item) => item.name).join("、") || "该职业的全部子职"}。</p>
          </div>
          <div className="mt-3 rounded border border-ink-700 p-3">
            <div className="flex items-center gap-2">
              <strong className="mr-auto text-sm text-parchment-100">职业技能熟练</strong>
              <Badge tone={selectedClassSkills.length === skillRule.count ? "ok" : "warn"}>
                {selectedClassSkills.length}/{skillRule.count}
              </Badge>
            </div>
            <p className="mb-2 mt-1 text-2xs text-stone-600">背景已固定提供：{selectedBackground?.skills.join("、") || "无"}。从职业列表中恰好选择 {skillRule.count} 项；与背景重复的技能已排除。</p>
            <div className="flex flex-wrap gap-2">
              {skillRule.choices.map((skill) => (
                <label className={`cursor-pointer rounded border px-2 py-1 text-xs ${selectedClassSkills.includes(skill) ? "border-emerald-500 bg-emerald-950/20 text-emerald-200" : "border-ink-700 text-stone-400"}`} key={skill}>
                  <input
                    checked={selectedClassSkills.includes(skill)}
                    className="mr-1"
                    onChange={(event) => {
                      if (!event.target.checked) setSelectedClassSkills((current) => current.filter((item) => item !== skill));
                      else if (selectedClassSkills.length < skillRule.count) setSelectedClassSkills((current) => [...current, skill]);
                      else showToast(`该职业只能选择 ${skillRule.count} 项技能熟练`, "error");
                    }}
                    type="checkbox"
                  />
                  {skill}
                </label>
              ))}
            </div>
          </div>
          {selectedClass?.spellcasting ? (
            <div className="mt-3">
              <div className="flex flex-wrap items-center gap-2">
                <strong className="mr-auto text-sm text-parchment-100">选择初始法术</strong>
                <Badge tone={spellCounts.cantrips === spellLimits.cantrips && spellCounts.leveled === spellLimits.leveled ? "ok" : "warn"}>
                  戏法 {spellCounts.cantrips}/{spellLimits.cantrips} · {spellLimits.leveledLabel} {spellCounts.leveled}/{spellLimits.leveled}
                </Badge>
                <input aria-label="搜索法术" className={`${inputCls} max-w-xs`} onChange={(event) => setSpellSearch(event.target.value)} placeholder="搜索全部2024法术" value={spellSearch} />
              </div>
              <p className="text-2xs text-stone-600">只显示该职业可用的2024法术。必须恰好选择 {spellLimits.cantrips} 个戏法和 {spellLimits.leveled} 个{spellLimits.leveledLabel}；1环法术共用法术位，不是每个法术各有次数。</p>
              <div className="max-h-72 overflow-y-auto rounded border border-ink-700 p-2">
                <div className="grid gap-2 sm:grid-cols-2">
                  {availableSpells.filter((spell) => !spellSearch.trim() || `${spell.name} ${spell.source_path}`.toLowerCase().includes(spellSearch.trim().toLowerCase())).map((spell) => (
                    <label className={`flex cursor-pointer items-start gap-2 rounded border p-2 text-xs ${selectedSpells.includes(spell.source_record_id) ? "border-violet-500 bg-violet-950/20" : "border-ink-700"}`} key={spell.source_record_id}>
                      <input checked={selectedSpells.includes(spell.source_record_id)} onChange={(event) => toggleSpell(spell.source_record_id, spell.level, event.target.checked)} type="checkbox" />
                      <span><strong className="block text-parchment-100">{spell.name} · {spell.level === 0 ? "戏法" : `${spell.level}环`}</strong><span className="text-2xs text-stone-600">{spell.casting_time || "施法时间未记录"} · {spell.range || "距离未记录"} · {spell.damage_expression || "叙事/辅助效果"}</span></span>
                    </label>
                  ))}
                </div>
              </div>
              {preparedRequired > 0 ? (
                <div className="mt-3 rounded border border-sky-800/60 bg-sky-950/15 p-2">
                  <p className="mb-2 mt-0 text-xs text-sky-200">法师准备栏：从已选的6个1环法术中恰好准备 {preparedRequired} 个（当前 {preparedCount}/{preparedRequired}）。只有已准备法术会出现在战斗动作栏；戏法始终可用。</p>
                  <div className="flex flex-wrap gap-2">
                    {availableSpells.filter((spell) => spell.level === 1 && selectedSpells.includes(spell.source_record_id)).map((spell) => (
                      <label className={`rounded border px-2 py-1 text-xs ${preparedSpellIds.includes(spell.source_record_id) ? "border-sky-500 text-sky-200" : "border-ink-700 text-stone-500"}`} key={`prepared-${spell.source_record_id}`}>
                        <input checked={preparedSpellIds.includes(spell.source_record_id)} className="mr-1" onChange={(event) => {
                          if (!event.target.checked) setPreparedSpellIds((current) => current.filter((id) => id !== spell.source_record_id));
                          else if (preparedCount < preparedRequired) setPreparedSpellIds((current) => [...current, spell.source_record_id]);
                          else showToast(`1级法师只能准备 ${preparedRequired} 个1环法术`, "error");
                        }} type="checkbox" />
                        准备 · {spell.name}
                      </label>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : <p className="rounded border border-ink-700 p-3 text-xs text-stone-500">该职业1级没有法术选择；职业资源与动作仍会按规则写入。</p>}
        </div>
      ) : null}
      {step === 4 ? (
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-xs text-stone-400">护甲等级 AC<input className={`${inputCls} mt-1`} max="99" min="0" onChange={(event) => setArmorClass(event.target.value)} type="number" value={armorClass} /></label>
          <label className="text-xs text-stone-400">速度<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setSpeed(event.target.value)} type="number" value={speed} /></label>
          <label className="text-xs text-stone-400">最大生命值 HP<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setHp(event.target.value)} type="number" value={hp} /></label>
          <label className="text-xs text-stone-400">初始装备<input className={`${inputCls} mt-1`} onChange={(event) => setEquipment(event.target.value)} placeholder="用逗号或换行分隔" value={equipment} /></label>
          <div className="rounded border border-ink-700 bg-ink-950/50 p-3 text-xs text-stone-400 md:col-span-2"><strong className="text-parchment-100">{name || "未命名角色"}</strong> · {race || "未设种族"} · {className || "未设职业"} · 1 级<br />创建后可以在角色卡表格中继续编辑。</div>
        </div>
      ) : null}
      <div className="mt-4 flex justify-between border-t border-ink-700 pt-3">
        <Button disabled={step === 1} onClick={() => setStep((current) => current - 1)} size="sm">上一步</Button>
        {step < 4 ? <Button disabled={step === 1 ? (!name.trim() || !race || !className || !background) : step === 3 ? !choicesComplete : false} onClick={() => { if (step === 2) applyDerivedStats(); else setStep((current) => current + 1); }} variant="primary">下一步</Button> : <Button disabled={!name.trim() || Number(hp) < 1 || !choicesComplete} loading={mutation.isPending} onClick={() => mutation.mutate()} variant="primary">确认创建角色</Button>}
      </div>
    </Panel>
  );
}

function CreateForm({ kind, campaignId, onDone }: { kind: EntityKind; campaignId: string | null; onDone: () => void }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [extra, setExtra] = useState("");
  const [secondary, setSecondary] = useState("");
  const [level, setLevel] = useState("1");
  const [hp, setHp] = useState("10");
  const [maxHp, setMaxHp] = useState("10");
  const [race, setRace] = useState("");
  const [armorClass, setArmorClass] = useState("10");
  const [speed, setSpeed] = useState("30");
  const [abilities, setAbilities] = useState<Record<string, string>>({
    strength: "10", dexterity: "10", constitution: "10",
    intelligence: "10", wisdom: "10", charisma: "10",
  });
  const [equipment, setEquipment] = useState("");
  const [alignment, setAlignment] = useState("");
  const [attitude, setAttitude] = useState("");
  const [goal, setGoal] = useState("");
  const [fear, setFear] = useState("");
  const [questType, setQuestType] = useState<"main" | "side" | "personal" | "faction">("side");
  const [giver, setGiver] = useState("");
  const [reward, setReward] = useState("");
  const [xpReward, setXpReward] = useState("0");
  const [playerText, setPlayerText] = useState("");
  const [dmTruth, setDmTruth] = useState("");
  const [verified, setVerified] = useState(false);
  const [allowLegacy, setAllowLegacy] = useState(false);
  const [encumbranceMode, setEncumbranceMode] = useState<"standard" | "variant" | "none">("standard");
  const [enabledRuleExtensions, setEnabledRuleExtensions] = useState<string[]>([]);
  const [enabledContentPacks, setEnabledContentPacks] = useState<string[]>([]);
  const extensionCatalog = useQuery({
    queryKey: ["rule-extensions"],
    queryFn: ({ signal }) => listRuleExtensions(signal),
    enabled: kind === "campaigns",
    staleTime: 5 * 60 * 1000,
  });
  const contentPackCatalog = useQuery({
    queryKey: ["content-packs"],
    queryFn: ({ signal }) => listContentPacks(signal),
    enabled: kind === "campaigns",
    staleTime: 5 * 60 * 1000,
  });
  const mutation = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error("名称不能为空");
      if (kind === "campaigns") return createCampaign({
        name: name.trim(),
        description: description || null,
        allow_legacy: allowLegacy,
        encumbrance_mode: encumbranceMode,
        enabled_rule_extensions: enabledRuleExtensions,
        enabled_content_packs: enabledContentPacks,
      });
      if (!campaignId) throw new Error("尚未选择战役");
      if (kind === "characters") return createCharacter(campaignId, {
        name: name.trim(), race: race || null, class_name: extra || null, level: Number(level),
        armor_class: Number(armorClass), speed: Number(speed),
        ability_scores: Object.fromEntries(
          Object.entries(abilities).map(([key, value]) => [key, Number(value)]),
        ),
        hp: Number(hp), max_hp: Number(maxHp), notes: description || null,
        class_levels: extra ? { [extra === "邪术师" ? "魔契师" : extra]: Number(level) } : {},
        equipment: equipment.split(/\n|、|,/).map((item) => item.trim()).filter(Boolean),
      } satisfies CharacterInput);
      if (kind === "npcs") return createNpc(campaignId, {
        name: name.trim(), description: description || null,
        alignment: alignment || null, attitude: attitude || null,
        personality: extra || null, goal: goal || null, fear: fear || null,
        secrets: secondary || null,
      } satisfies NpcInput);
      if (kind === "quests") return createQuest(campaignId, {
        name: name.trim(), description: description || null, quest_type: questType,
        giver: giver || null, reward: reward || null, xp_reward: Number(xpReward), status: "open",
      } satisfies QuestInput);
      if (kind === "clues") return createClue(campaignId, {
        name: name.trim(), description: description || null,
        player_text: playerText || null, dm_truth: dmTruth || null,
        verified, discovered: false,
      } satisfies ClueInput);
      if (kind === "locations") return createLocation(campaignId, { name: name.trim(), description: description || null } satisfies LocationInput);
      return createEvent(campaignId, { title: name.trim(), description: description || null, event_type: "narrative", occurred_at: new Date().toISOString(), visibility: "dm" } satisfies EventInput);
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [kind, campaignId] });
      void client.invalidateQueries({ queryKey: ["campaigns"] });
      setName(""); setDescription(""); setExtra(""); setSecondary("");
      setRace(""); setEquipment(""); setAlignment(""); setAttitude("");
      setGoal(""); setFear(""); setGiver(""); setReward("");
      setXpReward("0");
      setPlayerText(""); setDmTruth(""); setVerified(false); onDone();
      setAllowLegacy(false); setEncumbranceMode("standard"); setEnabledRuleExtensions([]); setEnabledContentPacks([]);
      showToast(`${META[kind].title}已创建`);
    },
    onError: () => showToast(`${META[kind].title}创建失败`, "error"),
  });
  return (
    <form className="grid gap-2 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event: FormEvent) => { event.preventDefault(); mutation.mutate(); }}>
      <input className={inputCls} onChange={(event) => setName(event.target.value)} placeholder={META[kind].name} value={name} />
      <input className={inputCls} onChange={(event) => setDescription(event.target.value)} placeholder={META[kind].description} value={description} />
      {kind === "campaigns" ? (
        <div className="grid gap-3 rounded-lg border border-ember-800/50 bg-ink-950/45 p-3 md:col-span-2 xl:col-span-4">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-stone-300">
              <input checked={allowLegacy} onChange={(event) => {
                const next = event.target.checked;
                setAllowLegacy(next);
                if (!next) {
                  setEnabledRuleExtensions((current) => current.filter((key) => !extensionCatalog.data?.items.find((item) => item.key === key)?.requires_legacy));
                }
              }} type="checkbox" />
              允许旧版 / 变体规则
            </label>
            <label className="flex items-center gap-2 text-xs text-stone-300">
              负重
              <select className={`${inputCls} !w-auto`} onChange={(event) => setEncumbranceMode(event.target.value as typeof encumbranceMode)} value={encumbranceMode}>
                <option value="standard">标准负重</option>
                <option value="variant">变体负重</option>
                <option value="none">关闭负重</option>
              </select>
            </label>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-parchment-100">开团时启用规则扩展（默认不启用）</p>
            {extensionCatalog.isLoading ? <p className="m-0 text-2xs text-stone-500">正在读取本地 D&D 规则目录…</p> : null}
            {extensionCatalog.isError ? <p className="m-0 text-2xs text-red-300">规则目录读取失败；仍可创建核心 2024 规则团。</p> : null}
            <div className="grid gap-2 md:grid-cols-2">
              {(extensionCatalog.data?.items ?? []).map((extension: RuleExtension) => (
                <label className={`rounded border p-2 text-xs ${extension.requires_legacy && !allowLegacy ? "border-ink-800 opacity-50" : "border-ink-700 hover:border-ember-700/60"}`} key={extension.key}>
                  <span className="flex items-start gap-2">
                    <input
                      checked={enabledRuleExtensions.includes(extension.key)}
                      disabled={extension.requires_legacy && !allowLegacy}
                      onChange={(event) => setEnabledRuleExtensions((current) => event.target.checked ? [...current, extension.key] : current.filter((key) => key !== extension.key))}
                      type="checkbox"
                    />
                    <span><strong className="text-parchment-100">{extension.label}</strong><span className="ml-2 text-[10px] text-stone-500">{extension.category} · {extension.automation_status === "full" ? "自动" : extension.automation_status === "partial" ? "部分自动" : "DM裁定"}</span><span className="mt-1 block text-2xs text-stone-500">{extension.summary}</span></span>
                  </span>
                </label>
              ))}
            </div>
            <p className="mb-0 mt-2 text-2xs text-stone-600">扩展会同时写入本团的规则原子库与规则积木；未实现自动结算的部分会明确标记为 DM 裁定，不会猜数字。</p>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-parchment-100">开团时启用本地资料书内容包（默认不启用）</p>
            {contentPackCatalog.isLoading ? <p className="m-0 text-2xs text-stone-500">正在核对本地资料书可导入内容…</p> : null}
            {contentPackCatalog.isError ? <p className="m-0 text-2xs text-red-300">资料书目录读取失败；仍可创建核心 2024 规则团。</p> : null}
            <div className="grid gap-2 md:grid-cols-2">
              {(contentPackCatalog.data?.items ?? []).map((pack: ContentPack) => (
                <label className="rounded border border-ink-700 p-2 text-xs hover:border-ember-700/60" key={pack.key}>
                  <span className="flex items-start gap-2">
                    <input
                      checked={enabledContentPacks.includes(pack.key)}
                      onChange={(event) => setEnabledContentPacks((current) => event.target.checked ? [...current, pack.key] : current.filter((key) => key !== pack.key))}
                      type="checkbox"
                    />
                    <span>
                      <strong className="text-parchment-100">{pack.label}</strong>
                      <span className="ml-2 text-[10px] text-stone-500">{pack.available_entries} 条可检索</span>
                      <span className="mt-1 block text-2xs text-stone-500">{pack.summary}</span>
                      <span className="mt-1 block text-2xs text-stone-600">已导入 {pack.status_counts.imported} · 待标准化 {pack.status_counts.needs_normalization}</span>
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <p className="mb-0 mt-2 text-2xs text-stone-600">启用后，资料库、角色法术选项和玩家规则查询都会只显示本团选中的资料书；待标准化条目保留原文与来源，不会伪装成可自动执行的职业成长或规则。</p>
          </div>
        </div>
      ) : null}
      {kind === "characters" ? (
        <>
          <input className={inputCls} onChange={(event) => setRace(event.target.value)} placeholder="种族" value={race} />
          <input className={inputCls} onChange={(event) => setExtra(event.target.value)} placeholder="职业" value={extra} />
          <input className={inputCls} max="20" min="1" onChange={(event) => setLevel(event.target.value)} placeholder="等级" type="number" value={level} />
          <input className={inputCls} max="99" min="0" onChange={(event) => setArmorClass(event.target.value)} placeholder="护甲等级 AC" type="number" value={armorClass} />
          <input className={inputCls} min="0" onChange={(event) => setSpeed(event.target.value)} placeholder="速度" type="number" value={speed} />
          <input className={inputCls} min="0" onChange={(event) => setHp(event.target.value)} placeholder="当前 HP" type="number" value={hp} />
          <input className={inputCls} min="0" onChange={(event) => setMaxHp(event.target.value)} placeholder="最大 HP" type="number" value={maxHp} />
          {Object.entries({ strength: "力量", dexterity: "敏捷", constitution: "体质", intelligence: "智力", wisdom: "感知", charisma: "魅力" }).map(([key, label]) => (
            <input
              aria-label={label}
              className={inputCls}
              key={key}
              max="30"
              min="1"
              onChange={(event) => setAbilities((current) => ({ ...current, [key]: event.target.value }))}
              placeholder={label}
              type="number"
              value={abilities[key]}
            />
          ))}
          <input className={`${inputCls} md:col-span-2`} onChange={(event) => setEquipment(event.target.value)} placeholder="装备（用逗号或换行分隔）" value={equipment} />
        </>
      ) : null}
      {kind === "npcs" ? (
        <>
          <input className={inputCls} onChange={(event) => setAlignment(event.target.value)} placeholder="阵营" value={alignment} />
          <input className={inputCls} onChange={(event) => setAttitude(event.target.value)} placeholder="对队伍态度" value={attitude} />
          <input className={inputCls} onChange={(event) => setExtra(event.target.value)} placeholder="性格" value={extra} />
          <input className={inputCls} onChange={(event) => setGoal(event.target.value)} placeholder="目标" value={goal} />
          <input className={inputCls} onChange={(event) => setFear(event.target.value)} placeholder="恐惧 / 弱点" value={fear} />
          <input className={inputCls} onChange={(event) => setSecondary(event.target.value)} placeholder="DM 私密信息" value={secondary} />
        </>
      ) : null}
      {kind === "quests" ? (
        <>
          <select className={inputCls} onChange={(event) => setQuestType(event.target.value as typeof questType)} value={questType}>
            <option value="main">主线</option><option value="side">支线</option>
            <option value="personal">个人</option><option value="faction">阵营</option>
          </select>
          <input className={inputCls} onChange={(event) => setGiver(event.target.value)} placeholder="发布者" value={giver} />
          <input className={inputCls} onChange={(event) => setReward(event.target.value)} placeholder="奖励" value={reward} />
          <input className={inputCls} min="0" onChange={(event) => setXpReward(event.target.value)} placeholder="每名玩家 XP" type="number" value={xpReward} />
        </>
      ) : null}
      {kind === "clues" ? (
        <>
          <input className={inputCls} onChange={(event) => setPlayerText(event.target.value)} placeholder="玩家可见版本" value={playerText} />
          <input className={inputCls} onChange={(event) => setDmTruth(event.target.value)} placeholder="DM 真相（私密）" value={dmTruth} />
          <label className="flex items-center gap-2 text-xs text-stone-400">
            <input checked={verified} onChange={(event) => setVerified(event.target.checked)} type="checkbox" /> 已验证
          </label>
        </>
      ) : null}
      <Button disabled={!name.trim() || (kind === "characters" && (Number(hp) > Number(maxHp) || Number(maxHp) < 0))} loading={mutation.isPending} type="submit" variant="primary" icon="plus">新建</Button>
      {mutation.isError ? <p className="m-0 text-xs text-red-300 md:col-span-full">{mutation.error instanceof Error ? mutation.error.message : "创建失败，请重试。"}</p> : null}
    </form>
  );
}

async function updateRow(
  kind: EntityKind,
  campaignId: string | null,
  row: Record<string, unknown>,
  name: string,
  description: string,
  detail: Record<string, string>,
) {
  const id = display(row.id, "");
  const version = typeof row.version === "number" ? row.version : 0;
  if (kind === "campaigns") return updateCampaign(id, {
    name,
    description: description || null,
    status: detail.status || "active",
  }, version);
  if (!campaignId) throw new Error("尚未选择战役");
  if (kind === "characters") return updateCharacter(campaignId, id, {
    name, notes: description || null, race: detail.race || null,
    class_name: detail.class_name || null, level: Number(detail.level),
    armor_class: Number(detail.armor_class), speed: Number(detail.speed),
    hp: Number(detail.hp), max_hp: Number(detail.max_hp),
    equipment: (detail.equipment ?? "").split(/\n|、|,/).map((item) => item.trim()).filter(Boolean),
  }, version);
  if (kind === "npcs") return updateNpc(campaignId, id, {
    name, description: description || null, alignment: detail.alignment || null,
    attitude: detail.attitude || null, personality: detail.personality || null,
    goal: detail.goal || null, fear: detail.fear || null, secrets: detail.secrets || null,
  }, version);
  if (kind === "quests") return updateQuest(campaignId, id, {
    name, description: description || null,
    quest_type: detail.quest_type as "main" | "side" | "personal" | "faction",
    giver: detail.giver || null, reward: detail.reward || null,
    xp_reward: Number(detail.xp_reward), status: detail.status,
  }, version);
  if (kind === "clues") return updateClue(campaignId, id, {
    name, description: description || null, player_text: detail.player_text || null,
    dm_truth: detail.dm_truth || null, verified: detail.verified === "true",
    discovered: detail.discovered === "true",
  }, version);
  if (kind === "locations") return updateLocation(campaignId, id, { name, description: description || null }, version);
  return updateEvent(campaignId, id, { title: name, description: description || null }, version);
}

async function removeRow(kind: EntityKind, campaignId: string | null, row: Record<string, unknown>) {
  const id = display(row.id, "");
  const version = typeof row.version === "number" ? row.version : 0;
  if (kind === "campaigns") return deleteCampaign(id, version);
  if (!campaignId) throw new Error("尚未选择战役");
  if (kind === "characters") return deleteCharacter(campaignId, id, version);
  if (kind === "npcs") return deleteNpc(campaignId, id, version);
  if (kind === "quests") return deleteQuest(campaignId, id, version);
  if (kind === "clues") return deleteClue(campaignId, id, version);
  if (kind === "locations") return deleteLocation(campaignId, id, version);
  return deleteEvent(campaignId, id, version);
}

function QuestXpAward({ campaignId, quest }: { campaignId: string; quest: Record<string, unknown> }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const characters = useQuery({
    queryKey: ["characters", campaignId],
    queryFn: ({ signal }) => listCharacters(campaignId, signal),
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const xp = Number(quest.xp_reward ?? 0);
  const awarded = quest.xp_awarded === true;
  const award = useMutation({
    mutationFn: async () => {
      const recipients = (characters.data ?? []).filter((character) => selected.has(character.id));
      if (recipients.length === 0 || xp <= 0) throw new Error("请选择玩家并设置大于 0 的任务经验");
      for (const character of recipients) {
        await updateCharacter(campaignId, character.id, {
          experience: character.experience + xp,
        }, character.version);
      }
      return updateQuest(campaignId, String(quest.id), {
        xp_awarded: true,
        status: "completed",
      }, Number(quest.version));
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      void client.invalidateQueries({ queryKey: ["quests", campaignId] });
      showToast(`任务经验已发放：每名所选玩家 ${xp} XP`);
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "任务经验发放失败", "error"),
  });
  if (awarded) return <p className="mb-0 mt-2 text-2xs text-emerald-300">该任务经验已由 DM 确认发放，已锁定避免重复领取。</p>;
  return (
    <div className="mt-3 rounded border border-ink-700 bg-ink-950/40 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-2xs text-stone-500">完成任务后选择获得经验的玩家：</span>
        {(characters.data ?? []).map((character) => <label className="flex items-center gap-1 text-2xs text-parchment-100" key={character.id}><input checked={selected.has(character.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); if (event.target.checked) next.add(character.id); else next.delete(character.id); return next; })} type="checkbox" />{character.name}</label>)}
        <Button disabled={selected.size === 0 || xp <= 0} loading={award.isPending} onClick={() => award.mutate()} size="sm" variant="primary">DM 确认发放 {xp} XP/人</Button>
      </div>
    </div>
  );
}

function RowCard({ kind, campaignId, row }: { kind: EntityKind; campaignId: string | null; row: Record<string, unknown> }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const originalName = display(row.name ?? row.title, "未命名");
  const originalDescription = display(row.description ?? row.notes ?? row.known_information, "");
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [name, setName] = useState(originalName);
  const [description, setDescription] = useState(originalDescription);
  const [detail, setDetail] = useState<Record<string, string>>(() => ({
    race: display(row.race, ""),
    class_name: display(row.class_name, ""),
    level: display(row.level, "1"),
    armor_class: display(row.armor_class, "10"),
    speed: display(row.speed, "30"),
    hp: display(row.hp, "0"),
    max_hp: display(row.max_hp, "0"),
    equipment: Array.isArray(row.equipment) ? row.equipment.map(String).join(", ") : "",
    alignment: display(row.alignment, ""),
    attitude: display(row.attitude, ""),
    personality: display(row.personality, ""),
    goal: display(row.goal, ""),
    fear: display(row.fear, ""),
    secrets: display(row.secrets, ""),
    quest_type: display(row.quest_type, "side"),
    giver: display(row.giver, ""),
    reward: display(row.reward, ""),
    xp_reward: display(row.xp_reward, "0"),
    status: display(row.status, kind === "quests" ? "open" : "active"),
    player_text: display(row.player_text, ""),
    dm_truth: display(row.dm_truth, ""),
    verified: row.verified === true ? "true" : "false",
    discovered: row.discovered === true ? "true" : "false",
  }));
  const setDetailValue = (key: string, value: string) => {
    setDetail((current) => ({ ...current, [key]: value }));
  };
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: [kind, campaignId] });
    void client.invalidateQueries({ queryKey: ["campaigns"] });
    if (campaignId) void client.invalidateQueries({ queryKey: ["campaign-state", campaignId] });
  };
  const save = useMutation({
    mutationFn: () => updateRow(kind, campaignId, row, name.trim(), description, detail),
    onSuccess: () => { setEditing(false); invalidate(); showToast(`${META[kind].title}已保存`); },
    onError: () => showToast("保存失败，请刷新后重试", "error"),
  });
  const remove = useMutation({
    mutationFn: () => removeRow(kind, campaignId, row),
    onSuccess: () => { setConfirming(false); invalidate(); showToast(`${META[kind].title}已删除`); },
    onError: (error) => showToast(
      kind === "locations" && error instanceof Error && /site|managed|建筑|地下城|楼层|房间/i.test(error.message)
        ? "这是生成建筑/地下城托管的地点，请在地点页上方选择整座建筑或地下城后安全删除"
        : "删除失败，请重试",
      "error",
    ),
  });
  const archive = useMutation({
    mutationFn: () => updateCampaign(
      display(row.id, ""),
      { status: detail.status === "archived" ? "active" : "archived" },
      Number(row.version),
    ),
    onSuccess: (campaign) => {
      setDetailValue("status", campaign.status);
      invalidate();
      showToast(campaign.status === "archived" ? "跑团已归档" : "跑团已恢复");
    },
    onError: () => showToast("归档状态更新失败，请刷新后重试", "error"),
  });
  return (
    <li className="py-3">
      {editing ? (
        <form className="grid gap-2 md:grid-cols-4" onSubmit={(event) => { event.preventDefault(); if (name.trim()) save.mutate(); }}>
          <input className={inputCls} onChange={(event) => setName(event.target.value)} value={name} />
          <input className={`${inputCls} md:col-span-2`} onChange={(event) => setDescription(event.target.value)} placeholder="描述 / 备注" value={description} />
          <div className="flex justify-end gap-1.5">
            <Button onClick={() => setEditing(false)} size="sm">取消</Button>
            <Button disabled={!name.trim()} loading={save.isPending} size="sm" type="submit" variant="primary">保存</Button>
          </div>
          {kind === "campaigns" ? (
            <label className="text-2xs text-stone-500">跑团状态
              <select className={`${inputCls} mt-1`} onChange={(event) => setDetailValue("status", event.target.value)} value={detail.status}>
                <option value="active">进行中</option>
                <option value="archived">已归档</option>
              </select>
            </label>
          ) : null}
          {kind === "characters" ? (
            <>
              <input className={inputCls} onChange={(event) => setDetailValue("race", event.target.value)} placeholder="种族" value={detail.race} />
              <input className={inputCls} onChange={(event) => setDetailValue("class_name", event.target.value)} placeholder="职业" value={detail.class_name} />
              {(["level", "armor_class", "speed", "hp", "max_hp"] as const).map((field) => (
                <input className={inputCls} key={field} min="0" onChange={(event) => setDetailValue(field, event.target.value)} placeholder={field} type="number" value={detail[field]} />
              ))}
              <input className={`${inputCls} md:col-span-2`} onChange={(event) => setDetailValue("equipment", event.target.value)} placeholder="装备" value={detail.equipment} />
            </>
          ) : null}
          {kind === "npcs" ? (
            <>
              {(["alignment", "attitude", "personality", "goal", "fear", "secrets"] as const).map((field) => (
                <input className={inputCls} key={field} onChange={(event) => setDetailValue(field, event.target.value)} placeholder={field} value={detail[field]} />
              ))}
            </>
          ) : null}
          {kind === "quests" ? (
            <>
              <select className={inputCls} onChange={(event) => setDetailValue("quest_type", event.target.value)} value={detail.quest_type}>
                <option value="main">主线</option><option value="side">支线</option>
                <option value="personal">个人</option><option value="faction">阵营</option>
              </select>
              <input className={inputCls} onChange={(event) => setDetailValue("giver", event.target.value)} placeholder="发布者" value={detail.giver} />
              <input className={inputCls} onChange={(event) => setDetailValue("reward", event.target.value)} placeholder="奖励" value={detail.reward} />
              <input className={inputCls} min="0" onChange={(event) => setDetailValue("xp_reward", event.target.value)} placeholder="每名玩家 XP" type="number" value={detail.xp_reward} />
              <input className={inputCls} onChange={(event) => setDetailValue("status", event.target.value)} placeholder="状态" value={detail.status} />
            </>
          ) : null}
          {kind === "clues" ? (
            <>
              <input className={inputCls} onChange={(event) => setDetailValue("player_text", event.target.value)} placeholder="玩家可见版本" value={detail.player_text} />
              <input className={inputCls} onChange={(event) => setDetailValue("dm_truth", event.target.value)} placeholder="DM 真相" value={detail.dm_truth} />
              <label className="flex items-center gap-2 text-xs text-stone-400"><input checked={detail.verified === "true"} onChange={(event) => setDetailValue("verified", String(event.target.checked))} type="checkbox" />已验证</label>
              <label className="flex items-center gap-2 text-xs text-stone-400"><input checked={detail.discovered === "true"} onChange={(event) => setDetailValue("discovered", String(event.target.checked))} type="checkbox" />已发现</label>
            </>
          ) : null}
          {save.isError ? <p className="m-0 text-xs text-red-300 md:col-span-full">保存失败，数据可能已被其他操作更新，请刷新后重试。</p> : null}
        </form>
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="m-0 text-sm font-medium text-parchment-100">{originalName}</p>
            {kind === "campaigns" ? <Badge tone={detail.status === "archived" ? "neutral" : "ok"}>{detail.status === "archived" ? "已归档" : "进行中"}</Badge> : null}
            <p className="prose-block mb-0 mt-1 text-xs text-stone-500">{originalDescription || "暂无描述"}</p>
            {kind === "characters" ? <p className="mb-0 mt-1 text-2xs text-ember-300/80">{display(row.race, "未设种族")} · {display(row.class_name, "未设职业")} Lv{display(row.level, "1")} · AC {display(row.armor_class, "10")} · 速度 {display(row.speed, "30")} · HP {display(row.hp, "0")}/{display(row.max_hp, "0")}</p> : null}
            {kind === "npcs" ? (
              <>
                <p className="mb-0 mt-1 text-2xs text-violet-300">{display(row.alignment, "阵营未定")} · {display(row.attitude, "态度未定")}{row.secrets ? " · DM 私密信息已设置" : ""}</p>
                <p className="mb-0 mt-1 text-2xs text-stone-400">HP {display(row.hp, "0")}/{display(row.max_hp, "0")} · 护甲 AC {display(row.armor_class, "10")} · 速度 {display(row.speed, "30")} · CR {display(row.challenge_rating, "—")}</p>
                <div className="mt-2 grid max-w-md grid-cols-6 gap-1">
                  {Object.entries(ABILITY_LABELS).map(([key, label]) => <span className="rounded border border-ink-700 bg-ink-950/60 px-1 py-1 text-center text-2xs text-stone-400" key={key}>{label.slice(0, 1)} <strong className="text-parchment-100">{display((row.ability_scores as Record<string, unknown> | undefined)?.[key], "10")}</strong></span>)}
                </div>
              </>
            ) : null}
            {kind === "quests" ? <p className="mb-0 mt-1 text-2xs text-amber-300">{display(row.quest_type, "side")} · {display(row.status, "open")}{row.giver ? ` · 发布者 ${display(row.giver, "")}` : ""}{row.reward ? ` · 奖励 ${display(row.reward, "")}` : ""} · {display(row.xp_reward, "0")} XP/人 · {row.xp_awarded === true ? "已发放" : "未发放"}</p> : null}
            {kind === "clues" ? <p className="mb-0 mt-1 text-2xs text-stone-500">{row.discovered === true ? "已发现" : "未发现"} · {row.verified === true ? "已验证" : "未验证"}{row.dm_truth ? " · DM 真相已记录" : ""}</p> : null}
            <p className="mb-0 mt-1 text-2xs text-stone-700">{typeof row.updated_at === "string" ? `更新于 ${formatDateTime(row.updated_at)} · v${display(row.version, "1")}` : ""}</p>
          </div>
          <div className="flex gap-1.5">
            {kind === "campaigns" ? <Button loading={archive.isPending} onClick={() => archive.mutate()} size="sm">{detail.status === "archived" ? "恢复" : "归档"}</Button> : null}
            <Button onClick={() => setEditing(true)} size="sm">编辑</Button>
            <Button onClick={() => setConfirming(true)} size="sm" variant="danger">删除</Button>
          </div>
        </div>
      )}
      {kind === "quests" && campaignId ? <QuestXpAward campaignId={campaignId} quest={row} /> : null}
      <ConfirmDialog body={`确认删除“${originalName}”？相关数据可能一并删除，此操作无法撤销。`} confirmLabel="确认删除" loading={remove.isPending} onCancel={() => setConfirming(false)} onConfirm={() => remove.mutate()} open={confirming} title={`删除${META[kind].title}`} />
    </li>
  );
}

function ManagementContent({ kind, campaignId }: { kind: EntityKind; campaignId: string | null }): ReactElement {
  const [showArchived, setShowArchived] = useState(false);
  const rows = useRows(kind, campaignId);
  const meta = META[kind];
  if (kind === "characters" && campaignId) return <CharacterWorkspace campaignId={campaignId} />;
  const visibleRows = kind === "campaigns" && !showArchived
    ? rows.data?.filter((row) => row.status !== "archived")
    : rows.data;
  return (
    <div className="mx-auto max-w-[1200px] p-4 lg:p-6">
      <Panel eyebrow={meta.eyebrow} title={`${meta.title}管理`}>
        <CreateForm campaignId={campaignId} kind={kind} onDone={() => undefined} />
      </Panel>
      <Panel className="mt-4" eyebrow="记录" title={`${meta.title}列表`}>
        {kind === "campaigns" ? (
          <div className="mb-3 flex items-center justify-between gap-3 rounded border border-ink-700 bg-ink-950/40 p-2">
            <span className="text-xs text-stone-500">主切团菜单默认只显示进行中的团；归档不会删除任何数据。</span>
            <label className="flex shrink-0 items-center gap-2 text-xs text-stone-300">
              <input checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} type="checkbox" />
              显示已归档
            </label>
          </div>
        ) : null}
        {rows.isLoading ? <LoadingBlock /> : null}
        {rows.isError ? <ErrorState error={rows.error} onRetry={() => void rows.refetch()} /> : null}
        {!rows.isLoading && !rows.isError && visibleRows?.length === 0 ? <EmptyState title={kind === "campaigns" && !showArchived ? "没有进行中的跑团" : `还没有${meta.title}`} hint={kind === "campaigns" && !showArchived ? "创建新团，或打开“显示已归档”恢复旧团。" : "使用上方表单创建第一条记录。"} /> : null}
        {visibleRows && visibleRows.length > 0 ? (
          <ul className="m-0 divide-y divide-ink-700/60 p-0">
            {visibleRows.map((row) => <RowCard campaignId={campaignId} key={display(row.id, "")} kind={kind} row={row} />)}
          </ul>
        ) : null}
      </Panel>
    </div>
  );
}

export function ManagementPage({ kind }: { kind: EntityKind }): ReactElement {
  if (kind === "campaigns") return <ManagementContent campaignId={null} kind={kind} />;
  return <RequireCampaign>{(id) => <ManagementContent campaignId={id} kind={kind} />}</RequireCampaign>;
}
