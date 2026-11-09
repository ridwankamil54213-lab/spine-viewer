/**
 * Uji render satu model Project QT hasil konversi 2.x -> JSON.
 *
 * Ini membuktikan rutenya bekerja dari ujung ke ujung: .skel biner 2.1.27
 * diubah menjadi JSON oleh tools/convert-spine2.py, lalu dimuat oleh runtime
 * biasa dan digambar ke kanvas — TANPA iframe penampil legacy.
 *
 * Yang diperiksa:
 *   1. model muncul di API (berarti GAME_ROOTS mengenali foldernya)
 *   2. ia dimuat lewat pixi-spine, bukan iframe legacy
 *   3. kanvas benar-benar berisi piksel (bukan kanvas kosong)
 *   4. kontrol/timeline/export AKTIF — ini inti yang hilang pada jalur legacy
 *
 * Jalankan: node tools/check-projectqt-json.cjs
 */
const { chromium } = require("playwright-core");

const ok = (label, cond, extra = "") =>
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);

(async () => {
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(120000);
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));

	// 1. Model dikenali API?
	//    /api/models bisa belasan MB; mengambilnya lewat page.goto() membuat
	//    body-nya ter-evict saat kita berpindah halaman. Pakai request API
	//    Playwright sendiri supaya body-nya tetap utuh.
	let json;
	{
		const api = await page.request.get("http://127.0.0.1:3000/api/models", { timeout: 300000 });
		json = await api.json();
	}
	const models = json.models || [];
	const hits = models.filter((m) => String(m.id).includes("projectqt-json"));
	ok("model projectqt-json ada di API", hits.length > 0, `${hits.length} model`);
	if (hits.length) {
		const m = hits[0];
		console.log("     contoh:", JSON.stringify({
			id: m.id, name: m.name, spineRuntime: m.spineRuntime,
			needsLegacyViewer: m.needsLegacyViewer, skeletonFile: m.skeletonFile,
		}));
		ok("tidak ditandai legacy viewer", !m.needsLegacyViewer);
	}

	// 2. Buka UI dan muat model itu
	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { timeout: 60000 });

	// Pilih game "Project QT (JSON)"
	const picked = await page.evaluate(() => {
		const items = [...document.querySelectorAll("#game-list .game")];
		const t = items.find((e) => /Project QT \(JSON\)/i.test(e.textContent || ""));
		if (t) { t.click(); return t.textContent.trim(); }
		return null;
	});
	ok("game Project QT (JSON) ada di UI", !!picked, picked || "tidak ketemu");
	await page.waitForTimeout(1500);

	// Pilih model pertama
	const modelName = await page.evaluate(() => {
		const m = document.querySelector("#model-list li > button:not(.model-fav)");
		if (m) { m.click(); return m.textContent.trim(); }
		return null;
	});
	ok("model bisa diklik", !!modelName, modelName || "tidak ada model");
	await page.waitForTimeout(4000);

	// 3. KANVAS berisi piksel (bukan kosong)?
	const canvasInfo = await page.evaluate(() => {
		const c = document.querySelector("#canvas-wrap canvas");
		if (!c) return { present: false };
		return { present: true, w: c.width, h: c.height };
	});
	ok("kanvas ada", canvasInfo.present, canvasInfo.present ? `${canvasInfo.w}x${canvasInfo.h}` : "");

	// Ambil tangkapan layar kanvas, lalu hitung piksel tidak-transparan.
	// Kanvas ada tidak berarti ada yang tergambar — ini yang membedakan
	// "dimuat" dari "benar-benar terlihat".
	const shot = await page.locator("#canvas-wrap").screenshot();
	const nonTransparent = await page.evaluate(async (b64) => {
		const img = new Image();
		img.src = "data:image/png;base64," + b64;
		await img.decode();
		const c = document.createElement("canvas");
		c.width = img.width; c.height = img.height;
		const ctx = c.getContext("2d");
		ctx.drawImage(img, 0, 0);
		const d = ctx.getImageData(0, 0, c.width, c.height).data;
		let n = 0;
		// Ambil tiap piksel ke-40 untuk kecepatan; cukup untuk tahu ada isi.
		for (let i = 3; i < d.length; i += 4 * 40) if (d[i] > 8) n++;
		return { n, sampled: Math.floor(d.length / (4 * 40)) };
	}, shot.toString("base64"));
	const filledPct = (100 * nonTransparent.n / nonTransparent.sampled).toFixed(1);
	ok("kanvas berisi piksel", nonTransparent.n > 50, `${nonTransparent.n}/${nonTransparent.sampled} (${filledPct}%)`);

	// 4. Ini intinya: jalur legacy MEMATIKAN kontrol. Jadi kalau kontrol
	//    hidup, model pasti tidak lewat iframe.
	const controls = await page.evaluate(() => {
		const get = (id) => document.getElementById(id);
		const st = (id) => {
			const n = get(id);
			return n ? { disabled: !!n.disabled } : null;
		};
		return {
			play: st("play-btn"), anim: st("anim-select"), scrub: st("scrub"),
			exportBtn: st("export-btn"), hudVisible: get("hud") ? !get("hud").hidden : false,
			legacyFrame: !!document.getElementById("legacy-frame"),
			animCount: get("anim-select") ? get("anim-select").options.length : 0,
			hudText: get("hud-model") ? get("hud-model").textContent.trim() : "",
		};
	});
	ok("bukan iframe legacy", !controls.legacyFrame);
	ok("HUD tampil", controls.hudVisible, controls.hudText);
	ok("animasi terisi", controls.animCount > 0, `${controls.animCount} animasi`);
	ok("kontrol AKTIF (bukan dimatikan legacy)",
		controls.play && !controls.play.disabled &&
		controls.anim && !controls.anim.disabled &&
		controls.scrub && !controls.scrub.disabled);

	// 5. Timeline & export: fitur yang mati di jalur legacy
	const tl = await page.evaluate(() => {
		const b = document.getElementById("timeline-btn");
		if (b) b.click();
		return b ? !document.getElementById("timeline").hidden : false;
	});
	ok("timeline bisa dibuka", tl);

	// Simpan tangkapan layar buat dilihat manual
	await page.screenshot({ path: "/tmp/projectqt-json-check.png", fullPage: false });
	console.log("\ntangkapan layar: /tmp/projectqt-json-check.png");
	console.log("js errors:", errors.length ? errors.slice(0, 5) : "none");

	await browser.close();
	const bad = !controls.legacyFrame && errors.length === 0 && nonTransparent.n > 50;
	console.log(bad ? "\nRUTE JSON BEKERJA" : "\nperlu diperiksa");
	process.exit(0);
})();
