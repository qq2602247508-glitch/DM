import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { describeError } from "./errors";

describe("frontend error guidance", () => {
  it("explains an unconfigured local model without suggesting a download", () => {
    const error = new ApiError(503, {
      code: "runtime_unavailable",
      message: "intent model is not configured",
      details: null,
      request_id: "req-1",
    });
    const result = describeError(error);
    expect(result.kind).toBe("model-unavailable");
    expect(result.guidance).toContain("DND_DM_INTENT_MODEL");
    expect(result.guidance).toContain("不会自动下载模型");
  });

  it("turns stale writes into actionable conflict guidance", () => {
    const error = new ApiError(409, {
      code: "version_conflict",
      message: "stale version",
      details: null,
      request_id: "req-2",
    });
    expect(describeError(error)).toMatchObject({
      kind: "conflict",
      title: "版本冲突",
    });
  });

  it("distinguishes network failures from API responses", () => {
    expect(describeError(new TypeError("fetch failed")).kind).toBe("offline");
  });
});
