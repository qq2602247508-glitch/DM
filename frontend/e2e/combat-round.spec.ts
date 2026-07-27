import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { playerUrl } from "../playwright.config";

const apiBase = process.env.E2E_API_URL ?? "http://127.0.0.1:8000/api/v1";
type Json = Record<string, unknown>;

async function ok(response: Awaited<ReturnType<APIRequestContext["post"]>>): Promise<Json> {
  const body = await response.json() as Json;
  expect(response.ok(), `${response.url()} -> ${response.status()} ${JSON.stringify(body)}`).toBe(true);
  return body;
}

async function join(page: Page, code: string): Promise<void> {
  await page.goto(`${playerUrl}/#/player`);
  await expect(page.getByRole("heading", { name: "加入跑团房间" })).toBeVisible();
  await page.getByLabel("房间码").fill(code);
  await page.getByLabel("玩家称呼").fill("战斗验收玩家");
  await page.getByRole("button", { name: "进入房间" }).click();
}

test("玩家端加载当前战斗地图、回合面板、攻击控件和公开日志", async ({ browser, request }) => {
  const campaign = await ok(await request.post(`${apiBase}/campaigns`, {
    data: { name: `战斗 UI 验收-${Date.now()}`, ruleset: "dnd5e", primary_rules_year: 2024 },
  }));
  const campaignId = String(campaign.id);
  const prefix = `${apiBase}/campaigns/${campaignId}`;
  const hero = await ok(await request.post(`${prefix}/characters`, {
    data: {
      name: "战斗验收法师",
      race: "人类",
      class_name: "战士",
      background: "士兵",
      level: 1,
      armor_class: 16,
      hp: 12,
      max_hp: 12,
      speed: 30,
      ability_scores: { strength: 16, dexterity: 12, constitution: 14 },
      actions: [{ name: "长剑", damage: "1d8+3 挥砍", range: "5尺", cost: "动作" }],
    },
  }));
  const scene = await ok(await request.post(`${prefix}/scenes`, {
    data: { name: "战斗验收酒馆", description: "带障碍物的公开测试场景", status: "active" },
  }));
  await ok(await request.post(`${prefix}/scenes/${String(scene.id)}/grid`, {
    data: {
      width: 8,
      height: 6,
      cell_size_ft: 5,
      mode: "combat",
      public_description: "吧台和墙壁",
      layers_json: { cells: [{ row: 2, col: 2, kind: "cover", label: "吧台" }] },
    },
  }));
  await ok(await request.post(`${prefix}/scenes/${String(scene.id)}/participants`, {
    data: { entity_type: "character", entity_id: String(hero.id), role: "present", visible: true },
  }));
  const combat = await ok(await request.post(`${prefix}/combats`, {
    data: { name: "战斗验收遭遇", scene_id: scene.id, status: "active" },
  }));
  const combatId = String(combat.id);
  await ok(await request.post(`${prefix}/combats/${combatId}/combatants`, {
    data: {
      display_name: hero.name,
      entity_type: "character",
      entity_id: hero.id,
      initiative: 20,
      armor_class: 16,
      hp: 12,
      max_hp: 12,
      speed_ft: 30,
      snapshot_json: { grid_position: { row: 4, col: 3 }, actions: hero.actions },
    },
  }));
  await ok(await request.post(`${prefix}/combats/${combatId}/combatants`, {
    data: {
      display_name: "验收地精",
      entity_type: "monster",
      initiative: 10,
      armor_class: 12,
      hp: 7,
      max_hp: 7,
      speed_ft: 30,
      snapshot_json: { grid_position: { row: 4, col: 5 }, actions: [{ name: "短剑", damage: "1d6+2 穿刺" }] },
    },
  }));
  const room = await ok(await request.post(`${prefix}/player-room/open`, { data: { hours: 1 } }));
  await ok(await request.post(`${prefix}/player-room/live-state`, {
    data: { scene_id: scene.id, combat_id: combatId },
  }));
  const player = await browser.newContext();
  try {
    const page = await player.newPage();
    await join(page, String(room.join_code));
    await expect(page.getByRole("heading", { name: "选择或创建你的角色" })).toBeVisible();
    await page.getByRole("button", { name: new RegExp(String(hero.name)) }).click();
    await page.getByRole("button", { name: "绑定所选角色" }).click();
    await expect(page.getByRole("heading", { name: "战斗验收遭遇" })).toBeVisible();
    await expect(page.getByText("玩家战斗地图 · 与 DM 共用当前 Scene", { exact: true })).toBeVisible();
    await expect(page.getByText("8×6 · 每格 5 尺", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "当前战斗面板" })).toBeVisible();
    await expect(page.getByLabel("攻击/技能")).toBeVisible();
    await expect(page.getByLabel("目标")).toBeVisible();
    await expect(page.getByRole("heading", { name: "公开战斗日志" })).toBeVisible();
    const endTurn = page.getByRole("button", { name: "结束我的回合" });
    if (await endTurn.isEnabled()) {
      await endTurn.click();
      await expect(page.getByText("等待其他单位", { exact: true })).toBeVisible();
    }
  } finally {
    await player.close();
    await request.delete(`${apiBase}/campaigns/${campaignId}`, {
      headers: { "If-Match": `"${Number(campaign.version)}"` },
    });
  }
});
