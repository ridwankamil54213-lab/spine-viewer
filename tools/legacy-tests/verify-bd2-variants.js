// Verify the BD2 relayout in the real UI: the "Varian" dropdown must appear
// beside Skin for a character that has variants, and switching must load the
// sibling skeleton.
const { chromium } = require("playwright-core");
const fs = require("fs");
const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const URL = "http://127.0.0.1:3000/";

const CASES = [
  ["bd2", "bd2/char/char000101", 2], // Utama + Cutscene
  ["bd2", "bd2/char/char000502", 3], // Utama + Cutscene + Tersensor
  ["bd2", "bd2/npc/npc000001", 0],   // no variants -> dropdown hidden
];

(async () => {
  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
  });
  let pass = 0;
  for (const [game, id, expectVariants] of CASES) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message.slice(0, 160)));
    try {
      await page.goto(URL, { waitUntil: "networkidle", timeout: 60000 });
      await page.waitForSelector(".game", { timeout: 45000 });
      await page.click(`.game[data-key="${game}"]`);
      await page.waitForSelector("#search:not([hidden])", { timeout: 30000 });
      const leaf = id.split("/").pop();
      await page.fill("#search", leaf);
      await page.waitForFunction(
        (w) => !!document.querySelector(`.model[data-id="${w}"]`), id, { timeout: 30000 }
      );
      await page.click(`.model[data-id="${id}"]`);
      await page.waitForFunction(
        () => !document.querySelector("#hud").hidden || !document.querySelector("#error").hidden,
        { timeout: 40000 }
      );
      await page.waitForTimeout(3000);

      const st = await page.evaluate(() => {
        const vs = document.querySelector("#variant-select");
        return {
          hudModel: document.querySelector("#hud-model")?.textContent,
          variantHidden: vs ? vs.hidden : null,
          variantOptions: vs ? [...vs.options].map((o) => o.value) : [],
          variantValue: vs?.value,
          hasSpine: !!window.spineStage?.spine,
          anim: document.querySelector("#anim-select")?.value,
          error: !document.querySelector("#error").hidden,
        };
      });
      const n = st.variantHidden ? 0 : st.variantOptions.length;
      const ok = st.hasSpine && !st.error && n === expectVariants;
      console.log(
        `${ok ? "OK  " : "FAIL"} ${id.padEnd(34)} varian=${n} (expect ${expectVariants}) ` +
        `opsi=[${st.variantOptions.join(", ")}] hud="${st.hudModel}" anim=${st.anim}`
      );

      // Switching to a non-default variant must actually load it.
      if (!st.variantHidden && st.variantOptions.length > 1) {
        const target = st.variantOptions.find((o) => o !== st.variantValue);
        await page.selectOption("#variant-select", target);
        await page.waitForTimeout(3500);
        const after = await page.evaluate(() => ({
          hudModel: document.querySelector("#hud-model")?.textContent,
          hasSpine: !!window.spineStage?.spine,
          error: !document.querySelector("#error").hidden,
        }));
        const sw = after.hasSpine && !after.error;
        console.log(`     switch -> "${target}": ${sw ? "OK" : "FAIL"} hud="${after.hudModel}"`);
        if (sw) pass++;
      }
      if (ok && (st.variantHidden || st.variantOptions.length <= 1)) pass++;
      if (errors.length) console.log("     pageerror:", errors[0]);
    } catch (e) {
      console.log(`FAIL ${id.padEnd(34)} ${String(e.message).split("\n")[0].slice(0, 110)}`);
    }
    await page.close();
  }
  await browser.close();
  console.log(`\n${pass}/${CASES.length} kasus OK`);
  process.exit(pass === CASES.length ? 0 : 1);
})();
