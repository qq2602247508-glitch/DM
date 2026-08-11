import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CampaignContext } from "../hooks/appContexts";
import { MerchantsPage } from "./MerchantsPage";

const mocks = vi.hoisted(() => ({
  listCharacters: vi.fn(),
  listLocations: vi.fn(),
  listMerchants: vi.fn(),
  listScenes: vi.fn(),
}));

vi.mock("../api/entities", () => ({
  listCharacters: mocks.listCharacters,
  listLocations: mocks.listLocations,
}));
vi.mock("../api/world", () => ({ listScenes: mocks.listScenes }));
vi.mock("../api/merchants", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/merchants")>();
  return { ...actual, listMerchants: mocks.listMerchants };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CampaignContext.Provider value={{ campaignId: "campaign-1", selectCampaign: vi.fn() }}>
        <MerchantsPage />
      </CampaignContext.Provider>
    </QueryClientProvider>,
  );
}

describe("MerchantsPage saved shops", () => {
  beforeEach(() => {
    mocks.listCharacters.mockResolvedValue([]);
    mocks.listLocations.mockResolvedValue([]);
    mocks.listScenes.mockResolvedValue([]);
    mocks.listMerchants.mockResolvedValue([
      {
        merchant_id: "merchant-1",
        name: "月灯杂货铺",
        npc_id: "npc-1",
        brief: "给冒险者准备的奥术远行补给",
        attitude: "neutral",
        hp: 9,
        max_hp: 9,
        armor_class: 10,
        location_id: "location-1",
        location_name: "长桥市场",
        scene_id: "scene-1",
        scene_name: "月灯铺面",
        item_tier: "uncommon",
        stock: [
          {
            id: "stock-1",
            name: "治疗药水",
            quantity: 3,
            price_copper: 5000,
            metadata_json: { category: "potion", source_kind: "official" },
          },
        ],
      },
    ]);
  });

  it("opens a saved merchant and shows its context and inventory", async () => {
    const user = userEvent.setup();
    renderPage();

    const opener = await screen.findByRole("button", { name: /月灯杂货铺/ });
    expect(opener).toHaveAttribute("aria-expanded", "false");

    await user.click(opener);

    expect(opener).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("给冒险者准备的奥术远行补给")).toBeInTheDocument();
    expect(screen.getByText("地点：长桥市场")).toBeInTheDocument();
    expect(screen.getByText("Scene：月灯铺面")).toBeInTheDocument();
    expect(screen.getByText("治疗药水")).toBeInTheDocument();
    expect(screen.getByText("50.00 gp · 库存 3")).toBeInTheDocument();
  });
});
