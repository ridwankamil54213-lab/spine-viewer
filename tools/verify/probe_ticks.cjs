// Does the model settle after N update() calls? Renders at increasing tick counts.
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

  // stop the automator so we control stepping precisely
  await page.evaluate(() => {
    window.__l2d.app.ticker.stop();
    if (window.__l2d.model.internalModel) {
      // force a pose reset so parts start from their authored positions
      try {
        window.__l2d.model.internalModel.coreModel.resetAllParameters
          ? window.__l2d.model.internalModel.coreModel.resetAllParameters()
          : null;
      } catch (e) {}
    }
  });

  for (const n of [1, 5, 30, 120]) {
    await page.evaluate((count) => {
      const m = window.__l2d.model;
      for (let i = 0; i < count; i++) m.update(16.67);
      window.__l2d.app.renderer.render(window.__l2d.app.stage);
    }, n);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `/root/l2d_tick_${n}.png` });
    console.log(`after ${n} updates -> /root/l2d_tick_${n}.png`);
  }

  await browser.close();
})();
