import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactElement } from "react";

import { getCampaignState } from "../api/campaigns";
import { listEvents } from "../api/entities";
import { listProposals } from "../api/assistant";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { useAssistantPrefill } from "../hooks/appContexts";
import { navigate } from "../hooks/useHashRoute";
import type { Clue, Quest } from "../api/types";
import { formatDateTime } from "../ui/format";
import { Icon } from "../ui/icons";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import {
  COMBAT_STATUS_LABELS,
  NPC_STATUS_LABELS,
  QUEST_STATUS_LABELS,
  btnAi,
} from "../ui/styles";
import { DmOnlyTag, HpBar } from "../ui/widgets";

function QuickAssistantEntry(): ReactElement {
  const { setPrefill } = useAssistantPrefill();
  const [text, setText] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const action = text.trim();
    if (!action) {
      return;
    }
    setPrefill(action);
    navigate("/assistant");
  };

  return (
    <form className="flex flex-col gap-2" onSubmit={submit}>
      <label className="sr-only" htmlFor="quick-assistant">
        向 AI 助手描述玩家行动
      </label>
      <textarea
        className="min-h-16 w-full resize-none rounded-md border border-ink-600 bg-ink-950/80 px-3 py-2 text-sm text-parchment-100 outline-none placeholder:text-stone-600 focus:border-violet-500/60"
        id="quick-assistant"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit(event);
          }
        }}
        placeholder="玩家想调查酒馆老板是否撒谎…"
        value={text}
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-2xs text-stone-600">Enter 发送 · Shift+Enter 换行</span>
        <button className={`${btnAi} px-2.5 py-1 text-xs`} disabled={!text.trim()} type="submit">
          <Icon name="send" size={13} />
          咨询 AI
        </button>
      </div>
    </form>
  );
}

function questTone(status: string): "ok" | "warn" | "neutral" {
  if (status === "active") {
    return "warn";
  }
  if (status === "completed") {
    return "ok";
  }
  return "neutral";
}

function DashboardContent({ campaignId }: { campaignId: string }): ReactElement {
  const state = useQuery({
    queryKey: ["campaign-state", campaignId],
    queryFn: ({ signal }) => getCampaignState(campaignId, 100, signal),
    refetchInterval: 30_000,
  });

  const events = useQuery({
    queryKey: ["events", campaignId],
    queryFn: ({ signal }) => listEvents(campaignId, signal),
  });

  const pendingProposals = useQuery({
    queryKey: ["proposals", campaignId, "pending"],
    queryFn: ({ signal }) => listProposals(campaignId, "pending", signal),
    refetchInterval: 20_000,
  });

  if (state.isLoading) {
    return <LoadingBlock label="正在读取战役状态…" />;
  }
  if (state.isError || !state.data) {
    return <ErrorState error={state.error} onRetry={() => void state.refetch()} />;
  }

  const snapshot = state.data;
  const campaign = snapshot.campaign;
  const locationName = snapshot.locations.find(
    (loc) => loc.id === campaign.current_location_id,
  )?.name;
  const activeQuests = snapshot.quests.filter((q) => q.status === "open" || q.status === "active");
  const activeNpcs = snapshot.npcs.filter((npc) => npc.status === "active").slice(0, 6);
  const recentEvents = [...(events.data ?? [])]
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
    .slice(0, 8);
  const proposals = (pendingProposals.data ?? []).slice(0, 5);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.9fr)_minmax(300px,1fr)]">
      {/* Main workspace */}
      <div className="flex min-w-0 flex-col gap-4">
        {/* Campaign strip */}
        <Panel eyebrow="当前战役" title={String(campaign.name ?? "未命名战役")}>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <span className="flex items-center gap-1.5 text-stone-400">
              <Icon name="map-pin" size={13} />
              {locationName ?? "未设置地点"}
            </span>
            <span className="text-stone-400">
              时间：{campaign.current_time ? formatDateTime(campaign.current_time) : "未设置"}
            </span>
            <Badge tone={campaign.status === "active" ? "ok" : "neutral"}>
              {campaign.status === "active" ? "进行中" : String(campaign.status ?? "")}
            </Badge>
            {campaign.world_setting ? (
              <span className="text-stone-500">{String(campaign.world_setting)}</span>
            ) : null}
          </div>
          {typeof campaign.description === "string" && campaign.description ? (
            <p className="mb-0 mt-2.5 line-clamp-2 text-xs leading-5 text-stone-500">
              {campaign.description}
            </p>
          ) : null}
        </Panel>

        {/* Characters */}
        <Panel
          action={
            <Button onClick={() => navigate("/characters")} size="sm">
              管理
            </Button>
          }
          eyebrow="队伍"
          title="玩家角色"
        >
          {snapshot.characters.length === 0 ? (
            <EmptyState hint="在角色管理中添加玩家角色。" title="还没有角色" />
          ) : (
            <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2">
              {snapshot.characters.map((character) => (
                <li
                  className="rounded-md border border-ink-700/70 bg-ink-950/50 px-3 py-2.5"
                  key={character.id}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="m-0 truncate text-sm font-medium text-parchment-100">
                      {character.name}
                    </p>
                    <span className="shrink-0 text-2xs text-stone-500">
                      {character.class_name ?? "未设定职业"} · Lv{character.level}
                    </span>
                  </div>
                  <div className="mt-2">
                    <HpBar hp={character.hp} maxHp={character.max_hp} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="grid gap-4 lg:grid-cols-2">
          {/* Quests */}
          <Panel
            action={
              <Button onClick={() => navigate("/quests")} size="sm">
                管理
              </Button>
            }
            eyebrow="故事线"
            title="当前任务"
          >
            {activeQuests.length === 0 ? (
              <EmptyState title="没有进行中的任务" />
            ) : (
              <ul className="m-0 list-none divide-y divide-ink-700/60 p-0">
                {activeQuests.map((quest: Quest) => (
                  <li className="flex items-center justify-between gap-2 py-2" key={quest.id}>
                    <span className="truncate text-sm text-parchment-100">{quest.name}</span>
                    <Badge tone={questTone(quest.status)}>
                      {QUEST_STATUS_LABELS[quest.status] ?? quest.status}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          {/* Open clues */}
          <Panel
            action={
              <Button onClick={() => navigate("/quests")} size="sm">
                管理
              </Button>
            }
            eyebrow="调查"
            title="未解决线索"
          >
            {snapshot.open_clues.length === 0 ? (
              <EmptyState title="没有待发现的线索" />
            ) : (
              <ul className="m-0 list-none divide-y divide-ink-700/60 p-0">
                {snapshot.open_clues.map((clue: Clue) => (
                  <li className="py-2" key={clue.id}>
                    <p className="m-0 truncate text-sm text-parchment-100">{clue.name}</p>
                    <p className="m-0 mt-0.5 text-2xs text-stone-600">
                      {clue.discovered ? "已发现，待跟进" : "未被发现"}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        {/* Active combats */}
        <Panel
          action={
            <Button onClick={() => navigate("/combat")} size="sm">
              进入战斗
            </Button>
          }
          eyebrow="交锋"
          title="活跃战斗"
        >
          {snapshot.active_combats.length === 0 ? (
            <EmptyState hint="当前没有进行中的战斗。" title="局势平静" />
          ) : (
            <ul className="m-0 list-none divide-y divide-ink-700/60 p-0">
              {snapshot.active_combats.map((combat) => (
                <li className="flex items-center justify-between gap-2 py-2" key={combat.id}>
                  <span className="truncate text-sm text-parchment-100">{combat.name}</span>
                  <span className="flex items-center gap-2 text-2xs text-stone-500">
                    <span className="font-mono">第 {combat.round_number} 轮</span>
                    <Badge tone="danger">{COMBAT_STATUS_LABELS[combat.status] ?? combat.status}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {/* Recent events */}
        <Panel eyebrow="编年史" title="最近事件">
          {events.isLoading ? (
            <LoadingBlock />
          ) : recentEvents.length === 0 ? (
            <EmptyState title="还没有记录任何事件" />
          ) : (
            <ol className="m-0 list-none divide-y divide-ink-700/60 p-0">
              {recentEvents.map((event) => (
                <li className="flex items-start justify-between gap-3 py-2" key={event.id}>
                  <div className="min-w-0">
                    <p className="m-0 text-sm text-parchment-100">{event.title}</p>
                    <p className="m-0 mt-0.5 text-2xs text-stone-600">
                      {formatDateTime(event.occurred_at)} · {event.event_type}
                    </p>
                  </div>
                  {event.visibility === "dm" ? <DmOnlyTag /> : null}
                </li>
              ))}
            </ol>
          )}
        </Panel>
      </div>

      {/* Right rail: AI entry + proposals + NPCs */}
      <div className="flex min-w-0 flex-col gap-4">
        <Panel eyebrow="协助" title="AI 助手">
          <QuickAssistantEntry />
          <button
            className="mt-2.5 w-full text-left text-2xs text-violet-300/80 transition-colors hover:text-violet-200"
            onClick={() => navigate("/assistant")}
            type="button"
          >
            打开完整助手（规则查询 / 剧情建议 / 战斗辅助）→
          </button>
        </Panel>

        <Panel
          action={
            <Badge tone={proposals.length > 0 ? "warn" : "neutral"}>{proposals.length}</Badge>
          }
          eyebrow="审查"
          title="待确认提案"
        >
          {pendingProposals.isLoading ? (
            <LoadingBlock />
          ) : proposals.length === 0 ? (
            <EmptyState hint="AI 提出的状态修改会在这里等待你的确认。" title="没有待处理的提案" />
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {proposals.map((proposal) => (
                <li key={proposal.id}>
                  <button
                    className="w-full rounded-md border border-amber-900/50 bg-amber-950/20 px-3 py-2 text-left transition-colors hover:border-amber-700/60"
                    onClick={() => navigate("/proposals")}
                    type="button"
                  >
                    <span className="block truncate text-xs text-parchment-100">
                      {proposal.reason}
                    </span>
                    <span className="mt-1 block text-2xs text-amber-300/80">
                      待确认 · 点击前往提案中心处理
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          action={
            <Button onClick={() => navigate("/npcs")} size="sm">
              管理
            </Button>
          }
          eyebrow="登场"
          title="活跃 NPC"
        >
          {activeNpcs.length === 0 ? (
            <EmptyState title="没有活跃 NPC" />
          ) : (
            <ul className="m-0 list-none divide-y divide-ink-700/60 p-0">
              {snapshot.npcs.slice(0, 8).map((npc) => (
                <li className="flex items-center justify-between gap-2 py-2" key={npc.id}>
                  <span className="truncate text-sm text-parchment-100">{npc.name}</span>
                  <span className="flex items-center gap-1.5">
                    {npc.secrets ? <DmOnlyTag /> : null}
                    <Badge tone={npc.status === "active" ? "ok" : "neutral"}>
                      {NPC_STATUS_LABELS[npc.status] ?? npc.status}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

export function DashboardPage(): ReactElement {
  return (
    <div className="mx-auto max-w-[1500px] p-4 lg:p-5">
      <RequireCampaign>
        {(campaignId) => <DashboardContent campaignId={campaignId} />}
      </RequireCampaign>
    </div>
  );
}
