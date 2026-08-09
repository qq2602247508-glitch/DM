import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  getCharacterOptions,
  previewAdvancement,
} from "../api/entities";
import type {
  AdvancementPreview,
  Character,
  CharacterOptionsCatalog,
} from "../api/types";
import { ToastProvider } from "./ToastProvider";
import { AdvancementDialog } from "./AdvancementDialog";

vi.mock("../api/entities", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/entities")>();
  return {
    ...original,
    getCharacterOptions: vi.fn(),
    previewAdvancement: vi.fn(),
  };
});

const CHARACTER = {
  id: "bard-1",
  campaign_id: "campaign-1",
  name: "成长测试者",
  class_name: "吟游诗人",
  level: 1,
  experience: 1_000,
  ability_scores: {},
  class_levels: { 吟游诗人: 1 },
  subclass_choices: {},
  skills: {},
  proficiencies: [],
  features: [],
  spells: [],
  resources: {},
  actions: [],
  equipment: [],
  inventory: [],
  spellcasting: {},
  race: null,
  background: null,
  armor_class: 10,
  speed: 30,
  hp: 8,
  max_hp: 8,
  max_hp_reduction: 0,
  ability_score_reductions: {},
  death_saves: { successes: 0, failures: 0 },
  notes: null,
  created_at: "2026-08-09T00:00:00Z",
  updated_at: "2026-08-09T00:00:00Z",
  version: 1,
} satisfies Character;

describe("AdvancementDialog", () => {
  it("submits fighting style through the keyed authoritative selector", async () => {
    vi.mocked(getCharacterOptions).mockResolvedValue({
      edition: 2024,
      officiality: "official",
      classes: [{
        name: "战士",
        source_record_id: "fighter",
        source_path: "PHB/Fighter",
        hit_die: 10,
        subclasses: [],
        levels: [{
          level: 1,
          proficiency_bonus: 2,
          features: ["战斗风格"],
          progression: {},
          choice_requirements: [{
            key: "fighting_style",
            kind: "selected_asset",
            minimum: 1,
            maximum: 1,
            strict: true,
            options_source: "feats:战斗风格",
            reason: "从权威目录选择",
            target_total: null,
            maximum_spell_level: null,
            options: [],
            expected_category: "战斗风格",
          }],
        }],
      }],
      feats: [{
        name: "防御",
        category: "战斗风格",
        prerequisite: "战斗风格特性",
        source_record_id: "defense-style",
        source_path: "PHB/Feats/Defense",
      }],
      spells: [],
      weapons: [],
      metamagic_options: [],
      species: [],
      backgrounds: [],
      skills: [],
      languages: [],
      tools: [],
    } as unknown as CharacterOptionsCatalog);
    vi.mocked(previewAdvancement).mockResolvedValue({
      preview_token: "preview",
      class_name: "战士",
      class_level: 1,
      subclass_name: null,
      hp_gain: 8,
      features_gained: [],
      warnings: [],
      rule_reference: { source_path: "PHB/Fighter" },
    } as unknown as AdvancementPreview);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <AdvancementDialog campaignId="campaign-1" character={CHARACTER} />
        </ToastProvider>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "升级向导" }));
    await user.selectOptions(
      await screen.findByLabelText("本级加入的职业"),
      "战士",
    );
    await user.selectOptions(
      screen.getByLabelText("fighting_style选择1"),
      "防御",
    );
    await user.click(screen.getByRole("button", { name: "生成升级预览" }));

    await waitFor(() => expect(previewAdvancement).toHaveBeenCalledTimes(1));
    expect(vi.mocked(previewAdvancement).mock.calls[0]?.[2]).toMatchObject({
      feature_choices: [],
      feature_choices_by_key: { fighting_style: ["防御"] },
    });
  });
});
