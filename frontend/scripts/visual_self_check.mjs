import { chromium } from "playwright";
import path from "path";
import fs from "fs";

const ARTIFACT_DIR = "/Users/inagi/.gemini/antigravity/brain/d81cf6b6-2d35-4b52-9769-122d26684265";
if (!fs.existsSync(ARTIFACT_DIR)) {
  fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
}

async function runVisualSelfCheck() {
  console.log("🚀 Starting Comprehensive Visual & Functional Self-Check...");

  const browser = await chromium.launch({
    headless: true,
    args: [
      "--enable-webgl",
      "--use-gl=angle",
      "--no-sandbox",
      "--disable-setuid-sandbox",
    ],
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });

  const page = await context.newPage();

  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
      console.error("[Browser Console Error]", msg.text());
    }
  });
  page.on("pageerror", (err) => {
    consoleErrors.push(err.message);
    console.error("[Browser Page Error]", err.message);
  });

  try {
    console.log("🌐 Step 1: Navigating to Quick Combat cockpit...");
    await page.goto("http://127.0.0.1:5173/#/quick-combat", { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);

    // If preset button is visible, click it
    const presetBtn = page.locator("button:has-text('一键发起《红落避难所前厅突袭》')");
    if (await presetBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
      console.log("⚡ Creating preset encounter...");
      await presetBtn.click();
      await page.waitForTimeout(2000);
    }

    // Capture 1: Combat Overview with Clean Tabletop
    const shot1 = path.join(ARTIFACT_DIR, "shot_1_combat_overview.png");
    await page.screenshot({ path: shot1, fullPage: true });
    console.log(`📸 Saved: ${shot1}`);

    // Step 2: Test Movement Mode (Reachable Emerald Grid)
    console.log("🏃 Step 2: Testing Movement Mode...");
    const moveBtn = page.locator("button:has-text('🏃 移动走位')");
    if (await moveBtn.isVisible()) {
      await moveBtn.click();
      await page.waitForTimeout(1000);
    }

    const shot2 = path.join(ARTIFACT_DIR, "shot_2_move_range.png");
    await page.screenshot({ path: shot2, fullPage: true });
    console.log(`📸 Saved: ${shot2}`);

    // Step 3: Test Spell Mode & Arcane AoE Highlighting
    console.log("🔮 Step 3: Testing Spells & AoE Range...");
    const spellTab = page.locator("button:has-text('法术书')");
    if (await spellTab.isVisible()) {
      await spellTab.click();
      await page.waitForTimeout(1000);
    }

    const burningHandsBtn = page.locator("button:has-text('燃烧之手')");
    if (await burningHandsBtn.isVisible()) {
      await burningHandsBtn.click();
      await page.waitForTimeout(1000);
    }

    const shot3 = path.join(ARTIFACT_DIR, "shot_3_spell_range.png");
    await page.screenshot({ path: shot3, fullPage: true });
    console.log(`📸 Saved: ${shot3}`);

    // Step 4: Advance turn and test Monster AI Action
    console.log("🤖 Step 4: Testing Turn Advancement & Monster AI Execution...");
    const advanceTurnBtn = page.locator("button:has-text('结束回合'), button:has-text('推进回合')").first();
    if (await advanceTurnBtn.isVisible()) {
      await advanceTurnBtn.click();
      await page.waitForTimeout(1500);
    }

    const shot4 = path.join(ARTIFACT_DIR, "shot_4_monster_turn.png");
    await page.screenshot({ path: shot4, fullPage: true });
    console.log(`📸 Saved: ${shot4}`);

    // If saving throw prompt modal appears, test rolling save
    const rollSaveBtn = page.locator("button:has-text('点击一键投掷豁免骰')");
    if (await rollSaveBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      console.log("🛡️ Step 5: Testing Interactive Saving Throw Modal...");
      const shotSave = path.join(ARTIFACT_DIR, "shot_5_save_modal.png");
      await page.screenshot({ path: shotSave, fullPage: true });
      console.log(`📸 Saved: ${shotSave}`);

      await rollSaveBtn.click();
      await page.waitForTimeout(1500);
    }

    console.log("🎉 Self-Check Finished! Total console errors:", consoleErrors.length);
  } catch (err) {
    console.error("❌ Visual Self-Check Error:", err);
  } finally {
    await browser.close();
  }
}

runVisualSelfCheck();
