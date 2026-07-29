import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import { listCharacters, listLocations } from "../api/entities";
import {
  confirmMerchant,
  listMerchants,
  previewMerchant,
  type MerchantPreview,
} from "../api/merchants";
import { listScenes } from "../api/world";
import { useCurrentCampaign } from "../hooks/appContexts";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";

const CATEGORIES = [
  ["weapon", "武器"],
  ["armor", "护甲"],
  ["shield", "盾牌"],
  ["adventuring_gear", "基础道具与探索杂物"],
  ["consumable", "药水、卷轴与消耗品"],
  ["magic", "魔法装备与奇物"],
] as const;

const TIER_LABELS: Record<string, string> = {
  mundane: "普通非魔法物品",
  common: "普通",
  uncommon: "非普通",
  rare: "珍稀",
  very_rare: "极珍稀",
  legendary: "传说",
};

const CATEGORY_LABELS = Object.fromEntries(CATEGORIES) as Record<string, string>;

function metadataText(stock: MerchantPreview["stock"][number], key: string): string | null {
  const value = stock.filters_json?.[key] ?? stock.metadata_json?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

export function MerchantsPage(): ReactElement {
  const { campaignId } = useCurrentCampaign();
  const queryClient = useQueryClient();
  const [name, setName] = useState("规则图鉴商店");
  const [brief, setBrief] = useState("为当前队伍提供实用冒险装备");
  const [locationId, setLocationId] = useState("");
  const [sceneId, setSceneId] = useState("");
  const [tier, setTier] = useState("common");
  const [stockSize, setStockSize] = useState(12);
  const [categories, setCategories] = useState<string[]>(["weapon", "armor", "adventuring_gear"]);
  const [characterIds, setCharacterIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<MerchantPreview | null>(null);

  const locations = useQuery({
    queryKey: ["locations", campaignId],
    queryFn: ({ signal }) => listLocations(campaignId ?? "", signal),
    enabled: Boolean(campaignId),
  });
  const scenes = useQuery({
    queryKey: ["scenes", campaignId],
    queryFn: ({ signal }) => listScenes(campaignId ?? "", signal),
    enabled: Boolean(campaignId),
  });
  const characters = useQuery({
    queryKey: ["characters", campaignId],
    queryFn: ({ signal }) => listCharacters(campaignId ?? "", signal),
    enabled: Boolean(campaignId),
  });
  const merchants = useQuery({
    queryKey: ["merchants", campaignId],
    queryFn: ({ signal }) => listMerchants(campaignId ?? "", signal),
    enabled: Boolean(campaignId),
  });
  const generation = useMutation({
    mutationFn: () =>
      previewMerchant(campaignId ?? "", {
        name,
        brief,
        location_id: locationId || undefined,
        scene_id: sceneId || undefined,
        categories,
        item_tier: tier,
        character_ids: characterIds,
        stock_size: stockSize,
        price_modifier_bps: 10_000,
        allow_original: true,
      }),
    onSuccess: setPreview,
  });
  const confirmation = useMutation({
    mutationFn: () => confirmMerchant(campaignId ?? "", preview as MerchantPreview),
    onSuccess: async () => {
      setPreview(null);
      await queryClient.invalidateQueries({ queryKey: ["merchants", campaignId] });
    },
  });

  if (!campaignId) return <EmptyState title="请先选择跑团档案" />;
  return (
    <div className="mx-auto max-w-7xl space-y-5 p-4 sm:p-6">
      <div>
        <h1 className="m-0 font-display text-2xl text-parchment-100">商人与商店</h1>
        <p className="mt-2 text-sm text-stone-500">
          从官方原子图鉴选货；原创补位会先进入原子库，再成为该商店的库存实例。
        </p>
      </div>
      <section className="grid gap-4 rounded-lg border border-ink-700 bg-ink-900/60 p-4 lg:grid-cols-3">
        <label className="text-xs text-stone-400">商人 / 商店名
          <input className="mt-1 w-full rounded border border-ink-600 bg-ink-950 p-2 text-sm text-parchment-100" onChange={(e) => setName(e.target.value)} value={name} />
        </label>
        <label className="text-xs text-stone-400">所属地点
          <select className="mt-1 w-full rounded border border-ink-600 bg-ink-950 p-2 text-sm" onChange={(e) => setLocationId(e.target.value)} value={locationId}>
            <option value="">不绑定地点</option>
            {locations.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-stone-400">所属 Scene
          <select className="mt-1 w-full rounded border border-ink-600 bg-ink-950 p-2 text-sm" onChange={(e) => setSceneId(e.target.value)} value={sceneId}>
            <option value="">不加入 Scene</option>
            {scenes.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-stone-400 lg:col-span-2">经营描述 / 风格
          <input className="mt-1 w-full rounded border border-ink-600 bg-ink-950 p-2 text-sm text-parchment-100" onChange={(e) => setBrief(e.target.value)} value={brief} />
        </label>
        <label className="text-xs text-stone-400">物品级别
          <select className="mt-1 w-full rounded border border-ink-600 bg-ink-950 p-2 text-sm" onChange={(e) => setTier(e.target.value)} value={tier}>
            {["mundane", "common", "uncommon", "rare", "very_rare", "legendary"].map((value) => <option key={value} value={value}>{TIER_LABELS[value]}</option>)}
          </select>
        </label>
        <div className="lg:col-span-2">
          <p className="mb-2 text-xs text-stone-400">贩卖类别</p>
          <div className="flex flex-wrap gap-2">{CATEGORIES.map(([value, label]) => (
            <label className="rounded border border-ink-700 px-2 py-1 text-xs" key={value}>
              <input checked={categories.includes(value)} className="mr-1" onChange={() => setCategories((old) => old.includes(value) ? old.filter((item) => item !== value) : [...old, value])} type="checkbox" />{label}
            </label>
          ))}</div>
          <p className="mb-0 mt-2 text-2xs text-stone-600">
            基础道具是绳索、照明、容器、工具等无战斗属性物品；魔法武器、护甲、药水和奇物均从装备图鉴选货。
          </p>
        </div>
        <label className="text-xs text-stone-400">库存数量
          <input className="mt-1 w-full rounded border border-ink-600 bg-ink-950 p-2 text-sm" max={40} min={1} onChange={(e) => setStockSize(Number(e.target.value))} type="number" value={stockSize} />
        </label>
        <div className="lg:col-span-3">
          <p className="mb-2 text-xs text-stone-400">按角色等级与职业配货（可多选）</p>
          <div className="flex flex-wrap gap-2">{characters.data?.map((item) => (
            <label className="rounded border border-ink-700 px-2 py-1 text-xs" key={item.id}>
              <input checked={characterIds.includes(item.id)} className="mr-1" onChange={() => setCharacterIds((old) => old.includes(item.id) ? old.filter((id) => id !== item.id) : [...old, item.id])} type="checkbox" />
              {item.name} · {item.class_name ?? "未定职业"} Lv.{item.level}
            </label>
          ))}</div>
        </div>
        <Button className="lg:col-span-3" loading={generation.isPending} onClick={() => generation.mutate()} variant="ai">生成商店预览</Button>
      </section>
      {generation.error ? <ErrorState error={generation.error} /> : null}
      {preview ? <section className="rounded-lg border border-violet-800/50 bg-violet-950/10 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="m-0 font-display text-lg">{preview.merchant.name}</h2>
          <Badge tone="ok">图鉴原子 {preview.summary.official_atoms}</Badge>
          <Badge tone="ai">原创补位 {preview.summary.original_atoms}</Badge>
          {preview.summary.party_level ? <Badge>队伍参考等级 {preview.summary.party_level}</Badge> : null}
          {preview.summary.seed !== undefined ? <Badge>选货种子 {preview.summary.seed}</Badge> : null}
        </div>
        {preview.summary.official_atoms === 0 ? (
          <p className="rounded border border-amber-800/60 bg-amber-950/20 p-2 text-xs text-amber-200">
            当前条件没有命中官方图鉴库存。请调整类别或级别；只有明确标记“原创补位”的条目才会写入原创图鉴。
          </p>
        ) : null}
        {preview.stock.length ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {preview.stock.map((item, index) => {
              const rarity = metadataText(item, "rarity");
              const sourceName = metadataText(item, "source_name");
              return (
                <div className="rounded border border-ink-700 bg-ink-950/50 p-3" key={`${item.name}-${index}`}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="m-0 text-sm text-parchment-100">{item.name}</p>
                    <Badge tone={item.source_kind === "official" ? "ok" : "ai"}>
                      {item.source_kind === "official" ? "官方图鉴" : "原创补位"}
                    </Badge>
                  </div>
                  <p className="mb-0 mt-2 text-xs text-stone-500">
                    {(item.price_copper / 100).toFixed(2)} gp · 库存 {item.quantity}
                  </p>
                  <p className="mb-0 mt-1 text-2xs text-stone-600">
                    {CATEGORY_LABELS[item.category ?? ""] ?? item.category ?? "未分类"}
                    {rarity ? ` · ${rarity}` : ""}
                    {sourceName ? ` · ${sourceName}` : ""}
                  </p>
                </div>
              );
            })}
          </div>
        ) : <EmptyState title="没有生成有效库存" hint="调整物品级别、贩卖类别或角色后重新生成。" />}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button loading={confirmation.isPending} onClick={() => confirmation.mutate()} variant="primary">确认创建商人与库存</Button>
          <Button loading={generation.isPending} onClick={() => generation.mutate()} variant="ai">换一批库存</Button>
        </div>
      </section> : null}
      <section>
        <h2 className="font-display text-lg">已创建商店</h2>
        {merchants.isLoading ? <LoadingBlock /> : merchants.error ? <ErrorState error={merchants.error} /> : merchants.data?.length ? <div className="grid gap-3 lg:grid-cols-2">{merchants.data.map((shop) => <article className="rounded-lg border border-ink-700 bg-ink-900/50 p-4" key={shop.merchant_id}><h3 className="m-0 text-base text-parchment-100">{shop.name}</h3><p className="mb-0 mt-2 text-xs text-stone-500">{shop.stock.length} 种库存 · {shop.item_tier}</p></article>)}</div> : <EmptyState title="还没有商店" hint="先从官方原子图鉴按地点、队伍和等级生成一间商店。" />}
      </section>
    </div>
  );
}
