#!/usr/bin/env node
/**
 * Verifikasi end-to-end Otherworld Mercenary Corps (com.Cryptect.Mercenary):
 *   1. /api/models?game=mercenary -> 98 model Spine 4.0.x: 9 dari XAPK APK
 *      lokal + 89 dari CDN Addressables Product/Live/3.0.1/Android. 49 kartu
 *      root + 49 varian dalam 32 family (kostum + rig alternatif).
 *   2. /api/models?game=mercenary-illust -> 85 ilustrasi slot resmi (image).
 *   3. Tiap model punya .json + .atlas + halaman PNG yang disebut atlas;
 *      skeleton JSON ter-parse dan versinya 4.0.64.
 *   4. /api/thumbnails -> 98/98 thumbnail WebP, semua berkas ada.
 *   5. /api/update/mercenary?mode=check -> ok:true, idempoten, have:98,
 *      illusts:85, state berisi cdnHash + cdnModels:89.
 *   6. Playwright: render 3 model (ada / moa / basilla dari CDN) di kanvas
 *      dengan 0 aset 404, popup Varian Ema, image stage ilustrasi, 0 JS error.
 */
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.SPINE_VIEWER_URL || "http://127.0.0.1:3000";

let pass = 0, fail = 0;
function ok(cond, msg, extra = "") {
	if (cond) { pass++; console.log(`  ok   ${msg}${extra ? " — " + extra : ""}`); }
	else { fail++; console.error(`  FAIL ${msg}${extra ? " — " + extra : ""}`); }
}
function getJson(urlPath) {
	return new Promise((resolve, reject) => {
		http.get(BASE + urlPath, (res) => {
			let raw = "";
			res.on("data", (d) => (raw += d));
			res.on("end", () => {
				try { resolve({ status: res.statusCode, body: JSON.parse(raw) }); }
				catch (e) { reject(new Error(`${urlPath}: JSON invalid (${e.message})`)); }
			});
		}).on("error", reject);
	});
}

(async () => {
	console.log("=== Check Otherworld Mercenary Corps (com.Cryptect.Mercenary) ===");

	const [sp, il, th, u1, u2] = await Promise.all([
		getJson("/api/models?game=mercenary&refresh=1"),
		getJson("/api/models?game=mercenary-illust&refresh=1"),
		getJson("/api/thumbnails"),
		getJson("/api/update/mercenary?mode=check"),
		getJson("/api/update/mercenary?mode=check"),
	]);
	const models = sp.body.models || [];
	const illusts = il.body.models || [];
	const thumbs = th.body.thumbs || {};
	const u = u1.body, u2b = u2.body;

	ok(models.length === 98, "jumlah model Spine = 98 (9 lokal + 89 CDN)", `${models.length}`);
	ok(illusts.length === 85, "jumlah ilustrasi karakter = 85", `${illusts.length}`);

	const namesPath = path.join(ROOT, "assets", "mercenary", "_names.json");
	const names = JSON.parse(fs.readFileSync(namesPath, "utf8"));
	const hidden = names.families.reduce((n, f) => n + f.members.length - 1, 0);
	const roots = models.filter((m) => !m.family || m.family.root === m.id);
	const variants = models.filter((m) => m.family && m.family.root !== m.id);
	ok(roots.length === models.length - hidden && variants.length === hidden,
		"kartu root + varian konsisten dengan _names.json",
		`roots=${roots.length} variants=${variants.length}`);
	ok(models.every((m) => m.character && m.character.name),
		"semua model punya metadata karakter");
	ok(models.filter((m) => m.character?.origin === "cdn").length === 89,
		"89 model berasal dari CDN", `${models.filter((m) => m.character?.origin === "cdn").length}`);
	ok(models.every((m) => /^4\.0\./.test(m.spine || "") && m.bones > 0
		&& (m.animations || []).length >= 1),
		"semua skeleton Spine 4.0.x, bertulang & beranimasi",
		`${Math.min(...models.map((m) => m.bones || 0))}–${Math.max(...models.map((m) => m.bones || 0))} tulang`);

	// --- kelengkapan berkas di disk ----------------------------------------
	let diskOk = 0;
	const diskErr = [];
	for (const m of models) {
		const dir = path.join(ROOT, "assets", m.id);
		const stem = path.basename(m.id);
		const jsonF = path.join(dir, `${stem}.json`);
		const atlasF = path.join(dir, `${stem}.atlas`);
		if (!fs.existsSync(jsonF) || !fs.existsSync(atlasF)) {
			diskErr.push(`${m.id}: json/atlas hilang`); continue;
		}
		let j;
		try { j = JSON.parse(fs.readFileSync(jsonF, "utf8").replace(/^\uFEFF/, "")); }
		catch (e) { diskErr.push(`${m.id}: JSON ${e.message}`); continue; }
		if (!/^4\.0\./.test(j.skeleton?.spine || "")) { diskErr.push(`${m.id}: spine ${j.skeleton?.spine}`); continue; }
		const atlas = fs.readFileSync(atlasF, "utf8").replace(/^\uFEFF/, "");
		const pages = [...new Set(atlas.split(/\r?\n/).map((x) => x.trim())
			.filter((x) => x.toLowerCase().endsWith(".png")))];
		const missing = pages.filter((p) => !fs.existsSync(path.join(dir, p)));
		if (missing.length) { diskErr.push(`${m.id}: halaman ${missing.join(",")}`); continue; }
		diskOk++;
	}
	ok(diskOk === models.length, "semua model lengkap (json + atlas + halaman PNG)",
		diskErr.length ? diskErr.slice(0, 3).join(" | ") : `${diskOk} folder`);

	// --- _names.json + thumbnail -------------------------------------------
	ok(names.characters.length === 95 && Object.keys(names.models).length === 183,
		"_names.json: 95 karakter kanonik & 183 entri nama",
		`${names.characters.length} / ${Object.keys(names.models).length}`);
	ok(names.families.length === 32, "_names.json: 32 family", String(names.families.length));
	const man = JSON.parse(fs.readFileSync(
		path.join(ROOT, "public", "thumbs", "mercenary", "_manifest.json"), "utf8"));
	ok(Object.keys(man).length === 98, "manifest 98/98 thumbnail", String(Object.keys(man).length));
	ok(Object.values(man).every((f) => fs.existsSync(
		path.join(ROOT, "public", "thumbs", "mercenary", f))), "semua berkas WebP ada");
	ok(Object.keys(man).every((k) => thumbs[k]), "/api/thumbnails memuat 98 kunci mercenary");
	ok(fs.existsSync(path.join(ROOT, "public", "thumbs", "_game", "mercenary.png")),
		"ikon game 128px ada");

	// --- updater ------------------------------------------------------------
	ok(u.ok === true && !u.error, "--check ok:true", JSON.stringify({ ok: u.ok, error: u.error }));
	ok(u.version === u.previous && u.changed === false && u.new === 0,
		"--check stabil (previous=version, changed:false)", JSON.stringify({
			version: u.version, previous: u.previous, changed: u.changed }));
	ok(u.have === 98 && u.illusts === 85, "--check melaporkan have:98 / illusts:85",
		`${u.have} / ${u.illusts}`);
	ok(u2b.ok === true && u2b.version === u.version && u2b.changed === u.changed,
		"dua --check berturut identik (idempoten)");
	const statePath = path.join(ROOT, "data", "mercenary-update-state.json");
	const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
	ok(state.version === u.version && state.models === 98 && state.illusts === 85
		&& state.cdnModels === 89 && !!state.cdnHash,
		"state updater tersimpan (98 model, 89 CDN)", JSON.stringify(state));

	// --- Playwright: render beneran ----------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(90000);
	const bad404 = [], pageErrors = [];
	page.on("response", (r) => {
		if (r.status() >= 400 && !r.url().includes("favicon")) bad404.push(`${r.status()} ${r.url()}`);
	});
	page.on("pageerror", (e) => pageErrors.push(e.message));

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible", timeout: 90000 });
	const tile = page.locator('#game-list .game[data-key="mercenary"]');
	ok(await tile.count() === 1, "tile game Otherworld Mercenary Corps tampil");
	await tile.click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	await page.waitForTimeout(500);
	const updUi = await page.evaluate(() => {
		const btn = document.getElementById("update-check");
		const dot = document.getElementById("update-dot");
		return { btnVisible: !!btn && !btn.hidden, dotHidden: !!dot && dot.hidden === true };
	});
	ok(updUi.btnVisible && updUi.dotHidden,
		"tombol Periksa pembaruan tampil & titik merah mati");

	// Kartu root saja yang tampil di daftar; varian (ema_alt / kei_alt) cuma
	// bisa dipilih lewat popup Varian. Tunggu model.id berganti, bukan cuma
	// skeleton yang sudah ada dari model sebelumnya.
	for (const ID of ["mercenary/ada", "mercenary/moa", "mercenary/basilla"]) {
		await page.fill("#search", "");
		const card = page.locator(`#model-list [data-id="${ID}"]`).first();
		await card.waitFor({ state: "visible" });
		await card.click();
		await page.waitForFunction(
			(id) => window.spineStage?.model?.id === id && !!window.spineStage?.spine?.skeleton,
			ID, { timeout: 90000 });
		const info = await page.evaluate(() => ({
			id: window.spineStage?.model?.id,
			anims: [...document.querySelectorAll("#anim-select option")].length,
			bones: window.spineStage?.spine?.skeleton?.bones?.length || 0,
		}));
		ok(info.id === ID && info.anims > 1 && info.bones > 0,
			`render ${ID}`, JSON.stringify(info));
	}

	// popup Varian Ema (4 baris: Utama + rig alternatif + 2 kostum CDN)
	await page.fill("#search", "Ema");
	await page.waitForTimeout(250);
	const emaCard = page.locator('#model-list [data-id="mercenary/ema"]').first();
	ok(await emaCard.count() === 1, "kartu Ema tampil");
	const chip = emaCard.locator(".variant-chip");
	ok(await chip.count() === 1, "chip Varian Ema ada");
	await chip.click();
	await page.waitForFunction(() => {
		const p = document.querySelector("#variant-popup");
		return !!p && !p.hidden && p.querySelectorAll("#variant-list .variant-item").length >= 2;
	}, null, { timeout: 30000 });
	const pop = await page.evaluate(() => {
		const items = [...document.querySelectorAll("#variant-list .variant-item")];
		return { open: !document.querySelector("#variant-popup")?.hidden,
			items: items.length, ids: items.map((x) => x.dataset.id) };
	});
	ok(pop.open && pop.items >= 2 && pop.ids.includes("mercenary/ema_alt"),
		"popup Varian Ema memuat ema_alt", JSON.stringify(pop));
	await page.locator('#variant-list .variant-item[data-id="mercenary/ema_alt"]').click();
	await page.waitForFunction(
		() => window.spineStage?.model?.id === "mercenary/ema_alt", null, { timeout: 60000 });
	ok(true, "klik varian Ema memuat ema_alt");

	// image stage: ilustrasi karakter
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible", timeout: 90000 });
	const tile2 = page.locator('#game-list .game[data-key="mercenary-illust"]');
	ok(await tile2.count() === 1, "tile game Ilustrasi tampil");
	await tile2.click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	const illCard = page.locator('#model-list [data-id^="mercenary-illust/"]').first();
	await illCard.click();
	const imgOk = await page.waitForFunction(() => {
		const img = document.querySelector("img.image-stage");
		return img && img.complete && img.naturalWidth > 0
			? { src: img.getAttribute("src"), w: img.naturalWidth } : false;
	}, null, { timeout: 30000 }).then((h) => h.jsonValue()).catch(() => null);
	ok(!!imgOk && imgOk.w > 0, "ilustrasi karakter ter-render di image stage",
		JSON.stringify(imgOk));

	ok(bad404.length === 0, "0 aset 404", bad404.slice(0, 4).join(" | "));
	ok(pageErrors.length === 0, "0 JS error", pageErrors.slice(0, 3).join(" | "));
	await browser.close();

	console.log(`\n=== Hasil Mercenary: ${pass} ok, ${fail} FAIL ===`);
	process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
