import { describe, expect, it } from "vitest";

import { formatDateTime, formatScore, formatValue } from "./format";

describe("format helpers", () => {
  it("formats scores deterministically", () => {
    expect(formatScore(0.6481)).toBe("0.65");
  });

  it("formats ISO timestamps for the DM timeline", () => {
    expect(formatDateTime("2024-01-02T03:04:05Z")).toMatch(/^2024-01-02 /);
  });

  it("renders structured values without throwing", () => {
    expect(formatValue({ hp: 12 })).toBe('{"hp":12}');
    expect(formatValue(null)).toBe("—");
  });
});
