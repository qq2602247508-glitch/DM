import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlayerPage } from "./PlayerPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<QueryClientProvider client={client}><PlayerPage /></QueryClientProvider>);
}

describe("PlayerPage", () => {
  it("shows the room-code join gate without querying DM character APIs", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      void input;
      return Promise.resolve(new Response(
        JSON.stringify({ detail: "player session is invalid or expired" }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    expect(await screen.findByRole("heading", { name: "加入跑团房间" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "房间码" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledOnce();
    const firstInput = fetchMock.mock.calls[0]?.[0];
    const requestedUrl = typeof firstInput === "string"
      ? firstInput
      : firstInput instanceof URL
      ? firstInput.href
      : firstInput?.url;
    expect(requestedUrl).toBe("/api/v1/player-room/me");
  });

  it("shows only the bound character and disables actions outside its turn", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      room: { id: "room-1", status: "active", expires_at: "2026-07-28T00:00:00Z" },
      campaign: { id: "campaign-1", name: "深水城之夜", current_time: null },
      player: { id: "session-1", display_name: "玩家甲", character_id: "hero-1" },
      available_characters: [],
      character: {
        id: "hero-1", name: "伊莱娜", race: "精灵", background: "学者",
        class_name: "法师", level: 1, experience: 0, armor_class: 12, speed: 30,
        ability_scores: { strength: 8, dexterity: 14, constitution: 13, intelligence: 15, wisdom: 12, charisma: 10 },
        hp: 7, max_hp: 7, max_hp_reduction: 0, death_saves: { successes: 0, failures: 0 },
        inventory: [], equipment: ["法杖"], proficiencies: ["简易武器"], skills: { 奥秘: { proficient: true } },
        features: ["黑暗视觉"], actions: [{ name: "火焰箭", damage: "1d10 火焰", range: "120尺", cost: "动作" }],
        resources: { spell_slots_1: { label: "1环法术位", current: 2, max: 2 } },
        spells: [], spellcasting: { ability: "智力" }, class_levels: { 法师: 1 },
        subclass_choices: {}, wallet: null, version: 1,
      },
      table: { scene: null, handouts: [], shared_log: [] },
      combat: {
        id: "combat-1", name: "酒馆突袭", status: "active", version: 2,
        round_number: 1, current_turn_index: 0, active_combatant_id: "enemy-1",
        is_my_turn: false, own_combatant_id: "hero-fighter",
        combatants: [
          { id: "enemy-1", version: 1, name: "地精", entity_type: "monster", initiative: 16, position: { row: 1, col: 1 }, health_status: "状态良好", is_own: false },
          { id: "hero-fighter", version: 1, name: "伊莱娜", entity_type: "character", initiative: 12, position: { row: 2, col: 2 }, health_status: "状态良好", is_own: true, hp: 7, max_hp: 7, armor_class: 12, movement_remaining_ft: 30, action_available: true, bonus_action_available: true, reaction_available: true },
        ],
        log: [], pending_rolls: [],
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } }))));
    renderPage();

    expect(await screen.findByRole("heading", { name: "酒馆突袭" })).toBeInTheDocument();
    expect(screen.getByText("等待其他单位")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交攻击并同步结算" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "我的角色" }));
    expect(screen.getByRole("heading", { name: "伊莱娜" })).toBeInTheDocument();
    expect(screen.getByText("法杖")).toBeInTheDocument();
    expect(screen.queryByText(/地精.*AC/)).not.toBeInTheDocument();
  });

  it("marks an ended battle read-only and keeps its public log visible", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      room: { id: "room-1", status: "active", expires_at: "2026-07-28T00:00:00Z" },
      campaign: { id: "campaign-1", name: "深水城之夜", current_time: null },
      player: { id: "session-1", display_name: "玩家甲", character_id: "hero-1" },
      available_characters: [],
      character: {
        id: "hero-1", name: "伊莱娜", race: "精灵", background: "学者",
        class_name: "法师", level: 1, experience: 50, armor_class: 12, speed: 30,
        ability_scores: {}, hp: 7, max_hp: 7, max_hp_reduction: 0,
        death_saves: { successes: 0, failures: 0 }, inventory: [{ name: "联机验收徽记" }],
        equipment: [], proficiencies: [], skills: {}, features: [],
        actions: [{ name: "火焰箭", damage: "1d10 火焰" }], resources: {}, spells: [],
        spellcasting: {}, class_levels: { 法师: 1 }, subclass_choices: {},
        wallet: { name: "角色钱包", copper: 300, gp: 3 }, version: 2,
      },
      table: { scene: null, handouts: [], shared_log: [] },
      combat: {
        id: "combat-1", name: "酒馆突袭", status: "ended", version: 3,
        round_number: 2, current_turn_index: 0, active_combatant_id: null,
        is_my_turn: false, own_combatant_id: "hero-fighter",
        combatants: [
          { id: "hero-fighter", name: "伊莱娜", entity_type: "character", initiative: 12, position: null, health_status: "状态良好", is_own: true },
          { id: "enemy-1", name: "地精", entity_type: "monster", initiative: 8, position: null, health_status: "倒地", is_own: false },
        ],
        log: [{ id: "log-1", summary: "伊莱娜击败了地精", round_number: 2, turn_index: 0, status: "confirmed" }],
        pending_rolls: [],
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } }))));
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "战斗" }));
    expect(screen.getByText("战斗已结束", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("伊莱娜击败了地精")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "结束我的回合" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "我的角色" }));
    expect(screen.getByText("50 XP")).toBeInTheDocument();
    expect(screen.getByText("3 GP")).toBeInTheDocument();
    expect(screen.getByText("联机验收徽记")).toBeInTheDocument();
  });
});
