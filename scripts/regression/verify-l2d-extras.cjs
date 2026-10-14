const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";
const id = process.argv[2] || "azurlane-l2d/adaerbote_3";
const [key, stem] = id.split("/");

// Sample parameters AT the end of each update frame (the "beforeModelUpdate"
// event fires after motion+blink+breath+physics are applied and before the
// per-frame loadParameters reset), otherwise every read returns the stale value.
const SAMPLER = `
  window.__l2dSampler = (ids, ms) => new Promise((resolve) => {
    const im = window.spineStage.spine.internalModel;
    const cm = im.coreModel;
    const series = {};
    ids.forEach((i) => { series[i] = []; });
    const onUpd = () => {
      ids.forEach((i) => { try { series[i].push(cm.getParameterValueById(i)); } catch {} });
      if (series[ids[0]].length >= 4000) done();
    };
    const done = () => {
      im.off("beforeModelUpdate", onUpd);
      const out = {};
      for (const i of ids) {
        const v = series[i];
        out[i] = v.length ? { n: v.length, min: Math.min(...v), max: Math.max(...v), span: +(Math.max(...v) - Math.min(...v)).toFixed(4) } : null;
      }
      resolve(out);
    };
    im.on("beforeModelUpdate", onUpd);
    setTimeout(done, ms || 6000);
  });
`;

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
  await p.addScriptTag({ content: SAMPLER });

  const info = await p.evaluate(() => {
    const im = window.spineStage?.spine?.internalModel;
    const sel = document.querySelector("#anim-select");
    return {
      extrasHidden: document.querySelector("#l2d-extra")?.hidden,
      optgroups: sel ? [...sel.querySelectorAll("optgroup")].map((g) => [g.label, g.children.length]) : [],
      startAnim: sel?.value,
      hasEyeBlink: !!im?.eyeBlink,
      hasPhysics: !!im?.physics,
      hasBreath: !!im?.breath,
      state: window.__l2d.state(),
    };
  });
  console.log("INFO:", JSON.stringify(info));

  const s = await p.evaluate(() => window.__l2dSampler(
    ["ParamEyeLOpen", "ParamEyeROpen", "ParamAngleX", "ParamBodyAngleX", "L_ParamHairFront1", "L_ParamHairFront2", "L_ParamHairSide1"], 12000));
  console.log("SAMPLE (in-frame):", JSON.stringify(s));

  const eye = Math.min(s.ParamEyeLOpen?.min ?? 9, s.ParamEyeROpen?.min ?? 9);
  console.log("BLINK:", eye < 0.9 ? "OK (min " + eye.toFixed(3) + ")" : "FAIL");
  console.log("BREATH:", (s.ParamAngleX?.span || 0) > 1e-3 ? "OK (span " + s.ParamAngleX.span + ")" : "FAIL");
  const hairMoved = ["L_ParamHairFront1", "L_ParamHairFront2", "L_ParamHairSide1"].filter((k) => (s[k]?.span || 0) > 1e-4);
  console.log("PHYSICS:", hairMoved.length ? "OK " + hairMoved.join(",") : "FAIL");

  // touch: tap the head zone via the debug hook
  const before = await p.evaluate(() => window.__l2d.state());
  await p.evaluate(() => window.__l2d.touchAt(600, 120));
  await p.waitForTimeout(900);
  const after = await p.evaluate(() => ({
    anim: window.__l2d.state().anim,
    group: window.spineStage?.spine?.internalModel?.motionManager?.currentGroup,
    animSel: document.querySelector("#anim-select")?.value,
  }));
  console.log("TOUCH:", JSON.stringify(before.anim), "->", JSON.stringify(after));

  console.log("errors:", errs.length, errs.slice(0, 5));
  await b.close();
})();
