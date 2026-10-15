const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";

async function shot(p, path) {
  // hide every overlay so only the model + backdrop remain
  await p.evaluate(() => {
    for (const s of ["#hud", "#fps-meter", ".fs-exit", ".transport", "#error", "#loading", "#legacy-note"]) {
      const e = document.querySelector(s);
      if (e) e.style.visibility = "hidden";
    }
  });
  await p.waitForTimeout(300);
  await p.screenshot({ path });
  await p.evaluate(() => {
    for (const s of ["#hud", "#fps-meter", ".fs-exit", ".transport", "#error", "#loading", "#legacy-note"]) {
      const e = document.querySelector(s);
      if (e) e.style.visibility = "";
    }
  });
}

(async () => {
  const b = await chromium.launch({ executablePath: CHROME, args: ["--use-gl=swiftshader", "--no-sandbox", "--disable-dev-shm-usage"] });
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
  await p.goto(URL, { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2500);
  await p.click('.game[data-key="azurlane-chibi"]');
  await p.fill("#search", "adaerbote_3");
  await p.waitForSelector('.model[data-id="azurlane-chibi/adaerbote_3"]', { timeout: 15000 });
  await p.click('.model[data-id="azurlane-chibi/adaerbote_3"]');
  await p.waitForTimeout(6000);
  await shot(p, "/tmp/fs-normal.png");
  await p.press("body", "f");
  await p.waitForTimeout(2600);
  await shot(p, "/tmp/fs-full.png");
  console.log("shots done");
  await b.close();
})();
