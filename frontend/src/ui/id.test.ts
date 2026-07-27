import { afterEach, describe, expect, it, vi } from "vitest";

import { createClientId } from "./id";

describe("createClientId", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses Web Crypto UUID when the browser supports it", () => {
    vi.stubGlobal("crypto", {
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
    });

    expect(createClientId()).toBe("00000000-0000-4000-8000-000000000001");
  });

  it("returns unique IDs when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {});
    vi.spyOn(Date, "now").mockReturnValue(1_750_000_000_000);
    vi.spyOn(Math, "random").mockReturnValue(0.123456789);

    const first = createClientId("player-action");
    const second = createClientId("player-action");

    expect(first).toMatch(/^player-action-[a-z0-9]+-[a-z0-9]+-[a-z0-9]+$/);
    expect(second).toMatch(/^player-action-[a-z0-9]+-[a-z0-9]+-[a-z0-9]+$/);
    expect(second).not.toBe(first);
  });
});
