#!/usr/bin/env node
/**
 * Regresi thumbnail CrossCore.
 *
 * crosscore.art cuma punya 79 ilustrasi statis; tools/crosscore/render-thumbs.cjs
 * merender 408 rig utama jadi WebP dan memetakan 227 rig efek ke thumbnail
 * induknya. Hasilnya SELURUH 713 model crosscore punya thumbnail.
 *
 * Dicek: kelengkapan /api/thumbnails, berkas di disk, magic WebP, HTTP 200,
 * pemetaan efek -> induk, dan <img> kartu (grid `.gcard-img` maupun daftar
 * `.model-thumb`) benar-benar terload di browser, bukan placeholder inisial.
 *
 * Usage: node tools/check-crosscore-thumbs.cjs
 */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const ok = (m) => console.log("ok   " + m);
const parentOf = (id) => id.replace(/_(effF|effB)$/, "");

(async () => {
	const idx = await fetch(`${BASE}/api/models?lean=1`, { cache: "no-store" }).then((r) => r.json());
	const all = idx.models || (Array.isArray(idx) ? idx : []);
	const cc = all.filter((m) => m.game === "crosscore");
	assert.strictEqual(cc.length, 713, `model crosscore: ${cc.length}`);
	const thumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs;
	const missing = cc.filter((m) => !thumbs[m.id]);
	assert.strictEqual(missing.length, 0,
		`tanpa thumbnail: ${missing.length} (${missing.slice(0, 3).map((m) => m.id).join(", ")})`);
	ok(`${cc.length}/${cc.length} model crosscore punya entri thumbnail`);

	// Berkas nyata + magic WebP (tidak butuh library gambar).
	let rendered = 0;
	for (const m of cc) {
		const rel = thumbs[m.id];
		const f = path.join(ROOT, "public", "thumbs", rel);
		assert.ok(fs.existsSync(f), `berkas hilang: ${rel}`);
		const head = fs.readFileSync(f).subarray(0, 12);
		assert.strictEqual(head.subarray(0, 4).toString(), "RIFF", `bukan RIFF: ${rel}`);
		assert.strictEqual(head.subarray(8, 12).toString(), "WEBP", `bukan WebP: ${rel}`);
		if (rel.startsWith("crosscore-render/")) rendered++;
	}
	ok(`${rendered} thumbnail hasil render + ${cc.length - rendered} ilustrasi CG valid WebP`);

	// Efek overlay memakai thumbnail rig induknya (rignya cuma lapisan partikel).
	const effects = cc.filter((m) => /_(effF|effB)$/.test(m.id));
	assert.strictEqual(effects.length, 227, `rig efek: ${effects.length}`);
	const wrong = effects.filter((m) => thumbs[m.id] !== thumbs[parentOf(m.id)]);
	assert.strictEqual(wrong.length, 0,
		`efek tak memakai thumb induk: ${wrong.slice(0, 2).map((m) => m.id).join(", ")}`);
	ok(`${effects.length} varian efek memakai thumbnail induknya`);

	// Sajian statis.
	const sample = cc.filter((m) => thumbs[m.id].startsWith("crosscore-render/")).slice(0, 6);
	for (const m of sample) {
		const r = await fetch(`${BASE}/thumbs/${thumbs[m.id]}`);
		assert.strictEqual(r.status, 200, `${thumbs[m.id]} -> ${r.status}`);
		assert.match(r.headers.get("content-type") || "", /image\//);
	}
	ok(`${sample.length} thumbnail hasil render tersaji HTTP 200`);

	// Browser: kartu perpustakaan memakai <img> yang benar-benar ke-load.
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errs = [], bad = [];
	page.on("pageerror", (e) => errs.push(e.message));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\/thumbs\//.test(r.url())) bad.push(r.status() + " " + r.url());
	});
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	await page.waitForSelector('#game-list .game[data-key="crosscore"]',
		{ state: "visible", timeout: 90000 });
	await page.locator('#game-list .game[data-key="crosscore"]').click();
	// Layout bawaan = grid (img.gcard-img); tombol X mengganti ke daftar
	// (img.model-thumb). Terima keduanya supaya regresi tidak bergantung layout.
	await page.waitForSelector("#model-list .gcard, #model-list li > button:not(.model-fav)",
		{ state: "visible", timeout: 90000 });
	await page.waitForTimeout(2500);
	const cards = await page.evaluate(() => {
		const imgs = [...document.querySelectorAll("#model-list img.gcard-img, #model-list img.model-thumb")];
		return {
			total: imgs.length,
			loaded: imgs.filter((i) => i.complete && i.naturalWidth > 0).length,
			rendered: imgs.filter((i) => i.getAttribute("src")?.startsWith("/thumbs/crosscore-render/")).length,
			placeholders: document.querySelectorAll("#model-list .gcard-none, #model-list .model-thumb-none").length,
		};
	});
	assert.ok(cards.total > 0, "tidak ada img.model-thumb");
	assert.ok(cards.loaded > 0, "tidak ada thumbnail yang ke-load: " + JSON.stringify(cards));
	assert.ok(cards.rendered > 0, "tidak ada thumbnail hasil render: " + JSON.stringify(cards));
	assert.strictEqual(bad.length, 0, "thumbnail 404: " + bad.slice(0, 2).join(" | "));
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	ok(`kartu pustaka: ${cards.loaded}/${cards.total} gambar ke-load, `
		+ `${cards.rendered} dari crosscore-render, ${cards.placeholders} placeholder, 0 404`);
	await browser.close();
	console.log("\nThumbnail CrossCore ok");
})().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
