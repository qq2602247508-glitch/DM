import { afterEach, describe, expect, it, vi } from "vitest";

import { listCompendium } from "./compendium";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listCompendium", () => {
  it("sends legacy visibility, grouping filters and sorting to the catalog API", async () => {
    const fetchMock = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(() =>
      Promise.resolve(
        new Response(JSON.stringify({
          items: [],
          total: 0,
          page: 1,
          page_size: 40,
          counts: {},
          official_total: 0,
          facets: {},
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listCompendium("campaign-1", {
      entry_type: "feature",
      class_name: "法师",
      feature_kind: "subclass",
      include_legacy: false,
      sort_by: "class",
      sort_order: "asc",
      page: 2,
      page_size: 40,
    });

    const requested = fetchMock.mock.calls[0]?.[0];
    if (!requested) throw new Error("expected a catalog request");
    const requestUrl = requested instanceof URL
      ? requested
      : new URL(typeof requested === "string" ? requested : requested.url);
    expect(requestUrl.pathname).toBe("/api/v1/campaigns/campaign-1/compendium");
    expect(Object.fromEntries(requestUrl.searchParams)).toMatchObject({
      entry_type: "feature",
      class_name: "法师",
      feature_kind: "subclass",
      include_legacy: "false",
      sort_by: "class",
      sort_order: "asc",
      page: "2",
      page_size: "40",
    });
  });
});
