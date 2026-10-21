// Verify BD2 icons and JP voice lines end-to-end in a real browser:
//  - grid cards show the character icon instead of the letter fallback
//  - the voice button appears for models with audio and is hidden without
//  - clicking it actually plays a real audio track (not just sets a flag)
const { chromium } = require("playwright-core");
const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const URL = "http://127.0.0.1:3000/";

const CASES = [
  // [id, hasAudio, hasIcon]
  ["bd2/char/char000101", true, true],   // icon + 3 voices
  ["bd2/char/char000502", true, true],
  ["bd2/npc/npc_ellin", false, false],   // no audio, no icon in the source
];

(async () => {
  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader",
           "--disable-dev-shm-usage", "--autoplay-policy=no-user-gesture-required"],
  });
  let pass = 0;
  for (const [id, expectAudio, expectIcon] of CASES) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errs = [];
    page.on("pageerror", (e) => errs.push(e.message.slice(0, 140)));
    try {
      await page.goto(URL, { waitUntil: "networkidle", timeout: 60000 });
      await page.waitForSelector(".game", { timeout: 45000 });
      await page.click('.game[data-key="bd2"]');
      await page.waitForSelector("#search:not([hidden])", { timeout: 30000 });

      // --- icon in the grid ---
      await page.fill("#search", id.split("/").pop());
      await page.waitForFunction((w) => !!document.querySelector(`.model[data-id="${w}"]`), id, { timeout: 30000 });
      const card = await page.evaluate((w) => {
        const b = document.querySelector(`.model[data-id="${w}"]`);
        const img = b?.querySelector("img.model-thumb");
        return { hasImg: !!img, src: img?.getAttribute("src") || null };
      }, id);

      await page.click(`.model[data-id="${id}"]`);
      await page.waitForFunction(
        () => !document.querySelector("#hud").hidden || !document.querySelector("#error").hidden,
        { timeout: 40000 }
      );
      await page.waitForTimeout(2500);

      const before = await page.evaluate(() => ({
        hidden: document.querySelector("#audio-btn").hidden,
        title: document.querySelector("#audio-btn").title,
      }));

      let played = null;
      if (!before.hidden) {
        // Autoplay is on by default, so the model may ALREADY be talking when
        // we get here — and the button is a play/STOP toggle, so clicking it
        // now would silence it. Only click if nothing is playing.
        const already = await page.evaluate(() => window.spineStage?.voice);
        if (!(already && already.hasElement && !already.paused)) {
          await page.click("#audio-btn");
        }
        await page.waitForTimeout(1500);
        // Probe the real media element, not the button's dataset.
        // The Audio object is detached from the DOM, so read it through the
        // window.spineStage.voice debug handle instead of querySelector.
        played = await page.evaluate(() => {
          const v = window.spineStage?.voice;
          if (!v || !v.hasElement) return { found: false, raw: v };
          return { found: true, ...v };
        });
      }

      const audioOk = before.hidden === !expectAudio;
      // Clips are ~2s, so by sample time one may already have finished.
      // "played" means: real src, no error, and it advanced (or completed).
      const playOk =
        !expectAudio ||
        (played &&
          played.found &&
          !played.error &&
          played.currentTime > 0 &&
          played.duration > 0 &&
          (!played.paused || played.currentTime >= played.duration - 0.05));
      const iconOk = expectIcon
        ? card.hasImg && /\/thumbs\/bd2\/icons\//.test(card.src || "")
        : !card.hasImg; // falls back to the letter tile
      const ok = audioOk && playOk && iconOk;
      if (ok) pass++;

      console.log(
        `${ok ? "OK  " : "FAIL"} ${id.padEnd(24)} icon=${iconOk ? card.src : "TIDAK ADA"} ` +
        `audioBtn=${before.hidden ? "sembunyi" : "tampil"}`
      );
      if (played) {
        console.log(`     putar: src=${played.src} t=${played.currentTime?.toFixed(2)}s ` +
                    `dur=${played.duration} paused=${played.paused} err=${played.error}`);
      }
      if (!expectAudio) console.log(`     (diharapkan tanpa audio)`);
      if (errs.length) console.log("     pageerror:", errs[0]);
    } catch (e) {
      console.log(`FAIL ${id.padEnd(24)} ${String(e.message).split("\n")[0].slice(0, 110)}`);
    }
    await page.close();
  }
  await browser.close();
  console.log(`\n${pass}/${CASES.length} kasus OK`);
  process.exit(pass === CASES.length ? 0 : 1);
})();
