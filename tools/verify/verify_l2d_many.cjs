// The real test: several Cubism models, each checked for an actual coherent
// render. "Ready" is not enough — a wrong texture order loads fine and draws
// scattered polygons (see LIVE2D-INTEGRATION.md).
const { chromium } = require('playwright-core');

const MODELS = [
  'l2d_10010100012',
  'l2d_10010100022',
  'l2d_1001011002',
  'l2d_1001041002',
  'l2d_10020100012',
  'l2d_10140100012',
];

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const results = [];

  for (const mid of MODELS) {
    const page = await browser.newPage({ viewport: { width: 1200, height: 820 } });
    const errs = [];
    page.on('pageerror', (e) => errs.push(e.message));

    try {
      await page.goto('http://127.0.0.1:3000/', { waitUntil: 'load', timeout: 60000 });
      await page.waitForTimeout(2500);
      await page.evaluate(() => {
        [...document.querySelectorAll('button.game')]
          .find((b) => b.dataset.key === 'dotabyss-l2d')
          ?.click();
      });
      await page.waitForTimeout(1500);
      const clicked = await page.evaluate((id) => {
        const n = [...document.querySelectorAll('[data-id]')].find(
          (e) => (e.dataset.id || '') === 'dotabyss-l2d/' + id
        );
        if (!n) return false;
        n.click();
        return true;
      }, mid);
      if (!clicked) throw new Error('model not found in library');

      await page.waitForTimeout(9000);

      // Measure coverage from a PNG screenshot. readPixels() cannot be used
      // here: the drawing buffer is already cleared by the time it is read,
      // so every model reports 0% no matter what is on screen.
      const buf = await page.screenshot({ clip: { x: 300, y: 90, width: 880, height: 640 } });
      const stat = await page.evaluate(async (b64) => {
        const img = new Image();
        img.src = 'data:image/png;base64,' + b64;
        await img.decode();
        const c = document.createElement('canvas');
        c.width = img.width; c.height = img.height;
        const g = c.getContext('2d');
        g.drawImage(img, 0, 0);
        const d = g.getImageData(0, 0, c.width, c.height).data;
        // The stage is a dark grid; count pixels that are clearly not
        // background (bright or saturated) as artwork.
        let lit = 0;
        for (let i = 0; i < d.length; i += 4) {
          const r = d[i], gg = d[i + 1], bb = d[i + 2];
          const mx = Math.max(r, gg, bb), mn = Math.min(r, gg, bb);
          if (mx > 70 && mx - mn > 18) lit++;
        }
        return {
          lit,
          pct: +((lit / (c.width * c.height)) * 100).toFixed(2),
          zoom: +(window.spineStage?.state?.zoom || 0).toFixed(3),
          w: c.width, h: c.height,
        };
      }, buf.toString('base64'));

      await page.screenshot({ path: `/root/scan_${mid}.png` });
      results.push({ mid, ok: !!stat && stat.pct > 1, stat, errs: errs.slice(0, 2) });
      console.log(
        mid.padEnd(18),
        stat ? `cover=${stat.pct}% zoom=${stat.zoom}` : 'no stat',
        errs.length ? 'ERR:' + errs[0].slice(0, 60) : ''
      );
    } catch (e) {
      results.push({ mid, ok: false, err: String(e).slice(0, 120) });
      console.log(mid.padEnd(18), 'FAIL', String(e).slice(0, 90));
    }
    await page.close();
  }

  const ok = results.filter((r) => r.ok).length;
  console.log(`\n=== ${ok}/${results.length} rendered ===`);
  await browser.close();
})();
