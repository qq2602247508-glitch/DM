import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Character } from "../api/types";
import { getCharacterAssets } from "../api/entities";
import { ToastProvider } from "./ToastProvider";
import { CharacterSheetDetail } from "./CharacterSheetDetail";

vi.mock("../api/entities", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/entities")>();
  return {
    ...original,
    getCharacterAssets: vi.fn(),
  };
});

const CHARACTER: Character = {
  id: "character-1",
  campaign_id: "campaign-1",
  name: "艾琳·晨盾",
  race: "人类",
  background: "士兵",
  class_name: "战士",
  level: 1,
  experience: 0,
  armor_class: 16,
  speed: 30,
  ability_scores: {
    strength: 15,
    dexterity: 14,
    constitution: 13,
    intelligence: 10,
    wisdom: 12,
    charisma: 8,
  },
  hp: 11,
  max_hp: 11,
  max_hp_reduction: 0,
  ability_score_reductions: {},
  death_saves: { successes: 0, failures: 0 },
  inventory: [],
  equipment: [],
  proficiencies: [],
  skills: { 运动: { proficient: true } },
  features: [
    { name: "第二风息", description: "以附赠动作恢复生命值。" },
    "足智多谋",
  ],
  actions: [],
  resources: {},
  spells: [],
  spellcasting: {},
  class_levels: { 战士: 1 },
  subclass_choices: {},
  notes: null,
  created_at: "2026-07-26T00:00:00Z",
  updated_at: "2026-07-26T00:00:00Z",
  version: 1,
};

describe("CharacterSheetDetail", () => {
  function renderSheet(character: Character = CHARACTER) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <CharacterSheetDetail
            campaignId="campaign-1"
            character={character}
            onClose={vi.fn()}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );
  }

  it("shows a visible feature tooltip on hover and keyboard focus", async () => {
    const user = userEvent.setup();
    renderSheet();

    const secondWind = screen.getByRole("button", { name: /第二风息/ });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.hover(secondWind);
    expect(screen.getByRole("tooltip")).toHaveTextContent("以附赠动作恢复生命值");
    expect(secondWind).toHaveAttribute("aria-expanded", "true");

    await user.unhover(secondWind);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    const resourceful = screen.getByRole("button", { name: /足智多谋/ });
    fireEvent.focus(resourceful);
    expect(screen.getByRole("tooltip")).toHaveTextContent("长休");
    expect(resourceful).toHaveAttribute("aria-describedby");

    fireEvent.blur(resourceful);
    await user.click(secondWind);
    expect(screen.getByRole("tooltip")).toHaveTextContent("以附赠动作恢复生命值");
  });

  it("renders spellcasting stats, slots and detailed atomized spells", async () => {
    vi.mocked(getCharacterAssets).mockResolvedValue({
      equipment: [],
      wallet: null,
      spells: [{
        id: "spell-1",
        name: "火球术",
        spell_level: 3,
        prepared: true,
        source_reference: "PHB 2024",
        metadata_json: {
          description: "一道火焰爆发覆盖目标区域。",
          damage_expression: "8d6 火焰",
          range: "150尺",
          casting_time: "动作",
          duration: "立即",
          components: "V、S、M",
          concentration: false,
        },
      }],
    });
    const user = userEvent.setup();
    renderSheet({
      ...CHARACTER,
      class_name: "法师",
      ability_scores: { ...CHARACTER.ability_scores, intelligence: 16 },
      resources: {
        spell_slots_1: {
          label: "1环法术位",
          current: 1,
          max: 2,
          recovery: "long_rest",
        },
      },
      spellcasting: { ability: "智力", mode: "slots" },
    });

    await user.click(screen.getByRole("button", { name: "资源与法术" }));

    expect(await screen.findByText("火球术")).toBeInTheDocument();
    expect(screen.getByText("+5")).toBeInTheDocument();
    expect(screen.getByText("13")).toBeInTheDocument();
    expect(screen.getByText("8d6 火焰")).toBeInTheDocument();
    expect(screen.getByText("150尺")).toBeInTheDocument();
    expect(screen.getByText("V、S、M")).toBeInTheDocument();
    expect(screen.getByText("已准备")).toBeInTheDocument();
    expect(screen.getAllByText("1环法术位：").length).toBeGreaterThan(0);
  });

  it("explains an empty spellbook instead of hiding the spell section", async () => {
    vi.mocked(getCharacterAssets).mockResolvedValue({
      equipment: [],
      wallet: null,
      spells: [],
    });
    const user = userEvent.setup();
    renderSheet({
      ...CHARACTER,
      class_name: "法师",
      spellcasting: { ability: "智力", mode: "slots" },
    });

    await user.click(screen.getByRole("button", { name: "资源与法术" }));

    expect(await screen.findByRole("region", { name: "角色法术栏" })).toBeInTheDocument();
    expect(screen.getByText("尚未学习或准备法术")).toBeInTheDocument();
    expect(screen.getByText(/法术栏还是空的/)).toBeInTheDocument();
  });
});
