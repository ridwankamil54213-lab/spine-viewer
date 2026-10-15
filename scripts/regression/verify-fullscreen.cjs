const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";
const id = process.argv[2] || "azurlane-chibi/adaerbote_3";
const [key, stem] = id.split("/");

const rect = (p, s) => p.evaluate((sel) => {
  const e = document.querySelector(sel);
  if (!e) return "absent";
  const r = e.getBoundingClientRect();
  const st = getComputedStyle(e);
  return { display: st.display, hidden: !!e.hidden, vis: st.visibility, w: Math.round(r.width), h: Math.round(r.height), bottom: Math.round(r.bottom) };
}, s);

// transport state: hidden = off-screen (visibility hidden, bottom > viewport)
const tstate = (p) => p.evaluate(() => {
  const e = document.querySelector(".transport");
  const st = getComputedStyle(e);
  const r = e.getBoundingClientRect();
  return { vis: st.visibility, peek: e.classList.contains("fs-peek"), bottom: Math.round(r.bottom), h: Math.round(r.height) };
});

(async () => {
  const b = await chromium.launch({ executablePath: CHROME, args: ["--use-gl=swiftshader", "--no-sandbox", "--disable-dev-shm-usage"] });
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
  const errs = [];
  p.on("pageerror", (e) => errs.push("PAGEERROR: " + e.message));
  await p.goto(URL, { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2500);
  await p.click(`.game[data-key="${key}"]`);
  await p.fill("#search", stem);
  await p.waitForSelector(`.model[data-id="${id}"]`, { timeout: 15000 });
  await p.click(`.model[data-id="${id}"]`);
  await p.waitForTimeout(5000);

  await p.press("body", "f");
  await p.waitForTimeout(1800);
  console.log("fs:", await p.evaluate(() => document.fullscreenElement?.tagName));
  console.log("canvas   :", JSON.stringify(await rect(p, "#canvas-wrap")));
  console.log("topbar   :", JSON.stringify(await rect(p, ".topbar")));
  console.log("sidebar  :", JSON.stringify(await rect(p, ".sidebar")));
  console.log("fs-exit  :", JSON.stringify(await rect(p, "#fs-exit")));

  await p.mouse.move(640, 400); await p.waitForTimeout(700);
  const mid = await tstate(p);
  console.log("kursor tengah:", JSON.stringify(mid), mid.vis === "hidden" && mid.bottom > 800 ? "OK (tersembunyi)" : "FAIL");

  await p.mouse.move(640, 795); await p.waitForTimeout(700);
  const low = await tstate(p);
  console.log("kursor bawah :", JSON.stringify(low), low.vis === "visible" && low.peek ? "OK (muncul)" : "FAIL");

  await p.mouse.move(640, 200); await p.waitForTimeout(800);
  const up = await tstate(p);
  console.log("kursor atas  :", JSON.stringify(up), up.vis === "hidden" ? "OK (sembunyi)" : "FAIL");

  await p.click("#fs-exit");
  await p.waitForTimeout(1200);
  console.log("keluar       :", await p.evaluate(() => document.fullscreenElement?.tagName || null), "| topbar:", JSON.stringify(await rect(p, ".topbar")), "| fs-exit:", JSON.stringify(await rect(p, "#fs-exit")));

  console.log("errors:", errs.length, errs.slice(0, 4));
  await b.close();
})();
