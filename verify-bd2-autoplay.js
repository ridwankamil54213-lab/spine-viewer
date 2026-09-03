// Verify BD2 voice autoplay in a real browser.
//
// Three scenarios, because the interesting behaviour is what happens when the
// browser BLOCKS autoplay (which is the normal case on a fresh load):
//   1. autoplay allowed  -> audio starts on model load, no click needed
//   2. autoplay blocked  -> silent on load, starts after the user's first click
//   3. autoplay switched off -> stays silent, and preference persists
const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const URL = "http://127.0.0.1:3000/";
const MODEL = "bd2/char/char000101"; // has 3 JP clips

async function openModel(browser, { blockAutoplay }) {
  const args = ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"];
  if (!blockAutoplay) args.push("--autoplay-policy=no-user-gesture-required");
  const b = await chromium.launch({ executablePath: CHROME, args });
  const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(URL, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForSelector(".game", { timeout: 45000 });
  await page.click('.game[data-key="bd2"]');
  await page.waitForSelector("#search:not([hidden])", { timeout: 30000 });
  await page.fill("#search", "char000101");
  await page.waitForFunction((w) => !!document.querySelector(`.model[data-id="${w}"]`), MODEL, { timeout: 30000 });
  await page.click(`.model[data-id="${MODEL}"]`);
  await page.waitForFunction(
    () => !document.querySelector("#hud").hidden || !document.querySelector("#error").hidden,
    { timeout: 40000 }
  );
  await page.waitForTimeout(2500);
  return { browser: b, page };
}

const read = (page) => page.evaluate(() => ({
  voice: window.spineStage?.voice,
  auto: window.spineStage?.voiceAutoplay,
}));

(async () => {
  let pass = 0;
  const results = [];

  // --- 1. autoplay permitted: should play with no click at all ---
  {
    const { browser, page } = await openModel(null, { blockAutoplay: false });
    const s = await read(page);
    const ok = s.voice?.hasElement && !s.voice.paused && s.voice.currentTime > 0 && !s.voice.error;
    console.log(`1. autoplay diizinkan      : ${ok ? "OK  " : "FAIL"} ` +
      `t=${s.voice?.currentTime?.toFixed(2)}s paused=${s.voice?.paused} err=${s.voice?.error}`);
    if (ok) pass++;
    results.push(ok);
    await browser.close();
  }

  // --- 2. autoplay blocked: silent, then plays after the first click ---
  {
    // Chrome counts Playwright's synthetic clicks as user gestures, so the
    // autoplay policy never actually blocks. Emulate the real constraint with
    // an init script: play() rejects until a genuine gesture has happened.
    const b = await chromium.launch({
      executablePath: CHROME,
      args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
    });
    const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
    // Picking a model requires clicking the game tile and the card, and Chrome
    // counts those as gestures — so by the time the model loads, audio is
    // already permitted. To exercise the blocked path we arm the block AFTER
    // navigation and only clear it on a click on empty chrome (not a control),
    // which is what a real first-visit looks like.
    await page.addInitScript(() => {
      const proto = Object.getPrototypeOf(new Audio());
      const real = proto.play;
      window.__gesture = false;
      proto.play = function () {
        if (!window.__gesture) return Promise.reject(new DOMException("blocked", "NotAllowedError"));
        return real.call(this);
      };
      // No auto-unlock listener: clicking the game tile and the model card are
      // real gestures, so they would latch the flag before any model loads and
      // the blocked path could never be exercised. The test flips __gesture
      // itself, then dispatches a click so the app's own unlock handler runs.
    });
    await page.goto(URL, { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForSelector(".game", { timeout: 45000 });
    await page.click('.game[data-key="bd2"]');
    await page.waitForSelector("#search:not([hidden])", { timeout: 30000 });
    await page.fill("#search", "char000101");
    await page.waitForFunction(
      (w) => !!document.querySelector(`.model[data-id="${w}"]`), MODEL, { timeout: 30000 }
    );
    await page.click(`.model[data-id="${MODEL}"]`);
    await page.waitForFunction(() => !document.querySelector("#hud").hidden, { timeout: 40000 });
    await page.waitForTimeout(2500);

    const before = await read(page);
    const silent = !before.voice?.hasElement || before.voice.paused || before.voice.currentTime === 0;
    // Now grant the gesture and click empty chrome; the app's own
    // voiceUnlock handler should notice and retry the pending autoplay.
    await page.evaluate(() => { window.__gesture = true; });
    await page.mouse.click(700, 60);
    await page.waitForTimeout(2500);
    const after = await read(page);
    // Clips are ~2s and we sample 2.5s later, so a finished clip (paused at
    // its end) counts as played — same rule as verify-bd2-media.js.
    const v = after.voice || {};
    const played =
      v.hasElement &&
      !v.error &&
      v.currentTime > 0 &&
      v.duration > 0 &&
      (!v.paused || v.currentTime >= v.duration - 0.05);
    const ok = silent && played;
    console.log(`2. diblokir lalu klik      : ${ok ? "OK  " : "FAIL"} ` +
      `sebelum: paused=${before.voice?.paused} t=${before.voice?.currentTime} | ` +
      `sesudah: t=${after.voice?.currentTime?.toFixed(2)}s paused=${after.voice?.paused} unlocked=${after.auto?.unlocked}`);
    if (ok) pass++;
    results.push(ok);
    await b.close();
  }

  // --- 3. autoplay switched off: stays silent, preference persists ---
  {
    const { browser, page } = await openModel(null, { blockAutoplay: false });
    await page.click("#audio-auto-btn");
    await page.waitForTimeout(600);
    const off = await read(page);
    const stopped = !off.voice?.hasElement || off.voice.paused;
    const flagOff = off.auto?.on === false;

    // It must survive a reload.
    await page.reload({ waitUntil: "networkidle", timeout: 60000 });
    await page.waitForSelector(".game", { timeout: 45000 });
    await page.click('.game[data-key="bd2"]');
    await page.waitForSelector("#search:not([hidden])", { timeout: 30000 });
    await page.fill("#search", "char000101");
    await page.waitForFunction((w) => !!document.querySelector(`.model[data-id="${w}"]`), MODEL, { timeout: 30000 });
    await page.click(`.model[data-id="${MODEL}"]`);
    await page.waitForFunction(() => !document.querySelector("#hud").hidden, { timeout: 40000 });
    await page.waitForTimeout(2500);
    const after = await read(page);
    const stillOff = after.auto?.on === false && (!after.voice?.hasElement || after.voice.paused);
    const ok = stopped && flagOff && stillOff;
    console.log(`3. dimatikan + tetap mati  : ${ok ? "OK  " : "FAIL"} ` +
      `stopped=${stopped} flag=${flagOff} setelah reload: on=${after.auto?.on} paused=${after.voice?.paused}`);
    if (ok) pass++;
    results.push(ok);
    await browser.close();
  }

  console.log(`\n${pass}/3 skenario OK`);
  process.exit(pass === 3 ? 0 : 1);
})();
