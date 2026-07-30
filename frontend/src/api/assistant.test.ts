import { afterEach, describe, expect, it, vi } from "vitest";

import { runAssistantTurn } from "./assistant";

const EMPTY_RESPONSE = {
  request_id: "request-1",
  campaign_id: "campaign-1",
  dm_hint: null,
  tool_results: [],
  citations: [],
  proposals: [],
  abstained: false,
  errors: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("runAssistantTurn", () => {
  it("sends canonical quick, narrative and combat modes and defaults to quick", async () => {
    const fetchMock = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(() =>
        Promise.resolve(
          new Response(JSON.stringify(EMPTY_RESPONSE), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await runAssistantTurn("campaign-1", "default");
    await runAssistantTurn("campaign-1", "fast", { mode: "quick" });
    await runAssistantTurn("campaign-1", "story", { mode: "narrative" });
    await runAssistantTurn("campaign-1", "fight", { mode: "combat" });
    await runAssistantTurn("campaign-1", "follow-up context", {
      mode: "narrative",
      userMessage: "再短一点",
      rememberConversation: true,
      includeCampaignState: false,
    });

    const bodies = fetchMock.mock.calls.map(([, init]) => {
      if (typeof init?.body !== "string") {
        throw new TypeError("expected a JSON request body");
      }
      return JSON.parse(init.body) as unknown;
    });
    expect(bodies).toEqual([
      { action: "default", mode: "quick" },
      { action: "fast", mode: "quick" },
      { action: "story", mode: "narrative" },
      { action: "fight", mode: "combat" },
      {
        action: "follow-up context",
        mode: "narrative",
        user_message: "再短一点",
        remember_conversation: true,
        include_campaign_state: false,
      },
    ]);
  });
});
