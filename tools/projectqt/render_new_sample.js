// Render a sample of the newly-extracted Project QT models in the native
// 2.1.27 viewer to confirm they aren't scrambled.
//
// These were missed by the original "spine" filename filter, so this checks
// the extraction produced working models and not just valid-looking files.
"use strict";
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const OUT = "/root/qt-new-shots";
const BASE = "http://127.0.0.1:3000";

// Pick a spread across bundle types, not just the first N.
const dir = "/root/projectqt-native2";
const all = fs.readdirSync(dir).filter((f) => !f.startsWith("_")).sort();
const step = Math.ceil(all.length / 8);
const SAMPLE = [...new Set(all.filter((_, i) => i % step === 0))].slice(0, 8);

(async () => {
	fs.mkdirSync(OUT, { recursive: true });
	const browser = await chromium.launch({
		executablePath: CHROME,
		args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
	});
	const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
	const errs = [];
	page.on("pageerror", (e) => errs.push("pageerror: " + e.message.slice(0, 150)));
	page.on("console", (m) => {
		if (m.type() === "error") errs.push("console: " + m.text().slice(0, 150));
	});

	let failures = 0;
	for (const name of SAMPLE) {
		const files = fs.readdirSync(path.join(dir, name));
		const skel = files.find((f) => f.endsWith(".skel") || f.endsWith(".json"));
		const url = `${BASE}/assets/projectqt/${name}/${skel}`;
		await page.goto(`${BASE}/legacy-spine/index.html?url=${encodeURIComponent(url)}`, {
			waitUntil: "networkidle",
			timeout: 60000,
		});
		await page.waitForTimeout(11000);

		const state = await page.evaluate(() => {
			const c = document.querySelector("canvas");
			return {
				canvas: c ? `${c.width}x${c.height}` : "none",
				// The viewer prints "Data Type: skel" once the model is in.
				text: (document.body.innerText || "").slice(0, 300),
			};
		});
		const loaded = /Data Type:/i.test(state.text);
		const file = path.join(OUT, name + ".png");
		await page.screenshot({ path: file });
		console.log(`${name}: canvas=${state.canvas} loaded=${loaded}`);
		if (!loaded) failures++;
	}

	console.log("\nerrors:", errs.length ? errs.slice(0, 5) : "none");
	console.log(failures ? `FAIL (${failures})` : "PASS");
	await browser.close();
	process.exit(failures ? 1 : 0);
})();
