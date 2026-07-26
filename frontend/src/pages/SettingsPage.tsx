import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type ChangeEvent, type ReactElement } from "react";

import { exportCampaign, importCampaign } from "../api/campaigns";
import { createRecoveryPoint, getDiagnostics, getIndexStatus, getModelStatus, getSafeMode, listAudit, listHouseRules, listRecoveryPoints, previewRestore, restorePoint, saveHouseRule, setSafeMode } from "../api/system";
import type { CampaignBackup } from "../api/types";
import { Panel } from "../components/Panel";
import { useCurrentCampaign } from "../hooks/appContexts";
import { useToast } from "../hooks/toastContext";
import { Badge, Button, ErrorState, KeyValue, LoadingBlock } from "../ui/primitives";
import { formatDateTime } from "../ui/format";

function saveJson(filename: string, value: unknown): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function SettingsPage(): ReactElement {
  const { campaignId, selectCampaign } = useCurrentCampaign();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [safeReason, setSafeReason] = useState("");
  const [house, setHouse] = useState({ rule_key: "", core_value: "", override_value: "", source: "DM", reason: "" });
  const models = useQuery({
    queryKey: ["runtime-models"],
    queryFn: ({ signal }) => getModelStatus(signal),
  });
  const index = useQuery({
    queryKey: ["knowledge-index-status"],
    queryFn: ({ signal }) => getIndexStatus(signal),
  });
  const diagnostics = useQuery({ queryKey: ["diagnostics"], queryFn: ({ signal }) => getDiagnostics(signal) });
  const safeMode = useQuery({ queryKey: ["safe-mode"], queryFn: ({ signal }) => getSafeMode(signal) });
  const points = useQuery({ queryKey: ["recovery-points"], queryFn: ({ signal }) => listRecoveryPoints(signal) });
  const audit = useQuery({ queryKey: ["audit", campaignId], queryFn: ({ signal }) => listAudit(campaignId, signal) });
  const houseRules = useQuery({ queryKey: ["house-rules", campaignId], queryFn: ({ signal }) => listHouseRules(campaignId ?? "", signal), enabled: Boolean(campaignId) });
  const backupPoint = useMutation({ mutationFn: () => createRecoveryPoint("DM 手动恢复点"), onSuccess: () => { void points.refetch(); showToast("已创建一致性 SQLite 恢复点"); }, onError: () => showToast("创建恢复点失败", "error") });
  const toggleSafe = useMutation({ mutationFn: () => setSafeMode(!safeMode.data?.enabled, safeReason), onSuccess: () => { void safeMode.refetch(); setSafeReason(""); showToast("安全模式已更新"); }, onError: () => showToast("启用安全模式需填写原因", "error") });
  const restore = useMutation({ mutationFn: async (id: string) => { const preview = await previewRestore(id); if (!window.confirm(`${preview.warning}\n\n恢复点：${preview.label}\n包含 ${preview.campaigns} 个战役。确定继续？`)) throw new Error("cancelled"); return restorePoint(id, preview.confirm_token); }, onSuccess: () => { void points.refetch(); showToast("恢复完成；已先创建自动备份，请刷新页面"); }, onError: (error) => { if (error instanceof Error && error.message === "cancelled") return; showToast("恢复被取消或失败", "error"); } });
  const houseSave = useMutation({ mutationFn: async () => { if (!campaignId) throw new Error("campaign required"); return saveHouseRule(campaignId, { ...house, core_value: house.core_value, override_value: house.override_value, enabled: true }); }, onSuccess: () => { setHouse({ rule_key: "", core_value: "", override_value: "", source: "DM", reason: "" }); void houseRules.refetch(); void audit.refetch(); showToast("房规覆盖已保存并记录来源与理由"); }, onError: () => showToast("请填写规则键、来源和理由", "error") });
  const exporting = useMutation({
    mutationFn: async () => {
      if (!campaignId) throw new Error("请先选择战役");
      return exportCampaign(campaignId);
    },
    onSuccess: (backup) => {
      const rawName = typeof backup.campaign.name === "string" ? backup.campaign.name : "campaign";
      const safeName = rawName.replace(/[\\/:*?"<>|]/g, "-");
      saveJson(`${safeName}-${new Date().toISOString().slice(0, 10)}.json`, backup);
      showToast("战役备份已下载");
    },
    onError: () => showToast("战役备份失败", "error"),
  });
  const importing = useMutation({
    mutationFn: (backup: CampaignBackup) => importCampaign(backup),
    onSuccess: (campaign) => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      selectCampaign(campaign.id);
      showToast("战役已作为新副本导入");
    },
    onError: () => showToast("备份导入失败，请确认文件来自本应用", "error"),
  });

  const onImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as CampaignBackup;
      if (parsed.schema_version !== "1.0" || typeof parsed.campaign !== "object") {
        throw new Error("invalid backup");
      }
      importing.mutate(parsed);
    } catch {
      showToast("无法读取该备份文件", "error");
    }
  };

  return (
    <div className="mx-auto max-w-[1000px] p-4 lg:p-6">
      <Panel eyebrow="本地运行环境" title="模型与索引">
        {models.isLoading || index.isLoading ? <LoadingBlock /> : null}
        {models.isError ? <ErrorState error={models.error} onRetry={() => void models.refetch()} /> : null}
        {models.data ? (
          <div className="grid gap-4 md:grid-cols-2">
            <dl className="m-0">
              <KeyValue k="Ollama" v={<Badge tone={models.data.ollama_available ? "ok" : "danger"}>{models.data.ollama_available ? "正常" : "不可用"}</Badge>} />
              <KeyValue k="思考模式" v={models.data.think_enabled ? "开启" : "关闭（快速）"} />
              {models.data.models.map((item) => (
                <KeyValue
                  k={item.role}
                  key={item.role}
                  v={<span className={item.installed ? "text-emerald-300" : "text-amber-300"}>{item.model ?? "未配置"}</span>}
                />
              ))}
            </dl>
            {index.data ? (
              <dl className="m-0">
                <KeyValue k="向量索引" v={<Badge tone={index.data.available ? "ok" : "warn"}>{index.data.state}</Badge>} />
                <KeyValue k="向量数量" v={index.data.points_count.toLocaleString("zh-CN")} />
                <KeyValue k="内容记录" v={index.data.indexed_records.toLocaleString("zh-CN")} />
                <KeyValue k="更新时间" v={index.data.updated_at ? formatDateTime(index.data.updated_at) : "未知"} />
              </dl>
            ) : null}
          </div>
        ) : null}
      </Panel>

      <Panel className="mt-4" eyebrow="本地数据安全" title="备份与恢复">
        <p className="mt-0 text-sm leading-6 text-stone-400">
          备份包含当前战役的角色、状态、NPC、地点连接、任务、线索、事件、战斗和参战者。
          导入始终创建新副本，不覆盖现有战役。
        </p>
        <div className="flex flex-wrap gap-2">
          <Button disabled={!campaignId} icon="copy" loading={exporting.isPending} onClick={() => exporting.mutate()} variant="primary">
            下载当前战役备份
          </Button>
          <Button icon="scroll" loading={importing.isPending} onClick={() => fileInput.current?.click()}>
            导入备份副本
          </Button>
          <input accept="application/json,.json" className="hidden" onChange={(event) => void onImport(event)} ref={fileInput} type="file" />
        </div>
        <p className="mb-0 mt-3 text-xs text-stone-600">
          文件保存在你选择的本机位置；应用不会上传备份或自动下载模型。
        </p>
        <div className="mt-4 border-t border-ink-700/60 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm text-parchment-100">SQLite 一致性恢复点</span><Button loading={backupPoint.isPending} onClick={() => backupPoint.mutate()} size="sm">创建恢复点</Button></div>
          <p className="text-xs text-stone-500">使用 SQLite backup API，包含所有本地战役与系统配置；恢复前总会自动备份当前数据库。</p>
          <ul className="m-0 list-none divide-y divide-ink-700/50 p-0">{points.data?.items.map((point) => <li className="flex items-center justify-between gap-3 py-2 text-xs" key={point.id}><span>{point.label} · {formatDateTime(point.created_at)} · {(point.size_bytes / 1024).toFixed(1)} KB</span><Button loading={restore.isPending} onClick={() => restore.mutate(point.id)} size="sm" variant="danger">预览并恢复</Button></li>) ?? <li className="py-2 text-xs text-stone-600">尚无恢复点</li>}</ul>
        </div>
      </Panel>

      <Panel className="mt-4" eyebrow="故障隔离" title="只读安全模式与启动诊断">
        <p className="mt-0 text-sm text-stone-400">只读模式会阻止所有状态写入，适合发现异常、升级或恢复前保护现有数据。</p>
        <div className="flex flex-wrap gap-2"><input className="rounded-md border border-ink-600 bg-ink-950 px-3 py-2 text-sm" onChange={(e) => setSafeReason(e.target.value)} placeholder="启用时必须说明原因" value={safeReason} /><Button loading={toggleSafe.isPending} onClick={() => toggleSafe.mutate()} variant={safeMode.data?.enabled ? "danger" : "primary"}>{safeMode.data?.enabled ? "退出只读模式" : "启用只读模式"}</Button><Badge tone={safeMode.data?.enabled ? "warn" : "ok"}>{safeMode.data?.enabled ? "写入已锁定" : "可写"}</Badge></div>
        {diagnostics.data ? <dl className="mt-4 grid gap-x-8 text-xs md:grid-cols-2"><KeyValue k="SQLite" v={diagnostics.data.database.available ? `正常 · 迁移 ${diagnostics.data.database.migration_revision ?? "未知"}` : diagnostics.data.database.reason ?? "不可用"} /><KeyValue k="备份目录" v={diagnostics.data.backups_directory} /></dl> : <LoadingBlock label="正在检查启动依赖…" />}
      </Panel>

      <Panel className="mt-4" eyebrow="规则透明度" title="房规覆盖层">
        <p className="mt-0 text-xs text-stone-500">每一项偏离核心规则都必须保留核心值、覆盖值、来源和理由，并写入操作审计。</p>
        <div className="grid gap-2 md:grid-cols-2">{(["rule_key", "core_value", "override_value", "source", "reason"] as const).map((field) => <input className="rounded-md border border-ink-600 bg-ink-950 px-3 py-2 text-sm" key={field} onChange={(e) => setHouse({ ...house, [field]: e.target.value })} placeholder={{ rule_key: "规则键，如 rest.long.duration", core_value: "核心规则值", override_value: "房规值", source: "来源（DM/团务共识）", reason: "偏离原因" }[field]} value={house[field]} />)}</div>
        <Button className="mt-2" disabled={!campaignId} loading={houseSave.isPending} onClick={() => houseSave.mutate()} size="sm" variant="primary">保存房规覆盖</Button>
        <ul className="m-0 mt-3 list-none divide-y divide-ink-700/50 p-0">{houseRules.data?.items.map((rule) => <li className="py-2 text-xs" key={rule.id}><span className="text-parchment-100">{rule.rule_key}</span>：核心 {String(rule.core_value_json)} → 覆盖 {String(rule.override_value_json)}；{rule.source} · {rule.reason}</li>)}</ul>
      </Panel>

      <Panel className="mt-4" eyebrow="可追溯性" title="最近操作审计">
        <ul className="m-0 list-none divide-y divide-ink-700/50 p-0">{audit.data?.items.slice(0, 30).map((entry) => <li className="py-2 text-xs" key={entry.id}><span className="text-parchment-100">{entry.action}</span> · {entry.entity_type} · {formatDateTime(entry.created_at)} <span className="text-stone-600">请求 {entry.request_id}</span></li>) ?? <li className="py-2 text-xs text-stone-600">尚无可显示的审计记录</li>}</ul>
      </Panel>
    </div>
  );
}
