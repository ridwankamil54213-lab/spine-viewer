/**
 * Screenshot the game grid (the top-level page) to verify each game card
 * renders its icon instead of the letter badge.
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const URL = process.env.URL || "http://localhost:3000/";
const OUT = "/tmp/cs-verify";
const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome";

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  await page.goto(URL, { waitUntil: "networkidle" });
  await page.waitForSelector(".game", { timeout: 15000 });
  await page.waitForTimeout(1500);

  const cards = await page.evaluate(() => {
    return [...document.querySelectorAll(".game")].map((g) => {
      const img = g.querySelector("img.game-icon, .game-icon img, img");
      return {
        key: g.getAttribute("data-key"),
        label: (g.querySelector(".game-label, .game-name") || {}).textContent || null,
        hasImg: !!img,
        imgSrc: img ? img.getAttribute("src") : null,
        // naturalWidth is 0 when the image failed to load
        imgW: img ? img.naturalWidth : null,
        imgH: img ? img.naturalHeight : null,
      };
    });
  });

  console.log("=== kartu game ===");
  for (const c of cards) {
    const ok = c.imgW > 0 ? "ICON OK" : c.hasImg ? "ICON GAGAL LOAD" : "TANPA ICON";
    console.log(
      `  ${String(c.key).padEnd(18)} ${ok.padEnd(16)} ${c.imgSrc || ""} (${c.imgW}x${c.imgH})`
    );
  }

  await page.screenshot({ path: path.join(OUT, "game-grid.png") });
  console.log("\nscreenshot:", path.join(OUT, "game-grid.png"));
  await browser.close();
}

main().catch((e) => {
  console.error("FATAL:", e);
  process.exit(1);
});
