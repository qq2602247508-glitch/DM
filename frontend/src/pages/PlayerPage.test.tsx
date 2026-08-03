import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
        log: [], pending_rolls: [], death_save: null,
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } }))));
    renderPage();

    expect(await screen.findByRole("heading", { name: "酒馆突袭" })).toBeInTheDocument();
    expect(screen.getByText("地精行动中")).toBeInTheDocument();
    expect(screen.getByTestId("player-active-enemy-panel")).toHaveTextContent("地精 · 当前行动单位");
    expect(screen.getByRole("button", { name: "提交攻击并结束回合" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "我的角色" }));
    expect(screen.getByRole("heading", { name: "伊莱娜" })).toBeInTheDocument();
    expect(screen.getByText("法杖")).toBeInTheDocument();
    expect(screen.queryByText(/地精.*AC/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "切换跑团" }));
    const roomCode = screen.getByRole("textbox", { name: "新团房间码" });
    const switchButton = screen.getByRole("button", { name: "确认切换" });
    expect(switchButton).toBeDisabled();
    await userEvent.type(roomCode, "dqsa3e");
    expect(roomCode).toHaveValue("DQSA3E");
    expect(switchButton).toBeEnabled();
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
        pending_rolls: [], death_save: null,
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

  it("offers a next-level request only for a stair already present in the public grid", async () => {
    const snapshot = {
      room: { id: "room-1", status: "active", expires_at: "2026-07-28T00:00:00Z" },
      campaign: { id: "campaign-1", name: "地下城测试", current_time: null },
      player: { id: "session-1", display_name: "玩家甲", character_id: "hero-1" },
      available_characters: [],
      character: {
        id: "hero-1", name: "伊莱娜", race: "精灵", background: "学者",
        class_name: "法师", level: 3, experience: 900, armor_class: 12, speed: 30,
        ability_scores: {}, hp: 16, max_hp: 16, max_hp_reduction: 0,
        death_saves: { successes: 0, failures: 0 }, inventory: [], equipment: [],
        equipment_assets: [], active_attunements: 0, proficiencies: [], skills: {},
        features: [], actions: [], resources: {}, spells: [], spellcasting: {},
        class_levels: { 法师: 3 }, subclass_choices: {}, wallet: null, version: 1,
      },
      table: {
        scene: {
          id: "scene-level-1",
          name: "遗迹第一层",
          description: "你们找到一段向下楼梯。",
          grid: {
            width: 2, height: 2, cell_size_ft: 5,
            cells: [
              { row: 1, col: 1, kind: "floor", label: "地面" },
              { row: 1, col: 2, kind: "stairs", label: "向下楼梯" },
              { row: 2, col: 1, kind: "wall", label: "墙" },
              { row: 2, col: 2, kind: "floor", label: "地面" },
            ],
          },
          tokens: [],
          objects: [],
          available_transitions: [{
            connector_id: "stairs-1",
            direction: "stairs_down",
            label: "通往下一层",
            row: 1,
            col: 2,
            from_scene_id: "scene-level-1",
            target_scene_id: "scene-level-2",
            target_level_index: 2,
            target_level_name: "地下城第 2 层",
          }],
        },
        handouts: [],
        shared_log: [],
        noncombat: { available_actions: [], pending_actions: [] },
      },
      combat: null,
    };
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/player-room/me/action-requests") && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({ id: "request-1" }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }));
      }
      return Promise.resolve(new Response(JSON.stringify(snapshot), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    const requestButton = await screen.findByRole("button", {
      name: /申请前往下一层 · 地下城第 2 层/,
    });
    await userEvent.click(requestButton);

    await waitFor(() => {
      const requestCall = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
      expect(requestCall).toBeDefined();
      const rawBody = requestCall?.[1]?.body;
      expect(typeof rawBody).toBe("string");
      const body = JSON.parse(typeof rawBody === "string" ? rawBody : "{}") as {
        action_type: string;
        payload_json: Record<string, unknown>;
      };
      expect(body).toMatchObject({
        action_type: "site_level_transition",
        payload_json: {
          connector_id: "stairs-1",
        },
      });
    });
  });

  it("shows the latest player-safe guidance and character-specific actions", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      room: { id: "room-1", status: "active", expires_at: "2026-07-28T00:00:00Z" },
      campaign: { id: "campaign-1", name: "暮铃磨坊", current_time: null },
      player: { id: "session-1", display_name: "玩家甲", character_id: "hero-1" },
      available_characters: [],
      character: {
        id: "hero-1", name: "莉亚", race: "人类", background: "艺人", class_name: "吟游诗人",
        level: 1, experience: 0, armor_class: 14, speed: 30, ability_scores: {}, hp: 10, max_hp: 10,
        max_hp_reduction: 0, death_saves: { successes: 0, failures: 0 }, inventory: [], equipment: [],
        equipment_assets: [], active_attunements: 0, proficiencies: [], skills: {}, features: [], actions: [],
        resources: {}, spells: [], spellcasting: {}, class_levels: { 吟游诗人: 1 }, subclass_choices: {},
        wallet: null, version: 1,
      },
      table: {
        scene: { id: "scene-1", name: "提灯旅店", description: "钟声刚刚停下。", grid: null, tokens: [], objects: [], available_transitions: [] },
        handouts: [],
        shared_log: [
          { id: "guide-2", event_type: "player_guidance", title: "场景进入了新的推进节点 · 轮到你们回应", description: "观察门外的动静。\n决定由谁先与店主交谈。", occurred_at: "2026-07-30T10:00:00Z" },
          { id: "log-1", event_type: "session_progress", title: "钟声停止", description: "大厅安静下来。", occurred_at: "2026-07-30T09:59:00Z" },
        ],
        noncombat: {
          available_actions: [
            { id: "skill-perception", kind: "skill", name: "察觉", description: "观察环境", target_types: ["area"] },
            { id: "skill-insight", kind: "skill", name: "洞悉", description: "判断态度", target_types: ["npc"] },
          ],
          pending_actions: [],
        },
      },
      combat: null,
    }), { status: 200, headers: { "Content-Type": "application/json" } }))));
    renderPage();

    const guidance = await screen.findByTestId("player-live-guidance");
    expect(guidance).toHaveTextContent("场景进入了新的推进节点 · 轮到你们回应");
    expect(guidance).toHaveTextContent("观察门外的动静");
    expect(guidance).toHaveTextContent("察觉");
    expect(guidance).toHaveTextContent("洞悉");
    expect(screen.getByRole("heading", { name: "公开游戏日志" }).parentElement).not.toHaveTextContent("轮到你们回应");
  });

  it("sends selected hit dice with a short-rest request", async () => {
    const snapshot = {
      room: { id: "room-1", status: "active", expires_at: "2026-07-28T00:00:00Z" },
      campaign: { id: "campaign-1", name: "短休测试团", current_time: null },
      player: { id: "session-1", display_name: "玩家甲", character_id: "hero-1" },
      available_characters: [],
      character: {
        id: "hero-1", name: "阿莱", race: "人类", background: "士兵", class_name: "战士",
        level: 2, experience: 0, armor_class: 16, speed: 30, ability_scores: {}, hp: 4, max_hp: 18,
        max_hp_reduction: 0, death_saves: { successes: 0, failures: 0 }, inventory: [], equipment: [],
        equipment_assets: [], active_attunements: 0, proficiencies: [], skills: {}, features: [], actions: [],
        resources: {}, spells: [], spellcasting: {}, class_levels: { 战士: 2 }, subclass_choices: {}, wallet: null,
        hit_dice: [{ id: "hit-die-1", key: "hit_dice_d10", label: "d10 生命骰", category: "hit_die", current: 2, maximum: 2, die_size: 10, version: 1 }],
        version: 1,
      },
      table: { scene: null, handouts: [], shared_log: [], noncombat: { available_actions: [], pending_actions: [] } },
      combat: null,
    };
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/player-room/me/action-requests") && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({ id: "request-1" }), { status: 201, headers: { "Content-Type": "application/json" } }));
      }
      return Promise.resolve(new Response(JSON.stringify(snapshot), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    const rollInput = await screen.findByRole("textbox", { name: "d10 生命骰结果" });
    await userEvent.type(rollInput, "6");
    await userEvent.click(screen.getByRole("button", { name: "申请短休 · 1小时" }));

    await waitFor(() => {
      const requestCall = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
      expect(requestCall).toBeDefined();
      const rawBody = requestCall?.[1]?.body;
      expect(typeof rawBody).toBe("string");
      const body = JSON.parse(typeof rawBody === "string" ? rawBody : "{}") as { payload_json: { rest_type: string; hit_dice: unknown[] } };
      expect(body.payload_json).toMatchObject({
        rest_type: "short",
        hit_dice: [{ resource_pool_id: "hit-die-1", roll: 6 }],
      });
    });
  });

  it("opens the current-scene shop and confirms a previewed purchase", async () => {
    const snapshot = {
      room: { id: "room-1", status: "active", expires_at: "2026-07-28T00:00:00Z" },
      campaign: { id: "campaign-1", name: "商店测试团", current_time: null },
      player: { id: "session-1", display_name: "玩家甲", character_id: "hero-1" },
      available_characters: [],
      character: {
        id: "hero-1", name: "阿莱", race: "人类", background: "士兵", class_name: "战士",
        level: 1, experience: 0, armor_class: 16, speed: 30, ability_scores: {}, hp: 10, max_hp: 10,
        max_hp_reduction: 0, death_saves: { successes: 0, failures: 0 }, inventory: [], equipment: [],
        equipment_assets: [], active_attunements: 0, proficiencies: [], skills: {}, features: [], actions: [],
        resources: {}, spells: [], spellcasting: {}, class_levels: { 战士: 1 }, subclass_choices: {},
        wallet: { id: "wallet-1", name: "角色钱包", copper: 100, gp: 1, version: 1 }, version: 1,
      },
      table: {
        scene: { id: "scene-1", name: "月灯杂货铺", description: "货架就在眼前。", grid: null, tokens: [], objects: [], available_transitions: [] },
        shops: [{ merchant_id: "shop-1", name: "月灯老板", description: "欢迎挑选。", stock: [{ id: "stock-1", name: "治疗药水", quantity: 2, price_copper: 25, version: 1, category: "potion", item_tier: "common" }] }],
        handouts: [], shared_log: [], noncombat: { available_actions: [], pending_actions: [] },
      },
      combat: null,
    };
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/player-room/me/commerce/preview") && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({ preview_token: "preview-1", total_copper: 25, wallet_before: 100, wallet_after: 75, stock_before: 2, stock_after: 1 }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      if (url.endsWith("/player-room/me/commerce/confirm") && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({ confirmed: true }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      return Promise.resolve(new Response(JSON.stringify(snapshot), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "商店" }));
    expect(screen.getByRole("heading", { name: "月灯老板" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "预览购买" }));
    expect(await screen.findByRole("heading", { name: "购买预览 · 治疗药水" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "确认购买" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, init]) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        return url.endsWith("/player-room/me/commerce/confirm") && init?.method === "POST";
      })).toBe(true);
    });
  });
});
