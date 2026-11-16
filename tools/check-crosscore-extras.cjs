#!/usr/bin/env node
/**
 * Regresi impor EFEK / TOUCH / SOUND CrossCore dari crosscore.art.
 *
 * - 227 rig efek jadi model varian dengan atlas + halaman lengkap
 * - 188 model punya audio.tracks, klipnya tersaji 200 dari /audio/crosscore/
 * - 225 model punya zona sentuh di /api/interaction/crosscore, dan prefab-nya
 *   benar-benar cocok dengan id folder model
 * - Browser: tombol audio muncul, tap memicu request klip, rig efek render
 *
 * Usage: node tools/check-crosscore-extras.cjs
 */
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const ok = (m) => console.log("ok   " + m);

(async () => {
	const d = await fetch(`${BASE}/api/models?lean=1`, { cache: "no-store" }).then((r) => r.json());
	const all = d.models || (Array.isArray(d) ? d : []);
	const cc = all.filter((m) => m.game === "crosscore");
	const eff = cc.filter((m) => m.character?.rig === "efek");
	const voiced = cc.filter((m) => (m.audio?.tracks || []).length);
	assert.strictEqual(eff.length, 227, `rig efek: ${eff.length}`);
	assert.strictEqual(voiced.length, 188, `model bersuara: ${voiced.length}`);
	ok(`${eff.length} rig efek, ${voiced.length} model bersuara, total ${cc.length} model`);

	// Integritas berkas efek: json + atlas + halaman yang dirujuk ada.
	let broken = 0;
	for (const m of eff) {
		const stem = m.id.split("/").pop();
		const dir = path.join(ROOT, "assets", "crosscore", stem);
		const skel = path.join(dir, stem + ".json");
		const atlas = path.join(dir, stem + ".atlas");
		if (!fs.existsSync(skel) || !fs.existsSync(atlas)) { broken++; continue; }
		const pages = fs.readFileSync(atlas, "utf8").split(/\r?\n/)
			.filter((l) => l && !l.startsWith(" ") && /\.(png|webp|jpg)$/i.test(l.trim()));
		if (!pages.length || pages.some((p) => !fs.existsSync(path.join(dir, p.trim())))) broken++;
	}
	assert.strictEqual(broken, 0, `efek rusak: ${broken}`);
	ok("227 folder efek lengkap (json + atlas + halaman tekstur)");

	// Klip audio tersaji.
	const sample = voiced[0].audio.tracks.slice(0, 5);
	for (const u of sample) {
		const r = await fetch(BASE + u);
		assert.strictEqual(r.status, 200, `${u} -> ${r.status}`);
	}
	const extras = JSON.parse(fs.readFileSync(path.join(ROOT, "assets/crosscore/_extras.json"), "utf8"));
	assert.strictEqual(Object.keys(extras.subtitles).length, 3638);
	ok(`${sample.length} klip audio HTTP 200, ${Object.keys(extras.subtitles).length} subtitle tersimpan`);

	// Zona sentuh: prefab harus cocok dengan folder model.
	const inter = await fetch(`${BASE}/api/interaction/crosscore`).then((r) => r.json());
	assert.ok(inter.models.length >= 200, `model interaksi: ${inter.models.length}`);
	const ids = new Set(cc.map((m) => m.id.split("/").pop().toLowerCase()));
	const actions = inter.models.reduce((n, m) => n + m.actions.length, 0);
	assert.ok(actions >= 1500, `aksi: ${actions}`);
	assert.ok(inter.models.every((m) => ids.has(m.prefab)), "ada prefab yang tidak cocok model");
	const withClip = inter.models.filter((m) => m.actions.some((a) => (a.audioId || []).some((x) => /\.webm$/.test(x))));
	assert.ok(withClip.length >= 100, `aksi bersuara: ${withClip.length}`);
	ok(`${inter.models.length} model touch / ${actions} aksi, ${withClip.length} punya klip, prefab valid`);

	// --- Browser ---------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errs = [], bad = [], clips = [];
	page.on("pageerror", (e) => errs.push(e.message));
	page.on("console", (m) => m.type() === "error" && errs.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /assets\/|audio\//.test(r.url())) bad.push(r.status() + " " + r.url());
		if (/audio\/crosscore\/clips/.test(r.url())) clips.push(r.status());
	});
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	await page.waitForSelector('#game-list .game[data-key="crosscore"]', { state: "visible", timeout: 90000 });
	await page.locator('#game-list .game[data-key="crosscore"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible", timeout: 90000 });
	const rootId = "crosscore/acheron_game-3005002_legacy-acheron";
	const voiceId = "crosscore/acheron_game-3005003_legacy-30050_skin_acheron03_spine";
	const effectId = "crosscore/acheron_game-3005002_legacy-acheron_effB";
	await page.fill("#search", rootId);
	await page.locator(`#model-list [data-id="${rootId}"]`).first()
		.waitFor({ state: "visible", timeout: 30000 });
	await page.locator(`#model-list [data-id="${rootId}"]`).first().click();
	await page.waitForFunction(() => !!window.spineStage?.model?.id, null, { timeout: 90000 });
	const jump = (t) => page.evaluate((id) => {
		const s = document.querySelector("#variant-select");
		const o = [...(s?.options || [])].find((x) => x.dataset.id === id);
		if (!o) return false;
		s.value = o.value;
		s.dispatchEvent(new Event("change", { bubbles: true }));
		return true;
	}, t);
	assert.ok(await jump(voiceId), "varian bersuara tidak ada di picker");
	await page.waitForFunction((id) => window.spineStage?.model?.id === id, voiceId, { timeout: 90000 });
	await page.waitForTimeout(2000);
	const v = await page.evaluate(() => ({
		tracks: window.spineStage?.model?.audio?.tracks?.length || 0,
		btnHidden: document.querySelector("#audio-btn")?.hidden,
	}));
	assert.ok(v.tracks > 0 && v.btnHidden === false, JSON.stringify(v));
	ok(`tombol audio tampil (${v.tracks} track) pada varian bersuara`);
	await page.locator("#canvas-wrap").click({ position: { x: 400, y: 300 } }).catch(() => {});
	await page.waitForFunction(
		() => (document.querySelector("#toast")?.textContent || "").trim().length > 0,
		null, { timeout: 4000 }).catch(() => {});
	const line = await page.evaluate(() =>
		(document.querySelector("#toast")?.textContent || "").trim());
	await page.waitForTimeout(2500);
	assert.ok(clips.length > 0, "tap tidak memicu request klip audio");
	ok(`tap memicu klip audio (${clips.length} request, status ${clips[0]})`);
	assert.ok(line.length > 0, "subtitle voice-line tidak tampil");
	ok(`subtitle tampil di toast: "${line.slice(0, 32)}"`);
	assert.ok(await jump(effectId), "varian efek tidak ada di picker");
	await page.waitForFunction((id) => window.spineStage?.model?.id === id, effectId, { timeout: 90000 });
	await page.waitForTimeout(2500);
	const e = await page.evaluate(() => ({
		rig: window.spineStage?.model?.character?.rig,
		canvas: !!document.querySelector("canvas"),
	}));
	assert.strictEqual(e.rig, "efek");
	assert.ok(e.canvas);
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	assert.strictEqual(bad.length, 0, "aset 404: " + bad.slice(0, 2).join(" | "));
	ok("rig efek ter-render, 0 aset 404, 0 JS error");
	await browser.close();
	console.log("\nCrossCore efek/touch/sound ok");
})().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
