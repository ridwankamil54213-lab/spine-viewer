/**
 * Render-test models from ANY game and save screenshots for both PMA modes.
 * Pass model ids like "pokerfate/1001_1"; the game key is derived from them.
 *
 * smoke-test.js is hard-wired to spineboy (it clicks .model[data-id=spineboy])
 * so it cannot verify a real model -- this one drives the UI per model:
 * click the game tile, type the id into #search, click the matching card.
 *
 * Usage:
 *   node scripts/verify-models.js [modelId...]
 * Defaults to a few representative models across the naming families
 * (Char_*, Char_SD_* chibi, cat_battle_mode_*, monster_LD_*).
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const URL = process.env.URL || "http://localhost:3000/";
const OUT = process.env.OUT || "/tmp/spine-shots";
const DEFAULT_MODELS = [
  "catshinobi/Char_10001",
  "catshinobi/Char_SD_10001",
  "catshinobi/cat_battle_mode_32001",
  "catshinobi/monster_LD_5012",
];

const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome";

async function main() {
  const models = process.argv.slice(2).length ? process.argv.slice(2) : DEFAULT_MODELS;
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push("console: " + m.text());
  });

  await page.goto(URL, { waitUntil: "networkidle" });

  // 1. Open the game. Derive the key from the first model id so the script
  //    works for ANY game, not just the one it was first written for.
  const firstKey = models[0].split("/")[0];
  console.log("game key:", firstKey);
  await page.click(`.game[data-key="${firstKey}"]`);
  await page.waitForSelector("#search:not([hidden])", { timeout: 20000 });

  for (const id of models) {
    const short = id.split("/").pop().split("#")[0];
    console.log("\n=== " + id + " ===");

    // Type the model id into search (grid paginates at 60/page).
    // An id may be given WITHOUT the "#stem" suffix the server uses for
    // several models sharing one folder — search by the bare folder name
    // and accept whichever card matches it.
    await page.fill("#search", short);
    try {
      await page.waitForSelector(`.model[data-id="${id}"]`, { timeout: 8000 });
    } catch {
      await page.waitForSelector(
        `.model[data-id^="${id}"]`,
        { timeout: 12000 }
      );
    }
    const card = await page.$(`.model[data-id="${id}"]`) ||
                 await page.$(`.model[data-id^="${id}"]`);
    await card.click();

    // 3. Wait for the skeleton to actually load
    try {
      await page.waitForFunction(
        () => window.spineStage && window.spineStage.spine && window.spineStage.spine.state,
        { timeout: 25000 }
      );
    } catch (e) {
      console.log("  GAGAL load skeleton:", e.message);
      await page.screenshot({ path: path.join(OUT, short + "-FAIL.png") });
      continue;
    }

    // The HUD label lags one model behind (it is written before the next
    // load settles), so wait until it actually matches this model before
    // reading state or screenshotting -- otherwise every shot is the
    // PREVIOUS model and the whole run proves nothing.
    try {
      await page.waitForFunction(
        (want) =>
          window.spineStage &&
          window.spineStage.spine &&
          window.spineStage.spine.skeleton &&
          window.spineStage.model &&
          String(window.spineStage.model.id || "").endsWith(want),
        short,
        { timeout: 20000 }
      );
    } catch (e) {
      console.log("  WARNING: model id tidak settle:", e.message);
    }
    await page.waitForTimeout(600);

    const info = await page.evaluate(() => {
      const st = window.spineStage;
      const sp = st.spine;
      const sk = sp && sp.skeleton;
      // pixi-spine exposes skeleton.data.animations / .skins; `state` is the
      // AnimationState wrapper and has no .data on some versions.
      let animations = [];
      let skins = [];
      try {
        if (sk && sk.data) {
          animations = (sk.data.animations || []).map((a) => a.name || String(a));
          skins = (sk.data.skins || []).map((s) => s.name || String(s));
        }
      } catch (e) {
        animations = ["ERR " + e.message];
      }
      return {
        hudModel: (document.querySelector("#hud-model") || {}).textContent || null,
        animations,
        skins,
        pma: {
          active: st.pma && st.pma.active,
          mode: st.pma && st.pma.mode,
          source: st.pma && st.pma.source,
          gamePmaDefault: st.pma && st.pma.gamePmaDefault,
          atlasSaysPMA: st.pma && st.pma.atlasSaysPMA,
        },
        worldSpan: (() => {
          try {
            const b = sk && sk.getBoundsRect ? sk.getBoundsRect() : null;
            return b ? { w: Math.round(b.width), h: Math.round(b.height) } : null;
          } catch (e) {
            return null;
          }
        })(),
      };
    });
    console.log("  hudModel   :", info.hudModel);
    console.log("  animasi    :", info.animations.slice(0, 8).join(", ") || "(none)");
    console.log("  skin       :", info.skins.join(", ") || "(none)");
    console.log("  pma        :", JSON.stringify(info.pma));
    console.log("  worldSpan  :", JSON.stringify(info.worldSpan));

    // 4. Screenshot in the current (auto) mode
    await page.waitForTimeout(1200);
    const autoShot = path.join(OUT, short + "-auto.png");
    await page.screenshot({ path: autoShot });
    console.log("  shot       :", autoShot, fs.statSync(autoShot).size, "bytes");

    // 5. Flip PMA via the UI selector, if present, and shoot again
    const hasPma = await page.$("#pma-select");
    if (hasPma) {
      for (const want of ["on", "off"]) {
        try {
          await page.selectOption("#pma-select", want);
          await page.waitForTimeout(1000);
          const p = path.join(OUT, `${short}-pma-${want}.png`);
          await page.screenshot({ path: p });
          const st = await page.evaluate(() => ({
            active: window.spineStage.pma.active,
            mode: window.spineStage.pma.mode,
          }));
          console.log(`  pma=${want}   :`, JSON.stringify(st), fs.statSync(p).size, "bytes");
        } catch (e) {
          console.log(`  pma=${want}   : gagal -`, e.message);
        }
      }
    } else {
      console.log("  pma select  : tidak ada #pma-select");
    }
  }

  if (errors.length) {
    console.log("\n=== error browser ===");
    for (const e of [...new Set(errors)].slice(0, 15)) console.log("  ", e);
  }

  await browser.close();
  console.log("\nscreenshot di:", OUT);
}

main().catch((e) => {
  console.error("FATAL:", e);
  process.exit(1);
});
