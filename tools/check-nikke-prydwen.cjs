#!/usr/bin/env node
/**
 * Regresi potret & filter NIKKE ala Prydwen.
 *
 * Sumber: https://www.prydwen.gg/nikke/characters (227 karakter: potret,
 * rarity R/SR/SSR, class, element, weapon, manufacturer, burst). Diimpor
 * tools/nikke/import-prydwen.py lewat jembatan kode cNNN di
 * data/nikke-characters.json.
 *
 * Usage: node tools/check-nikke-prydwen.cjs
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const ok = (m, x = "") => console.log("ok   " + m + (x ? " — " + x : ""));

(async () => {
	const idx = await fetch(`${BASE}/api/models?game=nikke&lean=1`,
		{ cache: "no-store" }).then((r) => r.json());
	const models = idx.models || [];
	const withMeta = models.filter((m) => m.nkRarity);
	// Jumlah id menyusut setelah 553 folder duplikat dibersihkan; source of
	// truth adalah data/nikke-prydwen.json, bukan angka lama hasil dobel.
	assert.ok(withMeta.length >= 1200, `metadata Prydwen: ${withMeta.length}`);
	const vals = (f) => [...new Set(withMeta.map((m) => m[f]).filter(Boolean))];
	assert.deepStrictEqual(vals("nkRarity").sort(), ["R", "SR", "SSR"]);
	assert.strictEqual(vals("nkClass").length, 3);
	assert.strictEqual(vals("nkElement").length, 5);
	assert.strictEqual(vals("nkWeapon").length, 6);
	assert.strictEqual(vals("nkManufacturer").length, 5);
	assert.strictEqual(vals("nkBurst").length, 3);
	ok(`${withMeta.length}/${models.length} model punya metadata Prydwen`,
		`3 rarity · 3 class · 5 elemen · 6 senjata · 5 manufacturer · 3 burst`);

	const thumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs;
	// NKAS dipasang sebagai overlay paling akhir, jadi boleh menimpa path
	// Prydwen di /api/thumbnails; metadata filter tetap dari Prydwen.
	const overrides = Object.entries(thumbs).filter(([k, v]) =>
		k.startsWith("nikke") &&
		/^nikke-(prydwen|nkas)\//.test(String(v)));
	assert.ok(overrides.length >= 1200, `override: ${overrides.length}`);
	ok(`${overrides.length} id model memakai potret Prydwen`);

	// Folder Prydwen lama sudah dihapus; metadata tetap dari Prydwen, tetapi
	// potret & ikon sekarang tinggal di folder NKAS.
	const dir = path.join(ROOT, "public", "thumbs", "nikke-nkas");
	const cards = fs.readdirSync(dir).filter((f) => /^c\d{3,4}_\d{2}\.webp$/.test(f));
	const icons = fs.readdirSync(dir).filter((f) =>
		/^(element|class|weapon|type)_/.test(f));
	assert.ok(cards.length >= 220 && icons.length >= 20,
		`kartu=${cards.length} ikon=${icons.length}`);
	let broken = 0;
	for (const f of [...cards, ...icons]) {
		const h = fs.readFileSync(path.join(dir, f)).subarray(0, 12);
		if (h.subarray(0, 4).toString() !== "RIFF" ||
			h.subarray(8, 12).toString() !== "WEBP") broken++;
	}
	assert.strictEqual(broken, 0, `non-WebP: ${broken}`);
	ok(`${cards.length} potret NKAS + ${icons.length} ikon WebP valid`);

	const data = JSON.parse(fs.readFileSync(
		path.join(ROOT, "data", "nikke-prydwen.json"), "utf8"));
	assert.ok(data.characters >= 220 && data.codes >= 190 &&
		Object.keys(data.models).length >= 1200);
	ok(`${data.characters} karakter Prydwen · ${data.matchedPrydwen} cocok · ${data.codes} kode cNNN`);

	// --- Browser ---------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	const errs = [], bad = [];
	page.on("pageerror", (e) => errs.push(e.message));
	page.on("response", (r) => {
		if (r.status() >= 400 && !r.url().includes("favicon")) bad.push(r.status() + " " + r.url());
	});
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	await page.waitForSelector('#game-list .game[data-key="nikke"]',
		{ state: "visible", timeout: 90000 });
	assert.strictEqual(await page.locator("#nk-filters").evaluate((e) => e.hidden), true);
	await page.locator('#game-list .game[data-key="nikke"]').click();
	await page.waitForSelector("#model-list .gcard", { state: "visible", timeout: 90000 });
	await page.waitForTimeout(2200);

	const bar = await page.evaluate(() => {
		const box = document.querySelector("#nk-filters");
		return {
			hidden: box.hidden,
			rows: [...box.querySelectorAll(".ls-row")].map((r) => ({
				kind: r.dataset.kind,
				chips: [...r.querySelectorAll(".ls-chip")].map((c) => c.dataset.value),
			})),
			count: document.querySelector("#nk-count")?.textContent || "",
			lsHidden: document.querySelector("#ls-filters").hidden,
		};
	});
	assert.strictEqual(bar.hidden, false);
	assert.strictEqual(bar.lsHidden, true);
	assert.deepStrictEqual(bar.rows.map((r) => r.kind),
		["rarity", "class", "element", "weapon", "manufacturer", "burst"]);
	assert.deepStrictEqual(bar.rows[0].chips, ["SSR", "SR", "R"]);
	ok(`filter bar 6 dimensi · ${bar.count}`);

	const ui = await page.evaluate(() => {
		const g = [...document.querySelectorAll("#model-list .gcard")];
		return {
			n: g.length,
			portraits: g.filter((x) => /^\/thumbs\/nikke-(prydwen|nkas)\//
				.test(x.querySelector("img.gcard-img")?.getAttribute("src") || "")).length,
			badges: g.filter((x) => x.querySelector(".ls-card-badges")).length,
			ssr: g.filter((x) => x.dataset.nkRarity === "SSR").length,
		};
	});
	// Karakter diurutkan ke depan, jadi seluruh halaman 1 berpotret Prydwen.
	assert.ok(ui.n > 0 && ui.portraits === ui.n, JSON.stringify(ui));
	assert.ok(ui.badges === ui.n && ui.ssr > 0);
	ok(`halaman 1: ${ui.portraits}/${ui.n} potret Prydwen + ${ui.badges} badge`);

	const count = async () => Number(await page.locator("#model-count").textContent());
	const all = await count();
	await page.locator('#nk-filters .ls-row[data-kind="rarity"] .ls-chip[data-value="SSR"]').click();
	await page.waitForTimeout(900);
	const ssr = await count();
	await page.locator('#nk-filters .ls-row[data-kind="manufacturer"] .ls-chip[data-value="Pilgrim"]').click();
	await page.waitForTimeout(900);
	const combo = await count();
	assert.ok(ssr < all && combo < ssr, `${all} -> ${ssr} -> ${combo}`);
	assert.strictEqual(await page.locator("#nk-filters .ls-chip.is-on").count(), 2);
	ok(`filter kumulatif: ${all} -> ${ssr} (SSR) -> ${combo} (SSR + Pilgrim)`);

	await page.locator("#nk-reset").click();
	await page.waitForTimeout(900);
	assert.strictEqual(await count(), all);
	assert.strictEqual(await page.locator("#nk-filters .ls-chip.is-on").count(), 0);
	ok(`Reset mengembalikan ${all} model`);
	assert.strictEqual(bad.length, 0, "404: " + bad.slice(0, 2).join(" | "));
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	ok("0 request 404, 0 JS error");
	await browser.close();
	console.log("\nThumbnail & filter Prydwen (NIKKE) ok");
})().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
