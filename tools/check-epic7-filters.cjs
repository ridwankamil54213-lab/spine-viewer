#!/usr/bin/env node
/**
 * Regresi filter Epic Seven ala https://epic7db.com/heroes.
 *
 * Usage: node tools/check-epic7-filters.cjs
 */
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const ok = (m, x = "") => console.log("ok   " + m + (x ? " — " + x : ""));

(async () => {
	const db = JSON.parse(fs.readFileSync(
		path.join(ROOT, "data", "epic7db-heroes.json"), "utf8"));
	const entries = Object.values(db.byModel || {});
	assert.ok(db.heroes >= 300 && entries.length >= 400,
		`Epic7DB: ${db.heroes} hero / ${entries.length} model`);
	const zodiac = new Set(entries.map((x) => x.zodiac).filter(Boolean));
	const effects = new Set(entries.flatMap((x) => x.effects || []));
	assert.ok(zodiac.size >= 12 && effects.size >= 50,
		`zodiac=${zodiac.size} effects=${effects.size}`);
	ok(`${db.heroes} hero Epic7DB · ${entries.length} model · ${zodiac.size} zodiac · ${effects.size} efek`);

	const models = (await fetch(`${BASE}/api/models?game=epic7&lean=1`,
		{ cache: "no-store" }).then((r) => r.json())).models || [];
	for (const f of ["e7Stars", "e7Element", "e7Class", "e7Zodiac", "e7Effects"]) {
		assert.ok(models.some((m) => m[f] !== undefined && m[f] !== null),
			`field ${f} tidak ada di API`);
	}
	ok("field e7* ikut ke payload lean");

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	const errs = [], bad = [];
	page.on("pageerror", (e) => errs.push(e.message));
	page.on("response", (r) => {
		if (r.status() >= 400 && !r.url().includes("favicon")) bad.push(r.status() + " " + r.url());
	});
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	await page.waitForSelector('#game-list .game[data-key="epic7"]',
		{ state: "visible", timeout: 90000 });
	assert.strictEqual(await page.locator("#e7-filters").evaluate((e) => e.hidden), true);
	await page.locator('#game-list .game[data-key="epic7"]').click();
	await page.waitForSelector("#model-list .gcard", { state: "visible", timeout: 90000 });
	await page.waitForTimeout(1600);

	const ui = await page.evaluate(() => {
		const box = document.querySelector("#e7-filters");
		return {
			hidden: box.hidden,
			rows: [...box.querySelectorAll(".ls-row")].map((r) => ({
				kind: r.dataset.kind,
				chips: r.querySelectorAll(".ls-chip").length,
			})),
			count: document.querySelector("#model-count")?.textContent || "",
			nkHidden: document.querySelector("#nk-filters").hidden,
			lsHidden: document.querySelector("#ls-filters").hidden,
		};
	});
	assert.strictEqual(ui.hidden, false);
	assert.deepStrictEqual(ui.rows.map((r) => r.kind),
		["stars", "element", "class", "zodiac", "effect"]);
	assert.ok(ui.rows.every((r) => r.chips > 0), JSON.stringify(ui.rows));
	assert.strictEqual(ui.nkHidden, true);
	assert.strictEqual(ui.lsHidden, true);
	ok(`filter tampil: ${ui.rows.map((r) => r.kind + "=" + r.chips).join(" · ")}`);

	const count = async () => Number(await page.locator("#model-count").textContent());
	const all = await count();
	const star = '#e7-filters .ls-row[data-kind="stars"] .ls-chip[data-value="5"]';
	await page.locator(star).click();
	await page.waitForTimeout(750);
	const five = await count();
	assert.ok(five > 0 && five < all, `${all} -> ${five}`);
	assert.strictEqual(await page.locator(star).evaluate((e) => e.classList.contains("is-on")), true);
	ok(`bintang 5★: ${all} -> ${five}`);

	const elem = '#e7-filters .ls-row[data-kind="element"] .ls-chip[data-value="Fire"]';
	await page.locator(elem).click();
	await page.waitForTimeout(750);
	const fire = await count();
	assert.ok(fire > 0 && fire < five, `${five} -> ${fire}`);
	ok(`5★ + Fire: ${five} -> ${fire}`);

	const fx = '#e7-filters .ls-row[data-kind="effect"] .ls-chip[data-value="dispel"]';
	if (await page.locator(fx).count()) {
		await page.locator(fx).click();
		await page.waitForTimeout(750);
		const withFx = await count();
		assert.ok(withFx > 0 && withFx <= fire, `${fire} -> ${withFx}`);
		ok(`+ status effect dispel: ${fire} -> ${withFx}`);
	}

	await page.locator("#e7-reset").click();
	await page.waitForTimeout(750);
	assert.strictEqual(await count(), all);
	assert.strictEqual(await page.locator("#e7-filters .ls-chip.is-on").count(), 0);
	ok(`reset kembali ke ${all}`);

	assert.strictEqual(bad.length, 0, "404: " + bad.slice(0, 2).join(" | "));
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	ok("0 request 404, 0 JS error");
	await browser.close();
	console.log("\nFilter Epic Seven ok");
})().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
