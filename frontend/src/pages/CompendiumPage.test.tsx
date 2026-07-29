import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/ToastProvider";
import { CampaignContext } from "../hooks/appContexts";
import { CompendiumPage } from "./CompendiumPage";

const mocks = vi.hoisted(() => ({
  listCampaigns: vi.fn(),
  listCharacters: vi.fn(),
  listCompendium: vi.fn(),
  listScenes: vi.fn(),
  searchKnowledge: vi.fn(),
}));

vi.mock("../api/campaigns", () => ({ listCampaigns: mocks.listCampaigns }));
vi.mock("../api/entities", () => ({ listCharacters: mocks.listCharacters }));
vi.mock("../api/world", () => ({ listScenes: mocks.listScenes }));
vi.mock("../api/knowledge", () => ({ searchKnowledge: mocks.searchKnowledge }));
vi.mock("../api/compendium", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/compendium")>();
  return {
    ...actual,
    listCompendium: mocks.listCompendium,
  };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CampaignContext.Provider value={{ campaignId: "campaign-1", selectCampaign: vi.fn() }}>
        <ToastProvider>
          <CompendiumPage />
        </ToastProvider>
      </CampaignContext.Provider>
    </QueryClientProvider>,
  );
}

describe("CompendiumPage catalog controls", () => {
  beforeEach(() => {
    mocks.listCampaigns.mockResolvedValue([{ id: "campaign-1", name: "测试团" }]);
    mocks.listCharacters.mockResolvedValue([]);
    mocks.listScenes.mockResolvedValue([]);
    mocks.searchKnowledge.mockResolvedValue([]);
    mocks.listCompendium.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 40,
      counts: {},
      official_total: 0,
      facets: {},
    });
  });

  it("hides legacy by default and groups class/subclass entries by class", async () => {
    const user = userEvent.setup();
    renderPage();

    const legacy = await screen.findByRole("checkbox", {
      name: /显示 2014 \/ legacy 旧版/,
    });
    expect(legacy).not.toBeChecked();
    await waitFor(() =>
      expect(mocks.listCompendium).toHaveBeenCalledWith(
        "campaign-1",
        expect.objectContaining({
          entry_type: "spell",
          include_legacy: false,
          sort_by: "level",
          sort_order: "asc",
        }),
        expect.any(AbortSignal),
      ),
    );

    await user.click(screen.getByRole("button", { name: /^职业与子职/ }));
    await waitFor(() =>
      expect(mocks.listCompendium).toHaveBeenCalledWith(
        "campaign-1",
        expect.objectContaining({
          entry_type: "feature",
          include_legacy: false,
          sort_by: "class",
          sort_order: "asc",
        }),
        expect.any(AbortSignal),
      ),
    );
    expect(screen.getByLabelText("图鉴排序")).toHaveValue("class:asc");

    await user.click(legacy);
    await waitFor(() =>
      expect(mocks.listCompendium).toHaveBeenCalledWith(
        "campaign-1",
        expect.objectContaining({
          entry_type: "feature",
          include_legacy: true,
        }),
        expect.any(AbortSignal),
      ),
    );
  });
});
