import { ApiError, isNetworkError } from "../api/client";

export type ErrorKind =
  | "offline"
  | "model-unavailable"
  | "conflict"
  | "not-found"
  | "validation"
  | "generic";

export type DescribedError = {
  kind: ErrorKind;
  title: string;
  message: string;
  /** Optional configuration guidance for 503 model/service unavailable. */
  guidance: string | null;
};

const MODEL_GUIDANCE =
  "本地模型未配置或未运行。请在项目根目录 .env 中设置 DND_DM_INTENT_MODEL 为本机已安装的模型（例如 qwen3:30b-instruct），确认 Ollama 正在运行，然后重启后端。前端不会自动下载模型。";

const INDEX_GUIDANCE =
  "本地向量索引不可用。请确认 Qdrant 本地数据目录存在、嵌入模型（如 bge-m3）已安装，并已执行 dnd-rag index 构建索引。详见 README 的 Local RAG 一节。";

export function describeError(error: unknown): DescribedError {
  if (isNetworkError(error)) {
    return {
      kind: "offline",
      title: "无法连接后端",
      message: "本地后端没有响应。请确认已通过 ./scripts/dev.sh 启动（默认 http://127.0.0.1:8000）。",
      guidance: null,
    };
  }
  if (error instanceof ApiError) {
    if (error.status === 503) {
      const isIndex = /vector|index|qdrant|embedding/i.test(error.message);
      return {
        kind: "model-unavailable",
        title: isIndex ? "规则检索服务不可用" : "本地模型不可用",
        message: error.message,
        guidance: isIndex ? INDEX_GUIDANCE : MODEL_GUIDANCE,
      };
    }
    if (error.status === 409) {
      return {
        kind: "conflict",
        title: "版本冲突",
        message: "数据已被其他地方修改。请刷新到最新状态后重试。",
        guidance: null,
      };
    }
    if (error.status === 400) {
      return {
        kind: "validation",
        title: "未通过 D&D 规则校验",
        message: error.message || "该操作与当前角色、装备位置或资源状态冲突。",
        guidance: null,
      };
    }
    if (error.status === 404) {
      return {
        kind: "not-found",
        title: "内容不存在",
        message: error.message || "请求的数据不存在或已被删除。",
        guidance: null,
      };
    }
    if (error.status === 422) {
      return {
        kind: "validation",
        title: "输入未通过校验",
        message: error.message || "请检查表单中标记的字段。",
        guidance: null,
      };
    }
    return {
      kind: "generic",
      title: `请求失败（${error.status}）`,
      message: error.message,
      guidance: null,
    };
  }
  return {
    kind: "generic",
    title: "发生未知错误",
    message: error instanceof Error ? error.message : String(error),
    guidance: null,
  };
}
