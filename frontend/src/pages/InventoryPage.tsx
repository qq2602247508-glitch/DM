import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactElement } from "react";

import {
  confirmCommerce,
  confirmEquipmentOperation,
  confirmSpellCast,
  getCharacterAssets,
  listCharacters,
  listShopInventory,
  previewCommerce,
  previewEquipmentOperation,
  previewSpellCast,
  type CommerceInput,
  type EquipmentOperationInput,
  type SpellCastInput,
} from "../api/entities";
import { getInventory } from "../api/world";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { useToast } from "../hooks/toastContext";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { selectCls } from "../ui/styles";

const STATE_LABELS = {
  normal: "负重正常",
  encumbered: "负重",
  heavily_encumbered: "重度负重",
  over_capacity: "超过承载上限",
  ignored: "不计算负重",
} as const;

function displayValue(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "—";
}

type PendingChange =
  | { kind: "spell"; input: SpellCastInput; preview: Record<string, unknown> }
  | { kind: "equipment"; input: EquipmentOperationInput; preview: Record<string, unknown> }
  | { kind: "commerce"; input: CommerceInput; preview: Record<string, unknown> };

function InventoryContent({ campaignId }: { campaignId: string }): ReactElement {
  const [characterId, setCharacterId] = useState("");
  const [pending, setPending] = useState<PendingChange | null>(null);
  const queryClient = useQueryClient();
  const { showToast } = useToast();
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
  const assets = useQuery({
    queryKey: ["character-assets", campaignId, characterId],
    queryFn: ({ signal }) => getCharacterAssets(campaignId, characterId, signal),
    enabled: Boolean(characterId),
  });
  const shop = useQuery({
    queryKey: ["shop-inventory", campaignId],
    queryFn: ({ signal }) => listShopInventory(campaignId, signal),
  });
  const previewMutation = useMutation({
    mutationFn: async (
      operation:
        | { kind: "spell"; input: SpellCastInput }
        | { kind: "equipment"; input: EquipmentOperationInput }
        | { kind: "commerce"; input: CommerceInput },
    ): Promise<PendingChange> => {
      if (operation.kind === "spell") {
        return {
          ...operation,
          preview: await previewSpellCast(campaignId, operation.input),
        };
      }
      if (operation.kind === "equipment") {
        return {
          ...operation,
          preview: await previewEquipmentOperation(campaignId, operation.input),
        };
      }
      return {
        ...operation,
        preview: await previewCommerce(campaignId, operation.input),
      };
    },
    onSuccess: setPending,
  });
  const confirmMutation = useMutation({
    mutationFn: async () => {
      if (!pending) throw new Error("没有待确认操作");
      const previewToken = String(pending.preview.preview_token);
      if (pending.kind === "spell") {
        return confirmSpellCast(campaignId, {
          ...pending.input,
          preview_token: previewToken,
          idempotency_key: crypto.randomUUID(),
        });
      }
      if (pending.kind === "equipment") {
        return confirmEquipmentOperation(campaignId, {
          ...pending.input,
          preview_token: previewToken,
          idempotency_key: crypto.randomUUID(),
        });
      }
      return confirmCommerce(campaignId, {
        ...pending.input,
        preview_token: previewToken,
        idempotency_key: crypto.randomUUID(),
      });
    },
    onSuccess: async () => {
      setPending(null);
      await queryClient.invalidateQueries({ queryKey: ["character-assets", campaignId] });
      await queryClient.invalidateQueries({ queryKey: ["characters", campaignId] });
      await queryClient.invalidateQueries({ queryKey: ["shop-inventory", campaignId] });
      showToast("已由 DM 确认并写入", "success");
    },
  });
  const selectedCharacter = characters.data?.find((item) => item.id === characterId);
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
            <div className="mt-6 grid gap-4 lg:grid-cols-2">
              <div className="rounded-md border border-ink-700 bg-ink-950/40 p-4">
                <p className="m-0 text-2xs uppercase tracking-[0.16em] text-stone-600">法术与施法资源</p>
                <p className="mb-2 mt-1 text-sm text-parchment-100">法术位、仪式与专注消耗在战斗或角色卡中均需先预览并由 DM 确认。</p>
                {assets.data?.spells.length ? <ul className="m-0 space-y-2 p-0 text-xs text-stone-400">{assets.data.spells.map((spell) => <li className="flex items-center justify-between gap-2" key={String(spell.id)}><span>{String(spell.name)} · {String(spell.spell_level)} 环{spell.prepared ? " · 已准备" : ""}</span><Button disabled={!selectedCharacter} onClick={() => selectedCharacter && previewMutation.mutate({ kind: "spell", input: { character_id: characterId, character_version: selectedCharacter.version, known_spell_id: String(spell.id), slot_level: Number(spell.spell_level), ritual: false, material_available: true, concentration: false } })} size="sm">预览施放</Button></li>)}</ul> : <span className="text-xs text-stone-600">尚未录入原子化法术。</span>}
              </div>
              <div className="rounded-md border border-ink-700 bg-ink-950/40 p-4">
                <p className="m-0 text-2xs uppercase tracking-[0.16em] text-stone-600">装备、同调与零钱包</p>
                <p className="mb-2 mt-1 text-sm text-parchment-100">{assets.data?.wallet ? `${displayValue(assets.data.wallet.copper ?? 0)} cp` : "未建立钱包"} · 同调物品最多 3 件</p>
                {assets.data?.equipment.length ? <ul className="m-0 space-y-2 p-0 text-xs text-stone-400">{assets.data.equipment.map((item) => <li className="flex flex-wrap items-center justify-between gap-2" key={String(item.id)}><span>{displayValue(item.name)} ×{displayValue(item.quantity)}{item.equipped ? " · 已装备" : ""}{item.attuned ? " · 已同调" : ""}{item.charges !== null && item.charges !== undefined ? ` · 充能 ${displayValue(item.charges)}` : ""}</span><div className="flex gap-1"><Button disabled={!selectedCharacter} onClick={() => selectedCharacter && previewMutation.mutate({ kind: "equipment", input: { character_id: characterId, character_version: selectedCharacter.version, equipment_id: String(item.id), operation: item.equipped ? "unequip" : "equip", amount: 1 } })} size="sm">{item.equipped ? "卸下" : "装备"}</Button>{item.attunement_required ? <Button disabled={!selectedCharacter} onClick={() => selectedCharacter && previewMutation.mutate({ kind: "equipment", input: { character_id: characterId, character_version: selectedCharacter.version, equipment_id: String(item.id), operation: item.attuned ? "unattune" : "attune", amount: 1 } })} size="sm">{item.attuned ? "解除同调" : "同调"}</Button> : null}</div></li>)}</ul> : <span className="text-xs text-stone-600">尚未录入原子化装备。</span>}
              </div>
            </div>
            <div className="mt-4 rounded-md border border-ink-700 bg-ink-950/40 p-4">
              <p className="m-0 text-2xs uppercase tracking-[0.16em] text-stone-600">商店交易</p>
              <p className="mb-3 mt-1 text-sm text-parchment-100">购买前预览余额、库存、重量与价格；确认后才写入背包和账本。</p>
              {shop.data?.length && assets.data?.wallet ? <ul className="m-0 grid gap-2 p-0 sm:grid-cols-2">{shop.data.map((item) => <li className="flex items-center justify-between rounded border border-ink-700 p-2 text-xs" key={String(item.id)}><span>{displayValue(item.name)} · {displayValue(item.price_copper)} cp · 库存 {displayValue(item.quantity)}</span><Button disabled={!Number(item.quantity)} onClick={() => previewMutation.mutate({ kind: "commerce", input: { wallet_id: String(assets.data?.wallet?.id), wallet_version: Number(assets.data?.wallet?.version), shop_inventory_id: String(item.id), shop_version: Number(item.version), quantity: 1, direction: "buy", price_modifier_bps: 10000 } })} size="sm">预览购买</Button></li>)}</ul> : <span className="text-xs text-stone-600">暂无商店库存或角色钱包。</span>}
            </div>
            {previewMutation.isError ? <div className="mt-4"><ErrorState error={previewMutation.error} /></div> : null}
            {pending ? <div className="mt-4 rounded-md border border-amber-700/60 bg-amber-950/20 p-4"><p className="m-0 text-sm font-medium text-amber-200">待 DM 确认：{pending.kind === "spell" ? "施法" : pending.kind === "equipment" ? "装备操作" : "商店交易"}</p><pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap text-xs text-stone-400">{JSON.stringify(pending.preview, null, 2)}</pre><div className="mt-3 flex gap-2"><Button loading={confirmMutation.isPending} onClick={() => confirmMutation.mutate()} variant="primary">确认写入</Button><Button onClick={() => setPending(null)}>取消</Button></div>{confirmMutation.isError ? <div className="mt-3"><ErrorState error={confirmMutation.error} /></div> : null}</div> : null}
          </>
        ) : null}
      </Panel>
    </div>
  );
}

export function InventoryPage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <InventoryContent campaignId={campaignId} />}</RequireCampaign>;
}
