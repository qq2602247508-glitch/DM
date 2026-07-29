import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactElement } from "react";

import {
  confirmSiteGeneration,
  deleteAdventureSite,
  getAdventureSite,
  listAdventureSites,
  listRegionMaps,
  previewSiteGeneration,
  setSiteRoomVisibility,
  type SiteGenerationInput,
  type SiteGenerationPreview,
  type SiteLevelPreview,
  type SiteRoomPlan,
} from "../api/world";
import { listCharacters } from "../api/entities";
import { useToast } from "../hooks/toastContext";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../ui/styles";
import { ConfirmDialog } from "../ui/widgets";
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
const oceanCellColor: Record<string, string> = {
  void: "bg-transparent border-transparent",
  wall: "bg-slate-900 border-sky-950",
  floor: "bg-cyan-950/70 border-cyan-900/70",
  door: "bg-sky-600/90 border-sky-300",
  cover: "bg-teal-900 border-teal-400",
  room: "bg-blue-950 border-cyan-300",
  stairs: "bg-indigo-950 border-sky-300",
};
const emberCellColor: Record<string, string> = {
  ...cellColor,
  wall: "bg-stone-950 border-red-950",
  floor: "bg-red-950/60 border-orange-950",
  room: "bg-orange-950 border-orange-400",
  cover: "bg-red-950 border-red-500",
};
const iceCellColor: Record<string, string> = {
  ...oceanCellColor,
  wall: "bg-slate-900 border-blue-900",
  floor: "bg-sky-950/50 border-sky-800",
  room: "bg-blue-950 border-sky-200",
};
const themedPalette = (
  wall: string,
  floor: string,
  door: string,
  cover: string,
  room: string,
  stairs: string,
): Record<string, string> => ({
  void: "bg-transparent border-transparent",
  wall,
  floor,
  door,
  cover,
  room,
  stairs,
});
const paletteColors: Record<string, Record<string, string>> = {
  ocean: oceanCellColor,
  ember: emberCellColor,
  ice: iceCellColor,
  ashen: themedPalette("bg-zinc-950 border-zinc-700", "bg-zinc-900/70 border-zinc-700", "bg-stone-600 border-stone-300", "bg-stone-800 border-stone-500", "bg-zinc-950 border-zinc-400", "bg-violet-950 border-violet-400"),
  moss: themedPalette("bg-stone-900 border-lime-950", "bg-lime-950/40 border-lime-900", "bg-amber-800 border-lime-600", "bg-green-950 border-lime-600", "bg-emerald-950 border-lime-400", "bg-violet-950 border-violet-400"),
  violet: themedPalette("bg-slate-950 border-purple-950", "bg-purple-950/50 border-purple-900", "bg-fuchsia-900 border-fuchsia-500", "bg-violet-950 border-fuchsia-600", "bg-purple-950 border-fuchsia-400", "bg-indigo-950 border-violet-300"),
  toxic: themedPalette("bg-stone-950 border-emerald-950", "bg-lime-950/60 border-emerald-900", "bg-emerald-900 border-lime-400", "bg-green-950 border-lime-500", "bg-emerald-950 border-lime-300", "bg-violet-950 border-violet-300"),
  crystal: themedPalette("bg-indigo-950 border-violet-900", "bg-purple-950/50 border-violet-800", "bg-violet-700 border-fuchsia-300", "bg-fuchsia-950 border-fuchsia-400", "bg-indigo-950 border-violet-200", "bg-cyan-950 border-cyan-300"),
  brass: themedPalette("bg-stone-950 border-yellow-950", "bg-amber-950/60 border-yellow-900", "bg-yellow-800 border-yellow-400", "bg-stone-800 border-amber-500", "bg-amber-950 border-yellow-300", "bg-slate-950 border-cyan-400"),
  sandstone: themedPalette("bg-stone-900 border-amber-900", "bg-yellow-950/50 border-amber-800", "bg-orange-900 border-amber-400", "bg-amber-950 border-yellow-600", "bg-orange-950 border-amber-300", "bg-violet-950 border-violet-300"),
  fungal: themedPalette("bg-stone-950 border-fuchsia-950", "bg-emerald-950/50 border-purple-900", "bg-purple-800 border-fuchsia-400", "bg-fuchsia-950 border-lime-500", "bg-purple-950 border-lime-300", "bg-cyan-950 border-cyan-300"),
  shadow: themedPalette("bg-black border-slate-800", "bg-slate-950 border-indigo-950", "bg-indigo-950 border-violet-500", "bg-black border-purple-700", "bg-slate-950 border-violet-400", "bg-violet-950 border-fuchsia-400"),
  radiant: themedPalette("bg-stone-900 border-yellow-700", "bg-amber-950/40 border-yellow-700", "bg-yellow-600 border-yellow-200", "bg-amber-900 border-yellow-300", "bg-yellow-950 border-yellow-100", "bg-sky-950 border-sky-200"),
  forest: themedPalette("bg-stone-950 border-green-950", "bg-green-950/50 border-emerald-900", "bg-amber-900 border-green-500", "bg-emerald-950 border-green-400", "bg-green-950 border-emerald-300", "bg-violet-950 border-violet-300"),
  storm: themedPalette("bg-slate-950 border-blue-950", "bg-slate-900/70 border-blue-900", "bg-blue-800 border-cyan-300", "bg-indigo-950 border-blue-400", "bg-slate-950 border-cyan-300", "bg-violet-950 border-fuchsia-300"),
};

function roomBounds(room: SiteRoomPlan): Record<string, number> {
  return room.bounds ?? room.bounds_json ?? {};
}

function roomAt(level: SiteLevelPreview, row: number, col: number): SiteRoomPlan | undefined {
  return level.rooms.find((room) => {
    const bounds = roomBounds(room);
    const top = Number(bounds.row ?? -1);
    const left = Number(bounds.col ?? -1);
    const width = Number(bounds.width ?? 0);
    const height = Number(bounds.height ?? 0);
    return row >= top && row < top + height && col >= left && col < left + width;
  });
}

export function SiteGrid({
  level,
  selectedRoomIndex,
  onSelectRoom,
}: {
  level: SiteLevelPreview;
  selectedRoomIndex?: number | null;
  onSelectRoom?: (roomIndex: number) => void;
}): ReactElement {
  const colors = paletteColors[level.visual_theme?.palette ?? ""] ?? cellColor;
  return (
    <div className="max-h-[62vh] overflow-auto rounded-lg border border-ink-700 bg-ink-950 p-2">
      <div
        aria-label={`${level.name}完整网格`}
        className="grid min-w-[650px]"
        style={{ gridTemplateColumns: `repeat(${level.layout.width}, minmax(24px, 1fr))` }}
      >
        {level.layout.cells.map((cell) => {
          const room = roomAt(level, cell.row, cell.col);
          const selected = room?.room_index === selectedRoomIndex;
          const bounds = room ? roomBounds(room) : {};
          const isRoomMarker = Boolean(room)
            && cell.row === Number(bounds.row ?? -10) + Math.floor(Number(bounds.height ?? 0) / 2)
            && cell.col === Number(bounds.col ?? -10) + Math.floor(Number(bounds.width ?? 0) / 2);
          const monsterCount = room
            ? level.monster_plan
                .filter((item) => item.room_index === room.room_index)
                .reduce((sum, item) => sum + item.quantity, 0)
            : 0;
          const rewardCount = room
            ? level.reward_plan.filter((item) => item.room_index === room.room_index).length
            : 0;
          const roomMonsters = room
            ? level.monster_plan.filter((item) => item.room_index === room.room_index)
            : [];
          return (
          <div
            className={`aspect-square border text-[7px] leading-none ${
              cell.label === "地图外区域"
                ? "border-black/70 bg-black/80"
                : colors[cell.kind] ?? "bg-ink-900 border-ink-700"
            } ${room && onSelectRoom ? "cursor-pointer hover:brightness-125" : ""} ${
              selected ? "relative z-10 ring-2 ring-inset ring-cyan-300" : ""
            }`}
            data-room-index={room?.room_index}
            key={`${cell.row}-${cell.col}`}
            onClick={() => room && onSelectRoom?.(room.room_index)}
            onKeyDown={(event) => {
              if (room && onSelectRoom && (event.key === "Enter" || event.key === " ")) {
                event.preventDefault();
                onSelectRoom(room.room_index);
              }
            }}
            role={room && onSelectRoom ? "button" : undefined}
            tabIndex={room && onSelectRoom ? 0 : undefined}
            title={`${cell.label}（${cell.row}, ${cell.col}）`}
          >
            {["room", "door", "cover", "stairs"].includes(cell.kind) ? (
              <span className="relative z-10 whitespace-nowrap text-[7px] text-parchment-100">
                {cell.kind === "door" ? "门" : cell.label}
              </span>
            ) : null}
            {isRoomMarker && (monsterCount || rewardCount) ? (
              <span className="relative z-20 flex flex-col items-center whitespace-nowrap text-[6px] font-bold">
                {roomMonsters.length ? (
                  <span className="rounded-full border border-red-300 bg-red-950/90 px-1 text-red-100" title={roomMonsters.map((item) => `${item.name} × ${item.quantity}`).join("、")}>
                    ⚔ {roomMonsters.map((item) => item.name.slice(0, 2)).join("/")} ×{monsterCount}
                  </span>
                ) : null}
                {rewardCount ? <span className="text-amber-200">宝 {rewardCount}</span> : null}
              </span>
            ) : null}
          </div>
          );
        })}
      </div>
    </div>
  );
}

export function LevelPlanDetails({
  level,
  selectedRoomIndex,
  onSelectRoom,
  persisted = false,
  visibilityPendingRoom = null,
  onVisibilityChange,
}: {
  level: SiteLevelPreview;
  selectedRoomIndex: number | null;
  onSelectRoom: (roomIndex: number) => void;
  persisted?: boolean;
  visibilityPendingRoom?: number | null;
  onVisibilityChange?: (roomIndex: number, visible: boolean) => void;
}): ReactElement {
  return (
    <div className="mt-3 rounded-lg border border-ink-700 bg-ink-950/45 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <strong className="text-sm text-parchment-100">房间内容规划</strong>
        <span className="text-2xs text-stone-500">展开房间查看怪物、NPC 与战利品；点击房间或地图格定位。</span>
      </div>
      <div className="grid gap-2 lg:grid-cols-2">
        {level.rooms.map((room) => {
          const monsters = level.monster_plan.filter((item) => item.room_index === room.room_index);
          const npcs = (level.npc_plan ?? []).filter((item) => item.room_index === room.room_index);
          const rewards = level.reward_plan.filter((item) => item.room_index === room.room_index);
          const selected = selectedRoomIndex === room.room_index;
          const revealed = room.encounter_json?.visibility === "revealed";
          return (
            <details
              className={`rounded border p-3 ${selected ? "border-cyan-500 bg-cyan-950/20" : "border-ink-700 bg-ink-900/50"}`}
              key={room.room_index}
              onToggle={(event) => {
                if (event.currentTarget.open) onSelectRoom(room.room_index);
              }}
            >
              <summary className="cursor-pointer text-sm text-parchment-100">
                <span>房间 {room.room_index} · {room.name}</span>
                <span className="ml-2 text-2xs text-stone-500">
                  怪物 {monsters.reduce((sum, item) => sum + item.quantity, 0)} · NPC {npcs.length} · 战利品 {rewards.length}
                </span>
              </summary>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {persisted ? (
                  <Button
                    aria-label={`${revealed ? "重新隐藏" : "向玩家揭露"}房间 ${room.room_index}`}
                    disabled={!onVisibilityChange}
                    loading={visibilityPendingRoom === room.room_index}
                    onClick={() => onVisibilityChange?.(room.room_index, !revealed)}
                    size="sm"
                    variant={revealed ? "primary" : "ghost"}
                  >
                    <span aria-hidden="true">{revealed ? "👁" : "👁̸"}</span>
                    {revealed ? "玩家已可见 · 点击隐藏" : "DM 私密 · 点击揭露"}
                  </Button>
                ) : <Badge>DM 预览可见 · 写入后可逐房揭露</Badge>}
                <span className="text-2xs text-stone-600">DM 始终看到完整房间与全部怪物；眼睛只控制玩家视图。</span>
              </div>
              <p className="mb-2 mt-2 text-xs leading-5 text-stone-400">
                {room.description || room.room_type || "暂无房间说明"}
              </p>
              <Button onClick={() => onSelectRoom(room.room_index)} size="sm">在地图上定位</Button>
              <div className="mt-3 grid gap-2 sm:grid-cols-3">
                <div>
                  <strong className="text-2xs text-red-300">怪物</strong>
                  {monsters.length ? monsters.map((monster, index) => (
                    <p className="mb-0 mt-1 text-xs text-stone-300" key={`${monster.name}-${index}`}>
                      {monster.name} × {monster.quantity} · {monster.xp_each} XP
                      <span className="block text-2xs text-stone-600">{monster.source}</span>
                    </p>
                  )) : <p className="text-2xs text-stone-600">无预设怪物</p>}
                </div>
                <div>
                  <strong className="text-2xs text-sky-300">NPC</strong>
                  {npcs.length ? npcs.map((npc, index) => (
                    <p className="mb-0 mt-1 text-xs text-stone-300" key={`${npc.name}-${index}`}>
                      {npc.name}<span className="block text-2xs text-stone-600">{npc.role}</span>
                    </p>
                  )) : <p className="text-2xs text-stone-600">无预设 NPC</p>}
                </div>
                <div>
                  <strong className="text-2xs text-emerald-300">战利品</strong>
                  {rewards.length ? rewards.map((reward, index) => (
                    <p className="mb-0 mt-1 text-xs text-stone-300" key={`${reward.name}-${index}`}>
                      {reward.name} · {reward.value_gp} gp
                      {reward.category ? (
                        <span className="block text-2xs text-stone-600">
                          {reward.category}
                          {reward.rarity ? ` · ${reward.rarity}` : ""}
                          {reward.source_kind
                            ? ` · ${reward.source_kind === "official" ? "官方图鉴" : "原创规划"}`
                            : ""}
                        </span>
                      ) : null}
                    </p>
                  )) : <p className="text-2xs text-stone-600">无预设战利品</p>}
                </div>
              </div>
            </details>
          );
        })}
      </div>
    </div>
  );
}

function RegionOverview({
  maps,
  onSelectSite,
}: {
  maps: Awaited<ReturnType<typeof listRegionMaps>>;
  onSelectSite: (siteId: string) => void;
}): ReactElement {
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
                onClick={() => onSelectSite(poi.site_id)}
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

export function SiteMapWorkbench({
  campaignId,
  requestedSiteId = "",
}: {
  campaignId: string;
  requestedSiteId?: string;
}): ReactElement {
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
    character_ids: [],
    starting_difficulty: "low",
    difficulty_growth: 1,
    monster_density: 60,
    reward_rate: 1,
    overall_scale: "medium",
    minimum_room_size: "medium",
    maximum_room_size: "large",
    generate_npcs: true,
    generate_monsters: true,
    generate_loot: true,
  });
  const [preview, setPreview] = useState<SiteGenerationPreview | null>(null);
  const [previewLevel, setPreviewLevel] = useState(0);
  const [selectedSiteId, setSelectedSiteId] = useState("");
  const [savedLevel, setSavedLevel] = useState(0);
  const [selectedPreviewRoom, setSelectedPreviewRoom] = useState<number | null>(null);
  const [selectedSavedRoom, setSelectedSavedRoom] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [requestId, setRequestId] = useState(`site-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const maps = useQuery({ queryKey: ["region-maps", campaignId], queryFn: ({ signal }) => listRegionMaps(campaignId, signal) });
  const sites = useQuery({ queryKey: ["adventure-sites", campaignId], queryFn: ({ signal }) => listAdventureSites(campaignId, signal) });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const site = useQuery({
    queryKey: ["adventure-site", campaignId, selectedSiteId],
    queryFn: ({ signal }) => getAdventureSite(campaignId, selectedSiteId, signal),
    enabled: Boolean(selectedSiteId),
  });
  const selectedLevel = site.data?.levels?.[savedLevel];
  const activePreviewLevel = preview?.levels[previewLevel];
  useEffect(() => {
    if (!requestedSiteId) return;
    setSelectedSiteId(requestedSiteId);
    setSavedLevel(0);
    setSelectedSavedRoom(null);
    document.getElementById("site-grid-viewer")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [requestedSiteId]);
  const generation = useMutation({
    mutationFn: (generationInput?: SiteGenerationInput) => previewSiteGeneration(
      campaignId,
      generationInput ?? input,
    ),
    onSuccess: (value) => {
      setPreview(value);
      setPreviewLevel(0);
      setSelectedPreviewRoom(null);
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
  const removal = useMutation({
    mutationFn: () => {
      if (!site.data) throw new Error("没有选择建筑或地下城");
      return deleteAdventureSite(campaignId, site.data.id, site.data.version);
    },
    onSuccess: async () => {
      setConfirmDelete(false);
      setSelectedSiteId("");
      setSavedLevel(0);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["region-maps", campaignId] }),
        client.invalidateQueries({ queryKey: ["adventure-sites", campaignId] }),
        client.invalidateQueries({ queryKey: ["locations", campaignId] }),
        client.invalidateQueries({ queryKey: ["scenes", campaignId] }),
      ]);
      showToast("建筑/地下城及其托管楼层、房间、Scene 和网格已完整删除");
    },
    onError: () => showToast("删除失败；数据可能已更新，请刷新后重试", "error"),
  });
  const visibility = useMutation({
    mutationFn: ({ roomIndex, visible }: { roomIndex: number; visible: boolean }) => {
      if (!site.data || !selectedLevel) throw new Error("没有选择已保存楼层");
      return setSiteRoomVisibility(
        campaignId,
        site.data.id,
        selectedLevel.level_index,
        roomIndex,
        visible,
      );
    },
    onSuccess: async (value) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["adventure-site", campaignId, selectedSiteId] }),
        client.invalidateQueries({ queryKey: ["scene-grid", campaignId] }),
      ]);
      showToast(
        value.visibility === "revealed"
          ? `房间 ${value.room_index} 已向玩家揭露`
          : `房间 ${value.room_index} 已重新隐藏`,
      );
    },
    onError: () => showToast("房间可见性更新失败，请刷新后重试", "error"),
  });
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
          <div className="rounded border border-ink-700 bg-ink-950/50 p-3">
            <strong className="text-xs text-parchment-100">按真实角色生成（可选）</strong>
            <p className="mb-2 mt-1 text-2xs text-stone-500">选择后以角色等级、职业与队伍构成为基准；下面的难度和奖励参数仍可继续覆盖调整。</p>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {characters.data?.map((character) => (
                <label className="flex items-center gap-2 rounded border border-ink-700/70 px-2 py-1.5 text-xs text-stone-300" key={character.id}>
                  <input
                    checked={input.character_ids.includes(character.id)}
                    onChange={(event) => setInput({
                      ...input,
                      character_ids: event.target.checked
                        ? [...input.character_ids, character.id]
                        : input.character_ids.filter((id) => id !== character.id),
                    })}
                    type="checkbox"
                  />
                  {character.name} · {character.class_name || "未定职业"} Lv.{character.level}
                </label>
              ))}
              {!characters.data?.length ? <span className="text-2xs text-stone-600">当前团还没有可选择的角色。</span> : null}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <label className="text-2xs text-stone-500">最多楼层<input className={`${inputCls} mt-1`} min={1} max={20} type="number" value={input.maximum_levels} onChange={(event) => setInput({ ...input, maximum_levels: Number(event.target.value) })} /></label>
            <label className="text-2xs text-stone-500">每层最少房间<input aria-label="每层最少房间" className={`${inputCls} mt-1`} min={2} max={9} type="number" value={input.rooms_min} onChange={(event) => setInput({ ...input, rooms_min: Number(event.target.value) })} /></label>
            <label className="text-2xs text-stone-500">每层最多房间<input aria-label="每层最多房间" className={`${inputCls} mt-1`} min={2} max={9} type="number" value={input.rooms_max} onChange={(event) => setInput({ ...input, rooms_max: Number(event.target.value) })} /></label>
            <label className="text-2xs text-stone-500">队伍等级<input className={`${inputCls} mt-1`} min={1} max={20} type="number" value={input.party_level} onChange={(event) => setInput({ ...input, party_level: Number(event.target.value) })} /></label>
            <label className="text-2xs text-stone-500">玩家人数<input className={`${inputCls} mt-1`} min={1} max={12} type="number" value={input.party_size} onChange={(event) => setInput({ ...input, party_size: Number(event.target.value) })} /></label>
            <label className="text-2xs text-stone-500">起始难度<select className={`${selectCls} mt-1`} value={input.starting_difficulty} onChange={(event) => setInput({ ...input, starting_difficulty: event.target.value as SiteGenerationInput["starting_difficulty"] })}><option value="low">低</option><option value="moderate">中</option><option value="high">高</option></select></label>
            <label className="text-2xs text-stone-500">地图总体规模<select className={`${selectCls} mt-1`} value={input.overall_scale} onChange={(event) => setInput({ ...input, overall_scale: event.target.value as SiteGenerationInput["overall_scale"] })}><option value="small">小</option><option value="medium">中</option><option value="large">大</option><option value="huge">巨大</option></select></label>
            <label className="text-2xs text-stone-500">最小房间<select className={`${selectCls} mt-1`} value={input.minimum_room_size} onChange={(event) => setInput({ ...input, minimum_room_size: event.target.value as SiteGenerationInput["minimum_room_size"] })}><option value="small">小（约 4–6 格）</option><option value="medium">中（约 6–10 格）</option><option value="large">大（约 8–14 格）</option><option value="huge">巨大（约 12–20 格）</option></select></label>
            <label className="text-2xs text-stone-500">最大房间<select className={`${selectCls} mt-1`} value={input.maximum_room_size} onChange={(event) => setInput({ ...input, maximum_room_size: event.target.value as SiteGenerationInput["maximum_room_size"] })}><option value="small">小</option><option value="medium">中</option><option value="large">大</option><option value="huge">巨大</option></select></label>
          </div>
          <div className="grid gap-2 rounded border border-ink-700 bg-ink-950/50 p-3 sm:grid-cols-3">
            <label className="flex items-center gap-2 text-xs text-stone-300"><input checked={input.generate_npcs} onChange={(event) => setInput({ ...input, generate_npcs: event.target.checked })} type="checkbox" />生成并分布 NPC</label>
            <label className="flex items-center gap-2 text-xs text-stone-300"><input checked={input.generate_monsters} onChange={(event) => setInput({ ...input, generate_monsters: event.target.checked })} type="checkbox" />生成并分布怪物</label>
            <label className="flex items-center gap-2 text-xs text-stone-300"><input checked={input.generate_loot} onChange={(event) => setInput({ ...input, generate_loot: event.target.checked })} type="checkbox" />生成职业相关战利品</label>
          </div>
          <p className="text-2xs text-stone-600">路径示例：深水城/海区。描述会决定风格与怪物主题；数值预算、连通性和难度曲线由规则程序重算。</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Button
              className="w-full"
              loading={generation.isPending}
              onClick={() => generation.mutate(input)}
              variant="ai"
            >
              {input.seed === undefined ? "生成新预览" : "按锁定种子复现"}
            </Button>
            <Button
              disabled={generation.isPending}
              onClick={() => {
                const nextInput = { ...input, seed: undefined };
                setInput(nextInput);
                generation.mutate(nextInput);
              }}
              variant="ghost"
            >换一版（新随机种子）</Button>
          </div>
          <p className="mt-1 text-2xs text-stone-600">
            {input.seed === undefined
              ? "当前为随机模式：同样描述每次会生成不同布局与遇敌组合。"
              : `已锁定种子 ${input.seed}：可精确复现当前版本。`}
          </p>
          {generation.isError ? <ErrorState error={generation.error} onRetry={() => generation.mutate(input)} /> : null}
        </div>
        <div>
          {preview ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {preview.levels.map((level, index) => <Button key={level.level_index} size="sm" variant={index === previewLevel ? "primary" : "ghost"} onClick={() => { setPreviewLevel(index); setSelectedPreviewRoom(null); }}>{level.name}</Button>)}
                <Badge>种子 {preview.site.seed}</Badge>
                <Button
                  onClick={() => setInput({ ...input, seed: preview.site.seed })}
                  size="sm"
                  variant={input.seed === preview.site.seed ? "primary" : "ghost"}
                >{input.seed === preview.site.seed ? "已锁定当前种子" : "锁定当前种子"}</Button>
                {input.seed !== undefined ? (
                  <Button onClick={() => setInput({ ...input, seed: undefined })} size="sm" variant="ghost">解除种子锁定</Button>
                ) : null}
                <Button className="ml-auto" loading={confirmation.isPending} onClick={() => confirmation.mutate()} variant="primary">确认写入战役</Button>
              </div>
              {activePreviewLevel ? <><div className="mb-2 flex flex-wrap gap-2"><Badge tone="danger">{activePreviewLevel.difficulty}</Badge>{activePreviewLevel.visual_theme?.label ? <Badge tone="ai">主题 · {activePreviewLevel.visual_theme.label}</Badge> : null}{activePreviewLevel.visual_theme?.source_kind ? <Badge>{activePreviewLevel.visual_theme.source_kind === "compiled" ? "动态编译主题" : "可靠预设主题"}</Badge> : null}<Badge>{activePreviewLevel.encounter_budget_xp} XP 预算</Badge><Badge tone="ok">{activePreviewLevel.reward_budget_gp} gp 奖励预算</Badge><Badge>{activePreviewLevel.rooms.length} 房间</Badge><Badge>{activePreviewLevel.monster_plan.length} 种怪物</Badge><Badge>{activePreviewLevel.npc_plan?.length ?? 0} NPC</Badge><Badge>{activePreviewLevel.reward_plan.length} 类战利品</Badge>{activePreviewLevel.quality ? <Badge tone={activePreviewLevel.quality.score >= 88 ? "ok" : "danger"}>布局评分 {activePreviewLevel.quality.score}/100 · 房间比例 {activePreviewLevel.quality.largest_smallest_ratio}×</Badge> : null}</div>{activePreviewLevel.visual_theme?.atmosphere ? <p className="mb-2 text-xs text-stone-400">{activePreviewLevel.visual_theme.atmosphere}{activePreviewLevel.visual_theme.keywords?.length ? ` · 主题词：${activePreviewLevel.visual_theme.keywords.join("、")}` : ""}</p> : null}<SiteGrid level={activePreviewLevel} onSelectRoom={setSelectedPreviewRoom} selectedRoomIndex={selectedPreviewRoom} /><LevelPlanDetails level={activePreviewLevel} onSelectRoom={setSelectedPreviewRoom} selectedRoomIndex={selectedPreviewRoom} /></> : null}
            </>
          ) : <RegionOverview maps={maps.data ?? []} onSelectSite={(siteId) => {
            setSelectedSiteId(siteId);
            setSavedLevel(0);
            setSelectedSavedRoom(null);
            requestAnimationFrame(() => document.getElementById("site-grid-viewer")?.scrollIntoView({ behavior: "smooth", block: "start" }));
          }} />}
        </div>
      </div>
      <div className="mt-5 scroll-mt-4 border-t border-ink-700 pt-4" id="site-grid-viewer">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <strong className="text-sm text-parchment-100">已保存建筑与地下城</strong>
          <select aria-label="选择已保存建筑或地下城" className={`${selectCls} ml-auto max-w-sm`} value={selectedSiteId} onChange={(event) => { setSelectedSiteId(event.target.value); setSavedLevel(0); setSelectedSavedRoom(null); }}>
            <option value="">选择建筑或地下城</option>
            {sites.data?.map((item) => <option key={item.id} value={item.id}>{item.site_type === "building" ? "建筑" : "地下城"} · {item.name}</option>)}
          </select>
          {site.data ? <Button onClick={() => setConfirmDelete(true)} size="sm" variant="danger">删除整座{site.data.site_type === "building" ? "建筑" : "地下城"}</Button> : null}
        </div>
        {site.isLoading ? <LoadingBlock /> : null}
        {selectedLevel ? (
          <>
            <div className="mb-3 flex flex-wrap gap-2">
              {site.data?.levels?.map((level, index) => <Button key={level.id} size="sm" variant={index === savedLevel ? "primary" : "ghost"} onClick={() => { setSavedLevel(index); setSelectedSavedRoom(null); }}>{level.name}</Button>)}
            </div>
            <div className="mb-2 flex flex-wrap gap-2">
              {selectedLevel.visual_theme?.label ? <Badge tone="ai">主题 · {selectedLevel.visual_theme.label}</Badge> : null}
              {selectedLevel.quality ? <Badge tone="ok">布局评分 {selectedLevel.quality.score}/100 · {selectedLevel.quality.algorithm}</Badge> : null}
            </div>
            <SiteGrid level={selectedLevel} onSelectRoom={setSelectedSavedRoom} selectedRoomIndex={selectedSavedRoom} />
            <LevelPlanDetails
              level={selectedLevel}
              onSelectRoom={setSelectedSavedRoom}
              onVisibilityChange={(roomIndex, visible) => visibility.mutate({ roomIndex, visible })}
              persisted
              selectedRoomIndex={selectedSavedRoom}
              visibilityPendingRoom={visibility.isPending ? visibility.variables?.roomIndex ?? null : null}
            />
          </>
        ) : null}
      </div>
      <ConfirmDialog
        body={site.data ? (
          <div>
            <p className="mt-0 text-parchment-100">{site.data.name}</p>
            <p className="mb-0 text-stone-400">
              将原子删除这座{site.data.site_type === "building" ? "建筑" : "地下城"}、全部楼层与房间地点、
              关联 Scene 和网格，并从区域地图移除对应标记和道路。角色、NPC、物品和其他地点不会删除。
            </p>
          </div>
        ) : null}
        confirmLabel="确认删除整座站点"
        loading={removal.isPending}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => removal.mutate()}
        open={confirmDelete}
        title="删除建筑或地下城"
      />
    </Panel>
  );
}
