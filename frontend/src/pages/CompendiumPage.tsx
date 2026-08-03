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
  { value: "feature", label: "职业与子职", contentType: "classes" },
  { value: "monster", label: "怪物", contentType: "monsters" },
  { value: "equipment", label: "装备", contentType: "equipment" },
  { value: "item", label: "道具", contentType: "items" },
  { value: "npc", label: "NPC 模板" },
  { value: "location", label: "地点模板" },
  { value: "scene", label: "场景模板" },
  { value: "rule", label: "规则扩展", contentType: "rules" },
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
    { key: "class_name", label: "所属职业" },
    { key: "feature_kind", label: "职业 / 子职" },
  ],
  monster: [
    { key: "monster_type", label: "怪物类型" },
    { key: "challenge_rating", label: "挑战等级 CR" },
  ],
  equipment: [
    { key: "category", label: "装备类别" },
    { key: "rarity", label: "稀有度" },
  ],
  item: [
    { key: "item_function", label: "用途" },
    { key: "category", label: "道具类别" },
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
  rule: [
    { key: "category", label: "规则类别" },
    { key: "automation_status", label: "自动化状态" },
  ],
};

const SORTS: Record<CompendiumEntryType, ReadonlyArray<{ value: string; label: string }>> = {
  spell: [
    { value: "level:asc", label: "环级：低到高" },
    { value: "level:desc", label: "环级：高到低" },
    { value: "name:asc", label: "名称：正序" },
  ],
  feature: [
    { value: "class:asc", label: "按职业与子职分组" },
    { value: "level:asc", label: "解锁等级：低到高" },
    { value: "name:asc", label: "名称：正序" },
  ],
  monster: [
    { value: "strength:asc", label: "CR：低到高" },
    { value: "strength:desc", label: "CR：高到低" },
    { value: "name:asc", label: "名称：正序" },
  ],
  equipment: [
    { value: "strength:asc", label: "稀有度：低到高" },
    { value: "strength:desc", label: "稀有度：高到低" },
    { value: "name:asc", label: "名称：正序" },
  ],
  item: [
    { value: "category:asc", label: "按用途分组" },
    { value: "name:asc", label: "名称：正序" },
    { value: "name:desc", label: "名称：倒序" },
  ],
  npc: [{ value: "name:asc", label: "名称：正序" }],
  location: [{ value: "name:asc", label: "名称：正序" }],
  scene: [{ value: "name:asc", label: "名称：正序" }],
  rule: [{ value: "name:asc", label: "名称：正序" }],
};

function defaultSort(entryType: CompendiumEntryType): string {
  return SORTS[entryType][0]?.value ?? "name:asc";
}

function display(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

const VALUE_LABELS: Record<string, string> = {
  weapon: "武器",
  armor: "护甲",
  shield: "盾牌",
  adventuring_gear: "冒险装备",
  wondrous: "奇物",
  potion: "药水",
  scroll: "卷轴",
  ring: "戒指",
  rod: "权杖",
  staff: "法杖",
  wand: "魔杖",
  ammunition: "弹药",
  magic_item: "其他魔法物品",
  class: "职业",
  subclass: "子职",
  class_rule: "职业规则",
  classes: "职业",
  subclasses: "子职",
  feats: "专长",
  backgrounds: "背景",
  conditions: "状态",
  actions: "动作规则",
  main_hand: "主手",
  off_hand: "副手",
  inventory: "背包",
  consumable: "消耗品",
  container: "容器",
  illumination: "照明",
  camping: "露营与补给",
  exploration: "探索工具",
  restraint_security: "束缚与安防",
  writing_navigation: "书写与导航",
  tool: "工具",
  miscellaneous: "杂物与演绎道具",
  legacy: "2014 旧版",
  "2024": "2024 版",
  "2025": "2025 版",
};

const FILTER_KEY_LABELS: Record<string, string> = {
  category: "分类",
  slot: "装备部位",
  rarity: "稀有度",
  recommended_level: "建议等级",
  edition: "规则版本",
  class_name: "职业",
  spell_level: "法术环级",
  school: "学派",
  casting_time: "施法时间",
  concentration: "专注",
  ritual: "仪式",
  monster_type: "怪物类型",
  challenge_rating: "挑战等级",
  attunement: "同调",
  attunement_classes: "同调限制",
  feature_kind: "条目类型",
  item_function: "用途",
  level: "解锁等级",
};

const HIDDEN_FILTER_KEYS = new Set([
  "atomic_item",
  "content_type",
  "classes",
  "source_book",
]);

function displayFilterValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(displayFilterValue).join("、");
  if (value === true) return "是";
  if (value === false) return "否";
  const raw = display(value);
  return VALUE_LABELS[raw] ?? raw;
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
        {entry.tags.filter((tag) => tag !== "官方").map((tag) => <Badge key={tag}>{VALUE_LABELS[tag] ?? tag}</Badge>)}
      </div>
      <p className="mb-2 mt-2 line-clamp-4 text-xs leading-5 text-stone-400">{entry.description || "暂无描述"}</p>
      {entry.description && entry.description.length > 220 ? (
        <details className="mb-2 text-xs text-stone-400">
          <summary className="cursor-pointer text-ember-300">展开完整说明</summary>
          <p className="whitespace-pre-wrap leading-5">{entry.description}</p>
        </details>
      ) : null}
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(entry.filters_json)
          .filter(([key, value]) => !HIDDEN_FILTER_KEYS.has(key) && value !== "" && value !== null)
          .slice(0, 8)
          .map(([key, value]) => (
            <Badge key={key}>
              {FILTER_KEY_LABELS[key] ?? key}: {displayFilterValue(value)}
            </Badge>
          ))}
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
  const [includeLegacy, setIncludeLegacy] = useState(false);
  const [sort, setSort] = useState(defaultSort("spell"));
  const [prompt, setPrompt] = useState("一套基于火龙指甲锻造的装备");
  const [mode, setMode] = useState<"single" | "equipment_set" | "monster_family">("equipment_set");
  const [level, setLevel] = useState(5);
  const [preview, setPreview] = useState<CompendiumGenerationPreview | null>(null);
  const activeFilters = FILTERS[entryType];
  const [sortBy, sortOrder] = sort.split(":");
  const entries = useQuery({
    queryKey: [
      "compendium", campaignId, entryType, sourceKind, text, filterA, filterB,
      includeLegacy, sortBy, sortOrder, page,
    ],
    queryFn: ({ signal }) => listCompendium(campaignId, {
      entry_type: entryType,
      source_kind: sourceKind || undefined,
      text: text || undefined,
      page,
      page_size: 40,
      include_legacy: includeLegacy,
      sort_by: sortBy,
      sort_order: sortOrder === "desc" ? "desc" : "asc",
      content_type: entryType === "feature" ? "classes" : undefined,
      [activeFilters[0].key]: filterA || undefined,
      [activeFilters[1].key]: filterB || undefined,
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
  const filterOptions = useMemo(() => {
    const options = ({ key }: { key: string }) =>
      entries.data?.facets[key] ?? [];
    return [options(activeFilters[0]), options(activeFilters[1])] as const;
  }, [activeFilters, entries.data?.facets]);
  const visibleEntries = useMemo(
    () => entries.data?.items ?? [],
    [entries.data?.items],
  );
  function chooseType(nextType: CompendiumEntryType): void {
    setEntryType(nextType);
    setPage(1);
    setFilterA("");
    setFilterB("");
    setSort(defaultSort(nextType));
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
        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_repeat(4,11rem)]">
          <input className={inputCls} onChange={(event) => { setText(event.target.value); setPage(1); }} placeholder="搜索图鉴名称、法术、怪物、装备…" value={text} />
          <select className={selectCls} onChange={(event) => { setSourceKind(event.target.value); setPage(1); }} value={sourceKind}>
            <option value="">全部来源</option>
            <option value="official">官方</option>
            <option value="ai_generated">原创 · AI</option>
            <option value="original">原创 · DM</option>
            <option value="third_party">第三方</option>
          </select>
          <select className={selectCls} onChange={(event) => { setFilterA(event.target.value); setPage(1); }} value={filterA}>
            <option value="">全部{activeFilters[0].label}</option>
            {filterOptions[0].map((value) => <option key={value} value={value}>{displayFilterValue(value)}</option>)}
          </select>
          <select className={selectCls} onChange={(event) => { setFilterB(event.target.value); setPage(1); }} value={filterB}>
            <option value="">全部{activeFilters[1].label}</option>
            {filterOptions[1].map((value) => <option key={value} value={value}>{displayFilterValue(value)}</option>)}
          </select>
          <select
            aria-label="图鉴排序"
            className={selectCls}
            onChange={(event) => { setSort(event.target.value); setPage(1); }}
            value={sort}
          >
            {SORTS[entryType].map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
        </div>
        <label className="mt-3 inline-flex cursor-pointer items-center gap-2 rounded border border-ink-700 px-3 py-2 text-xs text-stone-400">
          <input
            checked={includeLegacy}
            onChange={(event) => {
              setIncludeLegacy(event.target.checked);
              setPage(1);
            }}
            type="checkbox"
          />
          显示 2014 / legacy 旧版
          <span className="text-stone-600">（默认隐藏，避免与 2024/2025 条目重复）</span>
        </label>
        <p className="mb-0 mt-2 text-2xs text-stone-600">
          “装备”包含武器、护甲、盾牌与魔法装备；“道具”只收录无战斗属性的基础冒险用品、工具和演绎杂物。
        </p>
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
