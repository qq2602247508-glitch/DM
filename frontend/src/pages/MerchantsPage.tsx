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
  ["adventuring_gear", "冒险装备"],
  ["consumable", "消耗品"],
  ["magic", "魔法物品"],
] as const;

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
            {["mundane", "common", "uncommon", "rare", "very_rare", "legendary"].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <div className="lg:col-span-2">
          <p className="mb-2 text-xs text-stone-400">贩卖类别</p>
          <div className="flex flex-wrap gap-2">{CATEGORIES.map(([value, label]) => (
            <label className="rounded border border-ink-700 px-2 py-1 text-xs" key={value}>
              <input checked={categories.includes(value)} className="mr-1" onChange={() => setCategories((old) => old.includes(value) ? old.filter((item) => item !== value) : [...old, value])} type="checkbox" />{label}
            </label>
          ))}</div>
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
        <div className="flex flex-wrap items-center gap-2"><h2 className="m-0 font-display text-lg">{preview.merchant.name}</h2><Badge tone="ok">官方 {preview.summary.official_atoms}</Badge><Badge tone="ai">原创 {preview.summary.original_atoms}</Badge></div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{preview.stock.map((item, index) => <div className="rounded border border-ink-700 bg-ink-950/50 p-3" key={`${item.name}-${index}`}><p className="m-0 text-sm text-parchment-100">{item.name}</p><p className="mb-0 mt-1 text-xs text-stone-500">{(item.price_copper / 100).toFixed(2)} gp · {item.source_kind === "official" ? "官方原子" : "原创候选"}</p></div>)}</div>
        <Button className="mt-4" loading={confirmation.isPending} onClick={() => confirmation.mutate()} variant="primary">确认创建商人与库存</Button>
      </section> : null}
      <section>
        <h2 className="font-display text-lg">已创建商店</h2>
        {merchants.isLoading ? <LoadingBlock /> : merchants.error ? <ErrorState error={merchants.error} /> : merchants.data?.length ? <div className="grid gap-3 lg:grid-cols-2">{merchants.data.map((shop) => <article className="rounded-lg border border-ink-700 bg-ink-900/50 p-4" key={shop.merchant_id}><h3 className="m-0 text-base text-parchment-100">{shop.name}</h3><p className="mb-0 mt-2 text-xs text-stone-500">{shop.stock.length} 种库存 · {shop.item_tier}</p></article>)}</div> : <EmptyState title="还没有商店" hint="先从官方原子图鉴按地点、队伍和等级生成一间商店。" />}
      </section>
    </div>
  );
}
