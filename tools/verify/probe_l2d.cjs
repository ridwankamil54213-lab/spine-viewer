const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 900, height: 700 } });

  const logs = [];
  page.on('console', (m) => logs.push('[' + m.type() + '] ' + m.text()));
  page.on('pageerror', (e) => logs.push('[pageerror] ' + e.message + '\n' + e.stack));

  await page.goto('http://127.0.0.1:3000/l2d-test.html', { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(12000);

  const probe = await page.evaluate(() => ({
    l2d: window.__l2d ? Object.keys(window.__l2d) : null,
    l2dState: window.__l2d ? { ready: window.__l2d.ready, error: window.__l2d.error } : null,
    logText: document.getElementById('log').innerText,
  }));

  console.log('PROBE:', JSON.stringify(probe, null, 2));
  console.log('--- console (errors first) ---');
  const errs = logs.filter((l) => /error|pageerror/i.test(l));
  console.log(errs.slice(0, 10).join('\n') || '(no errors)');
  console.log('--- all logs tail ---');
  console.log(logs.slice(-15).join('\n'));

  await page.screenshot({ path: '/root/l2d_smoke.png' });
  await browser.close();
})();
