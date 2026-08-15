import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/ToastProvider";
import { CampaignContext } from "../hooks/appContexts";
import { QuickCombatPage } from "./QuickCombatPage";

const mocks = vi.hoisted(() => ({
  listCampaigns: vi.fn(),
  listCombats: vi.fn(),
  listCombatants: vi.fn(),
  listCombatActions: vi.fn(),
  listCharacters: vi.fn(),
  listNpcs: vi.fn(),
  listScenes: vi.fn(),
  advanceCombatTurn: vi.fn(),
  updateCombatant: vi.fn(),
  confirmCombatAction: vi.fn(),
  runAssistantTurn: vi.fn(),
}));

vi.mock("../api/campaigns", () => ({
  listCampaigns: mocks.listCampaigns,
}));

vi.mock("../api/entities", () => ({
  listCombats: mocks.listCombats,
  listCombatants: mocks.listCombatants,
  listCombatActions: mocks.listCombatActions,
  listCharacters: mocks.listCharacters,
  listNpcs: mocks.listNpcs,
  listScenes: mocks.listScenes,
  advanceCombatTurn: mocks.advanceCombatTurn,
  updateCombatant: mocks.updateCombatant,
  confirmCombatAction: mocks.confirmCombatAction,
  createCombat: vi.fn(),
  createCombatant: vi.fn(),
  deleteCombatant: vi.fn(),
  updateCombat: vi.fn(),
}));

vi.mock("../api/assistant", () => ({
  runAssistantTurn: mocks.runAssistantTurn,
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CampaignContext.Provider value={{ campaignId: "campaign-1", selectCampaign: vi.fn() }}>
        <ToastProvider>
          <QuickCombatPage />
        </ToastProvider>
      </CampaignContext.Provider>
    </QueryClientProvider>,
  );
}

describe("QuickCombatPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mocks.listCampaigns.mockResolvedValue([
      { id: "campaign-1", name: "红落避难所战役" },
    ]);

    mocks.listCombats.mockResolvedValue([
      { id: "combat-1", name: "红落避难所前厅突袭", status: "active", round_number: 2, version: 1, active_combatant_index: 0 },
    ]);

    mocks.listCombatants.mockResolvedValue([
      {
        id: "c-1",
        display_name: "圣骑士 瓦伦丁",
        entity_type: "character",
        hp: 24,
        max_hp: 28,
        armor_class: 18,
        initiative: 16,
        conditions: [],
        snapshot_json: { actions: [] },
        version: 1,
      },
      {
        id: "c-2",
        display_name: "地精斥候·裂牙",
        entity_type: "monster",
        hp: 7,
        max_hp: 7,
        armor_class: 15,
        initiative: 12,
        conditions: ["prone"],
        snapshot_json: { actions: [] },
        version: 1,
      },
    ]);

    mocks.listCombatActions.mockResolvedValue([
      { id: "a-1", action_name: "弯刀挥砍", resolution_note: "命中地精造成 6 点挥砍伤害", created_at: new Date().toISOString() },
    ]);

    mocks.listCharacters.mockResolvedValue([]);
    mocks.listNpcs.mockResolvedValue([]);
    mocks.listScenes.mockResolvedValue([]);
  });

  it("renders the standalone quick combat cockpit with active turn and initiative list", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("快捷战斗座舱 (Quick Combat)")).toBeInTheDocument();
      expect(screen.getByText("第 2 轮")).toBeInTheDocument();
      expect(screen.getAllByText("圣骑士 瓦伦丁").length).toBeGreaterThan(0);
      expect(screen.getAllByText("地精斥候·裂牙").length).toBeGreaterThan(0);
    });

    expect(screen.getByText("🎲 极速骰盘")).toBeInTheDocument();
    expect(screen.getByText("🤖 AI 战术军师")).toBeInTheDocument();
  });

  it("triggers quick HP adjustment on button click", async () => {
    mocks.updateCombatant.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getAllByText("圣骑士 瓦伦丁").length).toBeGreaterThan(0);
    });

    const minus5Buttons = screen.getAllByRole("button", { name: "-5" });
    await user.click(minus5Buttons[0]);

    expect(mocks.updateCombatant).toHaveBeenCalledWith(
      "campaign-1",
      "combat-1",
      "c-1",
      { hp: 19 },
      1,
    );
  });
});
