const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 900, height: 700 } });

  const logs = [];
  page.on('console', (m) => logs.push('[' + m.type() + '] ' + m.text()));
  page.on('pageerror', (e) => logs.push('[pageerror] ' + e.message));
  page.on('response', (r) => {
    if (r.status() >= 400) logs.push('[HTTP ' + r.status() + '] ' + r.url());
  });
  page.on('requestfailed', (r) => {
    const f = r.failure() || {};
    logs.push('[REQFAIL] ' + r.url() + ' :: ' + f.errorText);
  });

  await page.goto('http://127.0.0.1:3000/l2d-test.html', { waitUntil: 'load', timeout: 60000 });

  let state = null;
  try {
    await page.waitForFunction(() => window.__l2d && window.__l2d.ready, { timeout: 45000 });
    state = await page.evaluate(() => {
      const m = window.__l2d.model;
      return {
        ready: true,
        w: Math.round(m.width),
        h: Math.round(m.height),
        hasCore: !!(m.internalModel && m.internalModel.coreModel),
      };
    });
  } catch (e) {
    state = { ready: false, err: String(e).slice(0, 200) };
  }

  await page.waitForTimeout(2500);
  await page.screenshot({ path: '/root/l2d_smoke.png' });

  console.log('STATE:', JSON.stringify(state));
  console.log('--- console ---');
  console.log(logs.slice(0, 30).join('\n'));

  await browser.close();
})();
