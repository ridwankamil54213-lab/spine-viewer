const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";

const rect = (p, s) => p.evaluate((sel) => {
  const e = document.querySelector(sel);
  if (!e) return "absent";
  const r = e.getBoundingClientRect();
  const st = getComputedStyle(e);
  return { display: st.display, hidden: !!e.hidden, w: Math.round(r.width), h: Math.round(r.height) };
}, s);

(async () => {
  const b = await chromium.launch({ executablePath: CHROME, args: ["--use-gl=swiftshader", "--no-sandbox", "--disable-dev-shm-usage"] });
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
  const errs = [];
  p.on("pageerror", (e) => errs.push("PAGEERROR: " + e.message));
  await p.goto(URL, { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2500);
  await p.click('.game[data-key="azurlane-chibi"]');
  await p.fill("#search", "adaerbote_3");
  await p.waitForSelector('.model[data-id="azurlane-chibi/adaerbote_3"]', { timeout: 15000 });
  await p.click('.model[data-id="azurlane-chibi/adaerbote_3"]');
  await p.waitForTimeout(6000);

  // enter fullscreen with the F key
  await p.press("body", "f");
  await p.waitForTimeout(1500);
  console.log("fs element:", await p.evaluate(() => document.fullscreenElement?.tagName));
  console.log("canvas   :", JSON.stringify(await rect(p, "#canvas-wrap")));
  console.log("transport:", JSON.stringify(await rect(p, ".transport")));
  console.log("fs-exit  :", JSON.stringify(await rect(p, "#fs-exit")));

  // hover the transport strip -> should expand
  const tb = await p.$(".transport");
  const box = await tb.boundingBox();
  await p.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await p.waitForTimeout(500);
  console.log("transport hover:", JSON.stringify(await rect(p, ".transport")));
  // move away -> collapse
  await p.mouse.move(640, 300);
  await p.waitForTimeout(600);
  console.log("transport away :", JSON.stringify(await rect(p, ".transport")));

  // canvas must still fill the screen after the reflow
  console.log("canvas final:", JSON.stringify(await rect(p, "#canvas-wrap")));

  // exit via the floating button
  await p.click("#fs-exit");
  await p.waitForTimeout(1200);
  console.log("after exit fs:", await p.evaluate(() => document.fullscreenElement?.tagName || null));
  console.log("topbar back :", JSON.stringify(await rect(p, ".topbar")));
  console.log("fs-exit hid :", JSON.stringify(await rect(p, "#fs-exit")));

  console.log("errors:", errs.length, errs.slice(0, 4));
  await b.close();
})();
