import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactElement } from "react";

import { isApiError } from "../api/client";
import {
  getSimulation,
  prepareSimulation,
  resetSimulation,
  type SimulationState,
} from "../api/simulation";
import type { Campaign } from "../api/types";
import { Panel } from "../components/Panel";
import { useCurrentCampaign } from "../hooks/appContexts";
import { useToast } from "../hooks/toastContext";
import { navigate } from "../hooks/useHashRoute";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";

function readActionNames(actions: unknown): string[] {
  if (!Array.isArray(actions)) return [];
  return actions.map((action) => {
    if (typeof action === "string") return action;
    if (typeof action !== "object" || action === null) return "未命名动作";
    const record = action as Record<string, unknown>;
    return typeof record.name === "string" ? record.name : "未命名动作";
  });
}

function buildPlayerUrl(joinCode: string): string {
  const params = new URLSearchParams({
    simulation_join_code: joinCode,
    simulation_name: "模拟玩家",
  });
  return `${window.location.origin}/#/player?${params.toString()}`;
}

function syncCampaignCache(
  client: ReturnType<typeof useQueryClient>,
  campaign: Campaign,
): void {
  client.setQueryData<Campaign[]>(["campaigns"], (previous) => {
    if (!previous) return [campaign];
    if (previous.some((item) => item.id === campaign.id)) return previous;
    return [campaign, ...previous];
  });
}

function SimulationOverview({ state }: { state: SimulationState }): ReactElement {
  return (
    <Panel eyebrow="固定演练剧本" title={state.scenario.title}>
      <p className="mb-3 mt-0 text-sm leading-6 text-stone-300">{state.scenario.objective}</p>
      <div className="grid gap-2 md:grid-cols-2">
        {state.scenario.checkpoints.map((checkpoint, index) => (
          <div className="rounded-md border border-ink-700 bg-ink-950/45 p-3 text-xs leading-5 text-stone-400" key={checkpoint}>
            <span className="mr-2 font-mono text-ember-300">0{index + 1}</span>
            {checkpoint}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function CombatantCard({ state, combatant }: { state: SimulationState; combatant: SimulationState["combatants"][number] }): ReactElement {
  const side = combatant.entity_id === state.character.id ? "玩家" : "敌方 AI";
  const tone = side === "玩家" ? "ok" : "danger";
  const actions = readActionNames(combatant.snapshot_json.actions);
  return (
    <article className="rounded-lg border border-ink-700 bg-ink-950/45 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="m-0 text-sm font-medium text-parchment-100">{combatant.display_name}</h3>
          <p className="mb-0 mt-1 text-2xs text-stone-600">先攻 {combatant.initiative} · AC {combatant.armor_class}</p>
        </div>
        <Badge tone={tone}>{side}</Badge>
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-stone-400">
        <span className="font-mono text-emerald-300">{combatant.hp}/{combatant.max_hp} HP</span>
        <span>·</span>
        <span>速度 {combatant.speed_ft} 尺</span>
      </div>
      {actions.length > 0 ? <p className="mb-0 mt-2 text-2xs leading-5 text-stone-500">动作：{actions.join("、")}</p> : null}
    </article>
  );
}

export function SimulationPage(): ReactElement {
  const client = useQueryClient();
  const { selectCampaign } = useCurrentCampaign();
  const { showToast } = useToast();
  const simulation = useQuery({
    queryKey: ["simulation"],
    queryFn: ({ signal }) => getSimulation(signal),
    retry: false,
  });
  const [state, setState] = useState<SimulationState | null>(null);
  const [playerUrl, setPlayerUrl] = useState<string | null>(null);

  useEffect(() => {
    if (simulation.data) setState(simulation.data);
  }, [simulation.data]);

  const applyState = (next: SimulationState, message: string): void => {
    setState(next);
    client.setQueryData(["simulation"], next);
    syncCampaignCache(client, next.campaign);
    selectCampaign(next.campaign.id);
    if (next.player_join_code) {
      const url = buildPlayerUrl(next.player_join_code);
      setPlayerUrl(url);
    }
    showToast(message, "success");
  };

  const prepare = useMutation({
    mutationFn: prepareSimulation,
    onSuccess: (next) => applyState(next, "模拟战斗已准备，已接入真实战斗与玩家房间接口。"),
  });
  const reset = useMutation({
    mutationFn: resetSimulation,
    onSuccess: (next) => applyState(next, "模拟战斗已重置：HP、先攻、资源、状态和日志均回到初始值。"),
  });

  const openPlayer = async (): Promise<void> => {
    let url = playerUrl;
    if (!url) {
      const next = await prepare.mutateAsync();
      applyState(next, "已重新打开模拟玩家房间。即将启动玩家页面。" );
      url = next.player_join_code ? buildPlayerUrl(next.player_join_code) : null;
    }
    if (!url) return;
    window.open(url, "dnd-simulation-player", "noopener,noreferrer");
  };

  if (simulation.isLoading && !state) return <LoadingBlock label="正在读取模拟战斗…" />;
  if (simulation.isError && !isApiError(simulation.error, 404) && !state) {
    return <div className="p-6"><ErrorState error={simulation.error} onRetry={() => void simulation.refetch()} /></div>;
  }

  return (
    <div className="space-y-4 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="m-0 text-2xs font-semibold uppercase tracking-[0.22em] text-ember-400/90">DM 测试入口</p>
          <h1 className="mb-1 mt-1 font-display text-2xl text-parchment-100">模拟战斗</h1>
          <p className="m-0 max-w-2xl text-sm leading-6 text-stone-500">固定剧本用于回归测试。它创建独立的系统战役，但战斗、召唤、玩家房间和怪物 AI 都走现有正式接口。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={prepare.isPending} loading={prepare.isPending} onClick={() => prepare.mutate()} variant="primary">{state ? "重新载入剧本" : "加载模拟战斗"}</Button>
          {state ? <Button disabled={reset.isPending} loading={reset.isPending} onClick={() => reset.mutate()} variant="danger">重置模拟战斗</Button> : null}
        </div>
      </header>

      {!state ? (
        <Panel eyebrow="隔离测试场" title="尚未加载模拟战斗">
          <EmptyState
            action={<Button loading={prepare.isPending} onClick={() => prepare.mutate()} variant="primary">创建并加载固定战斗</Button>}
            hint="创建后会生成一名 5 级奥术师、两个敌方 AI、一个召唤物模板、真实 SceneGrid、Combat 和可加入的玩家房间。"
            icon="sword"
            title="准备一场可重复的元素熔炉演练"
          />
        </Panel>
      ) : (
        <>
          <SimulationOverview state={state} />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(300px,0.72fr)]">
            <Panel eyebrow="真实 Combat 数据" title={state.combat.name}>
              <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-stone-500">
                <Badge tone="ok">第 {state.combat.round_number} 轮</Badge>
                <span>{state.scene.name}</span>
                <span>·</span>
                <span>{state.grid?.width ?? 0} × {state.grid?.height ?? 0} 网格</span>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {state.combatants.map((combatant) => <CombatantCard combatant={combatant} key={combatant.id} state={state} />)}
              </div>
            </Panel>
            <Panel eyebrow="测试操作" title="从两个端点验收">
              <div className="grid gap-2">
                <Button onClick={() => navigate("/combat")} variant="primary">打开 DM 战斗辅助</Button>
                <Button loading={prepare.isPending} onClick={() => void openPlayer()} variant="ghost">启动玩家页面</Button>
              </div>
              {playerUrl ? (
                <div className="mt-3 rounded-md border border-emerald-900/60 bg-emerald-950/20 p-3">
                  <p className="m-0 text-2xs text-emerald-300">玩家入口已准备好</p>
                  <a className="mt-1 block break-all text-xs leading-5 text-emerald-200 underline decoration-emerald-700" href={playerUrl} rel="noreferrer" target="_blank">{playerUrl}</a>
                  <p className="mb-0 mt-2 text-2xs leading-5 text-stone-600">链接会自动加入房间并绑定“模拟玩家·奥术师”。重置后请使用页面重新生成的新链接。</p>
                </div>
              ) : <p className="mb-0 mt-3 text-xs leading-5 text-stone-500">点击“启动玩家页面”会重新打开玩家房间并生成一次性入口。</p>}
              <div className="mt-4 border-t border-ink-700 pt-3 text-xs leading-5 text-stone-500">
                <p className="m-0 text-stone-300">玩家角色：{state.character.name} · {state.character.class_name} Lv.{state.character.level}</p>
                <p className="mb-0 mt-1">召唤模板：{state.companion.name} · 召唤后由真实 CombatEngine 创建新单位并加入先攻。</p>
              </div>
            </Panel>
          </div>
          {prepare.isError ? <ErrorState error={prepare.error} onRetry={() => prepare.mutate()} /> : null}
          {reset.isError ? <ErrorState error={reset.error} onRetry={() => reset.mutate()} /> : null}
        </>
      )}
    </div>
  );
}
