const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome";
const URL = "http://127.0.0.1:3000/";
const id = process.argv[2] || "azurlane-l2d/adaerbote_3";
const [key, stem] = id.split("/");

const readUI = (p) => p.evaluate(() => ({
  cur: document.querySelector("#time-cur")?.textContent,
  dur: document.querySelector("#time-dur")?.textContent,
  scrub: document.querySelector("#scrub")?.value,
  t: window.__l2d.state().time,
  d: window.__l2d.state().duration,
  anim: window.__l2d.state().anim,
}));

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
  await p.waitForTimeout(8000);

  // wait until the idle motion is actually queued, then watch the clock advance
  await p.selectOption("#anim-select", "idle").catch(() => {});
  await p.waitForTimeout(1200);
  const a = await readUI(p);
  await p.waitForTimeout(1500);
  const c = await readUI(p);
  console.log("t0:", JSON.stringify(a));
  console.log("t1:", JSON.stringify(c));
  const advanced = a.t != null && c.t != null && c.t > a.t + 0.5;
  console.log("WAKTU JALAN:", advanced ? "OK (" + a.t.toFixed(2) + " -> " + c.t.toFixed(2) + "s)" : "FAIL");

  // duration label
  console.log("durasi:", c.dur, "| dur(manager):", c.d, c.d > 0 ? "OK" : "FAIL");

  // seek: drag scrub to ~70%
  const seek = await p.evaluate(() => {
    const s = document.querySelector("#scrub");
    s.value = "700";
    s.dispatchEvent(new Event("input", { bubbles: true }));
    return window.__l2d.state().time;
  });
  await p.waitForTimeout(150);
  const after = await readUI(p);
  console.log("SEEK ke 70% ->", seek?.toFixed(2), "| cur:", after.cur, "| anim tetap:", after.anim);

  // switch motion -> duration label should update
  await p.selectOption("#anim-select", "touch_head").catch((e) => console.log("(no touch_head)"));
  await p.waitForTimeout(1200);
  const th = await readUI(p);
  console.log("setelah ganti motion:", JSON.stringify({ anim: th.anim, dur: th.dur, cur: th.cur }));

  console.log("errors:", errs.length, errs.slice(0, 5));
  await b.close();
})();
