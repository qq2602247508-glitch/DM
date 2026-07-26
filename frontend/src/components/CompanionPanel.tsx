import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import { createCompanion, listCompanions, updateCompanion } from "../api/entities";
import type { Character } from "../api/types";
import { useToast } from "../hooks/toastContext";
import { Button } from "../ui/primitives";
import { inputCls, selectCls } from "../ui/styles";

const TYPES = [
  ["familiar", "魔宠"],
  ["animal_companion", "动物伙伴"],
  ["summon", "召唤物"],
  ["wild_shape", "荒野形态"],
  ["form", "变身形态"],
] as const;

export function CompanionPanel({
  campaignId,
  characters,
}: {
  campaignId: string;
  characters: Character[];
}): ReactElement {
  const { showToast } = useToast();
  const client = useQueryClient();
  const [ownerId, setOwnerId] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<(typeof TYPES)[number][0]>("familiar");
  const [hp, setHp] = useState("1");
  const [armorClass, setArmorClass] = useState("10");
  const [speed, setSpeed] = useState("30");
  const [sourceRecordId, setSourceRecordId] = useState("");
  const companions = useQuery({
    queryKey: ["companions", campaignId],
    queryFn: ({ signal }) => listCompanions(campaignId, undefined, signal),
  });
  const create = useMutation({
    mutationFn: () => {
      if (!ownerId || !name.trim()) throw new Error("请选择主人并填写名称");
      return createCompanion(campaignId, {
        owner_character_id: ownerId,
        name: name.trim(),
        companion_type: type,
        source_record_id: sourceRecordId || null,
        template_json: { rule_year: 2024 },
        hp: Number(hp),
        max_hp: Number(hp),
        armor_class: Number(armorClass),
        speed: Number(speed),
        active: true,
        notes: null,
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["companions", campaignId] });
      setName("");
      showToast("伙伴 / 形态模板已创建");
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "创建失败", "error"),
  });
  const toggle = useMutation({
    mutationFn: ({ id, active, version }: { id: string; active: boolean; version: number }) =>
      updateCompanion(campaignId, id, { active }, version),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["companions", campaignId] }),
    onError: () => showToast("伙伴状态更新失败", "error"),
  });
  const ownerName = (id: string) => characters.find((item) => item.id === id)?.name ?? "未知角色";
  return (
    <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/30 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <strong className="text-sm text-parchment-100">伙伴、召唤物与形态模板</strong>
          <p className="m-0 text-2xs text-stone-500">独立原子，可在场景和战斗中复用；保留规则记录来源。</p>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-4 xl:grid-cols-8">
        <select className={selectCls} onChange={(event) => setOwnerId(event.target.value)} value={ownerId}>
          <option value="">选择主人</option>
          {characters.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <select className={selectCls} onChange={(event) => setType(event.target.value as typeof type)} value={type}>
          {TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <input className={inputCls} onChange={(event) => setName(event.target.value)} placeholder="名称" value={name} />
        <input className={inputCls} min="1" onChange={(event) => setHp(event.target.value)} placeholder="HP" type="number" value={hp} />
        <input className={inputCls} min="0" onChange={(event) => setArmorClass(event.target.value)} placeholder="AC" type="number" value={armorClass} />
        <input className={inputCls} min="0" onChange={(event) => setSpeed(event.target.value)} placeholder="速度" type="number" value={speed} />
        <input className={inputCls} onChange={(event) => setSourceRecordId(event.target.value)} placeholder="规则记录ID（可选）" value={sourceRecordId} />
        <Button loading={create.isPending} onClick={() => create.mutate()} variant="primary">创建</Button>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {(companions.data ?? []).map((item) => (
          <div className="rounded border border-ink-700 p-3 text-xs" key={item.id}>
            <div className="flex items-center justify-between">
              <strong className="text-parchment-100">{item.name}</strong>
              <Button
                loading={toggle.isPending}
                onClick={() => toggle.mutate({
                  id: item.id,
                  active: !item.active,
                  version: item.version,
                })}
                size="sm"
                variant={item.active ? "primary" : "ghost"}
              >
                {item.active ? "在场" : "停用"}
              </Button>
            </div>
            <p className="mb-0 mt-1 text-stone-500">
              {ownerName(item.owner_character_id)} · {TYPES.find(([value]) => value === item.companion_type)?.[1]}
              {" · "}AC {item.armor_class} · HP {item.hp}/{item.max_hp} · {item.speed}尺
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
