#!/usr/bin/env node
// probe_parts.cjs — test two approaches: setPartOpacityByIndex vs globalModel
const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');

const CHROME = process.env.CHROME_PATH || '/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome';
const MODEL = 'l2d_10010100012';
const BASE  = 'http://127.0.0.1:3000';
const L2D   = `${BASE}/l2d/${MODEL}/`;

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.on('console', m => { if (m.type() === 'error') console.log('ERR', m.text()); });

  await page.goto(`${BASE}/l2d-test.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.__l2d?.coreReady === true, { timeout: 30000 });

  // Load model
  const loadOk = await page.evaluate(async (base) => {
    try {
      const { Live2DModel } = window.__mods;
      const m = await Live2DModel.from(base + 'model3.json', { autoUpdate: true });
      m.anchor.set(0.5);
      m.scale.set(0.25);
      m.x = 640; m.y = 400;
      const app = window.__l2d.app;
      app.stage.addChild(m);
      window._model = m;
      return { ok: true };
    } catch (e) { return { ok: false, err: String(e), stack: e.stack?.slice(0,500) }; }
  }, L2D);

  console.log('LOAD:', JSON.stringify(loadOk));
  if (!loadOk.ok) { await browser.close(); process.exit(1); }
  await page.waitForTimeout(6000);

  // Inspect internal structure
  const info = await page.evaluate(() => {
    const m = window._model;
    const im = m.internalModel;
    const mm = im?.internalModel;
    const sdk = mm?.live2DModel;
    const parts = mm?.coreModel;
    const params = mm?.parameterManager;

    const methods = sdk ? Object.getOwnPropertyNames(Object.getPrototypeOf(sdk)).filter(k => k.startsWith('set') || k.startsWith('get') || k.includes('Part') || k.includes('part') || k.includes('Opacity') || k.includes('opacity')).slice(0, 40) : [];

    // Try to find opacities
    let opacities = null;
    if (parts?.getPartOpacity) {
      const count = parts.getPartCount ? parts.getPartCount() : -1;
      opacities = [];
      for (let i = 0; i < count; i++) opacities.push(+(parts.getPartOpacity(i)).toFixed(3));
    }

    return {
      hasSDK: !!sdk,
      hasParts: !!parts,
      hasParams: !!params,
      methods,
      opacities,
      paramCount: parts?.getParameterCount?.() ?? -1,
      partCount: parts?.getPartCount?.() ?? -1,
      drawCount: parts?.getDrawCount?.() ?? -1,
    };
  });

  console.log('INFO:', JSON.stringify(info, null, 2));

  // Strategy 1: use raw CubismCore SDK methods directly
  const strategy1 = await page.evaluate(() => {
    const m = window._model;
    const im = m.internalModel;
    const mm = im?.internalModel;
    const parts = mm?.coreModel;
    if (!parts?.setPartOpacity) return { err: 'no setPartOpacity' };

    const count = parts.getPartCount();
    let forced = 0;
    for (let i = 0; i < count; i++) {
      if (parts.getPartOpacity(i) < 0.01) {
        parts.setPartOpacity(i, 1.0);
        forced++;
      }
    }
    return { count, forced };
  });

  console.log('STRATEGY1 (setPartOpacity):', JSON.stringify(strategy1));
  await page.waitForTimeout(6000);

  await page.screenshot({ path: '/root/l2d_parts1.png' });
  console.log('SCREENSHOT1: /root/l2d_parts1.png');

  // Strategy 2: set all params to something visible via parameterManager
  const strategy2 = await page.evaluate(() => {
    const m = window._model;
    const im = m.internalModel;
    const mm = im?.internalModel;
    const parts = mm?.coreModel;
    const params = mm?.parameterManager;

    // Also try setting opacity through the globalModel interface
    const gm = im?.globalModel;
    const gmMethods = gm ? Object.getOwnPropertyNames(Object.getPrototypeOf(gm)).filter(k => /part|opacity/i.test(k)).slice(0, 20) : [];

    // Try the pixi-live2d-display model's own part API if available
    const pixiPartAPI = Object.keys(m).filter(k => /part|opacity/i.test(k));

    // Check if internalModel has a partsVisible or similar
    const imKeys = Object.keys(im || {}).filter(k => /part|opacity|visible/i.test(k));

    return { gmMethods, pixiPartAPI, imKeys };
  });

  console.log('STRATEGY2:', JSON.stringify(strategy2));

  await browser.close();
})();
