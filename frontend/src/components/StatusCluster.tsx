import { useQuery } from "@tanstack/react-query";

import { getHealth, getIndexStatus, getModelStatus } from "../api/system";
import { StatusDot } from "../ui/primitives";
import type { Tone } from "../ui/styles";

function StatusItem({ label, tone, title }: { label: string; tone: Tone; title: string }) {
  return (
    <span className="flex items-center gap-1.5 text-2xs text-stone-400" title={title}>
      <StatusDot tone={tone} />
      {label}
    </span>
  );
}

/** Backend / SQLite / Qdrant / Ollama model status cluster for the header. */
export function StatusCluster() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
    retry: false,
    refetchInterval: 30_000,
  });

  const index = useQuery({
    queryKey: ["knowledge-index-status"],
    queryFn: ({ signal }) => getIndexStatus(signal),
    retry: false,
    refetchInterval: 60_000,
  });

  const models = useQuery({
    queryKey: ["runtime-models"],
    queryFn: ({ signal }) => getModelStatus(signal),
    retry: false,
    refetchInterval: 30_000,
  });

  const backendOk = health.data?.status === "ok";
  const sqliteOk = health.data?.database === "ok";

  const indexTone: Tone = index.isError
    ? "danger"
    : index.data?.state === "ready"
      ? "ok"
      : index.data?.state === "building"
        ? "warn"
        : "warn";
  const indexTitle = index.isError
    ? "无法读取索引状态（服务可能不可用）"
    : `索引状态：${index.data?.state ?? "未知"}，${index.data?.points_count ?? 0} 个向量${
        index.data?.embedding_model ? `，嵌入模型 ${index.data.embedding_model}` : ""
      }`;
  const configuredModels = models.data?.models ?? [];
  const modelReady =
    models.data?.ollama_available === true &&
    configuredModels.filter((item) => item.configured).every((item) => item.installed);
  const missingModels = configuredModels
    .filter((item) => item.configured && !item.installed)
    .map((item) => item.model)
    .filter(Boolean);
  const modelTone: Tone = models.isLoading
    ? "neutral"
    : modelReady
      ? "ok"
      : models.data?.ollama_available
        ? "warn"
        : "danger";
  const modelTitle = models.isError
    ? "无法读取模型状态"
    : !models.data?.ollama_available
      ? "Ollama 服务不可用"
      : missingModels.length
        ? `缺少模型：${missingModels.join("、")}`
        : `模型正常：${configuredModels
            .filter((item) => item.configured)
            .map((item) => `${item.role}=${item.model}`)
            .join("，")}；Think 已关闭`;

  return (
    <div className="flex items-center gap-3" role="status">
      <StatusItem
        label="后端"
        title={backendOk ? `后端正常（环境：${health.data?.environment ?? "?"}）` : "后端无响应"}
        tone={backendOk ? "ok" : "danger"}
      />
      <StatusItem
        label="SQLite"
        title={sqliteOk ? "数据库正常" : "数据库不可用或未连接"}
        tone={sqliteOk ? "ok" : "danger"}
      />
      <StatusItem label="向量索引" title={indexTitle} tone={index.isLoading ? "neutral" : indexTone} />
      <StatusItem
        label="模型"
        title={modelTitle}
        tone={modelTone}
      />
    </div>
  );
}
