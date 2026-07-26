import { describe, expect, it } from "vitest";

import { containsNonDndContent, safeDndText } from "./contentSafety";

describe("D&D-only content safety", () => {
  it("keeps D&D aberrations and saves", () => {
    expect(containsNonDndContent("夺心魔要求进行感知豁免")).toBe(false);
  });

  it("redacts COC-specific historical output", () => {
    expect(safeDndText("奈亚拉托提普正在低语")).toContain("已隔离");
  });
});
