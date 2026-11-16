#!/usr/bin/env node
/**
 * Regresi replace NIKKE: pohon aset harus persis katalog kanonik.
 *
 * Menjaga regression yang baru saja dibersihkan:
 *   - 553 folder sisa pipeline lama (nama polos `777`, `absolute`, ... atau
 *     `__catalog-...`) tidak boleh balik;
 *   - 430 model `#` dari beberapa skel dalam satu folder tidak boleh balik;
 *   - folder = _names.json = /api/models, tanpa yang kurang/lebih.
 *
 * Usage: node tools/check-nikke-clean.cjs
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const ASSETS = path.join(ROOT, "assets", "nikke");
const ok = (m, x = "") => console.log("ok   " + m + (x ? " — " + x : ""));
const PAGE_EXT = /\.(png|webp|jpe?g)$/i;

(async () => {
	const names = JSON.parse(fs.readFileSync(path.join(ASSETS, "_names.json"), "utf8"));
	const canonical = new Set(Object.keys(names).map((k) => k.replace(/^nikke\//, "")));
	assert.ok(canonical.size >= 2100, `katalog: ${canonical.size}`);

	const folders = new Set(fs.readdirSync(ASSETS, { withFileTypes: true })
		.filter((d) => d.isDirectory()).map((d) => d.name));
	const extra = [...folders].filter((f) => !canonical.has(f)).sort();
	const missing = [...canonical].filter((f) => !folders.has(f)).sort();
	assert.deepStrictEqual(extra, [], "folder asing: " + extra.slice(0, 8).join(", "));
	assert.deepStrictEqual(missing, [], "folder kurang: " + missing.slice(0, 8).join(", "));
	ok(`folder disk persis katalog (${folders.size})`, "0 sisa pipeline lama");

	const hashes = [...folders].filter((f) => f.includes("#"));
	const legacy = [...folders].filter((f) => f.includes("__catalog-"));
	assert.deepStrictEqual(hashes, [], "id #: " + hashes.slice(0, 5).join(", "));
	assert.deepStrictEqual(legacy, [], "folder __catalog-: " + legacy.slice(0, 5).join(", "));
	ok("0 model # dan 0 folder __catalog- dobel");

	let broken = 0;
	for (const id of canonical) {
		const d = path.join(ASSETS, id);
		const skel = path.join(d, `${id}.skel`);
		const atlas = path.join(d, `${id}.atlas`);
		if (!fs.existsSync(skel) || !fs.existsSync(atlas)) { broken++; continue; }
		const text = fs.readFileSync(atlas, "utf8").replace(/^\uFEFF/, "");
		const pages = [...new Set(text.split(/\r?\n/).map((s) => s.trim().replace(/^\uFEFF/, ""))
			.filter((s) => PAGE_EXT.test(s) && !/[\/\\]/.test(s)))];
		for (const p of pages) if (!fs.existsSync(path.join(d, p))) { broken++; break; }
	}
	assert.strictEqual(broken, 0, `${broken} folder tidak lengkap`);
	ok(`${canonical.size} folder lengkap (skel + atlas + semua halaman)`);

	const api = (await fetch(`${BASE}/api/models?game=nikke&lean=1`,
		{ cache: "no-store" }).then((r) => r.json())).models || [];
	const apiIds = api.map((m) => m.id);
	assert.strictEqual(new Set(apiIds).size, apiIds.length, "id API duplikat");
	const leaves = new Set(apiIds.map((id) => id.split("/").pop().split("#")[0]));
	assert.deepStrictEqual([...leaves].sort(), [...canonical].sort());
	ok(`API = katalog (${api.length} model, 0 duplikat id)`);

	const thumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs || {};
	const nikkeThumbs = Object.keys(thumbs).filter((k) => k.startsWith("nikke/"));
	// Empat `*_skillcut` tidak punya poster di repositori hulu (404), jadi
	// wajar tidak punya thumbnail ArtHub; model dan rig-nya tetap lengkap.
	// Dua di antaranya dapat potret Prydwen lewat override.
	const tanpaPoster = [
		"c019_00_skillcut", "c019_01_skillcut",
		"c150_00_skillcut--core-26174", "c471_01_skillcut",
	];
	const kurangThumb = [...canonical].filter((f) =>
		!nikkeThumbs.includes("nikke/" + f) && !tanpaPoster.includes(f));
	assert.deepStrictEqual(kurangThumb, [], "thumbnail kurang: " + kurangThumb.slice(0, 5).join(", "));
	ok(`thumbnail mencakup ${nikkeThumbs.length}/${canonical.size} model (2 poster tidak ada di hulu)`);

	const chk = await fetch(`${BASE}/api/update/nikke?mode=check`,
		{ cache: "no-store" }).then((r) => r.json());
	// Katalog ArtHub/NKAS bisa sah bertambah. Yang dilarang adalah folder
	// asing/# di disk — sudah dicek di atas — bukan updater yang melaporkan
	// model baru dari hulu.
	assert.strictEqual(chk.ok, true, JSON.stringify(chk.alasan));
	if (chk.changed) {
		assert.ok((chk.alasan || []).some((a) => /katalog ArtHub nikki berubah/.test(a)) &&
			(chk.new || 0) > 0, JSON.stringify(chk.alasan));
	}
	assert.strictEqual(chk.disk.folders, canonical.size);
	assert.strictEqual(chk.disk.thumbManifest,
		canonical.size - tanpaPoster.length,
		`thumbManifest ${chk.disk.thumbManifest} vs ${canonical.size}`);
	assert.ok(chk.disk.thumbs >= canonical.size - tanpaPoster.length,
		`thumb ${chk.disk.thumbs} vs ${canonical.size}`);
	ok(`updater ${chk.changed ? "ada katalog baru" : "bersih"} (expected ${chk.expected}, disk ${chk.disk.folders})`);

	console.log("\nPohon NIKKE bersih — 0 duplikat");
})().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
