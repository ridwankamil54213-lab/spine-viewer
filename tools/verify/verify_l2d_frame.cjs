// Confirm the "cut off" character is a camera/zoom issue, not a broken render:
// render the L2D model at a zoom level that fits the whole model.
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const logs = [];
  page.on('pageerror', (e) => logs.push('[pageerror] ' + e.message));

  await page.goto('http://127.0.0.1:3000/', { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(3000);

  await page.evaluate(() => {
    [...document.querySelectorAll('button.game')]
      .find((b) => b.dataset.key === 'dotabyss-l2d')
      ?.click();
  });
  await page.waitForTimeout(2000);
  await page.evaluate(() => {
    [...document.querySelectorAll('[data-id]')]
      .find((n) => (n.dataset.id || '').includes('l2d_10010100012'))
      ?.click();
  });
  await page.waitForTimeout(8000);

  // Zoom out so the entire model is inside the viewport.
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Minus');
    await page.waitForTimeout(120);
  }
  await page.waitForTimeout(1500);

  const info = await page.evaluate(() => {
    const s = window.spineStage;
    return s ? { ok: true, keys: Object.keys(s) } : { ok: false };
  });
  console.log('spineStage:', JSON.stringify(info));

  await page.screenshot({ path: '/root/l2d_ui_fit.png' });
  console.log('shot -> /root/l2d_ui_fit.png');
  console.log('errors:', logs.slice(0, 5).join('\n') || '(none)');

  await browser.close();
})();
