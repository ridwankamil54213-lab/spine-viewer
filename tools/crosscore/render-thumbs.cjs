#!/usr/bin/env node
/**
 * Render thumbnail CrossCore dari rig Spine yang tampil di viewer.
 *
 * crosscore.art hanya menyediakan 79 ilustrasi statis; 635 rig (408 utama +
 * 227 efek) tidak punya gambar sama sekali. Tool ini membuka tiap rig lewat
 * permalink `?v=<base64url {m:id}>`, menycreenshot canvas WebGL, lalu
 * tools/crosscore/normalize-thumbs.py memotong ke subjek dan menyimpan WebP.
 *
 * Kenapa screenshot, bukan canvas.toDataURL(): stage memakai WebGL tanpa
 * preserveDrawingBuffer, jadi toDataURL() mengembalikan gambar hitam polos.
 * Kenapa viewport 1200x800: di bawah ~1000px layout berubah jadi stack dan
 * canvas bergeser ke y≈4000 sehingga clip screenshot gagal.
 *
 * Efek overlay TIDAK dirender sendiri (rignya cuma lapisan partikel di atas
 * rig induk, hasilnya sepi); mereka memakai thumbnail rig induknya.
 *
 * Hasil:
 *   public/thumbs/crosscore-render/<slug>.webp     408 potret
 *   public/thumbs/crosscore-render/_manifest.json  635 model -> berkas thumb
 *
 * thumbManifest() di server menggabungkan SEMUA folder public/thumbs/*, jadi
 * 78 model crosscore-cg tetap memakai manifest lamanya (kunci tidak bentrok).
 *
 * Idempoten: berkas WebP yang sudah ada dilewati. Aman dijalankan ulang setelah
 * impor scene baru.
 *
 * Usage:
 *   node tools/crosscore/render-thumbs.cjs [--workers 3] [--limit N] [--force]
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..", "..");
const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const CROSS = path.join(ROOT, "assets", "crosscore");
const DEST = path.join(ROOT, "public", "thumbs", "crosscore-render");
const RAW = path.join(DEST, "_raw");
const MANIFEST = path.join(DEST, "_manifest.json");
const NORMALIZE = path.join(__dirname, "normalize-thumbs.py");
const VIEWPORT = { width: 1200, height: 800 };

/** Cari interpreter yang benar-benar punya Pillow. `/usr/bin/python3` di host
 * ini TIDAK memilikinya, sedangkan venv proyek dan venv agen memilikinya. */
function pythonWithPillow() {
	const candidates = [process.env.THUMB_PYTHON, "/srv/venv-spine/bin/python",
		"/usr/bin/python3", "python3"].filter(Boolean);
	for (const p of candidates) {
		try {
			execFileSync(p, ["-c", "import PIL"], { stdio: "ignore", timeout: 15000 });
			return p;
		} catch { /* coba berikutnya */ }
	}
	throw new Error("tidak ada Python dengan Pillow (set THUMB_PYTHON=...)");
}

const arg = (name, def) => {
	const i = process.argv.indexOf(name);
	return i < 0 ? def : (process.argv[i + 1] ?? def);
};
const WORKERS = Math.max(1, Math.min(6, Number(arg("--workers", 3)) || 3));
const LIMIT = Number(arg("--limit", 0)) || 0;
const FORCE = process.argv.includes("--force");

const safe = (id) => String(id).replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 150);
const isEffect = (id) => /_(effF|effB)$/.test(id);
const parentOf = (id) => id.replace(/_(effF|effB)$/, "");

/** Daftar model langsung dari DISK, bukan /api/models — tidak bergantung pada
 * indeks server yang mungkin masih basi saat tool dijalankan setelah apply. */
function diskModels() {
	const rigs = [];
	for (const name of fs.readdirSync(CROSS, { withFileTypes: true })) {
		if (!name.isDirectory()) continue;
		const stem = name.name;
		if (!fs.existsSync(path.join(CROSS, stem, stem + ".json"))) continue;
		rigs.push("crosscore/" + stem);
	}
	return rigs;
}

function manifestFor(rigs) {
	const map = {};
	const missing = [];
	for (const id of rigs) {
		let src = id;
		if (isEffect(id)) src = parentOf(id);
		const file = safe(src) + ".webp";
		if (!fs.existsSync(path.join(DEST, file))) {
			missing.push(id);
			continue;
		}
		// Nilai manifest biasa (tanpa prefix folder): thumbManifest() menambahkan
		// "crosscore-render/" sendiri saat menggabungkan.
		map[id] = file;
	}
	return { map, missing };
}

async function renderOne(page, id) {
	const v = Buffer.from(JSON.stringify({ m: id })).toString("base64url");
	await page.goto(`${BASE}/?v=${v}`, { waitUntil: "domcontentloaded", timeout: 90000 });
	await page.waitForFunction((want) => window.spineStage?.model?.id === want, id,
		{ timeout: 45000 });
	// Tunggu beberapa frame supaya tekstur selesai di-upload dan pose idle jalan.
	await page.waitForTimeout(1800);
	const box = await page.evaluate(() => {
		const c = [...document.querySelectorAll("canvas")].find((x) => x.width > 300);
		if (!c) return null;
		const r = c.getBoundingClientRect();
		return { x: Math.round(r.x), y: Math.round(r.y),
			width: Math.round(r.width), height: Math.round(r.height) };
	});
	if (!box || box.width < 200 || box.height < 200) throw new Error("canvas tidak valid");
	const out = path.join(RAW, safe(id) + ".png");
	await page.screenshot({ path: out, clip: box, timeout: 30000 });
	if (fs.statSync(out).size < 3000) throw new Error("screenshot terlalu kecil/kosong");
	return out;
}

(async () => {
	fs.mkdirSync(RAW, { recursive: true });
	const rigs = diskModels();
	const mains = rigs.filter((id) => !isEffect(id));
	const effects = rigs.filter(isEffect);
	let todo = mains.filter((id) => FORCE || !fs.existsSync(path.join(DEST, safe(id) + ".webp")));
	if (LIMIT) todo = todo.slice(0, LIMIT);
	console.log(`rig: ${rigs.length} (${mains.length} utama + ${effects.length} efek) | `
		+ `akan dirender: ${todo.length} | workers: ${WORKERS}`);

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const context = await browser.newContext({ viewport: VIEWPORT });
	const pages = [];
	for (let i = 0; i < Math.min(WORKERS, Math.max(1, todo.length)); i++) {
		pages.push(await context.newPage());
	}
	const failed = [];
	let done = 0;
	let cursor = 0;
	const t0 = Date.now();
	await Promise.all(pages.map(async (page) => {
		for (;;) {
			const i = cursor++;
			if (i >= todo.length) break;
			const id = todo[i];
			try {
				await renderOne(page, id);
			} catch (err) {
				failed.push(`${id}: ${String(err.message).slice(0, 120)}`);
			}
			done++;
			if (done % 25 === 0 || done === todo.length) {
				console.log(`  ${done}/${todo.length} | gagal ${failed.length} | `
					+ `${Math.round((Date.now() - t0) / 1000)} dtk`);
			}
		}
	}));
	await browser.close();

	// Potong ke subjek + resize + WebP (Pillow).
	const norm = execFileSync(pythonWithPillow(), [NORMALIZE, DEST],
		{ encoding: "utf8", timeout: 600000 });
	process.stdout.write(norm);

	const { map, missing } = manifestFor(rigs);
	const sorted = {};
	for (const k of Object.keys(map).sort()) sorted[k] = map[k];
	fs.writeFileSync(MANIFEST, JSON.stringify(sorted, null, 1) + "\n");
	const result = {
		ok: failed.length === 0 && missing.length === 0 && Object.keys(map).length === rigs.length,
		rendered: todo.length,
		manifest: Object.keys(map).length,
		rigs: rigs.length,
		effectsMapped: effects.filter((id) => map[id]).length,
		missing: missing.slice(0, 8),
		failed: failed.slice(0, 8),
		seconds: Math.round((Date.now() - t0) / 100) / 10,
	};
	console.log(JSON.stringify(result, null, 1));
	if (!result.ok) process.exitCode = 1;
})().catch((err) => {
	console.error("FATAL " + err.message);
	process.exit(1);
});
