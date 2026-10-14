const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";

// usage: node verify-l2d-motion.cjs <game>/<model> [anim]
const id = process.argv[2] || "azurlane-l2d/adaerbote_3";
const anim = process.argv[3] || null;
const [key, stem] = id.split("/");

(async () => {
  const b = await chromium.launch({ executablePath: CHROME, args: ["--use-gl=swiftshader", "--no-sandbox", "--disable-dev-shm-usage"] });
  const p = await b.newPage();
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

  const info = await p.evaluate(() => {
    const im = window.spineStage?.spine?.internalModel;
    const cm = im?.coreModel, mm = im?.motionManager;
    return {
      animOptions: document.querySelector("#anim-select")?.options.length ?? 0,
      defs: mm ? Object.keys(mm.definitions || {}) : null,
      firstGroup: mm ? Object.keys(mm.definitions || {})[0] : null,
      params: cm?._parameterIds?.length ?? null,
    };
  });
  const use = anim || (info.defs && info.defs.includes("idle") ? "idle" : info.firstGroup);
  console.log(`${id}: animasi=${info.animOptions} param=${info.params} grup=${JSON.stringify(info.defs)} -> pakai '${use}'`);

  await p.selectOption("#anim-select", use).catch(() => {});
  await p.waitForTimeout(300);

  // sample all parameters, twice, and count how many moved
  const snap = () => p.evaluate(() => {
    const cm = window.spineStage?.spine?.internalModel?.coreModel;
    const out = {};
    const ids = cm?._parameterIds || [];
    for (let i = 0; i < ids.length; i++) out[ids[i]] = +cm.getParameterValueByIndex(i).toFixed(4);
    return out;
  });
  const a = await snap();
  await p.waitForTimeout(900);
  const c = await snap();
  const moved = Object.keys(a).filter((k) => Math.abs(a[k] - c[k]) > 1e-3).length;
  console.log(`  parameter bergerak: ${moved}/${Object.keys(a).length} | errors: ${errs.length}${errs.length ? " " + errs.slice(0, 3) : ""}`);
  console.log(moved > 0 ? "  ✓ MOTION BERJALAN" : "  ✗ TIDAK BERGERAK");
  await b.close();
})();
