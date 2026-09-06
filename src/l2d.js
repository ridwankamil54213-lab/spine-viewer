// Smoke test: load one DotAbyss Cubism 4 model rebuilt from the game bundles.
import { Application, Ticker } from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display/cubism4';

// The plugin drives model update/transform from a ticker. Keep the shared
// ticker alive and let the model auto-update; without this the model loads but
// its parts never settle, which renders as a pile of scattered polygons.
window.PIXI = window.PIXI || {};
window.PIXI.Ticker = Ticker;

const logEl = document.getElementById('log');
const log = (msg, cls = '') => {
  logEl.innerHTML += '<span class="' + cls + '">' + msg + '</span>\n';
  console.log(msg);
};

const MODEL = '/l2d/l2d_10010100012/l2d_10010100012.model3.json';

(async () => {
  try {
    log('cubism core: ' + typeof window.Live2DCubismCore);

    const app = new Application({
      view: document.getElementById('stage'),
      resizeTo: window,
      backgroundAlpha: 0,
      antialias: true,
    });
    // Keep the ticker from auto-starting until the model is on stage; the plugin
    // hooks its own update into PIXI.Ticker.
    app.ticker.stop();

    log('loading ' + MODEL);
    const model = await Live2DModel.from(MODEL, { autoInteract: false });

    app.stage.addChild(model);

    // fit to viewport
    const scale = Math.min(
      (app.renderer.width * 0.9) / model.width,
      (app.renderer.height * 0.9) / model.height
    );
    model.scale.set(scale);
    model.x = app.renderer.width / 2;
    model.y = app.renderer.height / 2;
    model.anchor.set(0.5, 0.5);

    log('OK size=' + Math.round(model.width) + 'x' + Math.round(model.height), 'ok');
    log('OK internalModel=' + !!model.internalModel, 'ok');
    log('OK textures loaded', 'ok');

    // Let the plugin's own automator drive updates; our manual model.update()
    // here would double-step the animation.
    app.ticker.start();

    window.__l2d = { app, model, ready: true };
    window.__mods = { Live2DModel, base: '/l2d/l2d_10010100012/' };
    log('READY', 'ok');
  } catch (e) {
    const cause = e && e.cause ? e.cause : null;
    log('FAIL: ' + (e && e.message ? e.message : e), 'err');
    if (cause) {
      log('CAUSE: ' + (cause.message || cause), 'err');
      if (cause.stack) log('STACK: ' + cause.stack.split('\n').slice(0, 6).join(' | '), 'err');
    }
    console.error(e);
    window.__l2d = { ready: false, error: String(e), cause: cause ? String(cause.message || cause) : null };
  }
})();
