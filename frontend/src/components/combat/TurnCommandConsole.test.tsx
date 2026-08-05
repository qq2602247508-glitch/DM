import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CombatAction, Combatant, MonsterAIPreview } from "../../api/types";
import { ToastProvider } from "../ToastProvider";
import { TurnCommandConsole } from "./TurnCommandConsole";

const NOW = "2026-08-03T00:00:00Z";

function fighter(overrides: Partial<Combatant>): Combatant {
  return {
    id: "fighter-1",
    campaign_id: "campaign-1",
    combat_id: "combat-1",
    display_name: "战斗单位",
    entity_type: "character",
    entity_id: null,
    initiative: 20,
    armor_class: 16,
    hp: 40,
    max_hp: 40,
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
    ...overrides,
  };
}

const HERO = fighter({
  id: "hero-1",
  display_name: "冒险者",
  entity_type: "character",
  initiative: 20,
});

const DRAGON = fighter({
  id: "dragon-1",
  display_name: "黑龙",
  entity_type: "monster",
  initiative: 10,
  armor_class: 19,
  hp: 120,
  max_hp: 120,
  snapshot_json: {
    disposition: "enemy",
    legendary_actions_remaining: 3,
    actions: [
      {
        name: "借机尾击",
        action_type: "reaction",
        reaction_event: "leaves_reach",
        reaction_trigger: "目标离开近战威胁范围",
        attack_bonus: 9,
        damage: "1d8+5",
        damage_type: "bludgeoning",
      },
      {
        name: "传奇尾击",
        action_type: "legendary_action",
        legendary_cost: 1,
        legendary_pool_max: 3,
        attack_bonus: 9,
        damage: "2d8+5",
        damage_type: "bludgeoning",
      },
      {
        name: "巢穴震击",
        action_type: "lair_action",
        save_dc: 15,
        save_ability: "dexterity",
        damage: "2d6",
        damage_type: "thunder",
      },
    ],
  },
  version: 7,
});

const ENTERING_REACH_DRAGON = fighter({
  ...DRAGON,
  snapshot_json: {
    ...DRAGON.snapshot_json,
    actions: [
      {
        name: "借机尾击",
        action_type: "reaction",
        reaction_event: "enters_reach",
        reaction_trigger: "目标进入近战威胁范围",
        attack_bonus: 9,
        damage: "1d8+5",
        damage_type: "bludgeoning",
      },
    ],
  },
});

const PARALYZED_HERO = fighter({
  ...HERO,
  conditions: ["麻痹"],
  snapshot_json: { grid_position: { row: 1, col: 2 } },
});

const CRITICAL_DRAGON = fighter({
  ...DRAGON,
  snapshot_json: {
    disposition: "enemy",
    legendary_actions_remaining: 3,
    grid_position: { row: 1, col: 1 },
    actions: [{
      name: "传奇尾击",
      action_type: "legendary_action",
      legendary_cost: 1,
      legendary_pool_max: 3,
      attack_bonus: 9,
      damage: "2d8+5",
      damage_type: "bludgeoning",
    }],
  },
});

const CRITICAL_WINDOW: CombatAction = {
  id: "legendary-window-1",
  campaign_id: "campaign-1",
  combat_id: "combat-1",
  actor_combatant_id: CRITICAL_DRAGON.id,
  transaction_id: null,
  action_type: "eligible_action_window",
  target_combatant_ids: [],
  request_json: { source_action_type: "advance_turn" },
  result_json: {
    action_window: {
      action_cost: "legendary_action",
      status: "eligible",
      eligible_action_names: ["传奇尾击"],
      trigger: "其他单位回合结束",
    },
  },
  explanation: "等待 DM 确认",
  round_number: 1,
  turn_index: 0,
  summary: "黑龙：传奇动作窗口已开放",
  idempotency_key: "legendary-window-1",
  dm_override: false,
  override_reason: null,
  status: "confirmed",
  version: 1,
  created_at: NOW,
  updated_at: NOW,
};

function preview(planActionType = "reaction"): MonsterAIPreview {
  return {
    combat: {
      id: "combat-1",
      campaign_id: "campaign-1",
      scene_id: null,
      name: "龙巢",
      status: "active",
      round_number: 1,
      current_turn_index: 0,
      difficulty: null,
      base_xp: 0,
      difficulty_adjustments: [],
      xp_awarded: false,
      started_at: NOW,
      ended_at: null,
      created_at: NOW,
      updated_at: NOW,
      version: 1,
    },
    actor: DRAGON,
    plan: {
      actor_id: DRAGON.id,
      action_name: "借机尾击",
      action_type: planActionType,
      target_ids: [HERO.id],
      reason: "reaction窗口按结构化动作价值选择",
      steps: [],
      legendary_cost: 0,
      requires_player_roll: false,
      requires_dm_confirmation: true,
      confirmation_reasons: ["反应触发条件需要 DM 明示"],
    },
    requires_confirmation: true,
  };
}

function renderConsole(combatActions: CombatAction[] = [], fighters: Combatant[] = [HERO, DRAGON]): void {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <TurnCommandConsole
          active={HERO}
          autoEnemies={false}
          automationReady
          campaignId="campaign-1"
          combatId="combat-1"
          combatActions={combatActions}
          fighters={fighters}
          onAutoEnemiesChange={() => undefined}
          onEnemyTurnComplete={() => undefined}
          onRangeChange={() => undefined}
          turnKey="1:0"
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function requestUrl(input: RequestInfo | URL): URL {
  if (input instanceof URL) return input;
  return new URL(typeof input === "string" ? input : input.url);
}

function requestBody(init: RequestInit | undefined): Record<string, unknown> {
  if (typeof init?.body !== "string") throw new Error("expected a JSON request body");
  return JSON.parse(init.body) as Record<string, unknown>;
}

describe("TurnCommandConsole advanced monster action window", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("offers reaction, legendary and lair actions as distinct live windows", () => {
    renderConsole();

    expect(screen.getByRole("option", { name: /借机尾击 · 反应/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /传奇尾击 · 传奇动作/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /巢穴震击 · 巢穴动作/ })).toBeInTheDocument();
  });

  it("previews the selected phase and executes a reaction with the DM trigger", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >((input) => {
      const path = requestUrl(input).pathname;
      if (path.endsWith("/monster-ai/preview")) {
        return Promise.resolve(new Response(JSON.stringify(preview()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      if (path.endsWith("/actions/confirm")) {
        return Promise.resolve(new Response(JSON.stringify({
          action: { id: "action-1" },
          actor: { ...DRAGON, reaction_available: false, version: 8 },
          target: { ...HERO, hp: 34, version: 2 },
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderConsole();

    await user.selectOptions(screen.getByRole("combobox", { name: "怪物高级动作" }), "dragon-1:0");
    await user.selectOptions(screen.getByRole("combobox", { name: "怪物高级动作目标" }), HERO.id);
    await user.type(
      screen.getByRole("textbox", { name: "怪物反应触发事件" }),
      "冒险者离开黑龙的近战威胁范围",
    );
    await user.type(screen.getByRole("spinbutton", { name: "怪物高级动作攻击总值" }), "18");

    await user.click(screen.getByRole("button", { name: "读取后端窗口预览" }));
    expect(await screen.findByText(/后端 phase 预览：借机尾击 · reaction/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "DM确认并执行高级动作" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const requests = fetchMock.mock.calls.map(([input, init]) => ({
      path: requestUrl(input).pathname,
      body: requestBody(init),
    }));
    expect(requests[0]).toMatchObject({
      path: "/api/v1/campaigns/campaign-1/combats/combat-1/monster-ai/preview",
      body: {
        actor_combatant_id: DRAGON.id,
        actor_version: 7,
        phase: "reaction",
      },
    });
    expect(requests[1]).toMatchObject({
      path: "/api/v1/campaigns/campaign-1/combats/combat-1/actions/confirm",
      body: {
        actor_combatant_id: DRAGON.id,
        actor_version: 7,
        target_combatant_id: HERO.id,
        target_version: 1,
        action_cost: "reaction",
        action_name: "借机尾击",
        reaction_event: "leaves_reach",
        reaction_trigger: "冒险者离开黑龙的近战威胁范围",
        attack_roll_total: 18,
      },
    });
  });

  it("uses an eligible entering-reach window target and carries its id into confirmation", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      (input) => {
        const path = requestUrl(input).pathname;
        if (path.endsWith("/actions/confirm")) {
          return Promise.resolve(new Response(JSON.stringify({
            action: { id: "reaction-action-1" },
            actor: { ...DRAGON, reaction_available: false, version: 8 },
            target: { ...HERO, hp: 34, version: 2 },
          }), { status: 200, headers: { "Content-Type": "application/json" } }));
        }
        throw new Error(`unexpected request: ${path}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const windowAction: CombatAction = {
      id: "reaction-window-1",
      campaign_id: "campaign-1",
      combat_id: "combat-1",
      actor_combatant_id: DRAGON.id,
      transaction_id: null,
      action_type: "eligible_action_window",
      target_combatant_ids: [HERO.id],
      request_json: { reaction_event: "enters_reach" },
      result_json: {
        action_window: {
          action_cost: "reaction",
          status: "eligible",
          reaction_event: "enters_reach",
          trigger: "冒险者进入黑龙的近战威胁范围",
          trigger_combatant_id: HERO.id,
          eligible_action_names: ["借机尾击"],
        },
      },
      explanation: "等待 DM 确认",
      round_number: 1,
      turn_index: 0,
      summary: "黑龙：进入近战威胁范围反应窗口已开放",
      idempotency_key: "window-1",
      dm_override: false,
      override_reason: null,
      status: "confirmed",
      version: 1,
      created_at: NOW,
      updated_at: NOW,
    };
    renderConsole([windowAction], [HERO, ENTERING_REACH_DRAGON]);

    await user.selectOptions(screen.getByRole("combobox", { name: "怪物高级动作" }), "dragon-1:0");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "怪物高级动作目标" })).toHaveValue(HERO.id));
    expect(screen.getByRole("textbox", { name: "怪物反应触发事件" })).toHaveValue("冒险者进入黑龙的近战威胁范围");
    await user.type(screen.getByRole("spinbutton", { name: "怪物高级动作攻击总值" }), "18");
    await user.click(screen.getByRole("button", { name: "DM确认并执行高级动作" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(requestBody(fetchMock.mock.calls[0]?.[1])).toMatchObject({
      action_cost: "reaction",
      target_combatant_id: HERO.id,
      reaction_event: "enters_reach",
      reaction_window_id: "reaction-window-1",
      reaction_trigger: "冒险者进入黑龙的近战威胁范围",
    });
  });

  it("automatically rolls critical damage for a nearby paralyzed target", async () => {
    const user = userEvent.setup();
    vi.spyOn(Math, "random").mockReturnValue(0);
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      (input) => {
        const path = requestUrl(input).pathname;
        if (path.endsWith("/actions/confirm")) {
          return Promise.resolve(new Response(JSON.stringify({
            action: { id: "critical-action-1" },
            actor: { ...CRITICAL_DRAGON, version: 8 },
            target: { ...PARALYZED_HERO, hp: 31, version: 2 },
          }), { status: 200, headers: { "Content-Type": "application/json" } }));
        }
        throw new Error(`unexpected request: ${path}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    renderConsole([CRITICAL_WINDOW], [PARALYZED_HERO, CRITICAL_DRAGON]);

    await user.selectOptions(screen.getByRole("combobox", { name: "怪物高级动作" }), "dragon-1:0");
    await user.selectOptions(screen.getByRole("combobox", { name: "怪物高级动作目标" }), PARALYZED_HERO.id);
    expect(screen.getByText(/本次按暴击自动掷骰：4d8\+5/)).toBeInTheDocument();
    await user.type(screen.getByRole("spinbutton", { name: "怪物高级动作攻击总值" }), "18");
    await user.click(screen.getByRole("button", { name: "DM确认并执行高级动作" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(requestBody(fetchMock.mock.calls[0]?.[1])).toMatchObject({
      critical_hit: true,
      action_window_id: CRITICAL_WINDOW.id,
      amount: 9,
      damage_components: [{ amount: 9, damage_type: "bludgeoning" }],
    });
  });
});
