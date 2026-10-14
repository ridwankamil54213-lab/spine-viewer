const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";

const SEQ = [
  ["azurlane-l2d", "adaerbote_2"],   // Live2D  -> Live2D  (the double-destroy path)
  ["azurlane-l2d", "adaerbote_3"],   // Live2D  -> Live2D
  ["azurlane-chibi", "adaerbote_3"], // Live2D  -> Spine
  ["azurlane-l2d", "adaerbote_3"],   // Spine   -> Live2D
];

(async () => {
  const b = await chromium.launch({
    executablePath: CHROME,
    args: ["--use-gl=swiftshader", "--no-sandbox", "--disable-dev-shm-usage"],
  });
  const p = await b.newPage();
  const errs = [];
  p.on("console", (m) => { if (m.type() === "error") errs.push("CONSOLE-ERR: " + m.text()); });
  p.on("pageerror", (e) => errs.push("PAGEERROR: " + (e.stack || e.message)));

  await p.goto(URL, { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2500);

  for (const [key, stem] of SEQ) {
    await p.click(`.game[data-key="${key}"]`).catch(() => {});
    await p.fill("#search", stem).catch(() => {});
    await p.waitForSelector(`.model[data-id="${key}/${stem}"]`, { timeout: 15000 }).catch(() => {});
    await p.click(`.model[data-id="${key}/${stem}"]`).catch(() => {});
    await p.waitForTimeout(9000); // let it FULLY load before the next switch
    const st = await p.evaluate(() => {
      const s = window.spineStage;
      return {
        model: s?.model?.id || null,
        tag: s?.spine?.tag || null,
        live2dLoaded: !!s?.spine?.internalModel,
        destroyed: s?.spine?.internalModel?.destroyed ?? null,
        err: document.querySelector("#error")?.hidden === false
          ? document.querySelector("#error").querySelector("p")?.textContent : null,
      };
    });
    console.log(`after ${key}/${stem}:`, JSON.stringify(st));
  }
  const dErr = errs.filter((e) => /reading 'destroy'/.test(e));
  console.log("destroy-errors:", dErr.length);
  for (const e of errs) console.log(e);
  await b.close();
})();
