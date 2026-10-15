const { chromium } = require("playwright-core");
const fs = require("fs");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";
const id = process.argv[2];
const [key, stem] = id.split("/");

(async () => {
  const b = await chromium.launch({ executablePath: CHROME, args: ["--use-gl=swiftshader", "--no-sandbox", "--disable-dev-shm-usage"] });
  const p = await b.newPage({ viewport: { width: 1000, height: 800 } });
  const errs = [];
  p.on("pageerror", (e) => errs.push("PAGEERROR: " + e.message));
  p.on("console", (m) => { if (m.type() === "error") errs.push("ERR: " + m.text()); });
  await p.goto(URL, { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2500);
  await p.click(`.game[data-key="${key}"]`);
  await p.fill("#search", stem);
  await p.waitForSelector(`.model[data-id="${id}"]`, { timeout: 15000 });
  await p.click(`.model[data-id="${id}"]`);
  await p.waitForTimeout(9000);
  const st = await p.evaluate(() => ({
    hud: document.querySelector("#hud-model")?.textContent,
    legacy: document.querySelector("#legacy-note") && !document.querySelector("#legacy-note").hidden,
    iframe: !!document.querySelector("iframe"),
    canvas2d: !!document.querySelector("canvas:not([data-pixi])"),
    err: document.querySelector("#error")?.hidden === false ? document.querySelector("#error").querySelector("p")?.textContent : null,
  }));
  const shot = "/tmp/pq21-shot.png";
  await p.screenshot({ path: shot });
  console.log(id, JSON.stringify(st), "| errors:", errs.length, errs.slice(0, 3));
  await b.close();
})();
