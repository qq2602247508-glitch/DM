import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type ChangeEvent, type FormEvent, type ReactElement } from "react";

import { createCampaign, deleteCampaign, listCampaigns, updateCampaign } from "../api/campaigns";
import {
  createCharacter, createClue, createEvent, createLocation, createNpc, createQuest,
  deleteCharacter, deleteClue, deleteEvent, deleteLocation, deleteNpc, deleteQuest,
  listCharacters, listClues, listEvents, listLocations, listNpcs, listQuests,
  updateCharacter, updateClue, updateEvent, updateLocation, updateNpc, updateQuest,
  type CharacterInput, type ClueInput, type EventInput, type LocationInput, type NpcInput, type QuestInput,
} from "../api/entities";
import type { Campaign, CampaignEvent, Character, Clue, Location, Npc, Quest } from "../api/types";
import { Panel } from "../components/Panel";
import { RestPanel } from "../components/RestPanel";
import { RequireCampaign } from "../components/RequireCampaign";
import { inputCls } from "../ui/styles";
import { Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { formatDateTime } from "../ui/format";
import { ConfirmDialog } from "../ui/widgets";
import { useToast } from "../hooks/toastContext";
import { BACKGROUNDS_2024, CLASSES_2024, SPECIES_2024 } from "../ui/characterRules";
import { averageHpGain, levelFromXp, nextLevelXp, XP_THRESHOLDS } from "../ui/progressionRules";

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

function actionName(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null) {
    const name = (value as { name?: unknown }).name;
    return typeof name === "string" || typeof name === "number" ? String(name) : "";
  }
  return "";
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

const LEVEL_FEATURE_CHOICES = [
  "属性值提升", "警觉", "幸运", "健壮", "熟练", "战地施法者",
  "哨兵", "神射手", "巨武器大师", "防御式决斗", "技能专家", "魔法学徒",
];

function CharacterProgressCell({ campaignId, character }: { campaignId: string; character: Character }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [feature, setFeature] = useState("");
  const classRule = CLASSES_2024.find((item) => item.name === character.class_name);
  const nextThreshold = nextLevelXp(character.level);
  const eligibleLevel = levelFromXp(character.experience);
  const canLevel = eligibleLevel > character.level && character.level < 20;
  const currentFloor = XP_THRESHOLDS[Math.max(0, character.level - 1)] ?? 0;
  const progress = nextThreshold === null ? 100 : Math.max(0, Math.min(100,
    ((character.experience - currentFloor) / Math.max(1, nextThreshold - currentFloor)) * 100,
  ));
  const hpGain = averageHpGain(classRule?.hitDie ?? 8, character.ability_scores.constitution ?? 10);
  const levelUp = useMutation({
    mutationFn: () => updateCharacter(campaignId, character.id, {
      level: character.level + 1,
      hp: character.hp + hpGain,
      max_hp: character.max_hp + hpGain,
      features: feature ? [...character.features, `Lv${character.level + 1}：${feature}`] : character.features,
      resources: Object.fromEntries(Object.entries(character.resources).map(([key, raw]) => {
        const resource = raw as { current?: number; max?: number; label?: string };
        if (key === "focus") {
          const maximum = Math.max(Number(resource.max ?? 0), character.level + 1);
          return [key, { ...resource, current: maximum, max: maximum }];
        }
        return [key, raw];
      })),
    }, character.version),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      showToast(`${character.name} 已升至 ${character.level + 1} 级，最大生命 +${hpGain}`);
    },
    onError: () => showToast("升级失败，请刷新角色版本后重试", "error"),
  });
  return (
    <td className="min-w-56 px-3 py-3">
      <div className="flex items-center gap-2 text-2xs"><strong className="text-ember-300">{character.experience.toLocaleString()} XP</strong><span className="text-stone-600">/ {nextThreshold?.toLocaleString() ?? "满级"}</span></div>
      <div className="mt-1 h-1.5 overflow-hidden rounded bg-ink-700"><div className="h-full bg-ember-500" style={{ width: `${progress}%` }} /></div>
      {canLevel ? <div className="mt-2 flex gap-1"><select aria-label={`${character.name}升级选择`} className={`${inputCls} min-w-0 py-1 text-2xs`} onChange={(event) => setFeature(event.target.value)} value={feature}><option value="">本级无额外选择</option>{LEVEL_FEATURE_CHOICES.map((item) => <option key={item} value={item}>{item}</option>)}</select><Button loading={levelUp.isPending} onClick={() => levelUp.mutate()} size="sm" variant="primary">升级</Button></div> : null}
      {canLevel ? <p className="mb-0 mt-1 text-2xs text-stone-600">固定平均生命 +{hpGain}；可记录本级专长/技能选择。</p> : null}
    </td>
  );
}

function CharacterToolkit({ campaignId }: { campaignId: string }): ReactElement {
  const { showToast } = useToast();
  const client = useQueryClient();
  const characters = useQuery({
    queryKey: ["characters", campaignId],
    queryFn: ({ signal }) => listCharacters(campaignId, signal),
  });
  const fileRef = useRef<HTMLInputElement>(null);
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
  return (
    <Panel eyebrow="D&D 5e · 2024" title="角色卡工作台">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-auto text-xs text-stone-500">支持手动创建，也支持批量导入 / 导出 JSON、CSV 角色卡。</span>
        <input accept=".json,.csv,application/json,text/csv" className="hidden" onChange={(event) => { void importCharacters(event); }} ref={fileRef} type="file" />
        <Button onClick={() => fileRef.current?.click()} size="sm">导入角色卡</Button>
        <Button disabled={!characters.data?.length} onClick={() => exportCharacters("json")} size="sm">导出 JSON</Button>
        <Button disabled={!characters.data?.length} onClick={() => exportCharacters("csv")} size="sm">导出表格</Button>
        <RestPanel campaignId={campaignId} characters={characters.data ?? []} />
      </div>
      <div className="mt-3 overflow-x-auto rounded-lg border border-ink-700">
        <table className="w-full min-w-[980px] border-collapse text-left text-xs">
          <thead className="bg-ink-950/80 text-2xs uppercase tracking-wide text-stone-500">
            <tr>{["角色", "种族 / 职业 / 背景", "等级", "经验 / 升级", "力量", "敏捷", "体质", "智力", "感知", "魅力", "AC", "HP", "速度", "资源", "动作", "装备"].map((label) => <th className="border-b border-ink-700 px-3 py-2 font-medium" key={label}>{label}</th>)}</tr>
          </thead>
          <tbody>
            {(characters.data ?? []).map((character) => (
              <tr className="border-b border-ink-800/80 last:border-0 hover:bg-ink-900/50" key={character.id}>
                <td className="px-3 py-3 font-medium text-parchment-100">{character.name}</td>
                <td className="px-3 py-3 text-stone-400">{character.race || "—"} / {character.class_name || "—"} / {character.background || "—"}</td>
                <td className="px-3 py-3 font-mono text-ember-300">Lv {character.level}</td>
                <CharacterProgressCell campaignId={campaignId} character={character} />
                {Object.keys(ABILITY_LABELS).map((key) => {
                  const score = character.ability_scores[key] ?? 10;
                  return <td className="px-3 py-3 font-mono text-parchment-100" key={key}>{score} <span className="text-2xs text-violet-300">({modifier(score)})</span></td>;
                })}
                <td className="px-3 py-3 font-mono text-amber-300">{character.armor_class}</td>
                <td className="px-3 py-3 font-mono text-red-300">{character.hp}/{character.max_hp}</td>
                <td className="px-3 py-3 font-mono text-sky-300">{character.speed} 尺</td>
                <td className="max-w-48 px-3 py-3 text-violet-300">{resourceSummary(character.resources) || "—"}</td>
                <td className="max-w-48 px-3 py-3 text-stone-400">{character.actions.map(actionName).filter(Boolean).join("、") || "—"}</td>
                <td className="px-3 py-3 text-stone-400">{character.equipment.length} 件</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-0 mt-3 text-2xs text-stone-600">图片车卡可先用系统 OCR 转为文字后导入；标准 PDF/图片识别接口将在本地 OCR 模块接入后启用。</p>
    </Panel>
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
  campaigns: { title: "战役", eyebrow: "世界", name: "战役名称", description: "世界观与冒险说明" },
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
      return createCharacter(campaignId, {
        name: name.trim(), race: race || null, class_name: className || null,
        background: background || null,
        level: 1, armor_class: Number(armorClass), speed: Number(speed),
        ability_scores: Object.fromEntries(Object.entries(abilities).map(([key, value]) => [key, Number(value)])),
        hp: Number(hp), max_hp: Number(hp), equipment: initialEquipment,
        proficiencies: [...(classRule?.proficiencies ?? []), ...(classRule?.saves.map((item) => `${item}豁免`) ?? [])],
        skills: Object.fromEntries([...(classRule?.defaultSkills ?? []), ...(backgroundRule?.skills ?? [])].map((skill) => [skill, { proficient: true }])),
        features: [...(speciesRule?.features ?? []), ...(backgroundRule ? [`背景专长：${backgroundRule.feat}`] : [])],
        actions: classRule?.actions ?? [],
        resources: classResources,
        spells: [],
        spellcasting: classRule?.spellcasting ?? {},
        notes: `D&D 5e 2024规则角色${background ? ` · 背景：${background}` : ""}`,
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      setStep(1); setName(""); setRace(""); setClassName(""); setBackground(""); setEquipment("");
      showToast("角色卡已创建"); onDone();
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "角色创建失败", "error"),
  });
  const setAbility = (key: string, value: string) => setAbilities((current) => ({ ...current, [key]: value }));
  const standardArray = () => setAbilities({ strength: "15", dexterity: "14", constitution: "13", intelligence: "12", wisdom: "10", charisma: "8" });
  const selectedSpecies = SPECIES_2024.find((item) => item.name === race);
  const selectedBackground = BACKGROUNDS_2024.find((item) => item.name === background);
  const selectedClass = CLASSES_2024.find((item) => item.name === className);
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
        {[["1", "身份"], ["2", "属性"], ["3", "战斗与装备"]].map(([number, label]) => <div className={`flex items-center gap-2 text-xs ${step === Number(number) ? "text-ember-300" : "text-stone-600"}`} key={number}><span className={`flex h-6 w-6 items-center justify-center rounded-full border ${step === Number(number) ? "border-ember-400 bg-ember-500/15" : "border-ink-600"}`}>{number}</span>{label}</div>)}
      </div>
      {step === 1 ? (
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-xs text-stone-400">角色名称<input className={`${inputCls} mt-1`} onChange={(event) => setName(event.target.value)} placeholder="例如：艾拉" value={name} /></label>
          <label className="text-xs text-stone-400">种族（2024核心）<select className={`${inputCls} mt-1`} onChange={(event) => setRace(event.target.value)} value={race}><option value="">选择种族</option>{SPECIES_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.speed}尺</option>)}</select></label>
          <label className="text-xs text-stone-400">职业（全部12个核心职业）<select className={`${inputCls} mt-1`} onChange={(event) => setClassName(event.target.value)} value={className}><option value="">选择职业</option>{CLASSES_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · d{item.hitDie} · {item.primary}</option>)}</select></label>
          <label className="text-xs text-stone-400">背景（2024核心）<select className={`${inputCls} mt-1`} onChange={(event) => setBackground(event.target.value)} value={background}><option value="">选择背景</option>{BACKGROUNDS_2024.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.skills.join("、")}</option>)}</select></label>
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
        {step < 3 ? <Button disabled={step === 1 ? (!name.trim() || !race || !className || !background) : false} onClick={() => { if (step === 2) applyDerivedStats(); else setStep((current) => current + 1); }} variant="primary">下一步</Button> : <Button disabled={!name.trim() || Number(hp) < 1} loading={mutation.isPending} onClick={() => mutation.mutate()} variant="primary">确认创建角色</Button>}
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
  const mutation = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error("名称不能为空");
      if (kind === "campaigns") return createCampaign({ name: name.trim(), description: description || null });
      if (!campaignId) throw new Error("尚未选择战役");
      if (kind === "characters") return createCharacter(campaignId, {
        name: name.trim(), race: race || null, class_name: extra || null, level: Number(level),
        armor_class: Number(armorClass), speed: Number(speed),
        ability_scores: Object.fromEntries(
          Object.entries(abilities).map(([key, value]) => [key, Number(value)]),
        ),
        hp: Number(hp), max_hp: Number(maxHp), notes: description || null,
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
      showToast(`${META[kind].title}已创建`);
    },
    onError: () => showToast(`${META[kind].title}创建失败`, "error"),
  });
  return (
    <form className="grid gap-2 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event: FormEvent) => { event.preventDefault(); mutation.mutate(); }}>
      <input className={inputCls} onChange={(event) => setName(event.target.value)} placeholder={META[kind].name} value={name} />
      <input className={inputCls} onChange={(event) => setDescription(event.target.value)} placeholder={META[kind].description} value={description} />
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
  if (kind === "campaigns") return updateCampaign(id, { name, description: description || null }, version);
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
    onError: () => showToast("删除失败，请重试", "error"),
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
  const rows = useRows(kind, campaignId);
  const meta = META[kind];
  return (
    <div className="mx-auto max-w-[1200px] p-4 lg:p-6">
      {kind === "characters" && campaignId ? <CharacterToolkit campaignId={campaignId} /> : null}
      {kind === "characters" && campaignId ? <CharacterCreateWizard campaignId={campaignId} onDone={() => undefined} /> : (
        <Panel eyebrow={meta.eyebrow} title={`${meta.title}管理`}>
          <CreateForm campaignId={campaignId} kind={kind} onDone={() => undefined} />
        </Panel>
      )}
      <Panel className="mt-4" eyebrow="记录" title={`${meta.title}列表`}>
        {rows.isLoading ? <LoadingBlock /> : null}
        {rows.isError ? <ErrorState error={rows.error} onRetry={() => void rows.refetch()} /> : null}
        {!rows.isLoading && !rows.isError && rows.data?.length === 0 ? <EmptyState title={`还没有${meta.title}`} hint="使用上方表单创建第一条记录。" /> : null}
        {rows.data && rows.data.length > 0 ? (
          <ul className="m-0 divide-y divide-ink-700/60 p-0">
            {rows.data.map((row) => <RowCard campaignId={campaignId} key={display(row.id, "")} kind={kind} row={row} />)}
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
