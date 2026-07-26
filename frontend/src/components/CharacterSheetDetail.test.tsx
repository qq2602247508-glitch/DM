import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Character } from "../api/types";
import { ToastProvider } from "./ToastProvider";
import { CharacterSheetDetail } from "./CharacterSheetDetail";

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
  it("exposes feature explanations to mouse and keyboard users", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <CharacterSheetDetail
            campaignId="campaign-1"
            character={CHARACTER}
            onClose={vi.fn()}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText("第二风息")).toHaveAttribute(
      "title",
      "第二风息：以附赠动作恢复生命值。",
    );
    expect(screen.getByText("足智多谋")).toHaveAttribute(
      "aria-label",
      expect.stringContaining("长休"),
    );
    expect(screen.getByText("足智多谋")).toHaveAttribute("tabindex", "0");
  });
});
