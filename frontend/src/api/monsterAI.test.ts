import { afterEach, describe, expect, it, vi } from "vitest";

import { previewMonsterAI } from "./entities";
import type { MonsterAIPreview } from "./types";

const PREVIEW: MonsterAIPreview = {
  combat: {
    id: "combat-1",
    campaign_id: "campaign-1",
    name: "龙巢",
    scene_id: null,
    status: "active",
    round_number: 2,
    current_turn_index: 1,
    difficulty: null,
    base_xp: 0,
    difficulty_adjustments: [],
    xp_awarded: false,
    started_at: "2026-08-03T00:00:00Z",
    ended_at: null,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: "2026-08-03T00:00:00Z",
    version: 4,
  },
  actor: {
    id: "dragon-1",
    campaign_id: "campaign-1",
    combat_id: "combat-1",
    display_name: "黑龙",
    entity_type: "monster",
    entity_id: "monster-1",
    initiative: 18,
    armor_class: 19,
    hp: 120,
    max_hp: 120,
    temporary_hp: 0,
    max_hp_reduction: 0,
    damage_resistances: [],
    damage_vulnerabilities: [],
    damage_immunities: [],
    condition_immunities: [],
    conditions: [],
    concentration: {},
    speed_ft: 40,
    movement_remaining_ft: 40,
    action_available: true,
    bonus_action_available: true,
    reaction_available: true,
    snapshot_json: {},
    is_active: true,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: "2026-08-03T00:00:00Z",
    version: 7,
  },
  plan: null,
  requires_confirmation: true,
};

function response(): Response {
  return new Response(JSON.stringify(PREVIEW), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): URL {
  if (input instanceof URL) return input;
  return new URL(typeof input === "string" ? input : input.url);
}

function requestBody(init: RequestInit | undefined): Record<string, unknown> {
  if (typeof init?.body !== "string") throw new Error("expected a JSON request body");
  return JSON.parse(init.body) as Record<string, unknown>;
}

describe("monster AI API adapter", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the phase preview endpoint without inventing an empty recharge map", async () => {
    const fetchMock = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(() => Promise.resolve(response()));
    vi.stubGlobal("fetch", fetchMock);

    await previewMonsterAI("campaign-1", "combat-1", "dragon-1", {
      actorVersion: 7,
      phase: "reaction",
      tactics: "tactical",
      reactionEvent: "leaves_reach",
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const request = fetchMock.mock.calls[0];
    if (!request) throw new Error("expected a monster AI preview request");
    const [url, init] = request;
    expect(requestUrl(url).href).toBe(
      "http://127.0.0.1:8000/api/v1/campaigns/campaign-1/combats/combat-1/monster-ai/preview",
    );
    expect(init?.method).toBe("POST");
    expect(requestBody(init)).toEqual({
      actor_combatant_id: "dragon-1",
      actor_version: 7,
      phase: "reaction",
      tactics: "tactical",
      reaction_event: "leaves_reach",
    });
  });

  it("forwards an authoritative persisted recharge map unchanged", async () => {
    const fetchMock = vi.fn<
      (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    >(() => Promise.resolve(response()));
    vi.stubGlobal("fetch", fetchMock);

    await previewMonsterAI("campaign-1", "combat-1", "dragon-1", {
      actorVersion: 7,
      phase: "legendary",
      rechargeAvailable: { "酸液吐息": false, "尾击": true },
    });

    const request = fetchMock.mock.calls[0];
    if (!request) throw new Error("expected a monster AI preview request");
    const [, init] = request;
    expect(requestBody(init)).toMatchObject({
      phase: "legendary",
      recharge_available: { "酸液吐息": false, "尾击": true },
    });
  });
});
