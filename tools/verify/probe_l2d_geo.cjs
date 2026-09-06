// Measure the L2D model's real bounds vs. the camera to see whether the
// character is clipped, off-centre, or genuinely missing geometry.
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
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

  const geo = await page.evaluate(() => {
    const m = window.spineStage?.spine;
    if (!m) return { err: 'no model' };
    const b = m.getBounds ? m.getBounds() : null;
    return {
      width: m.width,
      height: m.height,
      scale: { x: m.scale?.x, y: m.scale?.y },
      pos: { x: m.x, y: m.y },
      anchor: m.anchor ? { x: m.anchor.x, y: m.anchor.y } : null,
      bounds: b ? { x: b.x, y: b.y, width: b.width, height: b.height } : null,
      pivot: m.pivot ? { x: m.pivot.x, y: m.pivot.y } : null,
    };
  });
  console.log('MODEL GEO:', JSON.stringify(geo, null, 2));

  // Also measure the canvas / wrap the camera renders into.
  const view = await page.evaluate(() => {
    const c = document.querySelector('canvas');
    const w = document.querySelector('#canvasWrap, .canvas-wrap, #stage');
    return {
      canvas: c ? { w: c.clientWidth, h: c.clientHeight } : null,
      wrap: w ? { w: w.clientWidth, h: w.clientHeight } : null,
    };
  });
  console.log('VIEW:', JSON.stringify(view));

  await browser.close();
})();
