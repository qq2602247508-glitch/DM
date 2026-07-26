import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import { createNpc } from "../api/entities";
import type { GeneratedNpc, NpcGenerationPreview } from "../api/types";
import { generateNpc } from "../api/world";
import { CitationList } from "../components/Citations";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { useToast } from "../hooks/toastContext";
import { Badge, Button, ErrorState, Tabs } from "../ui/primitives";
import { inputCls, textareaCls } from "../ui/styles";
import { AiTag, DmOnlyTag, SecretBlock } from "../ui/widgets";
import { ManagementPage } from "./ManagementPage";

const ABILITY_LABELS: Record<string, string> = {
  strength: "力",
  dexterity: "敏",
  constitution: "体",
  intelligence: "智",
  wisdom: "感",
  charisma: "魅",
};

function Preview({
  value,
  saving,
  onConfirm,
}: {
  value: NpcGenerationPreview;
  saving: boolean;
  onConfirm: () => void;
}): ReactElement {
  const npc = value.npc;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <AiTag>AI 草稿</AiTag>
        <Badge tone="ok">D&D 5e · 2024</Badge>
        {npc.challenge_rating ? <Badge>CR {npc.challenge_rating}</Badge> : null}
        <span className="ml-auto text-2xs text-stone-600">保存前不会写入战役</span>
      </div>
      <div>
        <h3 className="m-0 font-display text-xl text-parchment-100">{npc.name}</h3>
        <p className="prose-block mb-0 mt-2 text-sm text-stone-300">{npc.description}</p>
        <p className="mb-0 mt-2 text-xs text-violet-300">
          {npc.alignment || "阵营未定"} · {npc.attitude || "态度未定"} · AC {npc.armor_class} ·
          HP {npc.hp}/{npc.max_hp} · 速度 {npc.speed}
        </p>
      </div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {Object.entries(npc.ability_scores).map(([key, score]) => (
          <div className="rounded-md border border-ink-700 bg-ink-950/60 px-2 py-2 text-center" key={key}>
            <span className="block text-2xs text-stone-600">{ABILITY_LABELS[key] ?? key}</span>
            <strong className="font-mono text-sm text-parchment-100">{score}</strong>
          </div>
        ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-ink-700 bg-ink-950/40 p-3 text-xs leading-5 text-stone-300">
          <p className="m-0"><strong className="text-parchment-100">性格：</strong>{npc.personality || "—"}</p>
          <p className="mb-0 mt-1"><strong className="text-parchment-100">目标：</strong>{npc.goal || "—"}</p>
          <p className="mb-0 mt-1"><strong className="text-parchment-100">恐惧：</strong>{npc.fear || "—"}</p>
        </div>
        <SecretBlock label="NPC 秘密" value={npc.secret} />
      </div>
      {npc.actions.length ? (
        <div>
          <p className="mb-2 mt-0 text-xs font-medium text-stone-400">动作</p>
          <ul className="m-0 space-y-2 p-0">
            {npc.actions.map((action) => (
              <li className="list-none rounded border border-ink-700 px-3 py-2 text-xs text-stone-300" key={action.name}>
                <strong className="text-parchment-100">{action.name}：</strong>{action.description}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {value.warnings.map((warning) => (
        <p className="m-0 text-xs text-amber-300" key={warning}>复核提示：{warning}</p>
      ))}
      <CitationList citations={value.citations} />
      <div className="flex items-center justify-between border-t border-ink-700 pt-3">
        <span className="flex items-center gap-2 text-xs text-stone-500"><DmOnlyTag />由 DM 确认后保存</span>
        <Button loading={saving} onClick={onConfirm} variant="primary">确认并创建 NPC</Button>
      </div>
    </div>
  );
}

function toNpcInput(npc: GeneratedNpc) {
  return {
    name: npc.name,
    description: npc.description,
    alignment: npc.alignment,
    attitude: npc.attitude,
    personality: npc.personality,
    goal: npc.goal,
    fear: npc.fear,
    secrets: npc.secret,
    known_information: npc.known_information,
    armor_class: npc.armor_class,
    hp: npc.hp,
    max_hp: npc.max_hp,
    speed: npc.speed,
    ability_scores: npc.ability_scores,
    challenge_rating: npc.challenge_rating,
    actions: npc.actions,
    equipment: npc.equipment,
    status: "active",
  };
}

function NpcGenerator({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [mode, setMode] = useState<"quick" | "guided">("quick");
  const [brief, setBrief] = useState("生成一名适合当前战役、可立即登场的 NPC");
  const [answers, setAnswers] = useState({
    role: "",
    faction: "",
    attitude: "",
    tier: "",
    secret: "",
  });
  const [preview, setPreview] = useState<NpcGenerationPreview | null>(null);
  const generation = useMutation({
    mutationFn: () => generateNpc(campaignId, { mode, brief, answers }),
    onSuccess: (value) => {
      setPreview(value);
      showToast("NPC 草稿已生成，请复核后确认");
    },
    onError: () => showToast("NPC 生成失败，请检查本地模型与规则索引", "error"),
  });
  const save = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("没有可保存的草稿");
      return createNpc(campaignId, toNpcInput(preview.npc));
    },
    onSuccess: () => {
      setPreview(null);
      void client.invalidateQueries({ queryKey: ["npcs", campaignId] });
      showToast("NPC 已加入战役");
    },
    onError: () => showToast("NPC 保存失败", "error"),
  });
  return (
    <Panel eyebrow="本地 AI · 规则约束" title="NPC 生成器">
      <Tabs
        active={mode}
        onChange={(value) => setMode(value as "quick" | "guided")}
        tabs={[
          { id: "quick", label: "一键快速生成" },
          { id: "guided", label: "提问式生成" },
        ]}
      />
      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
        <textarea
          className={textareaCls}
          onChange={(event) => setBrief(event.target.value)}
          placeholder="例如：一位知道失踪商队下落、但不愿直接说出的港口医生"
          value={brief}
        />
        <Button
          disabled={!brief.trim()}
          loading={generation.isPending}
          onClick={() => generation.mutate()}
          variant="ai"
        >
          {mode === "quick" ? "一键生成" : "按条件生成"}
        </Button>
      </div>
      {mode === "guided" ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
          {([
            ["role", "身份 / 用途"],
            ["faction", "所属阵营"],
            ["attitude", "对玩家态度"],
            ["tier", "战斗定位 / 等级"],
            ["secret", "希望隐藏的秘密"],
          ] as const).map(([key, label]) => (
            <input
              className={inputCls}
              key={key}
              onChange={(event) => setAnswers((current) => ({ ...current, [key]: event.target.value }))}
              placeholder={label}
              value={answers[key]}
            />
          ))}
        </div>
      ) : null}
      {generation.isError ? <div className="mt-4"><ErrorState error={generation.error} onRetry={() => generation.mutate()} /></div> : null}
      {preview ? (
        <div className="mt-5 border-t border-ink-700 pt-4">
          <Preview onConfirm={() => save.mutate()} saving={save.isPending} value={preview} />
        </div>
      ) : null}
    </Panel>
  );
}

export function NpcPage(): ReactElement {
  return (
    <RequireCampaign>
      {(campaignId) => (
        <>
          <div className="mx-auto max-w-[1200px] px-4 pt-4 lg:px-6 lg:pt-6">
            <NpcGenerator campaignId={campaignId} />
          </div>
          <ManagementPage kind="npcs" />
        </>
      )}
    </RequireCampaign>
  );
}
