import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { dmUrl, playerUrl } from "../playwright.config";

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
      width: 20,
      height: 14,
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
  const heroCombatant = await ok(await request.post(`${prefix}/combats/${combatId}/combatants`, {
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
  const enemyCombatant = await ok(await request.post(`${prefix}/combats/${combatId}/combatants`, {
    data: {
      display_name: "验收地精",
      entity_type: "monster",
      initiative: 10,
      armor_class: 12,
      hp: 7,
      max_hp: 7,
      speed_ft: 30,
      snapshot_json: {
        grid_position: { row: 4, col: 5 },
        actions: [
          { name: "短剑", damage: "1d6+2 穿刺", range: "5尺" },
          {
            name: "毒雾爆发",
            damage: "4d6毒素",
            range: "60尺，10尺半径球形",
            save_ability: "constitution",
            save_dc: 13,
          },
        ],
      },
    },
  }));
  const room = await ok(await request.post(`${prefix}/player-room/open`, { data: { hours: 1 } }));
  await ok(await request.post(`${prefix}/player-room/live-state`, {
    data: { scene_id: scene.id, combat_id: combatId },
  }));
  const player = await browser.newContext();
  const dm = await browser.newContext();
  try {
    const page = await player.newPage();
    await page.setViewportSize({ width: 1366, height: 900 });
    await join(page, String(room.join_code));
    await expect(page.getByRole("heading", { name: "选择或创建你的角色" })).toBeVisible();
    await page.getByRole("button", { name: new RegExp(String(hero.name)) }).click();
    await page.getByRole("button", { name: "绑定所选角色" }).click();
    await expect(page.getByRole("heading", { name: "战斗验收遭遇" })).toBeVisible();
    await expect(page.getByText("玩家战斗地图 · 与 DM 共用当前 Scene", { exact: true })).toBeVisible();
    await expect(page.getByText("20×14 · 每格 5 尺", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "当前战斗面板" })).toBeVisible();
    const dmPage = await dm.newPage();
    await dmPage.addInitScript(({ activeCampaignId, activeCombatId }) => {
      window.localStorage.setItem("dnd.currentCampaignId", activeCampaignId);
      window.localStorage.setItem(`dnd-dm-auto-enemies:${activeCampaignId}:${activeCombatId}`, "false");
    }, { activeCampaignId: campaignId, activeCombatId: combatId });
    await dmPage.goto(`${dmUrl}/#/combat`);
    await expect(dmPage.getByRole("heading", { name: "战斗辅助" })).toBeVisible();
    const playerHeroToken = page.locator(`[data-token-id="${String(heroCombatant.id)}"]`);
    const dmHeroToken = dmPage.locator(`[data-token-id="${String(heroCombatant.id)}"]`);
    await expect(playerHeroToken).toHaveAttribute("data-grid-row", "4");
    await expect(playerHeroToken).toHaveAttribute("data-grid-col", "3");
    await expect(dmHeroToken).toHaveAttribute("data-grid-row", "4");
    await expect(dmHeroToken).toHaveAttribute("data-grid-col", "3");
    await page.getByRole("button", { name: "格子 5,3" }).click();
    await expect(playerHeroToken).toHaveAttribute("data-grid-row", "5");
    await expect(playerHeroToken).toHaveAttribute("data-grid-col", "3");
    await expect(dmHeroToken).toHaveAttribute("data-grid-row", "5");
    await expect(dmHeroToken).toHaveAttribute("data-grid-col", "3");
    const sharedCellStyles = await Promise.all([
      page.locator('[data-grid-row="1"][data-grid-col="1"]').evaluate((element) => {
        const style = getComputedStyle(element);
        return { width: element.getBoundingClientRect().width, background: style.backgroundColor };
      }),
      dmPage.locator('[data-grid-row="1"][data-grid-col="1"]').evaluate((element) => {
        const style = getComputedStyle(element);
        return { width: element.getBoundingClientRect().width, background: style.backgroundColor };
      }),
    ]);
    expect(Math.abs(sharedCellStyles[0].width - sharedCellStyles[1].width)).toBeLessThanOrEqual(1);
    expect(sharedCellStyles[0].background).toBe(sharedCellStyles[1].background);
    const dimensions = await page.evaluate(() => {
      const panelHeading = Array.from(document.querySelectorAll("h2"))
        .find((element) => element.textContent?.trim() === "当前战斗面板");
      const mapTitle = Array.from(document.querySelectorAll("strong"))
        .find((element) => element.textContent?.trim() === "玩家战斗地图 · 与 DM 共用当前 Scene");
      const sidebarElement = panelHeading?.closest<HTMLElement>("aside") ?? null;
      const layoutElement = sidebarElement?.parentElement ?? null;
      const mapElement = mapTitle?.parentElement?.parentElement ?? null;
      const sidebarRect = sidebarElement?.getBoundingClientRect();
      const mapGrid = mapElement?.querySelector<HTMLElement>(".grid.w-max");
      return {
        viewportWidth: document.documentElement.clientWidth,
        layoutVisible: Boolean(layoutElement && layoutElement.getBoundingClientRect().height > 0),
        sidebarVisible: Boolean(sidebarElement && sidebarElement.getBoundingClientRect().height > 0),
        mapVisible: Boolean(mapElement && mapElement.getBoundingClientRect().height > 0),
        sidebarWidth: sidebarRect?.width ?? 0,
        sidebarRight: sidebarRect?.right ?? Number.POSITIVE_INFINITY,
        mapGridWidth: mapGrid?.getBoundingClientRect().width ?? 0,
      };
    });
    expect(dimensions.layoutVisible).toBe(true);
    expect(dimensions.sidebarVisible).toBe(true);
    expect(dimensions.mapVisible).toBe(true);
    expect(dimensions.sidebarWidth).toBeGreaterThanOrEqual(320);
    expect(dimensions.sidebarRight).toBeLessThanOrEqual(dimensions.viewportWidth);
    // 20 × 48px cells plus 19 one-pixel grid gaps.
    expect(dimensions.mapGridWidth).toBeLessThanOrEqual(980);
    const stableMapTop = (await page.getByTestId("player-combat-map").boundingBox())?.y;
    expect(stableMapTop).toBeDefined();
    await ok(await request.patch(`${prefix}/combats/${combatId}/combatants/${String(enemyCombatant.id)}`, {
      headers: { "If-Match": `"${Number(enemyCombatant.version)}"` },
      data: {
        movement_remaining_ft: 25,
        snapshot_json: {
          grid_position: { row: 4, col: 6 },
          actions: [
            { name: "短剑", damage: "1d6+2 穿刺", range: "5尺" },
            {
              name: "毒雾爆发",
              damage: "4d6毒素",
              range: "60尺，10尺半径球形",
              save_ability: "constitution",
              save_dc: 13,
            },
          ],
        },
      },
    }));
    await expect.poll(async () => page.evaluate(async () => {
      const response = await fetch("/api/v1/player-room/me");
      const snapshot = await response.json() as {
        combat?: { log?: Array<{ actor_name?: string; action_type?: string }> };
      };
      return snapshot.combat?.log?.some(
        (entry) => entry.actor_name === "验收地精" && entry.action_type === "move",
      ) ?? false;
    })).toBe(true);
    await expect(page.getByTestId("player-enemy-action-banner")).toContainText("验收地精");
    await expect(page.getByTestId("player-enemy-action-banner")).toContainText("移动");
    await expect.poll(async () => (await page.getByTestId("player-combat-map").boundingBox())?.y)
      .toBe(stableMapTop);
    await expect(page.getByLabel("攻击/技能")).toBeVisible();
    await expect(page.getByLabel("目标")).toBeVisible();
    await expect(page.getByRole("heading", { name: "公开战斗日志" })).toBeVisible();
    const endTurn = page.getByRole("button", { name: "结束我的回合" });
    if (await endTurn.isEnabled()) {
      await endTurn.click();
      await expect(page.getByText("验收地精行动中", { exact: true })).toBeVisible();
      await expect(page.getByTestId("player-active-enemy-panel")).toContainText("验收地精 · 当前行动单位");
      const currentFightersResponse = await request.get(`${prefix}/combats/${combatId}/combatants`);
      const currentFighters = await currentFightersResponse.json() as { items: Json[] };
      const currentEnemy = currentFighters.items.find((item) => item.id === enemyCombatant.id);
      const currentHero = currentFighters.items.find((item) => item.id === heroCombatant.id);
      expect(currentEnemy).toBeTruthy();
      expect(currentHero).toBeTruthy();
      await ok(await request.post(`${prefix}/combats/${combatId}/actions/player-rolls/pending`, {
        headers: { "X-Request-ID": `e2e-danger-area-${Date.now()}` },
        data: {
          actor_combatant_id: currentEnemy?.id,
          actor_version: currentEnemy?.version,
          target_combatant_id: currentHero?.id,
          target_version: currentHero?.version,
          action_name: "毒雾爆发",
          resolution_type: "saving_throw",
          dc: 13,
          ability: "constitution",
          damage_on_failure: 14,
          damage_on_success: 7,
          damage_type: "毒素",
          description: "验收地精向战斗验收法师释放一团扩散毒雾。",
        },
      }));
      await expect(page.getByTestId("player-pending-roll")).toContainText("验收地精 对你使用「毒雾爆发」");
      await expect(page.getByTestId("player-pending-roll")).toContainText("失败将承受 14 点毒素伤害");
      await expect(page.getByText("红色描边：敌方技能影响范围", { exact: true })).toBeVisible();
      await expect.poll(async () => page.locator("button.outline-red-500").count()).toBeGreaterThan(1);
    }
  } finally {
    await Promise.all([player.close(), dm.close()]);
    await request.delete(`${apiBase}/campaigns/${campaignId}`, {
      headers: { "If-Match": `"${Number(campaign.version)}"` },
    });
  }
});

test("玩家火球术先结算范围内全部目标再切换回合", async ({ browser, request }) => {
  const campaign = await ok(await request.post(`${apiBase}/campaigns`, {
    data: { name: `火球术多目标验收-${Date.now()}`, ruleset: "dnd5e", primary_rules_year: 2024 },
  }));
  const campaignId = String(campaign.id);
  const prefix = `${apiBase}/campaigns/${campaignId}`;
  const hero = await ok(await request.post(`${prefix}/characters`, {
    data: {
      name: "十二级验收法师",
      race: "人类",
      class_name: "法师",
      background: "学者",
      level: 12,
      armor_class: 15,
      hp: 70,
      max_hp: 70,
      speed: 30,
      ability_scores: { intelligence: 20, dexterity: 14, constitution: 14 },
      actions: [{
        name: "火球术",
        cost: "动作",
        range: "150尺，20尺半径球形",
        damage: "8d6火焰",
        save_ability: "dexterity",
        save_dc: 17,
        half_damage_on_save: true,
      }],
    },
  }));
  const scene = await ok(await request.post(`${prefix}/scenes`, {
    data: { name: "火球术试验场", description: "三只敌人聚集在法术爆发范围内", status: "active" },
  }));
  await ok(await request.post(`${prefix}/scenes/${String(scene.id)}/grid`, {
    data: {
      width: 20,
      height: 10,
      cell_size_ft: 5,
      mode: "combat",
      public_description: "空旷法术试验场",
      layers_json: { cells: [] },
    },
  }));
  const combat = await ok(await request.post(`${prefix}/combats`, {
    data: { name: "火球术三目标战斗", scene_id: scene.id, status: "active" },
  }));
  const combatId = String(combat.id);
  await ok(await request.post(`${prefix}/combats/${combatId}/combatants`, {
    data: {
      display_name: hero.name,
      entity_type: "character",
      entity_id: hero.id,
      initiative: 20,
      armor_class: 15,
      hp: 70,
      max_hp: 70,
      speed_ft: 30,
      snapshot_json: { grid_position: { row: 5, col: 2 }, actions: hero.actions },
    },
  }));
  for (const [index, position] of [[5, 15], [5, 16], [6, 15]].entries()) {
    await ok(await request.post(`${prefix}/combats/${combatId}/combatants`, {
      data: {
        display_name: `火球目标${index + 1}`,
        entity_type: "monster",
        initiative: 10 - index,
        armor_class: 13,
        hp: 60,
        max_hp: 60,
        speed_ft: 30,
        snapshot_json: {
          grid_position: { row: position[0], col: position[1] },
          ability_scores: { dexterity: 10 },
        },
      },
    }));
  }
  const room = await ok(await request.post(`${prefix}/player-room/open`, { data: { hours: 1 } }));
  await ok(await request.post(`${prefix}/player-room/live-state`, {
    data: { scene_id: scene.id, combat_id: combatId },
  }));
  const player = await browser.newContext();
  try {
    const page = await player.newPage();
    await page.setViewportSize({ width: 1366, height: 900 });
    await join(page, String(room.join_code));
    await page.getByRole("button", { name: new RegExp(String(hero.name)) }).click();
    await page.getByRole("button", { name: "绑定所选角色" }).click();
    await expect(page.getByRole("heading", { name: "火球术三目标战斗" })).toBeVisible();
    await page.getByLabel("攻击/技能").selectOption("火球术");
    await page.getByRole("button", { name: /格子 5,15 · 火球目标1/ }).click();
    await expect(page.getByRole("button", { name: "提交玩家伤害骰并结算 3 个目标" })).toBeVisible();
    await page.getByLabel("伤害骰最终总值").fill("28");
    await page.getByRole("button", { name: "提交玩家伤害骰并结算 3 个目标" }).click();
    const resolution = page.getByTestId("player-last-resolution");
    await expect(resolution).toContainText("火球术已完成全部 3 个目标的结算");
    await expect(resolution).toContainText("火球目标1");
    await expect(resolution).toContainText("火球目标2");
    await expect(resolution).toContainText("火球目标3");
    await expect(resolution).toContainText("回合已切换至 火球目标1");
  } finally {
    await player.close();
    await request.delete(`${apiBase}/campaigns/${campaignId}`, {
      headers: { "If-Match": `"${Number(campaign.version)}"` },
    });
  }
});
