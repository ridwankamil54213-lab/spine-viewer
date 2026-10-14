const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";
const id = process.argv[2];
const [key, stem] = id.split("/");

async function open(p, id, key, stem) {
  await p.click("#back-btn").catch(() => {});
  await p.waitForTimeout(600);
  await p.click(`.game[data-key="${key}"]`).catch(() => {});
  await p.waitForTimeout(800);
  await p.fill("#search", stem).catch(() => {});
  await p.waitForSelector(`.model[data-id="${id}"]`, { timeout: 15000 }).catch(() => {});
  await p.click(`.model[data-id="${id}"]`).catch(() => {});
  await p.waitForTimeout(8000);
}

(async () => {
  const b = await chromium.launch({ executablePath: CHROME, args: ["--use-gl=swiftshader", "--no-sandbox", "--disable-dev-shm-usage"] });
  const p = await b.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push("PAGEERROR: " + e.message));
  p.on("console", (m) => { if (m.type() === "error") errs.push("ERR: " + m.text()); });

  await p.goto(URL, { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2500);

  // Live2D extra model: girlwars (tapXiong/tapPigu rods) + live-off check
  await open(p, id, key, stem);
  const info = await p.evaluate(() => {
    const sel = document.querySelector("#anim-select");
    const im = window.spineStage?.spine?.internalModel;
    return {
      id: window.spineStage?.model?.id,
      kind: im ? "live2d" : "spine",
      extrasHidden: document.querySelector("#l2d-extra")?.hidden,
      options: sel?.options.length,
      groups: sel ? [...sel.querySelectorAll("optgroup")].map((g) => g.label) : [],
      hasEyeBlink: !!im?.eyeBlink, hasPhysics: !!im?.physics,
      state: window.__l2d.state(),
    };
  });
  console.log("MODEL:", JSON.stringify(info));

  // toggle "Hidup" off -> operators must be detached
  await p.click("#l2d-live-btn");
  await p.waitForTimeout(400);
  const off = await p.evaluate(() => {
    const im = window.spineStage?.spine?.internalModel;
    return { live: window.__l2d.state().live, eyeBlink: !!im?.eyeBlink, physics: !!im?.physics, breath: !!im?.breath };
  });
  console.log("HIDUP off ->", JSON.stringify(off));
  await p.click("#l2d-live-btn");
  await p.waitForTimeout(300);
  const on = await p.evaluate(() => {
    const im = window.spineStage?.spine?.internalModel;
    return { live: window.__l2d.state().live, eyeBlink: !!im?.eyeBlink, physics: !!im?.physics, breath: !!im?.breath };
  });
  console.log("HIDUP on  ->", JSON.stringify(on));

  // Spine model: extras must be hidden and nothing must throw
  await open(p, "azurlane-chibi/adaerbote_3", "azurlane-chibi", "adaerbote_3");
  const spine = await p.evaluate(() => ({
    id: window.spineStage?.model?.id,
    kind: window.spineStage?.spine?.internalModel ? "live2d" : "spine",
    extrasHidden: document.querySelector("#l2d-extra")?.hidden,
  }));
  console.log("SPINE:", JSON.stringify(spine));
  await p.press("body", "l").catch(() => {});
  await p.waitForTimeout(500);

  console.log("errors:", errs.length, errs.slice(0, 6));
  await b.close();
})();
