// Loads a sample of Nikke models and checks each one renders with animations.
// Variants (c010/aim, c010/cover) are hidden from the grid now, so they're
// reached through the stage's "Varian" dropdown rather than by searching.
const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";

const SAMPLES = [
  { root: "nikke/c010", variant: null },
  { root: "nikke/c010", variant: "Aim" },
  { root: "nikke/c010", variant: "Cover" },
  { root: "nikke/bsideidol", variant: null },
  { root: "nikke/c402", variant: "Cover" },
];

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME,
    args: ["--no-sandbox","--use-gl=swiftshader","--enable-unsafe-swiftshader","--disable-dev-shm-usage"] });
  const page = await browser.newPage({ viewport: { width: 900, height: 700 } });
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => { if (m.type()==="error") errors.push(m.text()); });
  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForSelector(".game", { timeout: 45000 });
  await page.click('.game[data-key="nikke"]');
  await page.waitForSelector(".model", { timeout: 45000 });

  let okCount = 0;
  for (const s of SAMPLES) {
    const label = s.variant ? `${s.root} [${s.variant}]` : s.root;
    try {
      // grid lists roots only — search for the root and click it
      const leaf = s.root.replace(/^nikke\//, "");
      await page.fill("#search", leaf);
      await page.waitForTimeout(700);
      const found = await page.evaluate(i => !!document.querySelector(`.model[data-id="${i}"]`), s.root);
      if (!found) { console.log(`  FAIL ${label} (root tidak ada di grid)`); continue; }
      await page.evaluate(i => document.querySelector(`.model[data-id="${i}"]`)?.click(), s.root);
      await page.fill("#search", "");
      await page.waitForTimeout(300);
      await page.waitForFunction(() => !document.querySelector("#hud").hidden, { timeout: 40000 });
      await page.waitForTimeout(1800);

      // now switch variant if requested
      if (s.variant) {
        await page.selectOption("#variant-select", { label: s.variant });
        await page.waitForTimeout(2500);
      }

      const info = await page.evaluate(() => ({
        id: window.spineStage?.model?.id,
        hud: document.querySelector("#hud-model")?.textContent,
        anim: document.querySelector("#anim-select")?.options.length,
        stats: document.querySelector("#hud-stats")?.innerText.replace(/\n/g," "),
        err: !document.querySelector("#error").hidden,
      }));
      const ok = !info.err && info.anim > 0;
      if (ok) okCount++;
      console.log(`  ${ok?"OK  ":"FAIL"} ${label.padEnd(26)} hud=${String(info.hud).padEnd(18)} anim=${info.anim}  ${info.stats}`);
    } catch (e) {
      console.log(`  FAIL ${label.padEnd(26)} (${e.message.split("\n")[0]})`);
    }
  }
  console.log("\nerrors:", errors.length ? errors.join(" | ") : "none");
  console.log(`\nBERES ${okCount}/${SAMPLES.length}`);
  await browser.close();
  process.exit(okCount === SAMPLES.length && errors.length === 0 ? 0 : 1);
})();
