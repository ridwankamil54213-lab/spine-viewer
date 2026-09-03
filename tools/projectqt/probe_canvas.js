// Determine which graphics backend the vendored Spine 2.1.27 viewer uses.
//
// The GWT build is minified, so grepping for getContext() proves nothing.
// This asks the browser what the live canvas actually is, and patches
// getContext to record which context type gets requested.
"use strict";
const { chromium } = require("playwright-core");

const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:3000";
const MODEL = "PetBG1077_A";

(async () => {
	const browser = await chromium.launch({
		executablePath: CHROME,
		args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
	});
	const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });

	// Record every getContext request before any page script runs.
	await page.addInitScript(() => {
		window.__ctxCalls = [];
		const orig = HTMLCanvasElement.prototype.getContext;
		HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
			window.__ctxCalls.push(type);
			return orig.call(this, type, ...rest);
		};
	});

	const url = `${BASE}/assets/projectqt/${MODEL}/${MODEL}.skel`;
	await page.goto(`${BASE}/legacy-spine/index.html?url=${encodeURIComponent(url)}`, {
		waitUntil: "networkidle",
		timeout: 90000,
	});
	await page.waitForTimeout(13000);

	const info = await page.evaluate(() => {
		const out = { ctxCalls: window.__ctxCalls || [], canvases: [] };
		for (const c of document.querySelectorAll("canvas")) {
			let kind = "unknown";
			try {
				// Once a context exists, a second getContext of a different
				// type returns null — that's how we identify it.
				if (c.getContext("webgl") || c.getContext("experimental-webgl")) kind = "webgl";
				else if (c.getContext("2d")) kind = "2d";
			} catch (e) {
				kind = "err:" + e.message;
			}
			out.canvases.push({ size: `${c.width}x${c.height}`, kind, tag: c.tagName, id: c.id || "" });
		}
		return out;
	});

	console.log("getContext() calls requested:", JSON.stringify(info.ctxCalls));
	console.log("live canvases:");
	for (const c of info.canvases) console.log("  ", JSON.stringify(c));

	await browser.close();
})();
