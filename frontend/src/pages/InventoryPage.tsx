import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactElement } from "react";

import { listCharacters } from "../api/entities";
import { getInventory } from "../api/world";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { Badge, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { selectCls } from "../ui/styles";

const STATE_LABELS = {
  normal: "负重正常",
  encumbered: "负重",
  heavily_encumbered: "重度负重",
  over_capacity: "超过承载上限",
  ignored: "不计算负重",
} as const;

function InventoryContent({ campaignId }: { campaignId: string }): ReactElement {
  const [characterId, setCharacterId] = useState("");
  const characters = useQuery({
    queryKey: ["characters", campaignId],
    queryFn: ({ signal }) => listCharacters(campaignId, signal),
  });
  useEffect(() => {
    if (!characterId && characters.data?.[0]) setCharacterId(characters.data[0].id);
  }, [characterId, characters.data]);
  const inventory = useQuery({
    queryKey: ["inventory", campaignId, characterId],
    queryFn: ({ signal }) => getInventory(campaignId, characterId, signal),
    enabled: Boolean(characterId),
  });
  const ratio = inventory.data?.maximum_weight_lb
    ? Math.min(inventory.data.total_weight_lb / inventory.data.maximum_weight_lb, 1)
    : 0;
  return (
    <div className="mx-auto max-w-[1000px] p-4 lg:p-6">
      <Panel
        action={
          <select className={selectCls} onChange={(event) => setCharacterId(event.target.value)} value={characterId}>
            {characters.data?.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}
          </select>
        }
        eyebrow="原子物品 · D&D 5e 负重"
        title="玩家背包"
      >
        {characters.isLoading || inventory.isLoading ? <LoadingBlock /> : null}
        {inventory.isError ? <ErrorState error={inventory.error} onRetry={() => void inventory.refetch()} /> : null}
        {characters.data?.length === 0 ? <EmptyState hint="创建玩家角色后即可管理背包。" title="还没有玩家角色" /> : null}
        {inventory.data ? (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-md border border-ink-700 bg-ink-950/60 p-3">
                <p className="m-0 text-2xs text-stone-600">力量</p>
                <strong className="mt-1 block font-mono text-xl text-parchment-100">{inventory.data.strength}</strong>
              </div>
              <div className="rounded-md border border-ink-700 bg-ink-950/60 p-3">
                <p className="m-0 text-2xs text-stone-600">当前总重量</p>
                <strong className="mt-1 block font-mono text-xl text-parchment-100">{inventory.data.total_weight_lb} lb</strong>
              </div>
              <div className="rounded-md border border-ink-700 bg-ink-950/60 p-3">
                <p className="m-0 text-2xs text-stone-600">承载上限</p>
                <strong className="mt-1 block font-mono text-xl text-parchment-100">
                  {inventory.data.maximum_weight_lb === null ? "不限制" : `${inventory.data.maximum_weight_lb} lb`}
                </strong>
              </div>
            </div>
            <div className="mt-3">
              <div className="mb-1.5 flex items-center justify-between">
                <Badge tone={inventory.data.state === "normal" || inventory.data.state === "ignored" ? "ok" : "warn"}>
                  {STATE_LABELS[inventory.data.state]}
                </Badge>
                <span className="text-2xs text-stone-600">
                  {inventory.data.encumbrance_mode === "standard" ? "标准负重：力量 × 15" : inventory.data.encumbrance_mode === "variant" ? "变体负重：力量 × 5 / × 10 / × 15" : "负重已关闭"}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-ink-700">
                <div className={`h-full rounded-full ${ratio > 0.8 ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${ratio * 100}%` }} />
              </div>
            </div>
            {inventory.data.items.length ? (
              <ul className="m-0 mt-5 divide-y divide-ink-700/70 p-0">
                {inventory.data.items.map((item) => (
                  <li className="flex flex-wrap items-center gap-3 py-3" key={item.id}>
                    <div className="min-w-0 flex-1">
                      <p className="m-0 text-sm font-medium text-parchment-100">{item.name} ×{item.quantity}</p>
                      <p className="mb-0 mt-1 text-xs text-stone-500">{item.description || item.category}</p>
                    </div>
                    <span className="font-mono text-xs text-stone-400">{item.unit_weight_lb * item.quantity} lb</span>
                    <span className="font-mono text-xs text-amber-300">{item.price_cp} cp</span>
                  </li>
                ))}
              </ul>
            ) : <EmptyState hint="在地点页选择角色，然后点击物品的“拾取到背包”。" title="背包还是空的" />}
          </>
        ) : null}
      </Panel>
    </div>
  );
}

export function InventoryPage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <InventoryContent campaignId={campaignId} />}</RequireCampaign>;
}
