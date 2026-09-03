// Load every QT 3.8 test model through pixi-spine and report parse health.
//
// The point is to give the user something to eyeball: each model is opened in
// the normal viewer (pixi-spine 3.8) so the two renderers can be compared
// against the legacy 2.1.27 viewer.
"use strict";
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:3000";
const OUT = "/root/qt38-shots";

(async () => {
	fs.mkdirSync(OUT, { recursive: true });
	const browser = await chromium.launch({
		executablePath: CHROME,
		args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
	});
	const page = await browser.newPage({ viewport: { width: 1100, height: 850 } });
	const errs = [];
	page.on("pageerror", (e) => errs.push("pageerror: " + e.message.slice(0, 120)));

	await page.goto(`${BASE}/`, { waitUntil: "networkidle", timeout: 90000 });
	await page.waitForSelector(".game", { timeout: 60000 });
	await page.click('.game[data-key="qt38test"]');
	await page.waitForSelector(".model", { timeout: 60000 });

	const ids = await page.evaluate(() =>
		Array.from(document.querySelectorAll(".model")).map((m) => m.dataset.id)
	);
	console.log("models:", ids.length);

	let failures = 0;
	for (const id of ids) {
		await page.evaluate((i) => document.querySelector(`.model[data-id="${i}"]`).click(), id);
		await page.waitForTimeout(8000);
		const st = await page.evaluate(() => ({
			err: document.querySelector("#error").hidden ? null : document.querySelector("#error").textContent.trim().slice(0, 140),
			bones: window.spineStage?.spine?.skeleton?.bones?.length || 0,
			anims: window.spineStage?.spine?.spineData?.animations?.length || 0,
			runtime: window.spineStage?.runtime,
		}));
		const name = id.split("/").pop();
		await page.screenshot({ path: path.join(OUT, name + ".png") });
		console.log(`  ${name.padEnd(28)} bones=${String(st.bones).padStart(4)} anims=${st.anims} runtime=${st.runtime} ${st.err ? "ERR: " + st.err : "ok"}`);
		if (st.err || !st.bones) failures++;
	}

	console.log("\npageerrors:", errs.length ? errs.slice(0, 4) : "none");
	console.log(failures ? `FAIL (${failures})` : "PASS");
	await browser.close();
	process.exit(failures ? 1 : 0);
})();
