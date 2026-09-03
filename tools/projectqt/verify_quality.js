// Render the largest remaining Project QT models in the native 2.1.27 viewer.
//
// Size is a proxy for "full character" here: the bundles that turned out
// scrambled earlier (Pet9018) were tiny 18 KB UI effects, so this checks
// whether the big ones — the actual characters — draw correctly.
"use strict";
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:3000";
const OUT = "/root/qt-verify";
const MODELS = process.argv[2] ? process.argv[2].split(",") : ["PetBG1077_A", "PetBG1023_A", "PetBG1089", "PetBG1002_S04", "PetBG1079_A"];

(async () => {
	fs.mkdirSync(OUT, { recursive: true });
	const browser = await chromium.launch({
		executablePath: CHROME,
		args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
	});
	const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
	const bad = [];
	page.on("response", (r) => {
		if (r.status() >= 400) bad.push(`${r.status()} ${r.url().slice(0, 110)}`);
	});

	for (const m of MODELS) {
		const url = `${BASE}/assets/projectqt/${m}/${m}.skel`;
		await page.goto(`${BASE}/legacy-spine/index.html?url=${encodeURIComponent(url)}`, {
			waitUntil: "networkidle",
			timeout: 90000,
		});
		await page.waitForTimeout(13000);
		await page.screenshot({ path: path.join(OUT, m + ".png") });
		console.log("shot", m);
	}

	console.log("\nHTTP errors:", bad.length ? bad.slice(0, 5) : "none");
	await browser.close();
})();
