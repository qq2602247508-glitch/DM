import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactElement } from "react";

import {
  assignPlayerRoomCharacter,
  closePlayerRoom,
  getPlayerRoom,
  isMissingPlayerRoom,
  kickPlayerRoomMember,
  listPlayerActionRequests,
  openPlayerRoom,
  resolvePlayerActionRequest,
  setPlayerRoomLiveState,
} from "../api/playerRoom";
import { useToast } from "../hooks/toastContext";
import { Badge, Button, ErrorState, LoadingBlock } from "../ui/primitives";
import { selectCls } from "../ui/styles";
import { ConfirmDialog } from "../ui/widgets";
import { Panel } from "./Panel";

type CharacterOption = { id: string; name: string };

export function PlayerRoomPanel({
  campaignId,
  currentSceneId,
  currentCombatId,
  characters,
}: {
  campaignId: string;
  currentSceneId: string | null;
  currentCombatId: string | null;
  characters: CharacterOption[];
}): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [joinCode, setJoinCode] = useState("");
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [confirmAction, setConfirmAction] = useState<"rotate" | "close" | null>(null);
  const room = useQuery({
    queryKey: ["player-room-admin", campaignId],
    queryFn: ({ signal }) => getPlayerRoom(campaignId, signal),
    retry: false,
    refetchInterval: (query) => query.state.data?.status === "active" ? 15_000 : false,
  });
  const actionRequests = useQuery({
    enabled: room.data?.status === "active",
    queryKey: ["player-action-requests", campaignId],
    queryFn: ({ signal }) => listPlayerActionRequests(campaignId, signal),
    refetchInterval: 15_000,
  });
  const invalidate = () => client.invalidateQueries({ queryKey: ["player-room-admin", campaignId] });
  const open = useMutation({
    mutationFn: () => openPlayerRoom(campaignId),
    onSuccess: (result) => {
      setConfirmAction(null);
      setJoinCode(result.join_code ?? "");
      client.setQueryData(["player-room-admin", campaignId], result);
      showToast("玩家房间已开启；房间码只会完整显示这一次");
    },
    onError: () => showToast("无法开启玩家房间", "error"),
  });
  const close = useMutation({
    mutationFn: () => closePlayerRoom(campaignId),
    onSuccess: () => {
      setConfirmAction(null);
      setJoinCode("");
      void invalidate();
      showToast("玩家房间已关闭，现有玩家会话已撤销");
    },
    onError: () => showToast("关闭房间失败", "error"),
  });
  const kick = useMutation({
    mutationFn: (memberId: string) => kickPlayerRoomMember(campaignId, memberId),
    onSuccess: () => { void invalidate(); showToast("玩家已移出房间"); },
    onError: () => showToast("移出玩家失败", "error"),
  });
  const assign = useMutation({
    mutationFn: ({ memberId, characterId }: { memberId: string; characterId: string }) =>
      assignPlayerRoomCharacter(campaignId, memberId, characterId),
    onSuccess: () => { void invalidate(); showToast("角色已绑定给玩家"); },
    onError: () => showToast("角色绑定失败；该角色可能已被其他玩家占用", "error"),
  });
  const resolveRequest = useMutation({
    mutationFn: ({
      requestId,
      version,
      decision,
    }: {
      requestId: string;
      version: number;
      decision: "accept" | "reject";
    }) => resolvePlayerActionRequest(campaignId, requestId, version, decision),
    onSuccess: (_, variables) => {
      void client.invalidateQueries({ queryKey: ["player-action-requests", campaignId] });
      showToast(variables.decision === "accept" ? "已接受玩家行动" : "已驳回玩家行动");
    },
    onError: () => showToast("处理玩家行动失败，请刷新后重试", "error"),
  });

  useEffect(() => {
    if (room.data?.status !== "active") return;
    if (
      room.data.current_scene_id === currentSceneId
      && room.data.current_combat_id === currentCombatId
    ) return;
    void setPlayerRoomLiveState(campaignId, currentSceneId, currentCombatId)
      .then((result) => client.setQueryData(["player-room-admin", campaignId], result))
      .catch(() => showToast("玩家端实时场景同步失败", "error"));
  }, [campaignId, client, currentCombatId, currentSceneId, room.data, showToast]);

  if (room.isLoading) return <Panel eyebrow="局域网玩家" title="玩家房间"><LoadingBlock label="正在读取玩家房间…" /></Panel>;
  if (room.isError && !isMissingPlayerRoom(room.error)) {
    return <Panel eyebrow="局域网玩家" title="玩家房间"><ErrorState error={room.error} onRetry={() => void room.refetch()} /></Panel>;
  }
  const data = room.data;
  const active = data?.status === "active";
  const displayCode = joinCode || (data?.join_code ? data.join_code : data?.join_code_hint ? `••••${data.join_code_hint}` : "—");
  const activeMembers = data?.members.filter((member) => member.status === "active") ?? [];
  const pendingRequests = actionRequests.data?.items ?? [];

  return (
    <Panel className="mb-4" eyebrow="局域网玩家 · 安全公开视图" title="玩家房间">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={active ? "ok" : "neutral"}>{active ? "开放中" : data?.status === "expired" ? "已过期" : "未开启"}</Badge>
        {active ? <span className="font-mono text-xl font-bold tracking-[.2em] text-amber-200" aria-label="玩家房间码">{displayCode}</span> : null}
        <span className="mr-auto text-xs text-stone-500">玩家端只能访问公开场景、自己的角色与自己的战斗操作。</span>
        <Button
          loading={open.isPending}
          onClick={() => {
            if (active) setConfirmAction("rotate");
            else open.mutate();
          }}
          variant="primary"
        >{active ? "轮换房间码" : "开启玩家房间"}</Button>
        {active ? <Button loading={close.isPending} onClick={() => setConfirmAction("close")} variant="danger">关闭房间</Button> : null}
      </div>
      {active ? (
        <>
          <div className="mt-3 grid gap-2 lg:grid-cols-2">
            {(data?.urls ?? []).map((url) => (
              <div className="flex min-w-0 items-center gap-2 rounded border border-ink-700 bg-ink-950/50 p-2" key={url}>
                <code className="min-w-0 flex-1 truncate text-xs text-emerald-300">{url}</code>
                <Button onClick={() => void navigator.clipboard.writeText(url).then(() => showToast("玩家地址已复制"))} size="sm">复制</Button>
              </div>
            ))}
          </div>
          <p className="mb-0 mt-2 text-2xs text-stone-500">当前公开：Scene {currentSceneId ? "已同步" : "未选择"} · 战斗 {currentCombatId ? "已同步" : "未开始"} · 到期 {data ? new Date(data.expires_at).toLocaleString() : "—"}</p>
          <div className="mt-3 border-t border-ink-700 pt-3">
            <strong className="text-sm text-parchment-100">已加入玩家（{activeMembers.length}）</strong>
            {activeMembers.length === 0 ? <p className="mb-0 text-xs text-stone-500">等待玩家输入房间码加入。</p> : (
              <div className="mt-2 grid gap-2 lg:grid-cols-2">
                {activeMembers.map((member) => (
                  <div className="rounded border border-ink-700 bg-ink-950/40 p-2" key={member.id}>
                    <div className="flex items-center gap-2"><strong className="mr-auto text-sm">{member.display_name}</strong><Badge tone={member.character_id ? "ok" : "warn"}>{member.character_id ? "已绑角色" : "等待车卡/绑定"}</Badge><Button loading={kick.isPending} onClick={() => kick.mutate(member.id)} size="sm" variant="danger">移出</Button></div>
                    {!member.character_id ? (
                      <div className="mt-2 flex gap-2">
                        <select aria-label={`为${member.display_name}绑定角色`} className={selectCls} onChange={(event) => setAssignments((current) => ({ ...current, [member.id]: event.target.value }))} value={assignments[member.id] ?? ""}>
                          <option value="">DM 选择已有角色</option>
                          {characters.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}
                        </select>
                        <Button disabled={!assignments[member.id]} loading={assign.isPending} onClick={() => assign.mutate({ memberId: member.id, characterId: assignments[member.id] ?? "" })} size="sm">绑定</Button>
                      </div>
                    ) : <p className="mb-0 mt-1 text-2xs text-stone-600">角色 ID：{member.character_id}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="mt-3 border-t border-ink-700 pt-3">
            <strong className="text-sm text-parchment-100">待处理玩家行动（{pendingRequests.length}）</strong>
            {pendingRequests.length === 0 ? (
              <p className="mb-0 text-xs text-stone-500">玩家提交的自由行动会在这里实时出现。</p>
            ) : (
              <div className="mt-2 grid gap-2 lg:grid-cols-2">
                {pendingRequests.map((request) => {
                  const member = activeMembers.find((item) => item.id === request.player_key);
                  const character = characters.find((item) => item.id === request.character_id);
                  const payload = request.payload_json as {
                    phase?: string;
                    action?: { name?: string; kind?: string };
                    target?: { name?: string };
                    resolution?: {
                      kind?: string;
                      instruction?: string;
                      raw_roll?: number;
                      modifier?: number;
                      total?: number;
                      dc?: number;
                      success?: boolean;
                      save?: { raw_roll?: number; modifier?: number; total?: number; dc?: number; success?: boolean; ability_label?: string };
                    };
                    proposal?: { summary?: string };
                    cost?: { resource_key?: string; amount?: number; available_before?: number; available_after?: number };
                    narrative_suggestions?: string[];
                  };
                  const structured = request.action_type === "noncombat_rule";
                  const ready = !structured || payload.phase === "resolved";
                  return (
                    <div className="rounded border border-violet-800/70 bg-violet-950/20 p-3" key={request.id}>
                      <div className="flex items-center gap-2">
                        <strong className="mr-auto text-sm">{member?.display_name ?? character?.name ?? "玩家"}</strong>
                        <Badge tone={ready ? "warn" : "neutral"}>{ready ? "等待 DM" : "等待玩家投骰"}</Badge>
                      </div>
                      <p className="mb-0 mt-2 whitespace-pre-wrap text-sm text-stone-300">{request.message || "未填写说明"}</p>
                      {structured ? <div className="mt-2 rounded border border-violet-900/70 bg-ink-950/45 p-2 text-xs leading-5 text-stone-300">
                        <strong className="text-violet-200">{payload.action?.name ?? "结构化行动"} → {payload.target?.name ?? "当前区域"}</strong>
                        {payload.resolution?.instruction ? <span className="block">{payload.resolution.instruction}</span> : null}
                        {payload.resolution?.total !== undefined ? <span className="block">玩家裸骰 {payload.resolution.raw_roll} {Number(payload.resolution.modifier ?? 0) >= 0 ? "+" : ""}{payload.resolution.modifier} = {payload.resolution.total} vs DC {payload.resolution.dc} · {payload.resolution.success ? "成功" : "失败"}</span> : null}
                        {payload.resolution?.save ? <span className="block">系统代掷目标{payload.resolution.save.ability_label}豁免：{payload.resolution.save.raw_roll} {Number(payload.resolution.save.modifier ?? 0) >= 0 ? "+" : ""}{payload.resolution.save.modifier} = {payload.resolution.save.total} vs DC {payload.resolution.save.dc} · {payload.resolution.save.success ? "成功" : "失败"}</span> : null}
                        {payload.cost?.resource_key ? <span className="block text-amber-200">确认后消耗 {payload.cost.resource_key} × {payload.cost.amount}（{payload.cost.available_before} → {payload.cost.available_after}）</span> : null}
                        {payload.proposal?.summary ? <span className="mt-1 block text-emerald-200">建议结果：{payload.proposal.summary}</span> : null}
                        {payload.narrative_suggestions?.length ? <ul className="mb-0 mt-1 pl-4 text-stone-500">{payload.narrative_suggestions.map((suggestion) => <li key={suggestion}>{suggestion}</li>)}</ul> : null}
                      </div> : null}
                      <div className="mt-2 flex justify-end gap-2">
                        <Button
                          disabled={!ready}
                          loading={resolveRequest.isPending}
                          onClick={() => resolveRequest.mutate({
                            requestId: request.id,
                            version: request.version,
                            decision: "reject",
                          })}
                          size="sm"
                          variant="danger"
                        >驳回</Button>
                        <Button
                          loading={resolveRequest.isPending}
                          onClick={() => resolveRequest.mutate({
                            requestId: request.id,
                            version: request.version,
                            decision: "accept",
                          })}
                          size="sm"
                          variant="primary"
                        >接受</Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      ) : <p className="mb-0 mt-2 text-xs text-stone-500">开启后会生成 6 位房间码和局域网地址。完整 DM API 仍只监听本机，玩家无法读取 NPC 秘密或调用本地 AI。</p>}
      <ConfirmDialog
        body={confirmAction === "rotate"
          ? "轮换后当前房间码立即失效，所有已连接玩家都会退出；他们需要使用新房间码重新加入。角色与团数据不会删除。"
          : "关闭后所有玩家会立即退出，未提交的输入可能丢失；角色、Scene、战斗与公开日志仍会保留。"}
        confirmLabel={confirmAction === "rotate" ? "确认轮换房间码" : "确认关闭房间"}
        loading={open.isPending || close.isPending}
        onCancel={() => setConfirmAction(null)}
        onConfirm={() => {
          if (confirmAction === "rotate") open.mutate();
          if (confirmAction === "close") close.mutate();
        }}
        open={confirmAction !== null}
        title={confirmAction === "rotate" ? "轮换玩家房间码" : "关闭玩家房间"}
      />
    </Panel>
  );
}
