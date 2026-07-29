import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactElement } from "react";

import { listCharacters, listLocations } from "../api/entities";
import type {
  GeneratedLocationNode,
  Location,
  LocationGenerationPreview,
  WorldItem,
} from "../api/types";
import {
  confirmLocation,
  generateLocation,
  listAdventureSites,
  listWorldItems,
  pickupItem,
} from "../api/world";
import { CitationList } from "../components/Citations";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { SiteMapWorkbench } from "../components/SiteMapWorkbench";
import { useToast } from "../hooks/toastContext";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../ui/styles";
import { AiTag, SecretBlock } from "../ui/widgets";
import { ManagementPage } from "./ManagementPage";

function money(cp: number): string {
  if (cp >= 100) return `${cp / 100} gp`;
  if (cp >= 10) return `${cp / 10} sp`;
  return `${cp} cp`;
}

function GeneratedNode({ node, level = 0 }: { node: GeneratedLocationNode; level?: number }): ReactElement {
  return (
    <li className="list-none">
      <div
        className="rounded-md border border-ink-700 bg-ink-950/50 p-3"
        style={{ marginLeft: `${Math.min(level, 4) * 18}px` }}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="ember">第 {level + 1} 层</Badge>
          <strong className="text-sm text-parchment-100">{node.name}</strong>
          {node.suggested_npcs.length ? <Badge tone="ai">{node.suggested_npcs.length} NPC 建议</Badge> : null}
          {node.suggested_monsters.length ? <Badge tone="danger">{node.suggested_monsters.length} 怪物建议</Badge> : null}
        </div>
        <p className="prose-block mb-0 mt-2 text-xs text-stone-400">{node.description}</p>
        {node.interactive_objects.length ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {node.interactive_objects.map((object) => <Badge key={object}>{object}</Badge>)}
          </div>
        ) : null}
        {node.items.length ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {node.items.map((item, index) => (
              <div className="rounded border border-ink-700/70 bg-ink-900 px-2.5 py-2 text-xs" key={`${item.name}-${index}`}>
                <span className="font-medium text-parchment-100">{item.name} ×{item.quantity}</span>
                <span className="ml-2 text-stone-600">{item.unit_weight_lb} lb · {money(item.price_cp)}</span>
                {item.description ? <p className="mb-0 mt-1 text-stone-500">{item.description}</p> : null}
              </div>
            ))}
          </div>
        ) : null}
      </div>
      {node.children.length ? (
        <ul className="m-0 mt-2 space-y-2 p-0">
          {node.children.map((child) => <GeneratedNode key={child.temp_id} level={level + 1} node={child} />)}
        </ul>
      ) : null}
    </li>
  );
}

function ExistingNode({
  location,
  childrenByParent,
  items,
  characterId,
  pickupPending,
  onPickup,
  siteByLocation,
  onOpenSite,
  level = 0,
}: {
  location: Location;
  childrenByParent: Map<string | null, Location[]>;
  items: WorldItem[];
  characterId: string;
  pickupPending: boolean;
  onPickup: (item: WorldItem) => void;
  siteByLocation: Map<string, string>;
  onOpenSite: (siteId: string) => void;
  level?: number;
}): ReactElement {
  const [expanded, setExpanded] = useState(level === 0);
  const siteId = siteByLocation.get(location.id);
  const children = childrenByParent.get(location.id) ?? [];
  const localItems = items.filter((item) => item.location_id === location.id && !item.is_hidden);
  return (
    <li className="list-none">
      <div
        className="rounded-lg border border-ink-700 bg-ink-950/50 p-3"
        style={{ marginLeft: `${Math.min(level, 4) * 20}px` }}
      >
        <div className="flex flex-wrap items-center gap-2">
          {children.length ? (
            <Button
              aria-label={`${expanded ? "收起" : "展开"}${location.name}`}
              onClick={() => setExpanded((value) => !value)}
              size="sm"
              variant="ghost"
            >
              {expanded ? "−" : "+"}
            </Button>
          ) : <span className="inline-block w-8" />}
          <Badge tone={level === 0 ? "ember" : "neutral"}>层级 {location.depth}</Badge>
          <strong className="text-sm text-parchment-100">{location.name}</strong>
          {siteId ? <Button onClick={() => onOpenSite(siteId)} size="sm" variant="primary">查看网格</Button> : null}
          <span className="ml-auto text-2xs text-stone-700">{children.length} 个子地点</span>
        </div>
        <p className="prose-block mb-0 mt-1.5 text-xs text-stone-500">{location.description || "暂无描述"}</p>
        {location.interactive_objects.length ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {location.interactive_objects.map((object, index) => (
              <Badge key={`${String(object)}-${index}`}>{String(object)}</Badge>
            ))}
          </div>
        ) : null}
        {localItems.length ? (
          <div className="mt-3 space-y-2">
            {localItems.map((item) => (
              <div className="flex flex-wrap items-center gap-2 rounded border border-ink-700/70 bg-ink-900/80 px-3 py-2" key={item.id}>
                <span className="text-xs font-medium text-parchment-100">{item.name} ×{item.quantity}</span>
                <span className="text-2xs text-stone-500">{item.unit_weight_lb} lb/件 · {money(item.price_cp)}/件</span>
                <Button
                  className="ml-auto"
                  disabled={!characterId}
                  loading={pickupPending}
                  onClick={() => onPickup(item)}
                  size="sm"
                  variant="primary"
                >
                  拾取到背包
                </Button>
              </div>
            ))}
          </div>
        ) : null}
        {location.secrets ? <div className="mt-3"><SecretBlock label="地点秘密" value={location.secrets} /></div> : null}
      </div>
      {children.length && expanded ? (
        <ul className="m-0 mt-2 space-y-2 p-0">
          {children.map((child) => (
            <ExistingNode
              characterId={characterId}
              childrenByParent={childrenByParent}
              items={items}
              key={child.id}
              level={level + 1}
              location={child}
              onPickup={onPickup}
              onOpenSite={onOpenSite}
              pickupPending={pickupPending}
              siteByLocation={siteByLocation}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function LocationsContent({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [brief, setBrief] = useState("深水城的海区，以及其中几个值得记录的街区与地标");
  const [maximumDepth, setMaximumDepth] = useState(2);
  const [scale, setScale] = useState<"small" | "medium" | "large">("small");
  const [preview, setPreview] = useState<LocationGenerationPreview | null>(null);
  const [characterId, setCharacterId] = useState("");
  const [focusedSiteId, setFocusedSiteId] = useState("");
  const [showAbstractCreator, setShowAbstractCreator] = useState(false);
  const [showManualManagement, setShowManualManagement] = useState(false);
  const locations = useQuery({
    queryKey: ["locations", campaignId],
    queryFn: ({ signal }) => listLocations(campaignId, signal),
  });
  const items = useQuery({
    queryKey: ["world-items", campaignId],
    queryFn: ({ signal }) => listWorldItems(campaignId, {}, signal),
  });
  const characters = useQuery({
    queryKey: ["characters", campaignId],
    queryFn: ({ signal }) => listCharacters(campaignId, signal),
  });
  const sites = useQuery({
    queryKey: ["adventure-sites", campaignId],
    queryFn: ({ signal }) => listAdventureSites(campaignId, signal),
  });
  const siteByLocation = useMemo(
    () => new Map((sites.data ?? []).map((site) => [site.location_id, site.id])),
    [sites.data],
  );
  const generation = useMutation({
    mutationFn: () => generateLocation(campaignId, {
      brief,
      maximum_depth: maximumDepth,
      scale,
    }),
    onSuccess: (value) => {
      setPreview(value);
      showToast("抽象地点草稿已生成，请复核");
    },
    onError: () => showToast("抽象地点生成失败，请检查本地模型", "error"),
  });
  const confirmation = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("没有可确认的地点草稿");
      return confirmLocation(campaignId, preview);
    },
    onSuccess: () => {
      setPreview(null);
      void client.invalidateQueries({ queryKey: ["locations", campaignId] });
      void client.invalidateQueries({ queryKey: ["world-items", campaignId] });
      showToast("抽象地点和物品已写入战役地点索引");
    },
    onError: () => showToast("抽象地点保存失败", "error"),
  });
  const pickup = useMutation({
    mutationFn: (item: WorldItem) => {
      if (!characterId) throw new Error("请先选择拾取物品的角色");
      return pickupItem(campaignId, item.id, {
        character_id: characterId,
        quantity: item.quantity,
        version: item.version,
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["world-items", campaignId] });
      void client.invalidateQueries({ queryKey: ["inventory", campaignId, characterId] });
      showToast("物品已进入角色背包，负重已重新计算");
    },
    onError: () => showToast("拾取失败，物品可能已被移动", "error"),
  });
  const childrenByParent = useMemo(() => {
    const map = new Map<string | null, Location[]>();
    for (const location of locations.data ?? []) {
      const bucket = map.get(location.parent_location_id) ?? [];
      bucket.push(location);
      map.set(location.parent_location_id, bucket);
    }
    return map;
  }, [locations.data]);
  return (
    <div className="mx-auto max-w-[1200px] p-4 lg:p-6">
      <SiteMapWorkbench campaignId={campaignId} requestedSiteId={focusedSiteId} />
      <Panel
        action={<Button onClick={() => setShowAbstractCreator((value) => !value)} size="sm">{showAbstractCreator ? "收起" : "创建抽象地点"}</Button>}
        className="mt-4"
        eyebrow="可选 · 非网格化世界信息"
        title="抽象地点"
      >
        <p className="prose-block my-0 text-sm text-stone-400">
          只用于国家、城市、城区、组织领地和遥远地标。酒馆、宅邸、教堂与地下城请使用上方专用生成器，它会自动写入地点索引并生成楼层网格。
        </p>
        {showAbstractCreator ? (
          <div className="mt-4 border-t border-ink-700 pt-4">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_9rem_9rem_auto]">
              <textarea aria-label="抽象地点描述" className={textareaCls} onChange={(event) => setBrief(event.target.value)} value={brief} />
              <label className="text-xs text-stone-400">
                最大层级
                <select className={`${selectCls} mt-1.5`} onChange={(event) => setMaximumDepth(Number(event.target.value))} value={maximumDepth}>
                  {[1, 2, 3].map((depth) => <option key={depth} value={depth}>最多 {depth} 层</option>)}
                </select>
              </label>
              <label className="text-xs text-stone-400">
                规模
                <select className={`${selectCls} mt-1.5`} onChange={(event) => setScale(event.target.value as typeof scale)} value={scale}>
                  <option value="small">小型</option><option value="medium">中型</option><option value="large">大型</option>
                </select>
              </label>
              <Button disabled={!brief.trim()} loading={generation.isPending} onClick={() => generation.mutate()} variant="ai">
                生成抽象地点
              </Button>
            </div>
            <p className="mb-0 mt-2 text-2xs text-stone-600">这里不会创建战斗网格；最大层级只是上限。</p>
            {generation.isError ? <div className="mt-4"><ErrorState error={generation.error} onRetry={() => generation.mutate()} /></div> : null}
            {preview ? (
              <div className="mt-5 border-t border-ink-700 pt-4">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <AiTag>抽象地点草稿</AiTag><Badge tone="ok">D&D 5e · 2024</Badge>
                  <Button className="ml-auto" loading={confirmation.isPending} onClick={() => confirmation.mutate()} variant="primary">
                    确认写入地点索引
                  </Button>
                </div>
                <ul className="m-0 space-y-2 p-0"><GeneratedNode node={preview.root} /></ul>
                <div className="mt-4"><CitationList citations={preview.citations} /></div>
              </div>
            ) : null}
          </div>
        ) : null}
      </Panel>
      <Panel
        action={
          <select className={inputCls} onChange={(event) => setCharacterId(event.target.value)} value={characterId}>
            <option value="">选择拾取角色</option>
            {characters.data?.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}
          </select>
        }
        className="mt-4"
        eyebrow="自动汇总 · 原子地点与物品"
        title="世界地点索引"
      >
        {locations.isLoading || items.isLoading ? <LoadingBlock /> : null}
        {locations.isError ? <ErrorState error={locations.error} onRetry={() => void locations.refetch()} /> : null}
        {locations.data?.length === 0 ? <EmptyState hint="生成建筑、地下城或抽象地点后，系统会在这里统一汇总。" title="还没有地点" /> : null}
        {locations.data?.length ? (
          <ul className="m-0 space-y-2 p-0">
            {(childrenByParent.get(null) ?? []).map((location) => (
              <ExistingNode
                characterId={characterId}
                childrenByParent={childrenByParent}
                items={items.data ?? []}
                key={location.id}
                location={location}
                onPickup={(item) => pickup.mutate(item)}
                onOpenSite={setFocusedSiteId}
                pickupPending={pickup.isPending}
                siteByLocation={siteByLocation}
              />
            ))}
          </ul>
        ) : null}
      </Panel>
      <section className="mt-4 rounded-xl border border-ink-700 bg-ink-950/35">
        <div className="flex flex-wrap items-center gap-2 px-4 py-3">
          <div className="mr-auto">
            <strong className="block text-sm text-stone-300">高级 · 手动编辑抽象地点</strong>
            <span className="text-2xs text-stone-600">用于修正城市、城区和地标记录；建筑与地下城请使用上方专用工作台。</span>
          </div>
          <Button onClick={() => setShowManualManagement((value) => !value)} size="sm">
            {showManualManagement ? "收起手动管理" : "展开手动管理"}
          </Button>
        </div>
        {showManualManagement ? (
          <div className="-mx-4 -mb-4 border-t border-ink-700 lg:-mx-6">
            <ManagementPage kind="locations" />
          </div>
        ) : null}
      </section>
    </div>
  );
}

export function LocationsPage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <LocationsContent campaignId={campaignId} />}</RequireCampaign>;
}
