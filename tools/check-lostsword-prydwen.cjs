#!/usr/bin/env node
/**
 * Regresi potret & filter Lost Sword ala Prydwen.
 *
 * Sumber: https://www.prydwen.gg/lost-sword/characters (71 kartu karakter:
 * potret, rarity 3/4/5, class, element, position). Diimpor oleh
 * tools/lostsword/import-prydwen.py ke data/lostsword-prydwen.json dan
 * public/thumbs/lostsword-prydwen/.
 *
 * Dicek: metadata sampai ke indeks lean, thumbnail override menang, berkas
 * WebP/ikon ada, filter bar 4 baris tampil hanya di game ini, klik chip
 * menyaring secara kumulatif, Reset mengembalikan, dan kartu memakai potret
 * + bintang rarity + ikon atribut tanpa 404 / JS error.
 *
 * Usage: node tools/check-lostsword-prydwen.cjs
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const ok = (m, extra = "") => console.log("ok   " + m + (extra ? " — " + extra : ""));

(async () => {
	const idx = await fetch(`${BASE}/api/models?game=lostsword&lean=1`,
		{ cache: "no-store" }).then((r) => r.json());
	const models = idx.models || [];
	const withRarity = models.filter((m) => m.lsRarity);
	assert.ok(withRarity.length >= 200,
		`metadata Prydwen terlalu sedikit: ${withRarity.length}`);
	const kinds = (field) => [...new Set(withRarity.map((m) => m[field]).filter(Boolean))];
	assert.deepStrictEqual(kinds("lsRarity").sort(), [3, 4, 5]);
	assert.ok(kinds("lsClass").length >= 4);
	assert.ok(kinds("lsElement").length >= 5);
	assert.ok(kinds("lsPosition").length === 3);
	ok(`${withRarity.length}/${models.length} model punya metadata Prydwen`,
		`rarity ${kinds("lsRarity").sort().join("/")} · ${kinds("lsClass").length} class · `
		+ `${kinds("lsElement").length} elemen · ${kinds("lsPosition").length} posisi`);

	const thumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs;
	const overrides = Object.entries(thumbs)
		.filter(([k, v]) => k.startsWith("lostsword") && String(v).startsWith("lostsword-prydwen/"));
	assert.ok(overrides.length >= 300, `override thumbnail: ${overrides.length}`);
	ok(`${overrides.length} id model memakai potret Prydwen (override manifest)`);

	const dir = path.join(ROOT, "public", "thumbs", "lostsword-prydwen");
	const cards = fs.readdirSync(dir).filter((f) => f.endsWith("_card.webp"));
	const icons = fs.readdirSync(dir).filter((f) => /^(element|class|position)_/.test(f));
	assert.ok(cards.length >= 70 && icons.length >= 10,
		`kartu=${cards.length} ikon=${icons.length}`);
	let broken = 0;
	for (const f of [...cards, ...icons]) {
		const head = fs.readFileSync(path.join(dir, f)).subarray(0, 12);
		if (head.subarray(0, 4).toString() !== "RIFF" ||
			head.subarray(8, 12).toString() !== "WEBP") broken++;
	}
	assert.strictEqual(broken, 0, `berkas non-WebP: ${broken}`);
	ok(`${cards.length} potret + ${icons.length} ikon WebP valid`);

	const meta = JSON.parse(fs.readFileSync(
		path.join(ROOT, "data", "lostsword-prydwen.json"), "utf8"));
	assert.ok(meta.matchedFamilies >= 60 && Object.keys(meta.models).length >= 300);
	ok(`${meta.characters} karakter Prydwen · ${meta.matchedFamilies} family cocok`);

	// --- Browser ---------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	const errs = [], bad = [];
	page.on("pageerror", (e) => errs.push(e.message));
	page.on("response", (r) => {
		if (r.status() >= 400 && !r.url().includes("favicon")) bad.push(r.status() + " " + r.url());
	});
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	await page.waitForSelector('#game-list .game[data-key="lostsword"]',
		{ state: "visible", timeout: 90000 });
	// Filter tidak boleh tampil di daftar game.
	assert.strictEqual(await page.locator("#ls-filters").evaluate((e) => e.hidden), true);
	await page.locator('#game-list .game[data-key="lostsword"]').click();
	await page.waitForSelector("#model-list .gcard", { state: "visible", timeout: 90000 });
	await page.waitForTimeout(2000);
	const bar = await page.evaluate(() => {
		const box = document.querySelector("#ls-filters");
		return {
			hidden: box.hidden,
			rows: [...box.querySelectorAll(".ls-row")].map((r) => ({
				kind: r.dataset.kind,
				chips: [...r.querySelectorAll(".ls-chip")].map((c) => c.dataset.value),
			})),
			count: document.querySelector("#ls-count")?.textContent || "",
		};
	});
	assert.strictEqual(bar.hidden, false);
	assert.deepStrictEqual(bar.rows.map((r) => r.kind),
		["rarity", "class", "element", "position"]);
	assert.deepStrictEqual(bar.rows[0].chips, ["5", "4", "3"]);
	assert.ok(bar.rows[1].chips.length >= 4 && bar.rows[2].chips.length >= 5 &&
		bar.rows[3].chips.length === 3);
	ok(`filter bar: ${bar.rows.map((r) => r.kind + "=" + r.chips.length).join(", ")} · ${bar.count}`);

	const cardsUi = await page.evaluate(() => {
		const g = [...document.querySelectorAll("#model-list .gcard")];
		return {
			total: g.length,
			isLs: g.filter((x) => x.classList.contains("is-ls")).length,
			prydwen: g.filter((x) => x.querySelector("img.gcard-img")?.getAttribute("src")
				?.startsWith("/thumbs/lostsword-prydwen/")).length,
			badges: g.filter((x) => x.querySelector(".ls-card-badges")).length,
			stars: g.filter((x) => x.querySelector(".ls-card-stars")?.textContent.trim()).length,
		};
	});
	assert.strictEqual(cardsUi.isLs, cardsUi.total);
	assert.ok(cardsUi.prydwen >= 60 && cardsUi.badges >= 60 && cardsUi.stars >= 60,
		JSON.stringify(cardsUi));
	ok(`${cardsUi.total} kartu · ${cardsUi.prydwen} potret Prydwen · ${cardsUi.badges} badge`);

	const count = async () => Number(await page.locator("#model-count").textContent());
	const all = await count();
	await page.locator('.ls-row[data-kind="rarity"] .ls-chip[data-value="5"]').click();
	await page.waitForTimeout(800);
	const five = await count();
	assert.ok(five < all && five > 0, `5★: ${all} -> ${five}`);
	await page.locator('.ls-row[data-kind="element"] .ls-chip[data-value="Fire"]').click();
	await page.waitForTimeout(800);
	const combo = await count();
	assert.ok(combo < five, `5★ + Fire: ${five} -> ${combo}`);
	assert.strictEqual(await page.locator(".ls-chip.is-on").count(), 2);
	ok(`filter kumulatif: ${all} -> ${five} (5★) -> ${combo} (5★ + Fire)`);

	await page.locator("#ls-reset").click();
	await page.waitForTimeout(800);
	assert.strictEqual(await count(), all);
	assert.strictEqual(await page.locator(".ls-chip.is-on").count(), 0);
	ok(`Reset mengembalikan ${all} karakter`);
	assert.strictEqual(bad.length, 0, "404: " + bad.slice(0, 2).join(" | "));
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	ok("0 request 404, 0 JS error");
	await browser.close();
	console.log("\nThumbnail & filter Prydwen ok");
})().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
