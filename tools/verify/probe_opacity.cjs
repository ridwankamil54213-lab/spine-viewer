// Hypothesis: parts hidden because their opacity/params are driven by the
// game's AnimationClips, which we have not reconstructed. Force everything
// visible and see whether the full character appears.
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 900, height: 700 } });
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));

  await page.goto('http://127.0.0.1:3000/l2d-test.html', { waitUntil: 'load', timeout: 60000 });
  await page.waitForFunction(() => window.__l2d && window.__l2d.ready, { timeout: 45000 });

  const info = await page.evaluate(() => {
    const cm = window.__l2d.model.internalModel.coreModel;
    const n = cm.getDrawableCount();
    let zeroOpacity = 0;
    const perDrawable = [];
    for (let i = 0; i < n; i++) {
      const o = cm.getDrawableOpacity ? cm.getDrawableOpacity(i) : null;
      if (o !== null && typeof o === 'number' && o < 0.01) zeroOpacity++;
      if (i < 6) perDrawable.push({ i, opacity: o });
    }
    // force all visible
    let forced = 0;
    for (let i = 0; i < n; i++) {
      try {
        if (cm.setDrawableOpacity) {
          cm.setDrawableOpacity(i, 1);
          forced++;
        }
      } catch (e) {}
    }
    // also reset all params to authored defaults
    try {
      cm.resetAllParameters && cm.resetAllParameters();
    } catch (e) {}
    try {
      window.__l2d.model.update(16.67);
      window.__l2d.app.renderer.render(window.__l2d.app.stage);
    } catch (e) {}
    return { drawableCount: n, zeroOpacity, sample: perDrawable, forced };
  });

  console.log('INFO:', JSON.stringify(info));
  await page.waitForTimeout(800);
  await page.screenshot({ path: '/root/l2d_opacity_forced.png' });
  console.log('shot -> /root/l2d_opacity_forced.png');

  await browser.close();
})();
