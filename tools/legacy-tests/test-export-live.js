// End-to-end export test: drive the real export dialog in a browser and verify
// the server stitches frames with ffmpeg. Capabilities reporting true is not
// proof — this actually POSTs frames and downloads the result.
const { chromium } = require("playwright-core");
const fs = require("fs");
const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const BASE = process.env.URL || "http://127.0.0.1:3000/";

(async () => {
  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message.slice(0, 200)));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text().slice(0, 200)); });

  const caps = await (await fetch(BASE.replace(/\/$/, "") + "/api/export/capabilities")).json();
  console.log("capabilities:", JSON.stringify(caps));
  if (!caps.ffmpeg) { console.log("SKIP: ffmpeg not available"); await browser.close(); process.exit(2); }

  await page.goto(BASE, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForSelector(".game", { timeout: 45000 });
  await page.click('.game[data-key="demo"]');
  await page.waitForSelector('.model[data-id="spineboy"]', { timeout: 30000 });
  await page.click('.model[data-id="spineboy"]');
  await page.waitForFunction(() => !document.querySelector("#hud").hidden, { timeout: 30000 });
  await page.waitForTimeout(2500);

  // open the export dialog
  await page.click("#export-btn");
  await page.waitForTimeout(800);
  const dialogOpen = await page.evaluate(() => {
    const d = document.querySelector("#export-modal");
    return !!d && !d.hidden;
  });
  console.log("export dialog open:", dialogOpen);
  if (!dialogOpen) { console.log("FAIL: dialog did not open"); await browser.close(); process.exit(1); }

  // Keep it small and fast: pick GIF if offered, few frames.
  const chosen = await page.evaluate(() => {
    const fmt = document.querySelector("#export-format");
    if (fmt) {
      const opts = [...fmt.options].map((o) => o.value);
      if (opts.includes("gif")) fmt.value = "gif";
    }
    const fps = document.querySelector("#export-fps");
    if (fps) fps.value = "12";
    const size = document.querySelector("#export-size");
    if (size) {
      const small = [...size.options].map((o) => o.value).sort((a, b) => parseInt(a) - parseInt(b))[0];
      if (small) size.value = small;
    }
    return { format: fmt?.value, fps: fps?.value, size: size?.value };
  });
  console.log("export options:", JSON.stringify(chosen));

  // start export and wait for a download / completion
  const dl = page.waitForEvent("download", { timeout: 120000 }).catch(() => null);
  await page.click("#export-run");
  console.log("export started, waiting…");

  let status = "";
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(2000);
    status = await page.evaluate(() => [document.querySelector("#export-progress-text")?.textContent, document.querySelector("#export-result")?.textContent].filter(Boolean).join(" | ").trim());
    if (/selesai|berhasil|done|download|unduh/i.test(status)) break;
    if (/gagal|error/i.test(status)) break;
  }
  console.log("status text:", JSON.stringify(status.slice(0, 200)));

  const download = await dl;
  if (download) {
    const p = "/tmp/spine-export-test." + (download.suggestedFilename().split(".").pop() || "bin");
    await download.saveAs(p);
    const size = fs.statSync(p).size;
    const head = fs.readFileSync(p).subarray(0, 8);
    console.log(`DOWNLOAD: ${download.suggestedFilename()} -> ${p} (${size} bytes)`);
    console.log("magic:", head.toString("hex"));
    const ok = size > 2000;
    console.log(ok ? "EXPORT TEST: PASS" : "EXPORT TEST: FAIL (file too small)");
    await browser.close();
    process.exit(ok ? 0 : 1);
  }

  // no download event: look for a served file under /exports/
  const href = await page.evaluate(() => {
    const a = [...document.querySelectorAll("a")].map((x) => x.href).filter((h) => /\/exports\//.test(h));
    return a[a.length - 1] || null;
  });
  if (href) {
    const r = await fetch(href);
    const buf = Buffer.from(await r.arrayBuffer());
    console.log(`served file: ${href} -> ${r.status}, ${buf.length} bytes, magic ${buf.subarray(0,8).toString("hex")}`);
    const ok = r.status === 200 && buf.length > 2000;
    console.log(ok ? "EXPORT TEST: PASS" : "EXPORT TEST: FAIL");
    await browser.close();
    process.exit(ok ? 0 : 1);
  }

  console.log("EXPORT TEST: FAIL (no output produced)");
  if (errors.length) console.log("errors:\n" + errors.join("\n"));
  await browser.close();
  process.exit(1);
})();
