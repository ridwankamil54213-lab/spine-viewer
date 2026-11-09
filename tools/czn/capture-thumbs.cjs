#!/usr/bin/env node
/**
 * Capture CZN character thumbnails straight from the e7bot wiki.
 *
 * The Combatant and Partner tabs render each character as a `.combatant-display`
 * card (260x460 art with slot background, job/ego badges, rarity frame and the
 * name). Rather than approximating that card with local assets, we screenshot
 * the real DOM element — so the thumbnail is literally the web's artwork.
 *
 * The wiki card is laid out at 117x207 CSS px in a 1280px viewport; a device
 * scale factor of 260/117 makes Playwright rasterise it at the native 260x460.
 * Each image is named `<character id>.png`, matching _manifest.json written by
 * tools/czn/refresh.py.
 *
 * Usage: node tools/czn/capture-thumbs.cjs
 */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { chromium } = require("playwright-core");

const OUT = path.resolve(__dirname, "../../public/thumbs/czn-rigs");
const PAGES = [
	["combatant", "https://wiki.e7bot.top/#/czn/combatant"],
	["partner", "https://wiki.e7bot.top/#/czn/partner"],
];

(async () => {
	fs.mkdirSync(OUT, { recursive: true });
	const browser = await chromium.launch({ args: ["--no-sandbox"] });

	// Ukur lebar kartu CSS lebih dulu: di viewport 1280 lebarnya tidak persis
	// 117px, jadi DSF statis menghasilkan 273x482. DSF = 260/lebar nyata bikin
	// hasil raster tepat 260x460 (ukuran asli portrait wiki).
	const probe = await browser.newContext({
		viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1,
	});
	const pp = await probe.newPage();
	await pp.goto(PAGES[0][1], { waitUntil: "domcontentloaded" });
	await pp.waitForSelector(".combatant-display", { timeout: 90000 });
	const cardW = await pp.$eval(".combatant-display", (e) => e.getBoundingClientRect().width);
	await probe.close();
	const DSF = 260 / cardW;
	console.log(`lebar kartu ${cardW}px -> deviceScaleFactor ${DSF.toFixed(4)}`);

	const context = await browser.newContext({
		viewport: { width: 1280, height: 900 },
		deviceScaleFactor: DSF,
	});
	const seen = new Map();
	for (const [label, url] of PAGES) {
		// A fresh page per route: navigating between hash routes in the same
		// document does not remount the picker, so the Partner list would still
		// show combatants.
		const page = await context.newPage();
		page.setDefaultTimeout(90000);
		await page.goto(url, { waitUntil: "domcontentloaded" });
		await page.waitForSelector("img.portrait", { timeout: 90000 });
		await page.waitForFunction(() => {
			const imgs = [...document.querySelectorAll("img.portrait")];
			return imgs.length > 0 && imgs.every((i) => i.complete && i.naturalWidth > 0);
		}, null, { timeout: 90000 });
		await page.waitForTimeout(500);

		const imgs = await page.$$("img.portrait");
		console.log(`${label}: ${imgs.length} kartu`);
		for (const img of imgs) {
			const src = (await img.getAttribute("src")) || "";
			const id = (src.match(/(\d+)\.webp(?:\?|$)/) || [])[1];
			if (!id) continue;
			const card = await img.evaluateHandle((el) =>
				el.closest(".combatant-display") || el.parentElement.parentElement);
			const handle = card.asElement();
			if (!handle) continue;
			await handle.screenshot({ path: path.join(OUT, `${id}.png`) });
			seen.set(id, label);
		}
		await page.close();
	}
	await browser.close();
	console.log(`tersimpan ${seen.size} thumbnail di ${OUT}`);
	const missing = [];
	for (const id of seen.keys()) {
		const p = path.join(OUT, `${id}.png`);
		if (!fs.existsSync(p) || fs.statSync(p).size < 1000) missing.push(id);
	}
	if (missing.length) {
		console.error("thumbnail rusak/kosong:", missing.join(", "));
		process.exit(1);
	}
	// Samakan ke ukuran native portrait wiki (260x460), menghilangkan
	// pembulatan 1-3 px dari deviceScaleFactor.
	execFileSync("python3", [path.join(__dirname, "normalize-thumbs.py")], { stdio: "inherit" });
})().catch((err) => {
	console.error(err);
	process.exit(1);
});
