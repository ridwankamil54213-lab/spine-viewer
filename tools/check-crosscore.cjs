#!/usr/bin/env node
/**
 * Smoke test pustaka CrossCore — sumber https://crosscore.art/.
 *
 * Mengecek rantai tools/crosscore/import-art.py + update.py:
 *   - 486 scene (408 rig Spine + 78 ilustrasi statis), 0 sisa ArtHub
 *   - nama dari _names.json (crosscore.art), bukan slug mentah
 *   - integritas .json/.atlas/halaman tekstur untuk tiap rig
 *   - thumbnail manifest + /api/thumbnails + berkasnya tersaji
 *   - updater --check memakai katalog crosscore.art
 *   - model Spine ter-render di stage tanpa aset 404 / JS error
 *
 * Run: node tools/check-crosscore.cjs
 */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

(async () => {
	const d = await fetch(`${BASE}/api/models?lean=1`, { cache: "no-store" }).then((r) => r.json());
	const all = d.models || (Array.isArray(d) ? d : []);
	const cc = all.filter((m) => m.game === "crosscore");
	const spine = cc.filter((m) => String(m.id).startsWith("crosscore/"));
	const cg = cc.filter((m) => String(m.id).startsWith("crosscore-cg/"));
	ok("486 scene crosscore.art terpasang", cc.length === 486, String(cc.length));
	ok("408 rig Spine", spine.length === 408, String(spine.length));
	ok("78 ilustrasi statis", cg.length === 78, String(cg.length));
	ok("tidak ada sisa crosscore-interaction / ArtHub",
		!all.some((m) => String(m.id).startsWith("crosscore-interaction/")));
	ok("semua bernama dari crosscore.art",
		cc.every((m) => m.character?.source === "crosscore.art"),
		String(cc.filter((m) => m.character?.source === "crosscore.art").length));
	ok("nama memakai aksara Tionghoa", spine.some((m) => /[\u4e00-\u9fff]/.test(m.name || "")));

	const names = JSON.parse(fs.readFileSync(path.join(ROOT, "assets/crosscore/_names.json"), "utf8"));
	ok("_names.json 486 entri", Object.keys(names).length === 486, String(Object.keys(names).length));

	// --- integritas berkas -------------------------------------------------
	let bad = 0;
	for (const m of spine) {
		const folder = path.join(ROOT, "assets", m.id);
		const stem = path.basename(m.id);
		const skel = path.join(folder, stem + ".json");
		const atlas = path.join(folder, stem + ".atlas");
		if (!fs.existsSync(skel) || !fs.existsSync(atlas)) { bad++; continue; }
		const pages = fs.readFileSync(atlas, "utf8").split(/\r?\n/)
			.filter((l) => l && !l.startsWith(" ") && /\.(png|webp|jpg)$/i.test(l.trim()))
			.map((l) => l.trim());
		if (!pages.length || pages.some((p) => !fs.existsSync(path.join(folder, p)))) bad++;
	}
	for (const m of cg) {
		const parts = m.id.split("/");
		if (!fs.existsSync(path.join(ROOT, "assets", parts[0], parts[1], parts[2] + ".webp"))) bad++;
	}
	ok("integritas json/atlas/halaman & webp", bad === 0, `${bad} rusak`);

	// --- thumbnail ---------------------------------------------------------
	const tdir = path.join(ROOT, "public/thumbs/crosscore");
	const man = JSON.parse(fs.readFileSync(path.join(tdir, "_manifest.json"), "utf8"));
	const ids = new Set(cc.map((m) => m.id));
	ok("kunci manifest cocok id model",
		Object.keys(man).length >= 70 && Object.keys(man).every((k) => ids.has(k)),
		String(Object.keys(man).length));
	ok("berkas thumbnail ada semua",
		Object.values(man).every((f) => fs.existsSync(path.join(tdir, f))));
	const tmap = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs;
	ok("/api/thumbnails memuat crosscore",
		Object.keys(tmap).filter((k) => k.startsWith("crosscore")).length >= 70,
		String(Object.keys(tmap).filter((k) => k.startsWith("crosscore")).length));
	const sample = Object.values(man)[0];
	const tRes = await fetch(`${BASE}/thumbs/crosscore/${sample}`);
	ok("thumbnail tersaji 200", tRes.status === 200, String(tRes.status));

	// --- updater -----------------------------------------------------------
	const chk = await fetch(`${BASE}/api/update/crosscore?mode=check`, { cache: "no-store" })
		.then((r) => r.json());
	ok("updater --check memakai katalog crosscore.art",
		chk.ok === true && String(chk.version || "").startsWith("v") && chk.have === 486,
		JSON.stringify({ ok: chk.ok, changed: chk.changed, have: chk.have, version: chk.version }));

	// --- browser -----------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(90000);
	const errors = [], missing = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|png|atlas|json|webm|skel)(\?|$)/.test(r.url()))
			missing.push(`${r.status()} ${r.url()}`);
	});
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible", timeout: 90000 });
	const card = page.locator('#game-list .game[data-key="crosscore"]');
	ok("kartu game CrossCore tampil", await card.count() === 1);
	await card.click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible", timeout: 90000 });
	const wanted = "crosscore/machairodus_game-3018002_default";
	await page.fill("#search", wanted);
	await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 40000 });
	await page.waitForFunction(() => !!window.spineStage?.model?.id, null, { timeout: 90000 });
	await page.waitForTimeout(2500);
	const st = await page.evaluate(() => ({
		id: window.spineStage?.model?.id,
		runtime: window.spineStage?.runtime,
		name: window.spineStage?.model?.name,
		anims: document.querySelectorAll("#anim-select option").length,
	}));
	ok("model Spine crosscore.art ter-render",
		st.id === wanted && st.runtime === "4.2" && st.anims > 0, JSON.stringify(st));
	ok("tidak ada aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));
	ok("tidak ada JS error", errors.length === 0, errors.slice(0, 2).join(" | "));
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nCrossCore (crosscore.art) ok");
})().catch((err) => { console.error(err); process.exit(1); });
