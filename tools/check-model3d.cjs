/**
 * Smoke test: dukungan model 3D (glTF/GLB) lewat format "model3d".
 *
 * Membuktikan:
 *   1. three.js dibangun di bundle TERPISAH (viewer.js tidak membengkak) dan
 *      dimuat lazy lewat /dist/model3d.js.
 *   2. Server mendeteksi model.glb -> format model3d, nama/family/thumbnail.
 *   3. Aset & ilustrasi resolve 200 (bukan atlas).
 *   4. Browser: model 3D LANGSUNG beranimasi saat dibuka (auto-play idle),
 *      binding track nyata, frame berubah dari waktu ke waktu, root motion
 *      tidak membuat model hilang, jeda/lanjut bekerja, dan kembali ke model
 *      Spine 2D tetap bersih (stage 3D ter-dispose).
 *   5. 0 aset 404, 0 JS error.
 *
 * Run: node tools/check-model3d.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = "http://127.0.0.1:3000";
const ASSETS = path.join(ROOT, "assets", "stellasora-3d");
const THUMBS = path.join(ROOT, "public", "thumbs", "stellasora-3d");

const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

function installedChromium() {
	const roots = ["/root/.cache/ms-playwright", process.env.HOME + "/.cache/ms-playwright"];
	for (const root of roots) {
		try {
			for (const dir of fs.readdirSync(root)) {
				if (!dir.startsWith("chromium")) continue;
				for (const sub of fs.readdirSync(`${root}/${dir}`)) {
					if (!sub.startsWith("chrome-linux")) continue;
					for (const bin of ["chrome", "headless_shell"]) {
						const p = `${root}/${dir}/${sub}/${bin}`;
						if (fs.existsSync(p)) return p;
					}
				}
			}
		} catch { /* tidak ada */ }
	}
	return null;
}
async function launch() {
	try { return await chromium.launch({ args: ["--no-sandbox"] }); }
	catch (err) {
		const exe = installedChromium();
		if (!exe) throw err;
		return await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
	}
}
const get = (u) => fetch(BASE + u).then((r) => r.json());

(async () => {
	// --- 1. Kontrak sumber / build ------------------------------------------
	const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
	const srv = fs.readFileSync(path.join(ROOT, "src", "server.js"), "utf8");
	const view = fs.readFileSync(path.join(ROOT, "src", "viewer.js"), "utf8");
	const stage = fs.readFileSync(path.join(ROOT, "src", "model3d-stage.js"), "utf8");
	const css = fs.readFileSync(path.join(ROOT, "public", "styles.css"), "utf8");
	ok("three.js terdaftar sebagai dependency", !!pkg.dependencies?.three,
		pkg.dependencies?.three);
	ok("build menghasilkan bundle 3D terpisah",
		/src\/model3d-stage\.js/.test(pkg.scripts.build) && /model3d\.js/.test(pkg.scripts.build));
	ok("bundle utama tidak ikut membawa three",
		!/from ["']three["']/.test(view) && !/from ["']three["']/.test(srv));
	const mainBundle = fs.statSync(path.join(ROOT, "public", "dist", "viewer.js")).size;
	const threeBundle = fs.statSync(path.join(ROOT, "public", "dist", "model3d.js")).size;
	ok("viewer.js tetap ~4 MB", mainBundle < 4.6 * 1024 * 1024,
		`${(mainBundle / 2 ** 20).toFixed(1)} MB`);
	ok("model3d.js terpisah > 300 KB", threeBundle > 300_000,
		`${(threeBundle / 2 ** 10).toFixed(0)} KB`);
	ok("runtime 3D expose window.Model3DStage",
		/window\.Model3DStage\s*=/.test(stage) && /GLTFLoader/.test(stage) &&
		/OrbitControls/.test(stage) && /AnimationMixer/.test(stage));
	ok("server: root + deteksi model.glb + loader metadata",
		/key: "stellasora-3d"/.test(srv) && /format: "model3d"/.test(srv) &&
		/f\.toLowerCase\(\) === "model\.glb"/.test(srv) &&
		/game: "stellasora-3d"/.test(srv));
	ok("server: updater stellasora-3d terdaftar",
		/"stellasora-3d": \{[\s\S]{0,220}model3d", "update\.py/.test(srv));
	ok("viewer: dispatch + teardown + kontrol 3D",
		/const is3D/.test(view) && /is3D\(model\)/.test(view) &&
		/dispose3D\(\)/.test(view) && /ensure3DScript/.test(view) &&
		/if \(is3D\(current\)\)/.test(view));
	ok("viewer: HUD & export punya cabang 3D",
		/3D · glTF/.test(view) && /Ekspor video belum didukung untuk model 3D/.test(view) &&
		/Model3DStage\?\.capture\(\)/.test(view));
	ok("CSS: kanvas 3D ditumpuk, PIXI disembunyikan",
		/\.canvas-wrap\.is-3d/.test(css) && /\.model3d-canvas/.test(css));

	// --- 2. Data -------------------------------------------------------------
	const names = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "stellasora-3d-names.json"), "utf8"));
	const fam = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "stellasora-3d-family.json"), "utf8"));
	const manifest = JSON.parse(fs.readFileSync(path.join(THUMBS, "_manifest.json"), "utf8"));
	ok("nama karakter = 59 model", Object.keys(names).length === 59,
		String(Object.keys(names).length));
	ok("nama memakai character + variant",
		Object.values(names).every((v) => v.character && v.variant && v.name));
	ok("family varian >= 15", (fam.families || []).length >= 15,
		String((fam.families || []).length));
	ok("tiap family >= 2 anggota & root valid",
		fam.families.every((f) => f.members.length >= 2 && f.members.some((m) => m.id === f.root)));
	ok("manifest thumbnail >= 55", Object.keys(manifest).length >= 55,
		String(Object.keys(manifest).length));
	ok("semua kunci ber-prefix stellasora-3d/",
		Object.keys(manifest).every((k) => k.startsWith("stellasora-3d/")));
	const missingThumb = [...new Set(Object.values(manifest))]
		.filter((f) => !fs.existsSync(path.join(THUMBS, f)));
	ok("setiap thumbnail resolve ke berkas (0 404 lokal)", missingThumb.length === 0,
		missingThumb.slice(0, 3).join(" | "));
	ok("ikon game 3D dibuat dari ilustrasi",
		fs.existsSync(path.join(ROOT, "public", "thumbs", "_game", "stellasora-3d.png")));
	ok("59 model.glb + animasi terpasang",
		fs.readdirSync(ASSETS).filter((d) => fs.existsSync(path.join(ASSETS, d, "model.glb"))).length === 59);

	// --- 3. API --------------------------------------------------------------
	const all = (await get("/api/models?game=stellasora-3d")).models || [];
	ok("API: 59 model 3D", all.length === 59, String(all.length));
	ok("API: semua format model3d",
		all.every((m) => m.format === "model3d" && m.modelFile === "model.glb"));
	ok("API: semua punya daftar animasi", all.every((m) => (m.animations || []).length > 1));
	ok("API: >= 30 model ber-family && >= 50 bernama",
		all.filter((m) => m.family).length >= 30 && all.filter((m) => m.character).length >= 50,
		`${all.filter((m) => m.family).length} family / ${all.filter((m) => m.character).length} nama`);
	const thumbsApi = (await get("/api/thumbnails")).thumbs || {};
	const cs = Object.keys(thumbsApi).filter((k) => k.startsWith("stellasora-3d/"));
	ok("API /api/thumbnails >= 55 kunci 3D", cs.length >= 55, String(cs.length));
	const urls = [
		"/assets/stellasora-3d/allie/model.glb",
		"/assets/stellasora-3d/allie/anims/idle.glb",
		"/dist/model3d.js",
		"/thumbs/stellasora-3d/139.webp",
	];
	const statuses = await Promise.all(urls.map(async (u) => (await fetch(BASE + u)).status));
	ok("model.glb / clip / runtime / ilustrasi HTTP 200",
		statuses.every((s) => s === 200), statuses.join(","));

	// --- 4. Browser ----------------------------------------------------------
	const browser = await launch();
	const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
	const errors = [], missing = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
	page.on("response", (r) => { if (r.status() === 404) missing.push(r.url()); });

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector('#game-list .game[data-key="stellasora-3d"]',
		{ state: "visible", timeout: 30000 });
	await page.locator('#game-list .game[data-key="stellasora-3d"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	await page.waitForTimeout(1000);
	const imgs = await page.evaluate(() =>
		[...document.querySelectorAll('img[src*="/thumbs/stellasora-3d/"]')].length);
	ok("kartu galeri memakai ilustrasi 3D", imgs >= 5, `${imgs} gambar`);
	const chips = await page.evaluate(() => [...document.querySelectorAll(".variant-chip")].length);
	ok("chip varian kostum tampil", chips >= 3, `${chips} chip`);

	const wanted = "stellasora-3d/allie";
	await page.fill("#search", wanted);
	await page.locator(`#model-list [data-id="${wanted}"]`).first()
		.waitFor({ state: "visible", timeout: 30000 });
	await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 60000 });
	await page.waitForFunction(() => window.model3dStage?.ready === true,
		null, { timeout: 90000 });
	const st = await page.evaluate(() => ({
		id: window.model3dStage?.id,
		meshes: window.model3dStage?.meshes,
		triangles: window.model3dStage?.triangles,
		anims: window.model3dStage?.animations,
		canvas: !!document.querySelector("canvas.model3d-canvas"),
		is3d: document.getElementById("canvas-wrap")?.classList.contains("is-3d"),
		hud: document.getElementById("hud-stats")?.textContent || "",
		current: window.Model3DStage?.state?.().current,
		select: document.getElementById("anim-select")?.value,
		playDisabled: document.getElementById("play-btn")?.disabled,
	}));
	ok("model 3D render (mesh + triangle nyata)",
		st.id === wanted && st.meshes > 0 && st.triangles > 0 && st.canvas && st.is3d,
		JSON.stringify({ meshes: st.meshes, triangles: st.triangles }));
	ok("HUD menandai runtime 3D", /3D · glTF/.test(st.hud), st.hud.slice(0, 90));

	// Kanvas tidak boleh blank: ukur simpangan baku piksel yang tergambar.
	const px = await page.evaluate(() => {
		const c = document.querySelector("canvas.model3d-canvas");
		if (!c) return { std: 0, mean: 0 };
		const s = document.createElement("canvas");
		s.width = s.height = 64;
		const ctx = s.getContext("2d");
		ctx.drawImage(c, 0, 0, 64, 64);
		const d = ctx.getImageData(0, 0, 64, 64).data;
		let sum = 0, sum2 = 0, n = 0;
		for (let i = 0; i < d.length; i += 4) {
			const v = (d[i] + d[i + 1] + d[i + 2]) / 3;
			sum += v; sum2 += v * v; n++;
		}
		const mean = sum / n;
		return { mean: +mean.toFixed(1), std: +Math.sqrt(Math.max(0, sum2 / n - mean * mean)).toFixed(1) };
	});
	ok("kanvas 3D tidak blank", px.std > 6, JSON.stringify(px));

	// Regresi keluhan "animasinya nggak ada": model harus BERGERAK sejak dibuka,
	// bukan cuma state `current` yang berubah. Ukur tanda tangan piksel + jumlah
	// piksel terang (model) dari waktu ke waktu.
	const sample = () => page.evaluate(() => {
		const c = document.querySelector("canvas.model3d-canvas");
		window.Model3DStage.capture();
		const s = document.createElement("canvas"); s.width = s.height = 96;
		const x = s.getContext("2d"); x.drawImage(c, 0, 0, 96, 96);
		const d = x.getImageData(0, 0, 96, 96).data;
		let bright = 0, hash = 2166136261;
		for (let i = 0; i < d.length; i += 4) {
			const v = (d[i] + d[i + 1] + d[i + 2]) / 3;
			if (v > 60) bright++;
			hash ^= d[i] + d[i + 1] * 3 + d[i + 2] * 7;
			hash = Math.imul(hash, 16777619);
		}
		return { bright, hash: hash >>> 0 };
	});

	ok("auto-play clip idle, UI tersinkron (bukan Bind pose statis)",
		!!st.current && st.current !== "Bind pose" && st.select === st.current &&
		st.playDisabled === false,
		`runtime=${st.current} select=${st.select} playDisabled=${st.playDisabled}`);
	const dbg = await page.evaluate(() => window.Model3DStage.debug());
	ok("AnimationMixer punya action berjalan dengan track ter-binding",
		dbg.actions?.some((a) => a.running && a.tracks > 0 && a.bindings > 0),
		JSON.stringify(dbg.actions));

	const a1 = await sample();
	await page.waitForTimeout(650);
	const a2 = await sample();
	ok("animasi benar-benar mengubah gambar (frame A != frame B)",
		a1.hash !== a2.hash && a1.bright > 200 && a2.bright > 200,
		JSON.stringify({ a1: a1.bright, a2: a2.bright }));

	// Clip "Attack" punya translasi Root ~14,7 unit (model cuma ~2,5). Tanpa
	// pembuangan root motion, model meleset keluar kamera => 0 piksel terang.
	const pick = st.anims.find((n) => /attack/i.test(n)) ||
		st.anims.find((n) => n !== "Bind pose");
	await page.selectOption("#anim-select", pick);
	await page.waitForFunction((n) => window.model3dStage?.current === n &&
		window.Model3DStage?.state?.().current === n,
		pick, { timeout: 30000 });
	const series = [];
	for (let i = 0; i < 5; i++) {
		series.push((await sample()).bright);
		await page.waitForTimeout(320);
	}
	ok("clip 3D diputar (retarget dari GLB terpisah)", true, pick);
	ok("root motion tidak membuat model hilang (0 piksel)",
		series.every((n) => n > 200), JSON.stringify(series));

	// Ganti clip lagi: pose clip lama tidak boleh nempel (dulu bikin frame 0).
	await page.selectOption("#anim-select", "idle");
	await page.waitForFunction(() => window.model3dStage?.current === "idle",
		null, { timeout: 30000 });
	await page.waitForTimeout(400);
	const back = await sample();
	ok("ganti clip memulihkan bind pose (model tetap terlihat)", back.bright > 200,
		String(back.bright));

	// Tombol Play = jeda / lanjut mixer, bukan setAnimation() Spine.
	await page.locator("#play-btn").click();
	const p1 = await sample();
	await page.waitForTimeout(600);
	const p2 = await sample();
	ok("tombol jeda membekukan animasi", p1.hash === p2.hash);
	await page.locator("#play-btn").click();
	await page.waitForTimeout(600);
	const p3 = await sample();
	ok("tombol lanjut menggerakkan animasi lagi", p3.hash !== p2.hash);

	// Kembali ke model 2D: stage 3D harus benar-benar dilepas.
	await page.locator("#back-btn").click();
	await page.waitForSelector('#game-list .game[data-key="catshinobi"]', { state: "visible" });
	await page.locator('#game-list .game[data-key="catshinobi"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav)", { state: "visible" });
	await page.fill("#search", "catshinobi/Char_32001");
	await page.locator('#model-list [data-id="catshinobi/Char_32001"]').first()
		.waitFor({ state: "visible", timeout: 30000 });
	await page.locator('#model-list [data-id="catshinobi/Char_32001"]').first().click({ timeout: 60000 });
	await page.waitForFunction(() => window.spineStage?.model?.id === "catshinobi/Char_32001" &&
		!!window.spineStage?.spine, null, { timeout: 90000 });
	const after = await page.evaluate(() => ({
		id: window.spineStage.model?.id,
		is3d: document.getElementById("canvas-wrap")?.classList.contains("is-3d"),
		canvas3d: !!document.querySelector("canvas.model3d-canvas"),
		stage3d: window.model3dStage,
	}));
	ok("kembali ke Spine 2D: stage 3D ter-dispose",
		after.id === "catshinobi/Char_32001" && !after.is3d &&
		!after.canvas3d && !after.stage3d, JSON.stringify(after));

	ok("0 aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));
	ok("0 JS error", errors.length === 0, errors.slice(0, 3).join(" | "));
	await browser.close();

	console.log(`\n=== Hasil Model 3D: ${failed.length ? failed.length + " FAIL" : "semua ok"} ===`);
	if (failed.length) console.log(failed.map((x) => "  - " + x).join("\n"));
	process.exit(failed.length ? 1 : 0);
})().catch((err) => {
	console.error("FATAL", err);
	process.exit(1);
});
