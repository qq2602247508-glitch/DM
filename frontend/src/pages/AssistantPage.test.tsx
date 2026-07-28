import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AssistantPrefillContext,
  CampaignContext,
} from "../hooks/appContexts";
import { AssistantPage } from "./AssistantPage";

const mocks = vi.hoisted(() => ({
  answerKnowledge: vi.fn(),
  listCampaigns: vi.fn(),
  runAssistantTurn: vi.fn(),
}));

vi.mock("../api/assistant", () => ({
  runAssistantTurn: mocks.runAssistantTurn,
}));
vi.mock("../api/knowledge", () => ({
  answerKnowledge: mocks.answerKnowledge,
}));
vi.mock("../api/campaigns", () => ({
  listCampaigns: mocks.listCampaigns,
}));

const AGENT_RESPONSE = {
  request_id: "request-1",
  campaign_id: "campaign-1",
  dm_hint: null,
  tool_results: [],
  citations: [],
  proposals: [],
  abstained: false,
  errors: [],
};

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => {
      values.delete(key);
    },
    setItem: (key, value) => {
      values.set(key, value);
    },
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CampaignContext.Provider
        value={{ campaignId: "campaign-1", selectCampaign: vi.fn() }}
      >
        <AssistantPrefillContext.Provider
          value={{ prefill: null, setPrefill: vi.fn(), clearPrefill: vi.fn() }}
        >
          <AssistantPage />
        </AssistantPrefillContext.Provider>
      </CampaignContext.Provider>
    </QueryClientProvider>,
  );
}

async function submit(user: ReturnType<typeof userEvent.setup>, text: string) {
  const input = screen.getByLabelText("描述玩家行动或输入问题");
  await user.type(input, text);
  await user.click(screen.getByRole("button", { name: "发送" }));
}

describe("AssistantPage mode routing", () => {
  beforeEach(() => {
    const storage = memoryStorage();
    vi.stubGlobal("localStorage", storage);
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: storage,
    });
    Element.prototype.scrollIntoView = vi.fn();
    mocks.listCampaigns.mockResolvedValue([{ id: "campaign-1", name: "Test" }]);
    mocks.runAssistantTurn.mockResolvedValue(AGENT_RESPONSE);
    mocks.answerKnowledge.mockResolvedValue({
      answer: "规则答案",
      abstained: false,
      reason: null,
      citations: [],
    });
  });

  it("routes quick, story and combat to distinct assistant modes while rules stays dedicated", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByLabelText("描述玩家行动或输入问题");

    await submit(user, "快速建议");
    await waitFor(() =>
      expect(mocks.runAssistantTurn).toHaveBeenLastCalledWith(
        "campaign-1",
        "快速建议",
        { mode: "quick" },
      ),
    );

    await user.click(screen.getByRole("tab", { name: "剧情建议" }));
    await submit(user, "剧情推进");
    await waitFor(() =>
      expect(mocks.runAssistantTurn).toHaveBeenLastCalledWith(
        "campaign-1",
        "剧情推进",
        { mode: "narrative" },
      ),
    );

    await user.click(screen.getByRole("tab", { name: "战斗辅助" }));
    await submit(user, "战斗步骤");
    await waitFor(() =>
      expect(mocks.runAssistantTurn).toHaveBeenLastCalledWith(
        "campaign-1",
        "战斗步骤",
        { mode: "combat" },
      ),
    );

    await user.click(screen.getByRole("tab", { name: "规则查询" }));
    await submit(user, "火球术豁免");
    await waitFor(() =>
      expect(mocks.answerKnowledge).toHaveBeenLastCalledWith("火球术豁免"),
    );
    expect(mocks.runAssistantTurn).toHaveBeenCalledTimes(3);
  });
});
