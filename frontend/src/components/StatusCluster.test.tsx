import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StatusCluster } from "./StatusCluster";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StatusCluster", () => {
  it("shows a healthy configured local model instead of a neutral placeholder", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/health")) {
        return Promise.resolve(new Response(JSON.stringify({ status: "ok", database: "ok", environment: "test" })));
      }
      if (url.endsWith("/knowledge/index/status")) {
        return Promise.resolve(new Response(JSON.stringify({
          collection_name: "rules", available: true, state: "ready", reason: null,
          points_count: 42, vector_size: 1024, indexed_records: 12,
          embedding_model: "bge-m3:latest", chunking_fingerprint: "test", updated_at: null,
        })));
      }
      return Promise.resolve(new Response(JSON.stringify({
        ollama_available: true,
        think_enabled: false,
        installed_models: ["qwen3:30b-instruct", "bge-m3:latest"],
        reason: null,
        models: [
          { role: "intent", model: "qwen3:30b-instruct", configured: true, installed: true },
          { role: "reasoning", model: "qwen3:30b-instruct", configured: true, installed: true },
          { role: "embedding", model: "bge-m3:latest", configured: true, installed: true },
        ],
      })));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><StatusCluster /></QueryClientProvider>);
    expect(await screen.findByTitle(/模型正常/)).toHaveTextContent("模型");
    expect(screen.getByTitle(/Think 已关闭/)).toBeInTheDocument();
  });
});
