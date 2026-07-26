import type { ErrorEnvelope } from "./types";

const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string;

  constructor(status: number, envelope: ErrorEnvelope) {
    super(envelope.message);
    this.name = "ApiError";
    this.status = status;
    this.code = envelope.code;
    this.details = envelope.details;
    this.requestId = envelope.request_id;
  }
}

/** True when the backend could not be reached at all (offline / not running). */
export function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

export function isApiError(error: unknown, status?: number): boolean {
  return error instanceof ApiError && (status === undefined || error.status === status);
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, headers, signal } = options;
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method,
    signal,
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    let envelope: ErrorEnvelope;
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      envelope = {
        code: `http_${response.status}`,
        message: `请求失败（HTTP ${response.status}）`,
        details: null,
        request_id: "unknown",
      };
    }
    throw new ApiError(response.status, envelope);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** Extract per-field messages from FastAPI 422 validation details. */
export function fieldErrorsFromDetails(details: unknown): Record<string, string> {
  if (!Array.isArray(details)) {
    return {};
  }
  const result: Record<string, string> = {};
  for (const item of details) {
    if (typeof item !== "object" || item === null) {
      continue;
    }
    const record = item as Record<string, unknown>;
    const loc = Array.isArray(record.loc) ? record.loc : [];
    const field = loc.filter((part) => part !== "body").map(String).join(".");
    const message = typeof record.msg === "string" ? record.msg : "输入无效";
    if (field && !(field in result)) {
      result[field] = message;
    }
  }
  return result;
}
