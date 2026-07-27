import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { dmUrl, playerUrl } from "../playwright.config";

const apiBase = process.env.E2E_API_URL ?? "http://127.0.0.1:8000/api/v1";
type Json = Record<string, unknown>;

async function expectOk(response: Awaited<ReturnType<APIRequestContext["post"]>>): Promise<Json> {
  const body = await response.json() as Json;
  expect(response.ok(), `${response.url()} -> ${response.status()} ${JSON.stringify(body)}`).toBe(true);
  return body;
}

async function createFixture(request: APIRequestContext): Promise<{
  campaignId: string;
  campaignVersion: number;
  roomCode: string;
  heroName: string;
  secondHeroName: string;
}> {
  const campaign = await expectOk(await request.post(`${apiBase}/campaigns`, {
    data: {
      name: `浏览器联机验收-${Date.now()}`,
      description: "由 Playwright 自动创建，测试结束后删除。",
      world_setting: "D&D 5e 2024",
      ruleset: "dnd5e",
      primary_rules_year: 2024,
      allow_legacy: false,
    },
  }));
  const campaignId = String(campaign.id);
  const prefix = `${apiBase}/campaigns/${campaignId}`;
  const heroName = "联机验收勇士";
  const hero = await expectOk(await request.post(`${prefix}/characters`, {
    data: {
      name: heroName,
      race: "人类",
      background: "士兵",
      class_name: "战士",
      level: 1,
      armor_class: 16,
      hp: 12,
      max_hp: 12,
      speed: 30,
      ability_scores: {
        strength: 16,
        dexterity: 12,
        constitution: 14,
        intelligence: 10,
        wisdom: 10,
        charisma: 8,
      },
      skills: { 运动: { proficient: true } },
      actions: [{ name: "长剑", damage: "1d8+3 挥砍", range: "5尺", cost: "动作" }],
    },
  }));
  const secondHeroName = "联机验收游侠";
  await expectOk(await request.post(`${prefix}/characters`, {
    data: {
      name: secondHeroName,
      race: "精灵",
      background: "侦察兵",
      class_name: "游侠",
      level: 1,
      armor_class: 14,
      hp: 10,
      max_hp: 10,
      speed: 30,
      ability_scores: {
        strength: 10,
        dexterity: 16,
        constitution: 12,
        intelligence: 10,
        wisdom: 14,
        charisma: 8,
      },
      skills: { 察觉: { proficient: true } },
      actions: [{ name: "长弓", damage: "1d8+3 穿刺", range: "150尺", cost: "动作" }],
    },
  }));
  const scene = await expectOk(await request.post(`${prefix}/scenes`, {
    data: {
      name: "联机验收酒馆",
      description: "DM、玩家1和玩家2共同看到的公开场景。",
      status: "active",
    },
  }));
  await expectOk(await request.post(`${prefix}/scenes/${String(scene.id)}/grid`, {
    data: {
      width: 8,
      height: 6,
      cell_size_ft: 5,
      mode: "exploration",
      public_description: "公开酒馆网格",
      layers_json: { cells: [{ row: 2, col: 2, kind: "cover", label: "吧台" }] },
    },
  }));
  await expectOk(await request.post(`${prefix}/scenes/${String(scene.id)}/participants`, {
    data: { entity_type: "character", entity_id: String(hero.id), role: "present", visible: true },
  }));
  const room = await expectOk(await request.post(`${prefix}/player-room/open`, {
    data: { hours: 1 },
  }));
  await expectOk(await request.post(`${prefix}/player-room/live-state`, {
    data: { scene_id: scene.id, combat_id: null },
  }));
  return {
    campaignId,
    campaignVersion: Number(campaign.version),
    roomCode: String(room.join_code),
    heroName,
    secondHeroName,
  };
}

async function join(page: Page, roomCode: string, displayName: string): Promise<void> {
  await page.goto(`${playerUrl}/#/player`);
  await expect(page.getByRole("heading", { name: "加入跑团房间" })).toBeVisible();
  await page.getByLabel("房间码").fill(roomCode);
  await page.getByLabel("玩家称呼").fill(displayName);
  await page.getByRole("button", { name: "进入房间" }).click();
}

async function bindAvailableCharacter(page: Page, name: string): Promise<void> {
  await expect(page.getByRole("heading", { name: "选择或创建你的角色" })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await page.getByRole("button", { name: "绑定所选角色" }).click();
  await page.getByRole("button", { name: "我的角色" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await page.getByRole("button", { name: "游戏推进" }).click();
}

test.describe("DM 与双玩家房间基础联机", () => {
  test("两个独立玩家 context 加入、绑定角色并同步公开 Scene", async ({ browser, request }) => {
    const fixture = await createFixture(request);
    const dm = await browser.newContext();
    const playerOne = await browser.newContext();
    const playerTwo = await browser.newContext();
    try {
      const dmPage = await dm.newPage();
      await dmPage.addInitScript((campaignId) => {
        window.localStorage.setItem("dnd.currentCampaignId", campaignId);
      }, fixture.campaignId);
      await dmPage.goto(`${dmUrl}/#/game-table`);
      await expect(dmPage.getByRole("heading", { name: "玩家房间" })).toBeVisible();
      await expect(dmPage.getByText("开放中")).toBeVisible();

      const one = await playerOne.newPage();
      await join(one, fixture.roomCode, "玩家一");
      await bindAvailableCharacter(one, fixture.heroName);
      await expect(one.getByRole("heading", { name: "联机验收酒馆" })).toBeVisible();

      const two = await playerTwo.newPage();
      await join(two, fixture.roomCode, "玩家二");
      await bindAvailableCharacter(two, fixture.secondHeroName);
      await expect(two.getByRole("heading", { name: "联机验收酒馆" })).toBeVisible();

      await expect.poll(async () => {
        const text = await dmPage.getByText(/已加入玩家（\d+）/).textContent();
        return text ?? "";
      }).toContain("2");
      await expect(dmPage.getByText("联机验收酒馆", { exact: true })).toBeVisible();
      // 玩家端展示的是 SceneMap 的标题和网格尺寸；public_description
      // 当前仅作为场景数据保存，不在玩家视图直接渲染。
      await expect(one.getByText("玩家场景地图 · 点击绿色目标", { exact: true })).toBeVisible();
      await expect(one.getByText("8×6 · 每格 5 尺", { exact: true })).toBeVisible();
      await expect(two.getByText("玩家场景地图 · 点击绿色目标", { exact: true })).toBeVisible();
      await expect(two.getByText("8×6 · 每格 5 尺", { exact: true })).toBeVisible();
    } finally {
      await Promise.all([dm.close(), playerOne.close(), playerTwo.close()]);
      await request.delete(`${apiBase}/campaigns/${fixture.campaignId}`, {
        headers: { "If-Match": `"${fixture.campaignVersion}"` },
      });
    }
  });
});
