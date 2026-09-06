// Does the stage backdrop actually change colour, and does it persist?
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 1200, height: 820 } });
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));

  await page.goto('http://127.0.0.1:3000/', { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(2500);

  // Sample the top-left corner of the stage, away from any model.
  const sample = async () =>
    page.evaluate(() => {
      const el = document.querySelector('#stage-bg');
      if (!el) return null;
      return { attr: el.dataset.bg, bg: getComputedStyle(el).backgroundColor };
    });

  console.log('elemen ada:', JSON.stringify(await sample()));

  // Walk every option through the select.
  const opts = await page.evaluate(() =>
    [...document.querySelectorAll('#bg-select option')].map((o) => o.value)
  );
  console.log('opsi:', opts.join(', '));

  for (const v of opts) {
    await page.selectOption('#bg-select', v);
    await page.waitForTimeout(350);
    const s = await sample();
    console.log(`  ${v.padEnd(9)} -> attr=${s.attr}  color=${s.bg}`);
  }

  // Toggle button should cycle.
  await page.selectOption('#bg-select', 'dark');
  await page.click('#bg-btn');
  await page.waitForTimeout(300);
  console.log('setelah klik Latar:', (await sample()).attr);
  await page.click('#bg-btn');
  await page.waitForTimeout(300);
  console.log('klik lagi      :', (await sample()).attr);

  // Keyboard shortcut L.
  await page.keyboard.press('l');
  await page.waitForTimeout(300);
  console.log('setelah tombol L:', (await sample()).attr);

  // Persistence across reload.
  const before = (await sample()).attr;
  await page.reload({ waitUntil: 'load' });
  await page.waitForTimeout(2500);
  const after = (await sample()).attr;
  console.log(`persist: ${before} -> ${after}  ${before === after ? '✅' : '❌'}`);

  console.log('errors:', errs.slice(0, 3).join(' | ') || '(none)');
  await page.screenshot({ path: '/root/bg_test.png' });
  await browser.close();
})();
