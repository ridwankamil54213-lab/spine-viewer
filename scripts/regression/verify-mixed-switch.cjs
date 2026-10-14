const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";

// Cross-game switch mix: Spine -> Spine -> Live2D -> Spine -> Live2D
const SEQ = [
  ["azurlane-chibi", "adaerbote_2"],
  ["azurlane-chibi", "adaerbote_3"],
  ["azurlane-l2d", "adaerbote_2"],
  ["azurlane", "adaerbote_4"],
  ["azurlane-l2d", "adaerbote_3"],
];

(async () => {
  const b = await chromium.launch({ executablePath: CHROME, args: ["--use-gl=swiftshader", "--no-sandbox", "--disable-dev-shm-usage"] });
  const p = await b.newPage();
  const errs = [];
  p.on("console", (m) => { if (m.type() === "error") errs.push("CONSOLE-ERR: " + m.text()); });
  p.on("pageerror", (e) => errs.push("PAGEERROR: " + e.message));
  await p.goto(URL, { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2500);
  for (const [key, stem] of SEQ) {
    // Return to the game list first — the game tiles are not clickable while a
    // model is open, so a bare tile click is a silent no-op.
    await p.click("#back-btn").catch(() => {});
    await p.waitForTimeout(800);
    await p.click(`.game[data-key="${key}"]`).catch(() => {});
    await p.waitForTimeout(1200);
    await p.fill("#search", stem).catch(() => {});
    await p.waitForSelector(`.model[data-id="${key}/${stem}"]`, { timeout: 15000 }).catch(() => {});
    await p.click(`.model[data-id="${key}/${stem}"]`).catch(() => {});
    await p.waitForTimeout(8000);
    const st = await p.evaluate(() => ({
      hud: document.querySelector("#hud-model")?.textContent || null,
      kind: window.spineStage?.spine?.internalModel ? "live2d" : (window.spineStage?.spine ? "spine" : null),
      err: document.querySelector("#error")?.hidden === false
        ? document.querySelector("#error").querySelector("p")?.textContent : null,
    }));
    console.log(`${key}/${stem} ->`, JSON.stringify(st));
  }
  const bad = errs.filter((e) => /reading '|destroy/.test(e));
  console.log("DESTROY/UNDEFINED ERRORS:", bad.length);
  for (const e of errs) console.log(e);
  await b.close();
})();
