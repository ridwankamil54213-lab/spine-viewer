#!/usr/bin/env node
/**
 * Regresi fitur "change log" per game.
 *
 *  A. Unit: recordApply() menyimpan diff model before/after, seed restore,
 *     status GDrive, dan urutan entri terbaru-dulu. Pakai file temp lewat
 *     CHANGE_LOG_FILE / NEW_MODELS_FILE supaya data produksi tidak tersentuh.
 *  B. HTTP: /api/change-logs (ringkasan) dan ?game=chaoszero (entri).
 *  C. UI  : tombol, ringkasan lintas-game, Escape, entri per-game dengan
 *     tanggal + chip model yang bisa diklik, 0 JS error.
 *
 * Usage: node tools/check-change-log.cjs
 */
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ok = (m) => console.log("ok   " + m);
const fail = (m) => { console.error("FAIL " + m); process.exitCode = 1; };

async function httpJson(url) {
	const r = await fetch(url, { cache: "no-store" });
	assert.ok(r.ok, `${url} -> HTTP ${r.status}`);
	return r.json();
}

(async () => {
	// --- A. Unit ---------------------------------------------------------
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cl-test-"));
	process.env.CHANGE_LOG_FILE = path.join(tmp, "change-logs.json");
	process.env.NEW_MODELS_FILE = path.join(tmp, "new-models.json");
	fs.writeFileSync(process.env.NEW_MODELS_FILE, JSON.stringify({
		known: [],
		flagged: {
			"unitgame/a": Date.now() - 86400000,
			"unitgame/b": Date.now() - 86400000,
		},
	}));
	const cl = require("../src/change-log");
	const entry = cl.recordApply({
		game: "unitgame",
		beforeIds: new Set(["unitgame/a"]),
		afterIds: new Set(["unitgame/a", "unitgame/b", "unitgame/c"]),
		result: { version: "v1", new: 2 },
		gdrive: { ok: true },
	});
	assert.strictEqual(entry.addedCount, 2);
	assert.ok(entry.added.includes("unitgame/b") && entry.added.includes("unitgame/c"));
	assert.strictEqual(entry.removedCount, 0);
	assert.strictEqual(entry.gdrive, true);
	assert.strictEqual(entry.diffAvailable, true);
	assert.ok(entry.at);
	const list = cl.forGame("unitgame");
	assert.strictEqual(list.length, 2, "harus ada 1 restore + 1 apply");
	assert.strictEqual(list[0].kind, "apply");
	assert.strictEqual(list[1].kind, "restore");
	assert.ok(list[1].addedCount === 2 && list[1].added.length === 2);
	ok("unit: diff model + seed restore + urutan terbaru + status GDrive");

	// --- B. HTTP ---------------------------------------------------------
	const all = await httpJson(BASE + "/api/change-logs");
	assert.ok(all.games.length >= 20, `ringkasan terlalu sedikit: ${all.games.length}`);
	assert.ok(all.games.some((g) => g.game === "chaoszero"));
	const cz = await httpJson(BASE + "/api/change-logs?game=chaoszero");
	assert.strictEqual(cz.label, "Chaos Zero Nightmare");
	assert.ok(cz.entries.length >= 2, "butuh entri apply + restore");
	const ap = cz.entries.find((e) => e.kind === "apply");
	assert.ok(ap && ap.gdrive === true && ap.diffAvailable === true && ap.version,
		"entri apply belum lengkap");
	const rs = cz.entries.find((e) => e.kind === "restore");
	assert.ok(rs && rs.addedCount > 0 && rs.added.length > 0,
		"entri restore tidak membawa model");
	ok(`HTTP: ${all.games.length} game, chaoszero ${cz.entries.length} entri (apply + restore)`);

	// --- C. UI -----------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errs = [];
	page.on("pageerror", (e) => errs.push(e.message));
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });

	// Masih di daftar game -> ringkasan lintas-game.
	await page.click("#change-log-btn");
	await page.waitForSelector("#change-log-modal:not([hidden])");
	await page.waitForFunction(
		() => document.querySelectorAll("#change-log-body .cl-game-row").length > 0,
		{ timeout: 20000 });
	const rows = await page.locator("#change-log-body .cl-game-row").count();
	assert.ok(rows > 0);
	ok(`UI ringkasan: ${rows} game punya riwayat`);

	await page.keyboard.press("Escape");
	await page.waitForFunction(
		() => document.getElementById("change-log-modal").hidden === true,
		{ timeout: 5000 });
	ok("UI: Escape menutup modal");

	await page.waitForSelector('.game[data-key="chaoszero"]', { timeout: 60000 });
	await page.click('.game[data-key="chaoszero"]');
	await page.waitForTimeout(2500);
	await page.click("#change-log-btn");
	await page.waitForSelector("#change-log-modal:not([hidden])");
	await page.waitForFunction(
		() => document.querySelectorAll("#change-log-body .cl-entry").length >= 2,
		{ timeout: 20000 });
	const entries = await page.locator("#change-log-body .cl-entry").count();
	const dates = await page.locator("#change-log-body .cl-date").count();
	const chips = await page.locator("#change-log-body .cl-model").count();
	assert.ok(entries >= 2 && dates >= 2 && chips > 0,
		`entri=${entries} tanggal=${dates} chip=${chips}`);
	const firstDate = (await page.locator("#change-log-body .cl-date").first().textContent()) || "";
	assert.match(firstDate, /\d{4}/, "tanggal tidak terbaca: " + firstDate);
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	ok(`UI per-game: ${entries} entri, ${dates} tanggal, ${chips} chip model, 0 JS error`);

	await page.locator("#change-log-body .cl-model:not(.is-gone)").first().click();
	await page.waitForFunction(
		() => document.getElementById("change-log-modal").hidden === true,
		{ timeout: 5000 });
	ok("UI: klik chip model menutup riwayat dan membuka model");

	await browser.close();
	fs.rmSync(tmp, { recursive: true, force: true });
	console.log("\nChange log ok");
})().catch((e) => { fail(e.message); console.error(e.stack?.split("\n").slice(0, 4).join("\n") || ""); process.exit(1); });
