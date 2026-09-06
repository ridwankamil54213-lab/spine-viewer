// End-to-end: open the real viewer, pick the Live2D model, check it renders.
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

  const logs = [];
  page.on('console', (m) => logs.push('[' + m.type() + '] ' + m.text()));
  page.on('pageerror', (e) => logs.push('[pageerror] ' + e.message));

  await page.goto('http://127.0.0.1:3000/', { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(3000);

  // Core must be present before the bundle ran.
  const coreOk = await page.evaluate(() => typeof window.Live2DCubismCore);
  console.log('Cubism core:', coreOk);

  // Step 1: pick the game bucket.
  const gameClick = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button.game')].find(
      (b) => (b.dataset.key || '') === 'dotabyss-l2d'
    );
    if (!btn) {
      return { ok: false, keys: [...document.querySelectorAll('button.game')].map((b) => b.dataset.key) };
    }
    btn.click();
    return { ok: true, key: btn.dataset.key };
  });
  console.log('game click:', JSON.stringify(gameClick));

  await page.waitForTimeout(2500);

  // Step 2: click the model card.
  const modelClick = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll('[data-id], [data-model-id], .model, .card')];
    const hit = nodes.find((n) => {
      const t = (n.textContent || '').toLowerCase();
      const id = n.dataset.id || n.dataset.modelId || '';
      return id.includes('l2d_10010100012') || t.includes('l2d 10010100012');
    });
    if (hit) {
      hit.click();
      return { ok: true, id: hit.dataset.id || hit.dataset.modelId || hit.textContent.trim().slice(0, 40) };
    }
    return { ok: false, sample: nodes.slice(0, 6).map((n) => (n.textContent || '').trim().slice(0, 40)) };
  });
  console.log('model click:', JSON.stringify(modelClick));

  await page.waitForTimeout(9000);
  const errText = await page.evaluate(() => {
    const e = document.querySelector('#error, .error, [id*="error"]');
    return e && e.offsetParent !== null ? e.textContent.trim().slice(0, 200) : null;
  });
  console.log('visible error:', errText);

  await page.screenshot({ path: '/root/l2d_ui.png' });
  console.log('shot -> /root/l2d_ui.png');

  console.log('--- errors ---');
  console.log(logs.filter((l) => /error|pageerror/i.test(l)).slice(0, 10).join('\n') || '(none)');

  await browser.close();
})();
