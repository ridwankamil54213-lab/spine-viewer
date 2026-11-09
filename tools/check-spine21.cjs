/**
 * Uji render model Spine 2.1 dengan runtime official di kanvas 2D.
 *
 * Ini membuktikan rutenya bekerja tanpa iframe penampil legacy:
 *   .skel 2.1.27 -> tools/convert-spine2.py -> JSON 2.1.27
 *                -> vendor/spine21 runtime  -> kanvas 2D, bukan iframe
 *
 * Yang diperiksa:
 *   1. model dikenali dan ditandai jalur 2.1
 *   2. TIDAK ADA iframe legacy (penggantinya kanvas 2D)
 *   3. kanvas 2.1 benar-benar berisi piksel
 *   4. animasi terisi dan kontrol AKTIF — inti yang hilang pada jalur iframe
 *
 * Jalankan: node tools/check-spine21.cjs
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
	const api = await page.request.get("http://127.0.0.1:3000/api/models", { timeout: 300000 });
	const json = await api.json();
	const hits = (json.models || []).filter((m) => String(m.id).includes("projectqt21"));
	ok("model projectqt21 ada di API", hits.length > 0, `${hits.length} model`);
	if (hits.length) {
		const m = hits[0];
		console.log("     ", JSON.stringify({
			id: m.id, spine: m.spine, spineRuntime: m.spineRuntime,
			needsLegacyViewer: m.needsLegacyViewer, skeletonFile: m.skeletonFile,
		}));
	}

	// 2. Buka UI, pilih game lalu model
	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { timeout: 60000 });

	const picked = await page.evaluate(() => {
		const t = [...document.querySelectorAll("#game-list .game")]
			.find((e) => /Project QT \(2\.1\)/i.test(e.textContent || ""));
		if (t) { t.click(); return t.textContent.trim(); }
		return null;
	});
	ok("game Project QT (2.1) ada", !!picked, picked || "tidak ketemu");
	await page.waitForTimeout(1500);

	const modelName = await page.evaluate(() => {
		const m = document.querySelector("#model-list li > button:not(.model-fav)");
		if (m) { m.click(); return m.textContent.trim(); }
		return null;
	});
	ok("model bisa diklik", !!modelName, modelName || "tidak ada");
	await page.waitForTimeout(4500);

	// 3. KANVAS 2.1 ada, dan bukan iframe legacy
	const canv = await page.evaluate(() => {
		const c21 = document.getElementById("spine21-canvas");
		const frame = document.getElementById("legacy-frame");
		return {
			has21: !!c21,
			w: c21 ? c21.width : 0,
			h: c21 ? c21.height : 0,
			legacy: !!frame,
		};
	});
	ok("kanvas 2.1 dibuat", canv.has21, canv.has21 ? `${canv.w}x${canv.h}` : "");
	ok("TIDAK ada iframe legacy", !canv.legacy);

	// 4. Kanvas berisi piksel?
	const shot = await page.locator("#spine21-canvas").screenshot();
	const px = await page.evaluate(async (b64) => {
		const img = new Image();
		img.src = "data:image/png;base64," + b64;
		await img.decode();
		const c = document.createElement("canvas");
		c.width = img.width; c.height = img.height;
		const ctx = c.getContext("2d");
		ctx.drawImage(img, 0, 0);
		const d = ctx.getImageData(0, 0, c.width, c.height).data;
		let n = 0, sampled = 0;
		// Hitung piksel yang TIDAK sama dengan warna latar gelap (#101014).
		for (let i = 0; i < d.length; i += 4 * 20) {
			sampled++;
			const r = d[i], g = d[i + 1], b = d[i + 2];
			if (Math.abs(r - 16) > 12 || Math.abs(g - 16) > 12 || Math.abs(b - 20) > 12) n++;
		}
		return { n, sampled };
	}, shot.toString("base64"));
	const pct = ((100 * px.n) / px.sampled).toFixed(1);
	ok("kanvas berisi model (bukan latar polos)", px.n > 100, `${px.n}/${px.sampled} (${pct}%)`);

	// 5. Kontrol aktif & animasi terisi
	const ui = await page.evaluate(() => {
		const g = (id) => document.getElementById(id);
		return {
			animCount: g("anim-select") ? g("anim-select").options.length : 0,
			animDisabled: g("anim-select") ? !!g("anim-select").disabled : true,
			playDisabled: g("play-btn") ? !!g("play-btn").disabled : true,
			scrubDisabled: g("scrub") ? !!g("scrub").disabled : true,
			hud: g("hud") ? !g("hud").hidden : false,
			hudText: g("hud-model") ? g("hud-model").textContent.trim() : "",
		};
	});
	ok("HUD tampil", ui.hud, ui.hudText);
	ok("animasi terisi", ui.animCount > 0, `${ui.animCount} animasi`);
	ok("kontrol AKTIF", !ui.animDisabled && !ui.playDisabled && !ui.scrubDisabled,
		`anim:${ui.animDisabled ? "mati" : "aktif"} play:${ui.playDisabled ? "mati" : "aktif"} scrub:${ui.scrubDisabled ? "mati" : "aktif"}`);

	await page.screenshot({ path: "/tmp/spine21-check.png" });
	console.log("\ntangkapan layar: /tmp/spine21-check.png");
	console.log("js errors:", errors.length ? errors.slice(0, 5) : "none");

	await browser.close();
	process.exit(0);
})();
