const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";

(async () => {
  const b = await chromium.launch({ executablePath: CHROME, args: ["--use-gl=swiftshader", "--no-sandbox", "--disable-dev-shm-usage"] });
  const p = await b.newPage();
  p.on("pageerror", (e) => console.log("PAGEERROR STACK:\n" + (e.stack || e.message)));
  await p.goto(URL, { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2500);
  await p.click('.game[data-key="dotabyss-l2d"]');
  await p.fill("#search", "l2d_10010100012");
  await p.waitForSelector('.model[data-id="dotabyss-l2d/l2d_10010100012"]', { timeout: 15000 });
  await p.click('.model[data-id="dotabyss-l2d/l2d_10010100012"]');
  await p.waitForTimeout(8000);
  console.log("== toggle PMA ==");
  await p.selectOption("#pma-select", "on").catch(() => {});
  await p.waitForTimeout(1500);
  await p.selectOption("#pma-select", "off").catch(() => {});
  await p.waitForTimeout(1500);
  console.log("== toggle inspector ==");
  await p.press("body", "i").catch(() => {});
  await p.waitForTimeout(1500);
  await b.close();
})();
