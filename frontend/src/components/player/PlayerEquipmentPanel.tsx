import { useMutation } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import {
  confirmMyEquipment,
  previewMyEquipment,
  type PlayerEquipmentAsset,
  type PlayerEquipmentOperation,
  type PlayerEquipmentSlot,
  type SafePlayerCharacter,
} from "../../api/playerRoom";
import { createClientId } from "../../ui/id";
import { Button, ErrorState } from "../../ui/primitives";

const SLOT_LABELS: Record<PlayerEquipmentSlot, string> = {
  armor: "护甲",
  main_hand: "主手",
  off_hand: "副手 / 盾牌",
  focus: "法器 / 工具",
  worn: "其他穿戴物",
};

const SLOT_HELP: Record<PlayerEquipmentSlot, string> = {
  armor: "同一时间只能穿一套；必须具备对应轻甲、中甲或重甲训练。",
  main_hand: "武器、法器或工具；双手武器会同时占用主手与副手。",
  off_hand: "单手武器、盾牌或法器；盾牌需要训练并占用一只手。",
  focus: "用于记录可取用的施法法器或工具；实际施法仍须满足组件与空手要求。",
  worn: "按物品自身说明穿戴。5e 不设通用头盔、项链、鞋子装备槽。",
};

function text(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  return "";
}

function legacySlot(name: string): PlayerEquipmentSlot {
  if (/甲/u.test(name) && !/盾/u.test(name)) return "armor";
  if (/盾/u.test(name)) return "off_hand";
  if (/法器|圣徽|工具|乐器/u.test(name)) return "focus";
  if (/弓|弩|巨斧|巨剑|大锤|长枪/u.test(name)) return "main_hand";
  if (/剑|匕首|斧|锤|矛|棍|法杖/u.test(name)) return "main_hand";
  return "worn";
}

function itemDetails(item: PlayerEquipmentAsset): string {
  const metadata = item.metadata_json ?? {};
  const parts = [
    item.quantity > 1 ? `数量 ${item.quantity}` : "",
    metadata.unit_weight_lb !== undefined ? `${text(metadata.unit_weight_lb)} 磅/件` : "",
    metadata.price_gp !== undefined
      ? `${text(metadata.price_gp)} GP`
      : metadata.price_cp !== undefined
        ? `${Number(metadata.price_cp) / 100} GP`
        : "",
    item.profile.two_handed ? "双手" : item.profile.hand_usage === 1 ? "单手" : "",
    item.armor_class !== null ? `护甲基值 ${item.armor_class}` : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

export function PlayerEquipmentPanel({
  character,
  onChanged,
}: {
  character: SafePlayerCharacter;
  onChanged: () => void;
}): ReactElement {
  const [slotChoices, setSlotChoices] = useState<Record<string, PlayerEquipmentSlot>>({});
  const [pending, setPending] = useState<{
    input: PlayerEquipmentOperation;
    preview: Record<string, unknown>;
    itemName: string;
  } | null>(null);
  const preview = useMutation({
    mutationFn: async ({
      item,
      operation,
    }: {
      item: PlayerEquipmentAsset;
      operation: PlayerEquipmentOperation["operation"];
    }) => {
      const input: PlayerEquipmentOperation = {
        equipment_id: item.id,
        operation,
        slot: operation === "equip"
          ? slotChoices[item.id] ?? item.profile.default_slot
          : item.slot,
      };
      return { input, item, result: await previewMyEquipment(input) };
    },
    onSuccess: ({ input, item, result }) => {
      setPending({ input, itemName: item.name, preview: result });
    },
  });
  const confirm = useMutation({
    mutationFn: () => {
      if (!pending) throw new Error("没有待确认的装备操作");
      return confirmMyEquipment({
        ...pending.input,
        preview_token: text(pending.preview.preview_token),
        idempotency_key: createClientId("player-equipment"),
      });
    },
    onSuccess: () => {
      setPending(null);
      onChanged();
    },
  });
  const assets = character.equipment_assets ?? [];
  const equipped = assets.filter((item) => item.equipped);
  const backpack = assets.filter((item) => !item.equipped && item.quantity > 0);
  const legacy = character.equipment
    .map((item) => text(item && typeof item === "object" && "name" in item ? item.name : item))
    .filter((name) => name && !assets.some((asset) => asset.name === name));

  return (
    <section className="rounded-xl border border-ink-700 bg-ink-900/70 p-4 lg:col-span-2">
      <div className="flex flex-wrap items-start gap-3">
        <div className="mr-auto">
          <h2 className="m-0 font-display text-xl">装备栏</h2>
          <p className="mb-0 mt-1 text-xs leading-5 text-stone-500">
            使用 D&amp;D 5e 的护甲、持握、穿戴与同调规则，不使用头盔/鞋子等 MMO 固定部位。
          </p>
        </div>
        <span className={`rounded border px-3 py-2 text-xs ${character.active_attunements >= 3 ? "border-red-700 text-red-200" : "border-violet-700 text-violet-200"}`}>
          同调 {character.active_attunements}/3
        </span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {(Object.keys(SLOT_LABELS) as PlayerEquipmentSlot[]).map((slot) => {
          const items = equipped.filter((item) => item.slot === slot);
          const legacyItems = legacy.filter((name) => legacySlot(name) === slot);
          const blockedByTwoHanded = slot === "off_hand"
            && equipped.some((item) => item.profile.two_handed);
          return (
            <div className="min-h-36 rounded-lg border border-ink-700 bg-ink-950/50 p-3" key={slot}>
              <strong className="text-sm text-parchment-100">{SLOT_LABELS[slot]}</strong>
              <p className="mt-1 text-2xs leading-4 text-stone-600">{SLOT_HELP[slot]}</p>
              {blockedByTwoHanded ? <p className="rounded bg-amber-950/40 px-2 py-1 text-2xs text-amber-200">被双手武器占用</p> : null}
              {items.map((item) => (
                <div className="mt-2 rounded border border-emerald-800/60 bg-emerald-950/20 p-2" key={item.id}>
                  <strong className="block text-xs text-emerald-100">{item.name}</strong>
                  <span className="block text-2xs text-stone-500">{itemDetails(item) || "已装备"}</span>
                  <Button className="mt-2" loading={preview.isPending} onClick={() => preview.mutate({ item, operation: "unequip" })} size="sm">卸下</Button>
                </div>
              ))}
              {legacyItems.map((name) => (
                <div className="mt-2 rounded border border-ink-700 p-2" key={`legacy-${slot}-${name}`}>
                  <strong className="block text-xs">{name}</strong>
                  <span className="text-2xs text-stone-600">旧角色卡登记 · 由 DM 原子化后可操作</span>
                </div>
              ))}
              {!items.length && !legacyItems.length && !blockedByTwoHanded ? <span className="text-2xs text-stone-700">空</span> : null}
            </div>
          );
        })}
      </div>

      <div className="mt-4 rounded-lg border border-ink-700 p-3">
        <h3 className="m-0 text-sm">背包中可装备物</h3>
        {backpack.length ? (
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {backpack.map((item) => {
              const selectedSlot = slotChoices[item.id] ?? item.profile.default_slot;
              return (
                <div className="rounded border border-ink-700 bg-ink-950/40 p-3" key={item.id}>
                  <div className="flex items-start gap-2">
                    <div className="mr-auto">
                      <strong className="block text-sm">{item.name}</strong>
                      <span className="text-2xs text-stone-500">{itemDetails(item) || item.category}</span>
                    </div>
                    {item.attuned ? <span className="text-2xs text-violet-200">已同调</span> : null}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <select
                      aria-label={`${item.name}装备位置`}
                      className="rounded border border-ink-600 bg-ink-950 px-2 py-1 text-xs"
                      onChange={(event) => setSlotChoices((current) => ({
                        ...current,
                        [item.id]: event.target.value as PlayerEquipmentSlot,
                      }))}
                      value={selectedSlot}
                    >
                      {item.profile.allowed_slots.map((slot) => <option key={slot} value={slot}>{SLOT_LABELS[slot]}</option>)}
                    </select>
                    <Button loading={preview.isPending} onClick={() => preview.mutate({ item, operation: "equip" })} size="sm">预览装备</Button>
                    {item.attunement_required ? (
                      <Button
                        disabled={!item.attuned && character.active_attunements >= 3}
                        loading={preview.isPending}
                        onClick={() => preview.mutate({ item, operation: item.attuned ? "unattune" : "attune" })}
                        size="sm"
                      >
                        {item.attuned ? "解除同调" : "同调"}
                      </Button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        ) : <p className="mb-0 text-xs text-stone-600">背包里暂无可操作的原子化装备。普通道具仍保留在下方背包清单。</p>}
      </div>

      {preview.isError ? <div className="mt-3"><ErrorState error={preview.error} /></div> : null}
      {confirm.isError ? <div className="mt-3"><ErrorState error={confirm.error} /></div> : null}
      {pending ? (
        <div className="mt-4 rounded-lg border border-amber-700/70 bg-amber-950/20 p-4">
          <strong className="text-sm text-amber-100">
            待确认：{pending.itemName} · {pending.input.operation === "equip" ? "装备" : pending.input.operation === "unequip" ? "卸下" : pending.input.operation === "attune" ? "同调" : "解除同调"}
          </strong>
          <p className="mb-0 mt-1 text-xs text-stone-400">
            {Array.isArray(pending.preview.warnings) && pending.preview.warnings.length
              ? pending.preview.warnings.join("；")
              : "规则校验已通过；确认后才会同步写入角色状态。"}
          </p>
          <div className="mt-3 flex gap-2">
            <Button loading={confirm.isPending} onClick={() => confirm.mutate()} variant="primary">确认写入</Button>
            <Button onClick={() => setPending(null)}>取消</Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
