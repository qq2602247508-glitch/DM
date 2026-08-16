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

    // Reset or Preset encounter
    const resetBtn = page.locator("button:has-text('重置战斗')");
    if (await resetBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
      console.log("🔄 Resetting combat...");
      await resetBtn.click();
      await page.waitForTimeout(1500);
    } else {
      const presetBtn = page.locator("button:has-text('一键发起《红落避难所前厅突袭》')");
      if (await presetBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
        console.log("⚡ Creating preset encounter...");
        await presetBtn.click();
        await page.waitForTimeout(2000);
      }
    }

    // Capture 1: Combat Overview with Clean Tabletop
    const shot1 = path.join(ARTIFACT_DIR, "shot_1_combat_overview.png");
    await page.screenshot({ path: shot1, fullPage: true });
    console.log(`📸 Saved: ${shot1}`);

    // Step 2: Test Movement Mode (Clicking 3D Canvas to Move Player)
    console.log("🏃 Step 2: Testing Player Movement on 3D Grid...");
    const canvas = page.locator("canvas").first();
    if (await canvas.isVisible()) {
      const box = await canvas.boundingBox();
      if (box) {
        // Click near the player's reachable green zone (center-left)
        await page.mouse.click(box.x + box.width * 0.38, box.y + box.height * 0.52);
        await page.waitForTimeout(1200);
      }
    }

    const shot2 = path.join(ARTIFACT_DIR, "shot_2_move_range.png");
    await page.screenshot({ path: shot2, fullPage: true });
    console.log(`📸 Saved: ${shot2}`);

    // Step 3: Test Spell Mode & 3D Arcane Trajectory Beam
    console.log("🔮 Step 3: Testing Spells & 3D Trajectory Aiming Beam...");
    const spellTab = page.locator("button:has-text('法术书')");
    if (await spellTab.isVisible()) {
      await spellTab.click();
      await page.waitForTimeout(800);
    }

    const burningHandsBtn = page.locator("button:has-text('燃烧之手')");
    if (await burningHandsBtn.isVisible()) {
      await burningHandsBtn.click();
      await page.waitForTimeout(800);
    }

    // Hover / Click over enemy area in 3D canvas
    if (await canvas.isVisible()) {
      const box = await canvas.boundingBox();
      if (box) {
        // Move mouse to target area to trigger 3D trajectory beam & laser reticle
        await page.mouse.move(box.x + box.width * 0.62, box.y + box.height * 0.45);
        await page.waitForTimeout(600);
        await page.mouse.click(box.x + box.width * 0.62, box.y + box.height * 0.45);
        await page.waitForTimeout(800);
      }
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

    console.log("🎉 Self-Check Finished! Total console errors:", consoleErrors.length);
  } catch (err) {
    console.error("❌ Visual Self-Check Error:", err);
  } finally {
    await browser.close();
  }
}

runVisualSelfCheck();
