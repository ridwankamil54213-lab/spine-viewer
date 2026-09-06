// Do the synthesised Cubism motions actually move the model?
// Compares rendered pixels before and after starting a motion: if the
// parameters are wired correctly, the frame must change.
const { chromium } = require('playwright-core');

const MODEL = 'l2d_10010100012';

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
  await page.evaluate(() => {
    [...document.querySelectorAll('button.game')]
      .find((b) => b.dataset.key === 'dotabyss-l2d')?.click();
  });
  await page.waitForTimeout(1500);
  await page.evaluate((id) => {
    [...document.querySelectorAll('[data-id]')]
      .find((e) => (e.dataset.id || '') === 'dotabyss-l2d/' + id)?.click();
  }, MODEL);
  await page.waitForTimeout(9000);

  // What did the server advertise?
  const anims = await page.evaluate(() => {
    const sel = document.querySelector('#anim-select');
    return sel ? [...sel.options].map((o) => o.value) : null;
  });
  console.log('animations offered:', anims ? `${anims.length}: ${anims.slice(0, 6).join(', ')}…` : 'NONE');

  // Is the motion manager wired up?
  const mm = await page.evaluate(() => {
    const m = window.spineStage?.spine;
    const mm2 = m?.internalModel?.motionManager;
    if (!mm2) return { ok: false };
    const defs = mm2.definitions || {};
    return {
      ok: true,
      groups: Object.keys(defs),
      counts: Object.fromEntries(Object.entries(defs).map(([k, v]) => [k, (v || []).length])),
      sample: (defs.idle || []).slice(0, 3).map((d) => d?.name || d?.fileName || '?'),
    };
  });
  console.log('motionManager:', JSON.stringify(mm));

  const clip = { x: 380, y: 120, width: 700, height: 560 };
  const before = await page.screenshot({ clip });

  // Start a motion that should visibly move the eyes/face.
  const played = await page.evaluate(() => {
    const sel = document.querySelector('#anim-select');
    // Prefer something with obvious movement.
    const pick = [...sel.options].map((o) => o.value)
      .find((v) => /FaceAngle|EyeEmotion|EyeOpen/.test(v)) || sel.options[0]?.value;
    sel.value = pick;
    sel.dispatchEvent(new Event('change'));
    return pick;
  });
  console.log('playing:', played);
  await page.waitForTimeout(2500);

  const after = await page.screenshot({ clip });

  // Pixel diff between the two frames.
  const diff = await page.evaluate(async ([a, b]) => {
    const load = async (b64) => {
      const img = new Image();
      img.src = 'data:image/png;base64,' + b64;
      await img.decode();
      const c = document.createElement('canvas');
      c.width = img.width; c.height = img.height;
      c.getContext('2d').drawImage(img, 0, 0);
      return c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    };
    const [d1, d2] = [await load(a), await load(b)];
    let changed = 0;
    for (let i = 0; i < d1.length; i += 4) {
      if (Math.abs(d1[i] - d2[i]) > 12 ||
          Math.abs(d1[i + 1] - d2[i + 1]) > 12 ||
          Math.abs(d1[i + 2] - d2[i + 2]) > 12) changed++;
    }
    return +((changed / (d1.length / 4)) * 100).toFixed(2);
  }, [before.toString('base64'), after.toString('base64')]);

  console.log('pixels changed:', diff + '%');
  console.log(diff > 0.5 ? 'ANIMASI JALAN ✅' : 'TIDAK BERGERAK ❌');
  console.log('errors:', errs.slice(0, 3).join(' | ') || '(none)');

  await page.screenshot({ path: '/root/l2d_anim.png' });
  await browser.close();
})();
