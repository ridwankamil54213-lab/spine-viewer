// Are motions wired up across models, not just the first one?
// For each model: check the dropdown is populated and that starting a motion
// actually changes the rendered pixels.
const { chromium } = require('playwright-core');

const MODELS = ['l2d_10010100012', 'l2d_10010100022', 'l2d_10020100012', 'l2d_10140100012'];

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  let moved = 0, tested = 0;

  for (const mid of MODELS) {
    const page = await browser.newPage({ viewport: { width: 1200, height: 820 } });
    const errs = [];
    page.on('pageerror', (e) => errs.push(e.message));

    try {
      await page.goto('http://127.0.0.1:3000/', { waitUntil: 'load', timeout: 60000 });
      await page.waitForTimeout(2200);
      await page.evaluate(() => {
        [...document.querySelectorAll('button.game')]
          .find((b) => b.dataset.key === 'dotabyss-l2d')?.click();
      });
      await page.waitForTimeout(1300);
      await page.evaluate((id) => {
        [...document.querySelectorAll('[data-id]')]
          .find((e) => (e.dataset.id || '') === 'dotabyss-l2d/' + id)?.click();
      }, mid);
      await page.waitForTimeout(8000);

      const anims = await page.evaluate(() => {
        const s = document.querySelector('#anim-select');
        return s ? [...s.options].map((o) => o.value) : [];
      });
      const pick = anims.find((a) => /FaceAngle|EyeEmotion|EyeOpen|Brow/.test(a)) || anims[0];
      if (!pick) { console.log(mid, '- no animations'); await page.close(); continue; }

      const clip = { x: 380, y: 120, width: 700, height: 560 };
      const before = await page.screenshot({ clip });
      await page.evaluate((v) => {
        const s = document.querySelector('#anim-select');
        s.value = v;
        s.dispatchEvent(new Event('change'));
      }, pick);
      await page.waitForTimeout(2500);
      const after = await page.screenshot({ clip });

      const diff = await page.evaluate(async ([a, b]) => {
        const load = async (b64) => {
          const img = new Image();
          img.src = 'data:image/png;base64,' + b64;
          await img.decode();
          const c = document.createElement('canvas');
          c.width = img.width; c.height = img.height;
          c.getContext('2d').drawImage(img, 0, 0);
          return c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        };
        const [d1, d2] = [await load(a), await load(b)];
        let ch = 0;
        for (let i = 0; i < d1.length; i += 4) {
          if (Math.abs(d1[i] - d2[i]) > 12 || Math.abs(d1[i + 1] - d2[i + 1]) > 12 ||
              Math.abs(d1[i + 2] - d2[i + 2]) > 12) ch++;
        }
        return +((ch / (d1.length / 4)) * 100).toFixed(2);
      }, [before.toString('base64'), after.toString('base64')]);

      tested++;
      const ok = diff > 0.5;
      if (ok) moved++;
      console.log(`${mid.padEnd(18)} anim=${String(anims.length).padStart(3)}  ${pick.padEnd(22)} moved=${diff}%  ${ok ? '✅' : '❌'}`);
      if (errs.length) console.log('   ERR:', errs[0].slice(0, 70));
    } catch (e) {
      console.log(mid, 'FAIL', String(e).slice(0, 80));
    }
    await page.close();
  }

  console.log(`\n=== ${moved}/${tested} models animate ===`);
  await browser.close();
})();
