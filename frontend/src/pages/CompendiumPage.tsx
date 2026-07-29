import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactElement } from "react";

import {
  confirmCompendiumGeneration,
  generateCompendium,
  instantiateCompendiumEntry,
  listCompendium,
  type CompendiumEntry,
  type CompendiumEntryType,
  type CompendiumGenerationPreview,
} from "../api/compendium";
import { listCharacters } from "../api/entities";
import { searchKnowledge } from "../api/knowledge";
import { listScenes } from "../api/world";
import type { ContentType } from "../api/types";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { useToast } from "../hooks/toastContext";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../ui/styles";

const TYPES: Array<{ value: CompendiumEntryType; label: string; contentType?: ContentType }> = [
  { value: "spell", label: "法术", contentType: "spells" },
  { value: "feature", label: "职业能力", contentType: "classes" },
  { value: "monster", label: "怪物", contentType: "monsters" },
  { value: "equipment", label: "装备", contentType: "equipment" },
  { value: "item", label: "道具", contentType: "items" },
  { value: "npc", label: "NPC 模板" },
  { value: "location", label: "地点模板" },
  { value: "scene", label: "场景模板" },
];

const FILTERS: Record<
  CompendiumEntryType,
  readonly [
    { key: string; label: string },
    { key: string; label: string },
  ]
> = {
  spell: [
    { key: "class_name", label: "职业" },
    { key: "spell_level", label: "法术环级 / 消耗" },
  ],
  feature: [
    { key: "class_name", label: "职业" },
    { key: "level", label: "获得等级" },
  ],
  monster: [
    { key: "monster_type", label: "怪物类型" },
    { key: "challenge_rating", label: "挑战等级 CR" },
  ],
  equipment: [
    { key: "slot", label: "装备部位" },
    { key: "rarity", label: "稀有度" },
  ],
  item: [
    { key: "category", label: "功能分类" },
    { key: "rarity", label: "稀有度" },
  ],
  npc: [
    { key: "role", label: "职责" },
    { key: "faction", label: "阵营 / 组织" },
  ],
  location: [
    { key: "location_type", label: "地点类型" },
    { key: "region", label: "区域" },
  ],
  scene: [
    { key: "scene_type", label: "场景类型" },
    { key: "difficulty", label: "难度" },
  ],
};

function display(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function EntryCard({
  campaignId,
  entry,
  targets,
}: {
  campaignId: string;
  entry: CompendiumEntry;
  targets: Array<{ value: string; label: string }>;
}): ReactElement {
  const { showToast } = useToast();
  const [target, setTarget] = useState("");
  const action = useMutation({
    mutationFn: () => {
      const [targetType, targetId] = target.split(":");
      if (!targetType || !targetId) throw new Error("请选择目标");
      return instantiateCompendiumEntry(
        campaignId,
        entry.id,
        targetType as "character" | "scene",
        targetId,
      );
    },
    onSuccess: () => showToast("已从图鉴模板创建独立实例"),
    onError: () => showToast("添加失败，请检查条目类型和目标", "error"),
  });
  return (
    <article className="rounded-lg border border-ink-700 bg-ink-950/55 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-sm text-parchment-100">{entry.name}</strong>
        <Badge tone={entry.source_kind === "official" ? "ok" : "ai"}>
          {entry.source_kind === "official" ? "官方" : entry.source_kind === "ai_generated" ? "原创 · AI" : "原创"}
        </Badge>
        {entry.tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}
      </div>
      <p className="mb-2 mt-2 text-xs leading-5 text-stone-400">{entry.description || "暂无描述"}</p>
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(entry.filters_json).slice(0, 8).map(([key, value]) => <Badge key={key}>{key}: {display(value)}</Badge>)}
      </div>
      <div className="mt-3 flex gap-2">
        <select className={`${selectCls} min-w-0 flex-1`} onChange={(event) => setTarget(event.target.value)} value={target}>
          <option value="">选择快速添加目标</option>
          {targets.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <Button disabled={!target} loading={action.isPending} onClick={() => action.mutate()} size="sm" variant="primary">添加实例</Button>
      </div>
    </article>
  );
}

function CompendiumContent({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [entryType, setEntryType] = useState<CompendiumEntryType>("spell");
  const [sourceKind, setSourceKind] = useState("");
  const [text, setText] = useState("");
  const [page, setPage] = useState(1);
  const [filterA, setFilterA] = useState("");
  const [filterB, setFilterB] = useState("");
  const [prompt, setPrompt] = useState("一套基于火龙指甲锻造的装备");
  const [mode, setMode] = useState<"single" | "equipment_set" | "monster_family">("equipment_set");
  const [level, setLevel] = useState(5);
  const [preview, setPreview] = useState<CompendiumGenerationPreview | null>(null);
  const entries = useQuery({
    queryKey: ["compendium", campaignId, entryType, sourceKind, text, page],
    queryFn: ({ signal }) => listCompendium(campaignId, {
      entry_type: entryType,
      source_kind: sourceKind || undefined,
      text: text || undefined,
      page,
      page_size: 40,
    }, signal),
  });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const scenes = useQuery({ queryKey: ["scenes", campaignId], queryFn: ({ signal }) => listScenes(campaignId, signal) });
  const officialType = TYPES.find((item) => item.value === entryType)?.contentType;
  const official = useQuery({
    queryKey: ["compendium-official", entryType, text],
    queryFn: ({ signal }) => searchKnowledge({
      text,
      top_k: 12,
      candidate_k: 32,
      content_types: officialType ? [officialType] : undefined,
      editions: ["2024", "2025"],
      current_official: true,
    }, signal),
    enabled: Boolean(officialType && text.trim().length >= 2),
  });
  const generation = useMutation({
    mutationFn: () => generateCompendium(campaignId, {
      mode,
      entry_type: entryType,
      prompt,
      applicable_level: level,
    }),
    onSuccess: setPreview,
    onError: () => showToast("图鉴草案生成失败", "error"),
  });
  const confirmation = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("没有草案");
      return confirmCompendiumGeneration(campaignId, preview);
    },
    onSuccess: () => {
      setPreview(null);
      void client.invalidateQueries({ queryKey: ["compendium", campaignId] });
      showToast("原创内容已写入图鉴库");
    },
    onError: () => showToast("图鉴写入失败", "error"),
  });
  const targets = useMemo(() => {
    if (entryType === "monster" || entryType === "npc") {
      return (scenes.data ?? []).map((scene) => ({ value: `scene:${scene.id}`, label: `加入场景 · ${scene.name}` }));
    }
    if (["spell", "feature", "equipment", "item"].includes(entryType)) {
      return (characters.data ?? []).map((character) => ({ value: `character:${character.id}`, label: `给予角色 · ${character.name}` }));
    }
    return [];
  }, [characters.data, entryType, scenes.data]);
  const activeFilters = FILTERS[entryType];
  const filterOptions = useMemo(() => {
    const options = ({ key }: { key: string }) => Array.from(new Set(
      (entries.data?.items ?? [])
        .map((entry) => entry.filters_json[key])
        .filter((value) => value !== null && value !== undefined && value !== "")
        .map(display),
    )).sort((left, right) => left.localeCompare(right, "zh-CN", { numeric: true }));
    return [options(activeFilters[0]), options(activeFilters[1])] as const;
  }, [activeFilters, entries.data?.items]);
  const visibleEntries = useMemo(
    () => (entries.data?.items ?? [])
      .filter((entry) => !filterA || display(entry.filters_json[activeFilters[0].key]) === filterA)
      .filter((entry) => !filterB || display(entry.filters_json[activeFilters[1].key]) === filterB)
      .sort((left, right) => {
        const filterKey = activeFilters[1].key;
        return display(left.filters_json[filterKey] ?? "").localeCompare(
          display(right.filters_json[filterKey] ?? ""),
          "zh-CN",
          { numeric: true },
        ) || left.name.localeCompare(right.name, "zh-CN");
      }),
    [activeFilters, entries.data?.items, filterA, filterB],
  );
  function chooseType(nextType: CompendiumEntryType): void {
    setEntryType(nextType);
    setPage(1);
    setFilterA("");
    setFilterB("");
  }
  return (
    <div className="mx-auto max-w-[1280px] p-4 lg:p-6">
      <Panel eyebrow="统一原子库" title="D&D 图鉴库">
        <p className="mt-0 text-xs text-stone-400">
          已直接接入本地规则资料中的 {entries.data?.official_total ?? "…"} 个官方原子；
          原创条目仍按当前团独立保存。
        </p>
        <div className="flex flex-wrap gap-2">
          {TYPES.map((item) => <Button key={item.value} onClick={() => chooseType(item.value)} size="sm" variant={entryType === item.value ? "primary" : "ghost"}>{item.label} {entries.data?.counts[item.value] ? `(${entries.data.counts[item.value]})` : ""}</Button>)}
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_repeat(3,12rem)]">
          <input className={inputCls} onChange={(event) => { setText(event.target.value); setPage(1); }} placeholder="搜索图鉴名称、法术、怪物、装备…" value={text} />
          <select className={selectCls} onChange={(event) => { setSourceKind(event.target.value); setPage(1); }} value={sourceKind}>
            <option value="">全部来源</option>
            <option value="official">官方</option>
            <option value="ai_generated">原创 · AI</option>
            <option value="original">原创 · DM</option>
            <option value="third_party">第三方</option>
          </select>
          <select className={selectCls} onChange={(event) => setFilterA(event.target.value)} value={filterA}>
            <option value="">全部{activeFilters[0].label}</option>
            {filterOptions[0].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <select className={selectCls} onChange={(event) => setFilterB(event.target.value)} value={filterB}>
            <option value="">全部{activeFilters[1].label}</option>
            {filterOptions[1].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </div>
      </Panel>
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,.7fr)]">
        <Panel eyebrow="可复用模板" title={`${TYPES.find((item) => item.value === entryType)?.label ?? "图鉴"}条目`}>
          {entries.isLoading ? <LoadingBlock /> : null}
          {entries.isError ? <ErrorState error={entries.error} onRetry={() => void entries.refetch()} /> : null}
          {!entries.isLoading && !visibleEntries.length ? <EmptyState title="当前筛选条件下没有已保存模板" hint="调整筛选，或使用右侧生成器创建规则化原创内容。" /> : null}
          <div className="grid gap-3 md:grid-cols-2">
            {visibleEntries.map((entry) => <EntryCard campaignId={campaignId} entry={entry} key={entry.id} targets={targets} />)}
          </div>
          {entries.data && entries.data.total > entries.data.page_size ? <div className="mt-4 flex items-center justify-between border-t border-ink-700 pt-3 text-xs text-stone-400">
            <Button disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} size="sm">上一页</Button>
            <span>第 {page} / {Math.ceil(entries.data.total / entries.data.page_size)} 页 · 共 {entries.data.total} 条</span>
            <Button disabled={page * entries.data.page_size >= entries.data.total} onClick={() => setPage((value) => value + 1)} size="sm">下一页</Button>
          </div> : null}
        </Panel>
        <Panel eyebrow="严格校验 · 原创标签" title="AI 图鉴生成">
          <select className={selectCls} onChange={(event) => setMode(event.target.value as typeof mode)} value={mode}>
            <option value="single">单个条目</option>
            <option value="equipment_set">整套装备</option>
            <option value="monster_family">怪物家族</option>
          </select>
          <textarea className={`${textareaCls} mt-2`} onChange={(event) => setPrompt(event.target.value)} value={prompt} />
          <label className="mt-2 block text-xs text-stone-400">适用角色等级
            <input className={`${inputCls} mt-1`} max={20} min={1} onChange={(event) => setLevel(Number(event.target.value))} type="number" value={level} />
          </label>
          <Button className="mt-3 w-full" disabled={!prompt.trim()} loading={generation.isPending} onClick={() => generation.mutate()} variant="ai">生成规则化草案</Button>
          {preview ? <div className="mt-3 space-y-2 border-t border-ink-700 pt-3">
            {preview.entries.map((entry) => <div className="rounded border border-ink-700 p-2 text-xs" key={entry.name}><strong className="text-parchment-100">{entry.name}</strong><p className="mb-0 mt-1 text-stone-500">{entry.description}</p></div>)}
            {preview.warnings.map((warning) => <p className="m-0 text-2xs text-amber-300" key={warning}>{warning}</p>)}
            <Button className="w-full" loading={confirmation.isPending} onClick={() => confirmation.mutate()} variant="primary">DM 确认并加入图鉴</Button>
          </div> : null}
        </Panel>
      </div>
      {officialType ? <Panel className="mt-4" eyebrow="本地资料来源" title="官方规则检索">
        {text.trim().length < 2 ? <EmptyState title="输入至少两个字检索官方资料" hint="官方内容与原创图鉴分开标记，AI 生成内容不会冒充官方条目。" /> : null}
        {official.isLoading ? <LoadingBlock /> : null}
        <div className="grid gap-2 md:grid-cols-2">
          {official.data?.map((hit) => <article className="rounded border border-ink-700 bg-ink-950/50 p-3" key={hit.chunk.chunk_id}><div className="flex gap-2"><strong className="text-sm text-parchment-100">{hit.chunk.name}</strong><Badge tone="ok">官方 · {hit.chunk.edition}</Badge></div><p className="line-clamp-4 text-xs leading-5 text-stone-400">{hit.chunk.text}</p><a className="text-2xs text-ember-300" href={hit.chunk.canonical_url} rel="noreferrer" target="_blank">查看来源</a></article>)}
        </div>
      </Panel> : null}
    </div>
  );
}

export function CompendiumPage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <CompendiumContent campaignId={campaignId} />}</RequireCampaign>;
}
