#!/usr/bin/env node
/**
 * Regresi: log pembaruan tidak boleh hilang sebelum job selesai.
 *
 * Mensimulasikan urutan respons /status yang dulu bikin panel kosong:
 *   1) running + log berisi          -> tampil
 *   2) running TANPA field `log`     -> dulu menimpa dengan array kosong
 *   3) body kosong (fetch gagal)     -> dulu menghentikan polling
 *   4) running + log bertambah       -> harus tetap muncul
 *   5) selesai + log final
 *
 * Semua request /api/update/* dipalsukan lewat window.fetch; request lain
 * (pustaka model, thumbnail, dll) tetap mengarah ke server nyata.
 *
 * Usage: node tools/check-update-log.cjs
 */
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ok = (m) => console.log("ok   " + m);
const fail = (m) => { console.error("FAIL " + m); process.exitCode = 1; };

(async () => {
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const jsErrors = [];
	page.on("pageerror", (e) => jsErrors.push(e.message));
	page.on("dialog", (d) => d.accept());

	await page.addInitScript(() => {
		const orig = window.fetch.bind(window);
		const J = (o) => new Response(JSON.stringify(o), {
			status: 200, headers: { "Content-Type": "application/json" },
		});
		window.__statusSeq = 0;
		window.fetch = async (url, opts) => {
			const u = String(url);
			if (u.includes("/api/update/")) {
				// Sengaja TANPA field `log` supaya sesi log dimulai dari apply,
				// bukan dari log pemeriksaan (yang memang boleh di-reset).
				if (u.includes("mode=check")) return J({ ok: true, changed: true, new: 1 });
				if (u.includes("mode=apply")) return J({ started: true });
				if (u.includes("/status")) {
					const seq = window.__statusSeq++;
					const states = [
						{ running: true, game: "bd2", log: ["baris 1"] },
						{ running: true, game: "bd2" },
						null,
						{ running: true, game: "bd2", log: ["baris 1", "baris 2"] },
						{ running: false, game: "bd2", result: { ok: true }, log: ["baris 1", "baris 2", "selesai"] },
					];
					const pick = states[Math.min(seq, states.length - 1)];
					return pick === null ? new Response("", { status: 200 }) : J(pick);
				}
			}
			return orig(url, opts);
		};
	});

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	await page.waitForSelector('.game[data-key="bd2"]', { timeout: 60000 });
	await page.click('.game[data-key="bd2"]');
	await page.waitForSelector("#update-check:not([hidden])", { timeout: 30000 });
	await page.click("#update-check");

	const samples = [];
	for (let i = 0; i < 30; i++) {
		await page.waitForTimeout(500);
		const s = await page.evaluate(() => ({
			text: document.getElementById("update-log-view")?.textContent ?? "",
			status: document.getElementById("update-log-status")?.textContent ?? "",
		}));
		samples.push(s);
		if (s.status.includes("Selesai.") || s.status.includes("Gagal:")) break;
	}
	await browser.close();

	const texts = samples.map((s) => s.text);
	const firstFilled = texts.findIndex((t) => t.trim().length > 0);
	if (firstFilled < 0) return fail("log tidak pernah terisi");
	ok("log terisi pada sample #" + firstFilled + ": " + JSON.stringify(texts[firstFilled]));

	const vanished = texts.findIndex((t, i) => i > firstFilled && t.trim().length === 0);
	if (vanished >= 0) return fail("log menghilang pada sample #" + vanished + " sebelum selesai");
	ok("log tidak pernah kosong lagi setelah terisi (" + texts.length + " sample)");

	const last = texts[texts.length - 1] || "";
	if (!last.includes("selesai")) return fail("log akhir tidak memuat hasil: " + JSON.stringify(last.slice(-140)));
	ok("log akhir memuat baris 'selesai'");

	const finalStatus = samples[samples.length - 1].status || "";
	if (!finalStatus.includes("Selesai.")) return fail("status akhir: " + finalStatus);
	ok("status akhir 'Selesai.'");

	if (jsErrors.length) return fail("JS error: " + jsErrors.slice(0, 2).join(" | "));
	ok("0 JS error");
	console.log("\nLog pembaruan ok");
})().catch((e) => { console.error("FATAL " + e.message); process.exit(1); });
