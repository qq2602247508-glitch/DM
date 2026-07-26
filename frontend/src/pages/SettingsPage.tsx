import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, type ChangeEvent, type ReactElement } from "react";

import { exportCampaign, importCampaign } from "../api/campaigns";
import { getIndexStatus, getModelStatus } from "../api/system";
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
  const models = useQuery({
    queryKey: ["runtime-models"],
    queryFn: ({ signal }) => getModelStatus(signal),
  });
  const index = useQuery({
    queryKey: ["knowledge-index-status"],
    queryFn: ({ signal }) => getIndexStatus(signal),
  });
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
      </Panel>
    </div>
  );
}
