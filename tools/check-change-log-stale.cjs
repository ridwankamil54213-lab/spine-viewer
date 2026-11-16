#!/usr/bin/env node
/**
 * Regresi: riwayat pembaruan vs indeks pustaka yang basi.
 *
 * Skenario nyata: apply dijalankan dari tab/perangkat lain. Tab ini masih
 * memegang snapshot /api/models lama, sementara /api/change-logs selalu
 * dibaca langsung dari server. Hasilnya entri "N model baru" tampil, tapi
 * chip-nya disabled ("sudah tidak ada") dan modelnya memang tidak ada di
 * daftar.
 *
 * Yang diuji:
 *  1. openChangeLog() mendeteksi ETag yang berubah (HEAD, tanpa body 12 MB)
 *     dan memanggil refresh(), sehingga jumlah model kembali lengkap.
 *  2. Chip model aktif (tidak is-gone / disabled).
 *  3. Klik chip mengarahkan pustaka: pindah game, hapus filter, lompat ke
 *     halaman yang benar, dan kartunya tersorot — walaupun markSeen()
 *     membuang badge NEW dan mengurut ulang daftar.
 *
 * Sengaja TIDAK bergantung pada isi data/change-logs.json produksi: respons
 * change-logs disuntik lewat route Playwright, dan id model diambil dari
 * indeks yang sedang berjalan.
 *
 * Usage: node tools/check-change-log-stale.cjs
 */
"use strict";

const assert = require("assert");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ok = (m) => console.log("ok   " + m);

async function main() {
	const idx = await fetch(`${BASE}/api/models?lean=1`).then((r) => r.json());
	const all = idx.models || [];
	assert.ok(all.length > 100, "indeks model terlalu kecil");

	// Game kecil supaya daftar muat satu halaman dan assertions stabil.
	const byGame = new Map();
	for (const m of all) {
		const g = m.game || "lainnya";
		if (!byGame.has(g)) byGame.set(g, []);
		byGame.get(g).push(m);
	}
	let game = null;
	let roots = [];
	for (const g of ["ryzachat", "azuretaboo", "epic7-wallpaper", "demo"]) {
		const rs = (byGame.get(g) || []).filter((m) => !m.family);
		if (rs.length >= 2) { game = g; roots = rs; break; }
	}
	assert.ok(game, "tidak ada game kecil untuk diuji");
	const target = roots[0].id;
	const staleModels = all.filter((m) => m.id !== target);
	const staleBody = JSON.stringify({ models: staleModels });
	ok(`game uji: ${game} · ${roots.length} root · target ${target}`);

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errs = [];
	page.on("pageerror", (e) => errs.push(e.message));

	let firstGet = true;
	await page.route("**/api/models?lean=1*", (route) => {
		if (route.request().method() === "HEAD") return route.continue();
		if (firstGet) {
			firstGet = false;
			return route.fulfill({
				status: 200,
				contentType: "application/json",
				headers: { "Cache-Control": "no-store" },
				body: staleBody,
			});
		}
		return route.continue();
	});

	// Riwayat sintetis: satu entri apply yang menyebut model yang "baru".
	const now = new Date().toISOString();
	await page.route(/\/api\/change-logs/, (route) => {
		const u = new URL(route.request().url());
		const body = u.searchParams.get("game")
			? { entries: [{
				at: now, kind: "apply", version: "test",
				added: [target], addedCount: 1,
				removed: [], removedCount: 0,
				diffAvailable: true, gdrive: true,
			}] }
			: { games: [{
				game, label: game, count: 1,
				newModels: 1, lastAt: now,
			}] };
		return route.fulfill({ status: 200, contentType: "application/json",
			body: JSON.stringify(body) });
	});

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	const tile = page.locator(`#game-list .game[data-key="${game}"]`);
	await tile.waitFor({ state: "visible", timeout: 90000 });
	await tile.click();
	await page.waitForSelector("#model-list .gcard, #model-list li > button:not(.model-fav)",
		{ state: "visible", timeout: 90000 });
	const before = Number(await page.locator("#model-count").textContent());
	assert.strictEqual(before, roots.length - 1,
		`indeks basi harus kehilangan 1 model: ${before} vs ${roots.length - 1}`);
	ok(`tab basi: ${before} model (target tidak ada)`);

	await page.locator("#change-log-btn").click();
	// syncChangeLog(game) membuat panel langsung menampilkan entri game ini;
	// kalau dibuka dari daftar semua game, akan ada baris game dulu.
	await page.waitForSelector(".cl-model, .cl-game-row",
		{ state: "visible", timeout: 30000 });
	if (await page.locator(".cl-game-row").count()) {
		await page.locator(".cl-game-row").first().click();
	}
	await page.waitForSelector(".cl-model", { state: "visible", timeout: 30000 });
	// ensureFreshModels() -> refresh(): ETag berubah, indeks ditarik ulang.
	await page.waitForFunction(
		(n) => Number(document.querySelector("#model-count")?.textContent) === n,
		roots.length, { timeout: 30000 });
	const after = Number(await page.locator("#model-count").textContent());
	assert.strictEqual(after, roots.length, `indeks tidak tersegarkan: ${after}`);
	const chip = page.locator(`.cl-model[title="${target}"]`);
	assert.strictEqual(await chip.count(), 1, "chip model tidak ada");
	assert.strictEqual(await chip.evaluate((e) => e.disabled), false,
		"chip masih disabled (sudah tidak ada)");
	assert.strictEqual(await chip.evaluate((e) => e.classList.contains("is-gone")), false);
	ok(`riwayat menyegarkan indeks: ${before} -> ${after}, chip aktif`);

	await chip.click();
	await page.waitForFunction(
		(id) => window.spineStage?.model?.id === id, target, { timeout: 60000 });
	await page.waitForTimeout(800);
	const state = await page.evaluate((id) => ({
		active: [...document.querySelectorAll("#model-list .is-active")].map((x) => x.dataset.id),
		visible: [...document.querySelectorAll("#model-list [data-id]")]
			.some((x) => x.dataset.id === id),
		search: document.querySelector("#search")?.value || "",
	}), target);
	assert.ok(state.visible, "kartu model tidak terlihat di daftar");
	assert.ok(state.active.includes(target), "kartu model tidak tersorot");
	assert.strictEqual(state.search, "", "filter pencarian tidak dibersihkan");
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	ok(`klik chip: kartu terlihat + tersorot, stage = ${target}, 0 JS error`);

	await browser.close();
	console.log("\nChange-log vs indeks basi ok");
}

main().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
