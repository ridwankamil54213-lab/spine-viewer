/**
 * Render one model across EVERY animation and EVERY skin, so a defect that
 * only shows in one clip (or under one skin) is not missed.
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const URL = process.env.URL || "http://localhost:3000/";
const OUT = process.env.OUT || "/tmp/skin-shots";
const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome";
const MODEL = process.argv[2];

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
  page.on("pageerror", (e) => errs.push("pageerror: " + e.message));

  await page.goto(URL, { waitUntil: "networkidle" });
  const key = MODEL.split("/")[0];
  await page.click(`.game[data-key="${key}"]`);
  await page.waitForSelector("#search:not([hidden])", { timeout: 20000 });

  const short = MODEL.split("/").pop().split("#")[0];
  await page.fill("#search", short);
  try { await page.waitForSelector(`.model[data-id="${MODEL}"]`, { timeout: 8000 }); }
  catch { await page.waitForSelector(`.model[data-id^="${MODEL}"]`, { timeout: 12000 }); }
  const card = (await page.$(`.model[data-id="${MODEL}"]`)) ||
               (await page.$(`.model[data-id^="${MODEL}"]`));
  await card.click();

  await page.waitForFunction(
    () => window.spineStage && window.spineStage.spine && window.spineStage.spine.skeleton,
    { timeout: 25000 }
  );
  await page.waitForTimeout(1500);

  const meta = await page.evaluate(() => {
    const sp = window.spineStage.spine;
    return {
      id: window.spineStage.model.id,
      anims: (sp.skeleton.data.animations || []).map((a) => a.name),
      skins: (sp.skeleton.data.skins || []).map((s) => s.name),
      slots: (sp.skeleton.slots || []).map((s) => s.data.name),
    };
  });
  console.log("model :", meta.id);
  console.log("anim  :", meta.anims.join(", "));
  console.log("skin  :", meta.skins.join(", "));

  // Untuk tiap kombinasi animasi x skin, simpan screenshot
  for (const anim of meta.anims) {
    for (const skin of meta.skins) {
      // Drive the REAL selects, not the JS objects. Setting state via
      // window.spineStage left the UI dropdowns reading "AVG_Hit" while the
      // canvas showed something else, so every screenshot was mislabelled
      // and two reads of the same file disagreed. selectOption fires the
      // app's own change handlers, which is what we actually want to test.
      await page.selectOption("#skin-select", skin).catch(() => {});
      await page.selectOption("#anim-select", anim).catch(() => {});
      await page.waitForTimeout(700);

      // Confirm the app really switched before shooting.
      const now = await page.evaluate(() => ({
        anim: document.querySelector("#anim-select")?.value,
        skin: document.querySelector("#skin-select")?.value,
      }));
      if (now.anim !== anim || now.skin !== skin) {
        console.log(`  !! LABEL TIDAK SESUAI: minta ${anim}/${skin}, dapat ${now.anim}/${now.skin}`);
      }
      const f = path.join(OUT, `${short}__${anim}__${skin}.png`.replace(/[^\w.-]/g, "_"));
      await page.screenshot({ path: f });
      console.log(`  ${anim} / ${skin} -> ${f}`);
    }
  }

  if (errs.length) {
    console.log("\n=== error ===");
    [...new Set(errs)].slice(0, 8).forEach((e) => console.log("  ", e));
  }
  await browser.close();
}

main().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
