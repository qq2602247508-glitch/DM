import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CombatAction, Combatant } from "../../api/types";
import { ToastProvider } from "../ToastProvider";
import { PlayerRollPanel } from "./PlayerRollPanel";

const NOW = "2026-07-26T00:00:00Z";
const FIGHTERS: Combatant[] = [
  {
    id: "monster-1",
    campaign_id: "campaign-1",
    combat_id: "combat-1",
    display_name: "相位蜘蛛",
    entity_type: "monster",
    entity_id: "monster-atom-1",
    initiative: 14,
    armor_class: 13,
    hp: 32,
    max_hp: 32,
    temporary_hp: 0,
    max_hp_reduction: 0,
    damage_resistances: [],
    damage_vulnerabilities: [],
    damage_immunities: [],
    condition_immunities: [],
    conditions: [],
    concentration: {},
    speed_ft: 30,
    movement_remaining_ft: 30,
    action_available: true,
    bonus_action_available: true,
    reaction_available: true,
    snapshot_json: {
      actions: [
        { name: "毒牙", description: "目标进行体质豁免，失败时承受毒素伤害。" },
      ],
    },
    is_active: true,
    created_at: NOW,
    updated_at: NOW,
    version: 1,
  },
  {
    id: "player-1",
    campaign_id: "campaign-1",
    combat_id: "combat-1",
    display_name: "艾琳",
    entity_type: "character",
    entity_id: "character-1",
    initiative: 12,
    armor_class: 16,
    hp: 11,
    max_hp: 11,
    temporary_hp: 0,
    max_hp_reduction: 0,
    damage_resistances: [],
    damage_vulnerabilities: [],
    damage_immunities: [],
    condition_immunities: [],
    conditions: [],
    concentration: {},
    speed_ft: 30,
    movement_remaining_ft: 30,
    action_available: true,
    bonus_action_available: true,
    reaction_available: true,
    snapshot_json: {},
    is_active: true,
    created_at: NOW,
    updated_at: NOW,
    version: 1,
  },
];

const PENDING: CombatAction = {
  id: "action-1",
  campaign_id: "campaign-1",
  combat_id: "combat-1",
  actor_combatant_id: "monster-1",
  transaction_id: null,
  action_type: "player_roll_prompt",
  target_combatant_ids: ["player-1"],
  request_json: {
    actor_name: "相位蜘蛛",
    target_name: "艾琳",
    action_name: "毒牙",
    resolution_type: "saving_throw",
    roll_formula: "1d20",
    ability: "constitution",
    dc: 11,
  },
  result_json: { phase: "awaiting_player_roll" },
  explanation: null,
  round_number: 1,
  turn_index: 0,
  summary: "相位蜘蛛 对 艾琳 使用「毒牙」",
  idempotency_key: "prompt-1",
  dm_override: false,
  override_reason: null,
  status: "previewed",
  created_at: NOW,
  updated_at: NOW,
  version: 1,
};

const LEGENDARY_RESISTANCE_FIGHTERS = FIGHTERS.map((fighter) => (
  fighter.id === "player-1"
    ? {
        ...fighter,
        snapshot_json: {
          advanced_defenses: {
            legendary_resistance: { remaining: 2, maximum: 3 },
          },
        },
      }
    : fighter
));

const COUNTERCHARM_FIGHTERS: Combatant[] = [
  ...FIGHTERS,
  {
    ...FIGHTERS[1]!,
    id: "bard-1",
    display_name: "吟游诗人甲",
    entity_id: "bard-character-1",
    initiative: 10,
  },
  {
    ...FIGHTERS[1]!,
    id: "bard-2",
    display_name: "吟游诗人乙",
    entity_id: "bard-character-2",
    initiative: 9,
  },
];

const COUNTERCHARM_PENDING: CombatAction = {
  ...PENDING,
  result_json: {
    phase: "awaiting_feature_reroll",
    feature_reroll_window: {
      feature_id: "countercharm",
      source: "反迷惑",
      original_roll_total: 5,
      dc: 15,
      requires_second_roll: true,
      reroll_mode: "advantage",
      reaction_candidates: [
        { reaction_combatant_id: "bard-1", source: "反迷惑", distance_ft: 5 },
        { reaction_combatant_id: "bard-2", source: "反迷惑", distance_ft: 10 },
      ],
    },
  },
  version: 2,
};

describe("PlayerRollPanel", () => {
  it("makes actor, target, action, roll and DC explicit", () => {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <PlayerRollPanel
            activeEnemy={FIGHTERS[0]}
            actions={[PENDING]}
            campaignId="campaign-1"
            combatId="combat-1"
            fighters={FIGHTERS}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText("相位蜘蛛 → 艾琳 · 毒牙")).toBeInTheDocument();
    expect(screen.getByText(/玩家掷 1d20/)).toHaveTextContent("DC 11");
    expect(screen.getByRole("combobox", { name: "怪物动作名称" })).toHaveValue("毒牙");
    expect(screen.getByRole("spinbutton", { name: "艾琳玩家骰结果" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "DM确认" })).toBeDisabled();
  });

  it("explains the automatic enemy flow without showing manual prompt controls", () => {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <PlayerRollPanel
            activeEnemy={FIGHTERS[0]}
            actions={[]}
            automationEnabled
            campaignId="campaign-1"
            combatId="combat-1"
            fighters={FIGHTERS}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText("相位蜘蛛 正在自动行动")).toBeInTheDocument();
    expect(screen.getByText(/普通攻击由怪物自动掷攻击骰/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "要求玩家掷骰" })).not.toBeInTheDocument();
  });

  it("offers legendary resistance only for a saving-throw target", () => {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <PlayerRollPanel
            activeEnemy={LEGENDARY_RESISTANCE_FIGHTERS[0]}
            actions={[PENDING]}
            campaignId="campaign-1"
            combatId="combat-1"
            fighters={LEGENDARY_RESISTANCE_FIGHTERS}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText(/失败时使用传奇抗性（剩余 2 次/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /失败时使用传奇抗性/ })).not.toBeChecked();
  });

  it("requires the DM to select one countercharm reactor when multiple are eligible", () => {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <PlayerRollPanel
            activeEnemy={COUNTERCHARM_FIGHTERS[0]}
            actions={[COUNTERCHARM_PENDING]}
            campaignId="campaign-1"
            combatId="combat-1"
            fighters={COUNTERCHARM_FIGHTERS}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );

    const checkbox = screen.getByRole("checkbox", { name: /使用反迷惑反应重骰/ });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    expect(screen.getByRole("combobox", { name: "艾琳反迷惑反应者" })).toHaveValue("");
    expect(screen.getByRole("option", { name: "吟游诗人甲" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "吟游诗人乙" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("spinbutton", { name: "艾琳玩家骰结果" }), {
      target: { value: "5" },
    });
    expect(screen.getByRole("button", { name: "预览结果" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "艾琳反迷惑反应者" }), {
      target: { value: "bard-1" },
    });
    expect(screen.getByRole("button", { name: "预览结果" })).not.toBeDisabled();
  });
});
