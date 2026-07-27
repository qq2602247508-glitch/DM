import { expect, test } from "@playwright/test";

import { dmUrl } from "../playwright.config";

const apiBase = process.env.E2E_API_URL ?? "http://127.0.0.1:8000/api/v1";

test("DM 可从角色详情打开升级向导并看到升级预览入口", async ({ browser, request }) => {
  const campaignResponse = await request.post(`${apiBase}/campaigns`, {
    data: { name: `升级 UI 验收-${Date.now()}`, ruleset: "dnd5e", primary_rules_year: 2024 },
  });
  expect(campaignResponse.ok()).toBe(true);
  const campaign = await campaignResponse.json() as { id: string; version: number };
  const characterResponse = await request.post(`${apiBase}/campaigns/${campaign.id}/characters`, {
    data: {
      name: "升级验收战士",
      race: "人类",
      class_name: "战士",
      background: "士兵",
      level: 1,
      armor_class: 16,
      hp: 12,
      max_hp: 12,
      speed: 30,
      ability_scores: { strength: 16, dexterity: 12, constitution: 14 },
      class_levels: { 战士: 1 },
      experience: 300,
    },
  });
  expect(characterResponse.ok()).toBe(true);
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.addInitScript((campaignId: string) => {
      window.localStorage.setItem("dnd.currentCampaignId", campaignId);
    }, campaign.id);
    await page.goto(`${dmUrl}/#/characters`);
    await expect(page.getByRole("heading", { name: "角色列表" })).toBeVisible();
    await page.getByRole("button", { name: `打开升级验收战士的详细角色卡` }).click();
    await expect(page.getByRole("dialog", { name: "升级验收战士详细角色卡" })).toBeVisible();
    await page.getByRole("button", { name: "升级向导" }).click();
    const sheetDialog = page.getByRole("dialog", { name: "升级验收战士详细角色卡" });
    const dialog = sheetDialog.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("D&D 5e 2024 · 完整职业成长库", { exact: true })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "生成升级预览" })).toBeVisible();
    const classSelect = dialog.getByLabel("本级加入的职业");
    await expect(classSelect).toBeVisible();
    await expect(classSelect.locator("option")).toHaveCount(13);
  } finally {
    await context.close();
    await request.delete(`${apiBase}/campaigns/${campaign.id}`, {
      headers: { "If-Match": `"${campaign.version}"` },
    });
  }
});
