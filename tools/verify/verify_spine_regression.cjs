// fitModel() was changed for Cubism; confirm Spine models still frame correctly.
const { chromium } = require('playwright-core');

async function shoot(page, gameKey, modelId, out) {
  await page.goto('http://127.0.0.1:3000/', { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(2500);
  await page.evaluate((k) => {
    [...document.querySelectorAll('button.game')].find((b) => b.dataset.key === k)?.click();
  }, gameKey);
  await page.waitForTimeout(2000);
  const clicked = await page.evaluate((mid) => {
    const n = [...document.querySelectorAll('[data-id]')].find((e) => (e.dataset.id || '').includes(mid));
    if (!n) return false;
    n.click();
    return true;
  }, modelId);
  if (!clicked) {
    // Fall back to the first card in the bucket.
    await page.evaluate(() => document.querySelector('[data-id]')?.click());
  }
  await page.waitForTimeout(6000);
  const geo = await page.evaluate(() => {
    const m = window.spineStage?.spine;
    if (!m) return null;
    return { pos: { x: m.x, y: m.y }, w: m.width, h: m.height };
  });
  await page.screenshot({ path: out });
  return { clicked, geo, out };
}

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));

  console.log('SPINE :', JSON.stringify(await shoot(page, 'spineboy', 'spineboy', '/root/reg_spineboy.png')));
  console.log('NIKKE :', JSON.stringify(await shoot(page, 'nikke', 'c010', '/root/reg_nikke.png')));
  console.log('errors:', errs.slice(0, 5).join(' | ') || '(none)');

  await browser.close();
})();
