// Headless smoke test: loads the viewer, picks a model, verifies it renders and animates.
//
// IMPORTANT: you cannot pixel-sample a Pixi WebGL canvas from page JS — the drawing
// buffer is cleared after compositing (preserveDrawingBuffer defaults to false), so
// both gl.readPixels() and ctx.drawImage(canvas) report an empty/transparent frame
// even when the character is visibly on screen. The reliable assertion is the real
// screenshot: a blank stage compresses to a tiny PNG, a rendered skeleton does not.
const { chromium } = require("playwright-core");
const fs = require("fs");

const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const URL = process.env.URL || "http://127.0.0.1:3000/";
const SHOT = "/srv/spine-viewer/screenshot.png";

(async () => {
	const browser = await chromium.launch({
		executablePath: CHROME,
		args: [
			"--no-sandbox",
			"--use-gl=swiftshader",
			"--enable-unsafe-swiftshader",
			"--disable-dev-shm-usage",
		],
	});
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

	const errors = [];
	page.on("console", (m) => {
		if (m.type() === "error") errors.push("console: " + m.text());
	});
	page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

	await page.goto(URL, { waitUntil: "networkidle", timeout: 60000 });

	const count = await page.textContent("#model-count");
	console.log("models in library:", count);

	// spineboy now lives inside the "Demo" game, so open that first.
	await page.waitForSelector(".game", { timeout: 45000 });
	await page.click('.game[data-key="demo"]');
	await page.waitForSelector('.model[data-id="spineboy"]', { timeout: 30000 });
	await page.click('.model[data-id="spineboy"]');
	await page.waitForFunction(() => !document.querySelector("#hud").hidden, { timeout: 30000 });
	await page.waitForTimeout(2500);

	const info = await page.evaluate(() => {
		const canvas = document.querySelector("#canvas-wrap canvas");
		const sp = window.spineStage?.spine;
		const pages = [];
		if (sp) {
			const seen = new Set();
			for (const slot of sp.skeleton.slots) {
				const bt = slot.getAttachment()?.region?.page?.baseTexture;
				if (bt && !seen.has(bt.uid)) {
					seen.add(bt.uid);
					// ALPHA_MODES: NPM=0, UNPACK=1, PMA=2 — must be PMA for pma atlases
					pages.push({ page: slot.getAttachment().region.page?.name, alphaMode: bt.alphaMode });
				}
			}
		}
		return {
			canvas: canvas ? canvas.width + "x" + canvas.height : null,
			atlasPages: pages,
			hudModel: document.querySelector("#hud-model")?.textContent,
			hudStats: document.querySelector("#hud-stats")?.innerText,
			anim: document.querySelector("#anim-select")?.value,
			animCount: document.querySelector("#anim-select")?.options.length,
			dur: document.querySelector("#time-dur")?.textContent,
			zoom: document.querySelector("#zoom-label")?.textContent,
			errorVisible: !document.querySelector("#error").hidden,
		};
	});
	console.log("render:", JSON.stringify(info, null, 2));

	// playback advances
	const t1 = await page.textContent("#time-cur");
	await page.waitForTimeout(1200);
	const t2 = await page.textContent("#time-cur");
	console.log(`time advance: ${t1} -> ${t2}`);

	// pause freezes
	await page.click("#play-btn");
	const p1 = await page.textContent("#time-cur");
	await page.waitForTimeout(900);
	const p2 = await page.textContent("#time-cur");
	console.log(`paused: ${p1} -> ${p2} (should be identical)`);

	// switching animation works
	await page.selectOption("#anim-select", "jump");
	await page.waitForTimeout(1000);
	const after = await page.evaluate(() => ({
		anim: document.querySelector("#anim-select").value,
		dur: document.querySelector("#time-dur").textContent,
	}));
	console.log("after switching to 'jump':", JSON.stringify(after));

	await page.click("#bones-btn");
	await page.waitForTimeout(400);
	console.log("bones:", await page.getAttribute("#bones-btn", "data-on"));

	await page.screenshot({ path: SHOT });
	const shotBytes = fs.statSync(SHOT).size;
	console.log("screenshot bytes:", shotBytes);

	console.log(errors.length ? "\nERRORS:\n" + errors.join("\n") : "\nno console errors");
	await browser.close();

	const pmaOk = info.atlasPages.length > 0 && info.atlasPages.every((p) => p.alphaMode === 2);
	const ok =
		shotBytes > 60000 &&
		!!info.canvas &&
		info.animCount === 11 &&
		pmaOk &&
		!info.errorVisible &&
		t1 !== t2 &&
		p1 === p2 &&
		after.anim === "jump" &&
		errors.length === 0;

	console.log(`\npma correct: ${pmaOk}`);
	console.log(ok ? "SMOKE TEST: PASS" : "SMOKE TEST: FAIL");
	process.exit(ok ? 0 : 1);
})();
