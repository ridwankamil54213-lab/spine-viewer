// Verify the ws-scrcpy web UI actually shows the Android device and can start
// a stream. A 200 on / proves nothing — the page is a static shell; the device
// list comes from the WebSocket/AJAX layer.
const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:8000/";

(async () => {
  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errs = [];
  page.on("pageerror", (e) => errs.push("pageerror: " + e.message.slice(0, 200)));
  page.on("console", (m) => { if (m.type() === "error") errs.push("console: " + m.text().slice(0, 200)); });

  const resp = await page.goto(BASE, { waitUntil: "networkidle", timeout: 60000 });
  console.log("HTTP:", resp.status());
  await page.waitForTimeout(6000);

  // What does the page think is connected?
  const state = await page.evaluate(() => {
    const txt = document.body.innerText || "";
    const btns = [...document.querySelectorAll("button, a, .device, [class*=device]")]
      .map((e) => (e.innerText || e.getAttribute("title") || "").trim())
      .filter(Boolean);
    return {
      title: document.title,
      hasCanvas: !!document.querySelector("canvas"),
      hasVideo: !!document.querySelector("video"),
      buttons: [...new Set(btns)].slice(0, 25),
      bodyHead: txt.slice(0, 600),
    };
  });
  console.log("title:", state.title);
  console.log("canvas:", state.hasCanvas, "| video:", state.hasVideo);
  console.log("UI teks/tombol:", JSON.stringify(state.buttons));
  console.log("--- cuplikan halaman ---");
  console.log(state.bodyHead);

  await page.screenshot({ path: "/tmp/wsscrcpy-page.png" });
  const fs = require("fs");
  console.log("\nscreenshot:", fs.statSync("/tmp/wsscrcpy-page.png").size, "bytes");

  if (errs.length) console.log("errors:\n" + errs.slice(0, 6).join("\n"));
  await browser.close();
})();
