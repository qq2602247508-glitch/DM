import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import {
  confirmSiteGeneration,
  getAdventureSite,
  listAdventureSites,
  listRegionMaps,
  previewSiteGeneration,
  type SiteGenerationInput,
  type SiteGenerationPreview,
  type SiteLevelPreview,
} from "../api/world";
import { useToast } from "../hooks/toastContext";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../ui/styles";
import { Panel } from "./Panel";

const cellColor: Record<string, string> = {
  void: "bg-transparent border-transparent",
  wall: "bg-stone-800 border-stone-600",
  floor: "bg-amber-950/30 border-amber-900/40",
  door: "bg-amber-500/80 border-amber-300",
  cover: "bg-emerald-900 border-emerald-500",
  room: "bg-cyan-950 border-cyan-500",
  stairs: "bg-violet-950 border-violet-400",
};

function SiteGrid({ level }: { level: SiteLevelPreview }): ReactElement {
  return (
    <div className="max-h-[62vh] overflow-auto rounded-lg border border-ink-700 bg-ink-950 p-2">
      <div
        aria-label={`${level.name}完整网格`}
        className="grid min-w-[650px]"
        style={{ gridTemplateColumns: `repeat(${level.layout.width}, minmax(24px, 1fr))` }}
      >
        {level.layout.cells.map((cell) => (
          <div
            className={`aspect-square border text-[7px] leading-none ${cell.label === "地图外区域" ? "border-black/70 bg-black/80" : cellColor[cell.kind] ?? "bg-ink-900 border-ink-700"}`}
            key={`${cell.row}-${cell.col}`}
            title={`${cell.label}（${cell.row}, ${cell.col}）`}
          >
            {["room", "door", "cover", "stairs"].includes(cell.kind) ? (
              <span className="relative z-10 whitespace-nowrap text-[7px] text-parchment-100">
                {cell.kind === "door" ? "门" : cell.label}
              </span>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function RegionOverview({ maps }: { maps: Awaited<ReturnType<typeof listRegionMaps>> }): ReactElement {
  if (!maps.length) return <EmptyState title="还没有区域地图" hint="确认生成一个建筑或地下城后，系统会把它放到对应区域。" />;
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {maps.map((map) => (
        <div className="rounded-lg border border-ink-700 bg-ink-950/60 p-3" key={map.id}>
          <div className="mb-2 flex items-center justify-between">
            <strong className="text-sm text-parchment-100">{map.name}</strong>
            <Badge>{map.width}×{map.height}</Badge>
          </div>
          <div
            className="relative aspect-[3/2] overflow-hidden rounded border border-ink-700 bg-[linear-gradient(135deg,rgba(120,90,45,.12)_25%,transparent_25%),linear-gradient(315deg,rgba(120,90,45,.12)_25%,transparent_25%)] bg-[length:32px_32px]"
          >
            {(map.map_json.pois ?? []).map((poi) => (
              <button
                className="absolute -translate-x-1/2 -translate-y-1/2 rounded border border-amber-500 bg-ink-950 px-2 py-1 text-2xs text-amber-200 shadow"
                key={poi.site_id}
                style={{ left: `${(poi.col / map.width) * 100}%`, top: `${(poi.row / map.height) * 100}%` }}
                title={poi.site_type === "building" ? "建筑" : "地下城"}
                type="button"
              >
                {poi.name}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function SiteMapWorkbench({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [input, setInput] = useState<SiteGenerationInput>({
    site_type: "building",
    name: "普罗宅邸",
    brief: "海区的一座旧贵族宅邸，包含会客厅、卧室、密室与地下储藏室",
    region_path: "深水城/海区",
    maximum_levels: 3,
    rooms_min: 4,
    rooms_max: 8,
    party_level: 3,
    party_size: 4,
    starting_difficulty: "low",
    difficulty_growth: 1,
    monster_density: 60,
    reward_rate: 1,
    seed: 20240728,
  });
  const [preview, setPreview] = useState<SiteGenerationPreview | null>(null);
  const [previewLevel, setPreviewLevel] = useState(0);
  const [selectedSiteId, setSelectedSiteId] = useState("");
  const [savedLevel, setSavedLevel] = useState(0);
  const [requestId, setRequestId] = useState(`site-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const maps = useQuery({ queryKey: ["region-maps", campaignId], queryFn: ({ signal }) => listRegionMaps(campaignId, signal) });
  const sites = useQuery({ queryKey: ["adventure-sites", campaignId], queryFn: ({ signal }) => listAdventureSites(campaignId, signal) });
  const site = useQuery({
    queryKey: ["adventure-site", campaignId, selectedSiteId],
    queryFn: ({ signal }) => getAdventureSite(campaignId, selectedSiteId, signal),
    enabled: Boolean(selectedSiteId),
  });
  const generation = useMutation({
    mutationFn: () => previewSiteGeneration(campaignId, input),
    onSuccess: (value) => {
      setPreview(value);
      setPreviewLevel(0);
      setRequestId(`site-${Date.now()}-${Math.random().toString(36).slice(2)}`);
      showToast("建筑/地下城草稿已按规则生成");
    },
    onError: () => showToast("地图生成失败，请检查参数", "error"),
  });
  const confirmation = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("没有可保存的预览");
      return confirmSiteGeneration(campaignId, preview, requestId);
    },
    onSuccess: (value) => {
      setSelectedSiteId(value.id);
      setPreview(null);
      void client.invalidateQueries({ queryKey: ["region-maps", campaignId] });
      void client.invalidateQueries({ queryKey: ["adventure-sites", campaignId] });
      void client.invalidateQueries({ queryKey: ["locations", campaignId] });
      showToast("已写入区域地图、地点树、楼层、房间和连接器");
    },
    onError: () => showToast("保存失败，草稿仍保留，可重试", "error"),
  });
  const selectedLevel = site.data?.levels?.[savedLevel];
  const activePreviewLevel = preview?.levels[previewLevel];
  return (
    <Panel eyebrow="战役地图原子库" title="区域、建筑与地下城">
      <div className="grid gap-4 xl:grid-cols-[minmax(360px,.8fr)_minmax(0,1.4fr)]">
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Button onClick={() => setInput({ ...input, site_type: "building" })} variant={input.site_type === "building" ? "primary" : "ghost"}>建筑生成</Button>
            <Button onClick={() => setInput({ ...input, site_type: "dungeon" })} variant={input.site_type === "dungeon" ? "primary" : "ghost"}>地下城生成</Button>
          </div>
          <input className={inputCls} aria-label="建筑或地下城名称" onChange={(event) => setInput({ ...input, name: event.target.value })} value={input.name} />
          <input className={inputCls} aria-label="所属区域路径" onChange={(event) => setInput({ ...input, region_path: event.target.value })} value={input.region_path} />
          <textarea className={textareaCls} aria-label="生成描述与风格" onChange={(event) => setInput({ ...input, brief: event.target.value })} value={input.brief} />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <label className="text-2xs text-stone-500">最多楼层<input className={`${inputCls} mt-1`} min={1} max={20} type="number" value={input.maximum_levels} onChange={(event) => setInput({ ...input, maximum_levels: Number(event.target.value) })} /></label>
            <label className="text-2xs text-stone-500">队伍等级<input className={`${inputCls} mt-1`} min={1} max={20} type="number" value={input.party_level} onChange={(event) => setInput({ ...input, party_level: Number(event.target.value) })} /></label>
            <label className="text-2xs text-stone-500">玩家人数<input className={`${inputCls} mt-1`} min={1} max={12} type="number" value={input.party_size} onChange={(event) => setInput({ ...input, party_size: Number(event.target.value) })} /></label>
            <label className="text-2xs text-stone-500">起始难度<select className={`${selectCls} mt-1`} value={input.starting_difficulty} onChange={(event) => setInput({ ...input, starting_difficulty: event.target.value as SiteGenerationInput["starting_difficulty"] })}><option value="low">低</option><option value="moderate">中</option><option value="high">高</option></select></label>
          </div>
          <p className="text-2xs text-stone-600">路径示例：深水城/海区。描述会决定风格与怪物主题；数值预算、连通性和难度曲线由规则程序重算。</p>
          <Button className="w-full" loading={generation.isPending} onClick={() => generation.mutate()} variant="ai">生成完整预览</Button>
          {generation.isError ? <ErrorState error={generation.error} onRetry={() => generation.mutate()} /> : null}
        </div>
        <div>
          {preview ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {preview.levels.map((level, index) => <Button key={level.level_index} size="sm" variant={index === previewLevel ? "primary" : "ghost"} onClick={() => setPreviewLevel(index)}>{level.name}</Button>)}
                <Button className="ml-auto" loading={confirmation.isPending} onClick={() => confirmation.mutate()} variant="primary">确认写入战役</Button>
              </div>
              {activePreviewLevel ? <><div className="mb-2 flex flex-wrap gap-2"><Badge tone="danger">{activePreviewLevel.difficulty}</Badge><Badge>{activePreviewLevel.encounter_budget_xp} XP 预算</Badge><Badge tone="ok">{activePreviewLevel.reward_budget_gp} gp 奖励预算</Badge><Badge>{activePreviewLevel.rooms.length} 房间</Badge>{activePreviewLevel.quality ? <Badge tone={activePreviewLevel.quality.score >= 88 ? "ok" : "danger"}>布局评分 {activePreviewLevel.quality.score}/100 · 房间比例 {activePreviewLevel.quality.largest_smallest_ratio}×</Badge> : null}</div><SiteGrid level={activePreviewLevel} /></> : null}
            </>
          ) : <RegionOverview maps={maps.data ?? []} />}
        </div>
      </div>
      <div className="mt-5 border-t border-ink-700 pt-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <strong className="text-sm text-parchment-100">已保存建筑与地下城</strong>
          <select className={`${selectCls} ml-auto max-w-sm`} value={selectedSiteId} onChange={(event) => { setSelectedSiteId(event.target.value); setSavedLevel(0); }}>
            <option value="">选择建筑或地下城</option>
            {sites.data?.map((item) => <option key={item.id} value={item.id}>{item.site_type === "building" ? "建筑" : "地下城"} · {item.name}</option>)}
          </select>
        </div>
        {site.isLoading ? <LoadingBlock /> : null}
        {selectedLevel ? (
          <>
            <div className="mb-3 flex flex-wrap gap-2">
              {site.data?.levels?.map((level, index) => <Button key={level.id} size="sm" variant={index === savedLevel ? "primary" : "ghost"} onClick={() => setSavedLevel(index)}>{level.name}</Button>)}
            </div>
            {selectedLevel.quality ? <div className="mb-2"><Badge tone="ok">布局评分 {selectedLevel.quality.score}/100 · {selectedLevel.quality.algorithm}</Badge></div> : null}
            <SiteGrid level={selectedLevel} />
          </>
        ) : null}
      </div>
    </Panel>
  );
}
