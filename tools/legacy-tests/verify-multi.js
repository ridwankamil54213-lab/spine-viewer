// Multi-model verification: loads a set of REAL game models (not just the demo)
// and reports load/render state for each. Complements smoke-test.js, which is
// hard-wired to the spineboy demo and ignores the MODEL env var.
//
// NOTE: pixel-sampling a Pixi WebGL canvas from page JS returns an empty frame
// (no preserveDrawingBuffer), so "non-blank" is judged by screenshot byte size.
const { chromium } = require("playwright-core");
const fs = require("fs");

const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const URL = process.env.URL || "http://127.0.0.1:3000/";
const OUT = process.env.OUT || "/tmp/spine-multi.json";

// id -> game key, sampled across every game in the library
const MODELS = [
  ["demo", "spineboy"],
  ["demo", "raptor"],
  ["nikke", "777"],
  ["azurlane", "2b_2"],
  ["azurlane-chibi", "22"],
  ["deposegirls", "Spine_Act_GiftAnniversary_zgm"],
  ["projectqt", "1001_Event_CG10"],
  ["lostsword", "lobbyunit/Agravaine"],
  ["alliancesages", "1001"],
  ["alliancesages-cg", "1001_H1"],
  ["arkrecode", "A0001"],
  ["shoujoukaisen", "anheijuntuan01"],
  ["bd2-illust", "avatar/body/avatarbodyaccessory_1006"],
];

(async () => {
  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
  });
  const results = [];

  for (const [game, id] of MODELS) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 200)); });
    page.on("pageerror", (e) => errors.push("pageerror: " + e.message.slice(0, 200)));

    const rec = { game, id, ok: false };
    try {
      await page.goto(URL, { waitUntil: "networkidle", timeout: 60000 });
      await page.waitForSelector(".game", { timeout: 45000 });
      await page.click(`.game[data-key="${game}"]`);
      // The grid paginates at 60/page, so a target model is usually not on
      // page 1. Type its id into the in-game search box to surface it.
      // The library is 11k models, so the list needs real time to re-render
      // after both the game click and the keystroke — polling for the row is
      // far more reliable than a fixed sleep.
      await page.waitForSelector("#search:not([hidden])", { timeout: 30000 });
      await page.fill("#search", id);
      await page.waitForFunction(
        (wanted) => {
          // The list must have settled AND contain our row.
          const first = document.querySelector(".model")?.dataset.id;
          return first === wanted || !!document.querySelector(`.model[data-id="${wanted}"]`);
        },
        id,
        { timeout: 30000 }
      );
      await page.click(`.model[data-id="${id}"]`);
      // wait for either HUD (loaded) or the error banner (failed)
      await page.waitForFunction(
        () => !document.querySelector("#hud").hidden || !document.querySelector("#error").hidden,
        { timeout: 40000 }
      );
      await page.waitForTimeout(3000);

      rec.info = await page.evaluate(() => {
        const canvas = document.querySelector("#canvas-wrap canvas");
        const sp = window.spineStage?.spine;
        const pages = [];
        if (sp) {
          const seen = new Set();
          for (const slot of sp.skeleton.slots) {
            const bt = slot.getAttachment()?.region?.page?.baseTexture;
            if (bt && !seen.has(bt.uid)) {
              seen.add(bt.uid);
              pages.push({ page: slot.getAttachment().region.page?.name, alphaMode: bt.alphaMode });
            }
          }
        }
        return {
          canvas: canvas ? canvas.width + "x" + canvas.height : null,
          loaded: !!sp,
          atlasPages: pages,
          hudModel: document.querySelector("#hud-model")?.textContent,
          hudStats: document.querySelector("#hud-stats")?.innerText,
          animCount: document.querySelector("#anim-select")?.options.length ?? 0,
          errorVisible: !document.querySelector("#error").hidden,
          errorText: document.querySelector("#error")?.innerText?.slice(0, 200),
        };
      });

      const shot = `/tmp/spine-shot-${game.replace(/[^\w]/g, "_")}.png`;
      await page.screenshot({ path: shot });
      rec.shotBytes = fs.statSync(shot).size;
      rec.errors = errors;
      rec.ok = rec.info.loaded && !rec.info.errorVisible && rec.info.animCount > 0 && rec.shotBytes > 60000;
    } catch (e) {
      rec.fatal = String(e.message).split("\n")[0].slice(0, 200);
      rec.errors = errors;
    }
    results.push(rec);
    await page.close();
  }

  await browser.close();
  fs.writeFileSync(OUT, JSON.stringify(results, null, 2));

  console.log(
    "GAME".padEnd(20) + " " + "MODEL".padEnd(38) + " " +
    "LOAD ".padEnd(5) + " " + "ANIM ".padEnd(5) + " " + "PMA  ".padEnd(5) + " " +
    "SHOT".padStart(8) + "  VERDICT"
  );
  for (const r of results) {
    if (r.fatal) {
      console.log(
        r.game.padEnd(20) + " " + r.id.slice(0, 38).padEnd(38) + " " +
        "ERR".padEnd(5) + " " + "-".padEnd(5) + " " + "-".padEnd(5) + " " +
        "-".padStart(8) + "  FATAL: " + r.fatal
      );
      continue;
    }
    const i = r.info;
    const pma = i.atlasPages.length ? i.atlasPages.map(p => p.alphaMode).join(",") : "n/a";
    console.log(
      `${r.game.padEnd(20)} ${r.id.slice(0,38).padEnd(38)} ` +
      `${String(i.loaded).padEnd(5)} ${String(i.animCount).padEnd(5)} ${pma.padEnd(5)} ${String(r.shotBytes).padStart(8)}  ` +
      (r.ok ? "OK" : "GAGAL" + (i.errorVisible ? ` — ${i.errorText}` : ""))
    );
  }
  const ok = results.filter(r => r.ok).length;
  console.log(`\n${ok}/${results.length} model render OK`);
  const noisy = results.filter(r => r.errors?.length);
  if (noisy.length) {
    console.log("\nConsole errors:");
    for (const r of noisy) console.log(`  ${r.game}/${r.id}: ${r.errors.slice(0,2).join(" | ")}`);
  }
  process.exit(ok === results.length ? 0 : 1);
})();
