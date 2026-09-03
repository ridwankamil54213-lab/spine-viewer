/**
 * Verify the "Varian" dropdown works for a game: open a model, read the
 * dropdown options, switch to the second variant, and confirm the loaded
 * model id actually changed.
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const URL = process.env.URL || "http://localhost:3000/";
const OUT = process.env.OUT || "/tmp/spine-shots";
const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome";

const MODELS = (process.env.MODELS ||
  "echocalypse/200000#200000,nikke/c010,catshinobi/Char_10001")
  .split(",");

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto(URL, { waitUntil: "networkidle" });

  const firstKey = MODELS[0].split("/")[0];
  await page.click(`.game[data-key="${firstKey}"]`);
  await page.waitForSelector("#search:not([hidden])", { timeout: 20000 });

  for (const id of MODELS) {
    const short = id.split("/").pop().split("#")[0];
    console.log("\n=== " + id + " ===");

    await page.fill("#search", short);
    try {
      await page.waitForSelector(`.model[data-id="${id}"]`, { timeout: 8000 });
    } catch {
      await page.waitForSelector(`.model[data-id^="${id}"]`, { timeout: 12000 });
    }
    const card =
      (await page.$(`.model[data-id="${id}"]`)) ||
      (await page.$(`.model[data-id^="${id}"]`));
    await card.click();

    await page.waitForFunction(
      () => window.spineStage && window.spineStage.spine && window.spineStage.spine.skeleton,
      { timeout: 25000 }
    );
    await page.waitForTimeout(1200);

    const before = await page.evaluate(() => {
      const w = document.querySelector("#variant-wrap");
      const s = document.querySelector("#variant-select");
      return {
        id: window.spineStage.model && window.spineStage.model.id,
        wrapHidden: w ? w.hidden : null,
        options: s ? [...s.options].map((o) => o.value) : [],
        current: s ? s.value : null,
        title: s ? s.title : null,
      };
    });
    console.log("  id awal   :", before.id);
    console.log("  wrap hidden:", before.wrapHidden);
    console.log("  opsi      :", JSON.stringify(before.options));
    console.log("  terpilih  :", before.current);
    console.log("  title     :", before.title);

    if (!before.options || before.options.length < 2) {
      console.log("  -> TIDAK ada varian (dropdown < 2 opsi)");
      await page.screenshot({ path: path.join(OUT, short + "-novariant.png") });
      continue;
    }

    // Pilih opsi ke-2 lalu konfirmasi model berubah
    const target = before.options[1];
    await page.selectOption("#variant-select", target);
    await page.waitForTimeout(3000);
    const after = await page.evaluate(() => ({
      id: window.spineStage.model && window.spineStage.model.id,
      current: document.querySelector("#variant-select").value,
    }));
    console.log("  pilih     :", target);
    console.log("  id sesudah:", after.id);
    console.log("  BERUBAH   :", after.id !== before.id ? "YA" : "TIDAK");
    await page.screenshot({ path: path.join(OUT, short + "-varian.png") });
  }

  if (errors.length) {
    console.log("\n=== error ===");
    [...new Set(errors)].slice(0, 5).forEach((e) => console.log("  ", e));
  }
  await browser.close();
}

main().catch((e) => {
  console.error("FATAL:", e.message);
  process.exit(1);
});
