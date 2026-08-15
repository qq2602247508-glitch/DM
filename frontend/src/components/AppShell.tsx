import { useQuery } from "@tanstack/react-query";
import { useEffect, type ReactElement, type ReactNode } from "react";

import { listCampaigns } from "../api/campaigns";
import { listProposals } from "../api/assistant";
import { listLocations } from "../api/entities";
import { useCurrentCampaign } from "../hooks/appContexts";
import { navigate, useHashRoute, type RoutePath } from "../hooks/useHashRoute";
import { useOffline } from "../hooks/useOffline";
import { useCampaignRealtime } from "../hooks/useRealtimeInvalidation";
import { Icon, type IconName } from "../ui/icons";
import { formatDateTime } from "../ui/format";
import { StatusCluster } from "./StatusCluster";
import { SoundboardBar } from "./SoundboardBar";

const NAV_GROUPS: Array<{ label: string; items: Array<{ path: RoutePath; label: string; icon: IconName }> }> = [
  { label: "现场", items: [
    { path: "/", label: "DM 仪表板", icon: "home" },
    { path: "/game-table", label: "游戏推进台", icon: "sparkle" },
    { path: "/quick-combat", label: "⚡ 快捷战斗座舱", icon: "sword" },
    { path: "/simulation", label: "模拟战斗", icon: "sword" },
    { path: "/combat", label: "战斗辅助", icon: "sword" },
  ] },
  { label: "战役档案", items: [
    { path: "/campaigns", label: "跑团档案", icon: "scroll" },
    { path: "/characters", label: "玩家角色", icon: "users" },
    { path: "/npcs", label: "NPC 与人物", icon: "users" },
    { path: "/locations", label: "地点与场景", icon: "map-pin" },
    { path: "/scenes", label: "Scene 编排", icon: "map-pin" },
    { path: "/quests", label: "任务与线索", icon: "scroll" },
    { path: "/events", label: "事件时间线", icon: "scroll" },
  ] },
  { label: "D&D 图鉴库", items: [
    { path: "/compendium", label: "原子图鉴", icon: "copy" },
    { path: "/merchants", label: "商人与商店", icon: "users" },
    { path: "/inventory", label: "角色背包与装备", icon: "copy" },
    { path: "/rules", label: "D&D 规则库", icon: "scroll" },
  ] },
  { label: "副驾驶", items: [
    { path: "/assistant", label: "AI 助手", icon: "sparkle" },
    { path: "/proposals", label: "提案中心", icon: "alert" },
  ] },
  { label: "系统", items: [
    { path: "/settings", label: "设置与备份", icon: "copy" },
  ] },
];
const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

export function AppShell({ children }: { children: ReactNode }): ReactElement {
  const route = useHashRoute();
  const offline = useOffline();
  const { campaignId, selectCampaign } = useCurrentCampaign();
  useCampaignRealtime(campaignId);

  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: ({ signal }) => listCampaigns(signal),
    retry: 1,
  });

  // Auto-select the first campaign when nothing (valid) is selected.
  useEffect(() => {
    const items = campaigns.data;
    if (!items || items.length === 0) {
      return;
    }
    if (campaignId === null || !items.some((c) => c.id === campaignId)) {
      selectCampaign(items.find((campaign) => campaign.status !== "archived")?.id ?? items[0]?.id ?? null);
    }
  }, [campaigns.data, campaignId, selectCampaign]);

  const currentCampaign = campaigns.data?.find((c) => c.id === campaignId) ?? null;
  const selectableCampaigns = campaigns.data?.filter(
    (campaign) => campaign.status !== "archived" || campaign.id === campaignId,
  );

  const locations = useQuery({
    queryKey: ["locations", campaignId],
    queryFn: ({ signal }) => listLocations(campaignId ?? "", signal),
    enabled: campaignId !== null,
  });

  const pendingProposals = useQuery({
    queryKey: ["proposals", campaignId, "pending"],
    queryFn: ({ signal }) => listProposals(campaignId ?? "", "pending", signal),
    enabled: campaignId !== null,
    refetchInterval: 20_000,
  });

  const pendingCount = pendingProposals.data?.length ?? 0;
  const currentLocation = locations.data?.find(
    (loc) => loc.id === currentCampaign?.current_location_id,
  );

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Left navigation */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-ink-700/70 bg-ink-950/70 md:flex">
        <button
          className="flex items-center gap-2.5 border-b border-ink-700/70 px-4 py-4 text-left transition-colors hover:bg-ink-900/60"
          onClick={() => navigate("/")}
          type="button"
        >
          <span
            aria-hidden="true"
            className="grid size-9 shrink-0 place-items-center rounded-full border border-ember-400/50 bg-ember-500/10 font-display text-sm text-ember-300"
          >
            d20
          </span>
          <span className="min-w-0">
            <span className="block font-display text-sm text-parchment-100">DM 控制台</span>
            <span className="block truncate text-2xs text-stone-600">本地 D&D 助手</span>
          </span>
        </button>
        <nav aria-label="主导航" className="flex-1 overflow-y-auto px-2 py-3">
          {NAV_GROUPS.map((group) => <section className="mb-3" key={group.label}>
            <h2 className="mb-1 px-3 text-[10px] font-medium uppercase tracking-[.18em] text-stone-700">{group.label}</h2>
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
              {group.items.map((item) => {
                const active = route === item.path;
                const badge = item.path === "/proposals" && pendingCount > 0;
                return (
                  <li key={item.path}>
                    <button
                      aria-current={active ? "page" : undefined}
                      className={`flex w-full items-center gap-2.5 rounded-md border px-3 py-2 text-sm transition-colors ${
                        active
                          ? "border-ember-600/40 bg-ember-500/10 text-ember-200"
                          : "border-transparent text-stone-400 hover:bg-ink-800/70 hover:text-parchment-100"
                      }`}
                      onClick={() => navigate(item.path)}
                      type="button"
                    >
                      <Icon name={item.icon} size={15} />
                      <span className="flex-1 text-left">{item.label}</span>
                      {badge ? <span className="rounded-full bg-amber-500/20 px-1.5 py-0.5 text-2xs font-medium text-amber-300">{pendingCount}</span> : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>)}
        </nav>
        <div className="border-t border-ink-700/70 px-4 py-3 text-2xs leading-5 text-stone-600">
          数据保存在本机 SQLite
          <br />
          AI 仅提供建议，DM 拥有最终决定权
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-ink-700/70 bg-ink-900/80 px-4 py-2.5">
          {/* Mobile nav select */}
          <select
            aria-label="页面导航"
            className="rounded-md border border-ink-600 bg-ink-950 px-2 py-1.5 text-sm text-parchment-100 md:hidden"
            onChange={(event) => navigate(event.target.value as RoutePath)}
            value={route}
          >
            {NAV_ITEMS.map((item) => (
              <option key={item.path} value={item.path}>
                {item.label}
              </option>
            ))}
          </select>

          <div className="flex min-w-0 items-center gap-2">
            <label className="sr-only" htmlFor="campaign-switcher">
              当前跑团
            </label>
            <select
              className="max-w-56 truncate rounded-md border border-ink-600 bg-ink-950 px-2.5 py-1.5 text-sm text-parchment-100"
              disabled={!campaigns.data || campaigns.data.length === 0}
              id="campaign-switcher"
              onChange={(event) => selectCampaign(event.target.value)}
              value={campaignId ?? ""}
            >
              {selectableCampaigns && selectableCampaigns.length > 0 ? (
                selectableCampaigns.map((campaign) => (
                  <option key={campaign.id} value={campaign.id}>
                    {campaign.name}{campaign.status === "archived" ? "（已归档）" : ""}
                  </option>
                ))
              ) : (
                <option value="">未选择跑团</option>
              )}
            </select>
            {currentCampaign ? (
              <span className="hidden rounded border border-emerald-800/50 bg-emerald-950/25 px-2 py-1 text-2xs text-emerald-300 sm:inline">
                团档隔离
              </span>
            ) : null}
            {currentCampaign ? (
              <span className="hidden items-center gap-1.5 truncate text-xs text-stone-500 lg:flex">
                <Icon name="map-pin" size={12} />
                {currentLocation ? currentLocation.name : "未设置地点"}
                {currentCampaign.current_time
                  ? ` · ${formatDateTime(currentCampaign.current_time)}`
                  : ""}
              </span>
            ) : null}
          </div>

          <div className="ml-auto flex items-center gap-3">
            <SoundboardBar />
            <StatusCluster />
          </div>
        </header>

        {offline ? (
          <div className="border-b border-amber-800/60 bg-amber-950/50 px-4 py-1.5 text-center text-xs text-amber-200">
            浏览器处于离线状态 — 所有数据都来自本机后端，请检查本地服务
          </div>
        ) : null}

        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
