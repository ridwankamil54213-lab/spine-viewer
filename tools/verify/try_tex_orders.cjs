// Try texture orderings and see which one renders a coherent character.
const { chromium } = require('playwright-core');

const ORDERS = [
  ['texture_00.png', 'texture_01.png', 'texture_02.png'],
  ['texture_00.png', 'texture_02.png', 'texture_01.png'],
  ['texture_01.png', 'texture_00.png', 'texture_02.png'],
  ['texture_01.png', 'texture_02.png', 'texture_00.png'],
  ['texture_02.png', 'texture_00.png', 'texture_01.png'],
  ['texture_02.png', 'texture_01.png', 'texture_00.png'],
];

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 900, height: 700 } });
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));

  await page.goto('http://127.0.0.1:3000/l2d-test.html', { waitUntil: 'load', timeout: 60000 });
  await page.waitForFunction(() => window.__mods && window.__l2d && window.__l2d.ready, {
    timeout: 45000,
  });
  console.log('base model ready, testing texture orders…');

  for (let i = 0; i < ORDERS.length; i++) {
    const order = ORDERS[i];
    const ok = await page.evaluate(async (ord) => {
      const { Live2DModel } = window.__mods;
      const base = '/l2d/l2d_10010100012/';
      const settings = {
        url: base + 'l2d_10010100012.model3.json',
        Version: 3,
        FileReferences: {
          Moc: base + 'l2d_10010100012.moc3',
          Textures: ord.map((t) => base + t),
        },
        Groups: [],
        HitAreas: [],
      };
      try {
        const m = await Live2DModel.from(settings, { autoInteract: false, autoHitTest: false, autoFocus: false });
        const app = window.__l2d.app;
        app.stage.removeChildren();
        app.stage.addChild(m);
        const s = Math.min(
          (app.renderer.width * 0.9) / m.width,
          (app.renderer.height * 0.9) / m.height
        );
        m.scale.set(s);
        m.x = app.renderer.width / 2;
        m.y = app.renderer.height / 2;
        m.anchor.set(0.5, 0.5);
        window.__l2d.model = m;
        return true;
      } catch (e) {
        return { ok: false, err: String((e && e.message) || e) };
      }
    }, order);

    if (ok && ok.ok === false) {
      console.log(`order ${i} FAILED: ${ok.err}`);
      continue;
    }
    if (!ok) {
      console.log(`order ${i}: no result`);
      continue;
    }
    await page.waitForTimeout(1800);
    await page.screenshot({ path: `/root/l2d_order_${i}.png` });
    console.log(`order ${i}: ${order.join(',')}  -> /root/l2d_order_${i}.png`);
  }

  await browser.close();
})();
