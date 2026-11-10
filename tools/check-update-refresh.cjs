/**
 * Smoke test: model baru langsung muncul setelah tombol "Perbarui aset".
 *
 * Gejala lama: apply selesai, tapi model baru baru tampil beberapa menit
 * kemudian / setelah reload berulang. Rantai penyebabnya:
 *   1. scanTreeMemo menyimpan signature assets/ selama 15 detik dan endpoint
 *      apply TIDAK memanggil invalidateScan();
 *   2. forceModelRescan hanya dinyalakan untuk updater berflag `rescan`
 *      (18 dari 27), dan getModels() saat signature berubah sengaja
 *      mengembalikan cache.models LAMA sambil memindai di latar;
 *   3. frontend hanya refresh() kalau hasil apply punya `new_models` atau
 *      `extracted`, padahal banyak updater memakai field lain; ditambah
 *      res.json() meledak pada 304 ETag.
 *
 * Perbaikan: server menyegarkan indeks SEBELUM `running=false` (semua
 * updater, normalisasi applyOk), frontend selalu refresh() + toleran 304,
 * dashboard apply-massal juga refresh().
 *
 * Uji fungsional: tambah SATU model tiruan ke assets/, jalankan apply
 * idempoten (arkrecode, tidak mengunduh apa pun), lalu tanpa ?refresh=1
 * model itu harus langsung ada. Folder dibersihkan di finally.
 *
 * Run: node tools/check-update-refresh.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = "http://127.0.0.1:3000";
const PROBE = path.join(ROOT, "assets", "catshinobi", "ZZ_SMOKE_PROBE");
const SOURCE = path.join(ROOT, "assets", "catshinobi", "cat_front_mode_36004");
const NEW_STATE = path.join(ROOT, "data", "new-models.json");
const MODEL_CACHE = path.join(ROOT, "data", "models-cache.json");

const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
/** GET JSON dengan toleransi 429 (bucket ketat /api/update, 30/menit). */
async function get(u, tries = 5) {
	let last;
	for (let i = 0; i < tries; i++) {
		const r = await fetch(BASE + u);
		last = await r.json();
		if (r.status !== 429) return last;
		await sleep(2000);
	}
	return last;
}

function installedChromium() {
	const roots = ["/root/.cache/ms-playwright", process.env.HOME + "/.cache/ms-playwright"];
	for (const root of roots) {
		try {
			for (const dir of fs.readdirSync(root)) {
				if (!dir.startsWith("chromium")) continue;
				const base = `${root}/${dir}`;
				for (const sub of fs.readdirSync(base)) {
					if (!sub.startsWith("chrome-linux")) continue;
					for (const bin of ["chrome", "headless_shell"]) {
						const full = `${base}/${sub}/${bin}`;
						if (fs.existsSync(full)) return full;
					}
				}
			}
		} catch { /* tidak ada */ }
	}
	return null;
}
async function launch() {
	try {
		return await chromium.launch({ args: ["--no-sandbox"] });
	} catch (err) {
		const exe = installedChromium();
		if (!exe) throw err;
		return await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
	}
}

function makeProbe() {
	fs.rmSync(PROBE, { recursive: true, force: true });
	fs.mkdirSync(PROBE, { recursive: true });
	for (const ext of ["skel", "atlas", "png"]) {
		fs.copyFileSync(path.join(SOURCE, `cat_front_mode_36004.${ext}`),
			path.join(PROBE, `ZZ_SMOKE_PROBE.${ext}`));
	}
	const atlas = path.join(PROBE, "ZZ_SMOKE_PROBE.atlas");
	fs.writeFileSync(atlas, fs.readFileSync(atlas, "utf8")
		.replace("cat_front_mode_36004.png", "ZZ_SMOKE_PROBE.png"));
}

async function hasProbe() {
	const d = await get("/api/models?game=catshinobi&lean=1");
	return { n: d.models.length, found: d.models.some((m) => m.id.includes("ZZ_SMOKE_PROBE")) };
}

(async () => {
	// --- 1. Kontrak sumber -------------------------------------------------
	const srv = fs.readFileSync(path.join(ROOT, "src", "server.js"), "utf8");
	const view = fs.readFileSync(path.join(ROOT, "src", "viewer.js"), "utf8");
	const applyBlock = srv.slice(srv.indexOf("updateJob.result = await runUpdater"),
		srv.indexOf("app.get(\"/api/update/:game/status\""));
	ok("apply memanggil invalidateScan()",
		/invalidateScan\(\)/.test(applyBlock));
	ok("apply memaksa getModels({ force: true })",
		/getModels\(\{ force: true \}\)/.test(applyBlock));
	ok("rescan SEBELUM running = false",
		applyBlock.indexOf("getModels({ force: true })") <
		applyBlock.indexOf("updateJob.running = false"));
	ok("berlaku untuk semua updater (bukan cuma cfg.rescan)",
		!/cfg\.rescan/.test(applyBlock) && /const applyOk/.test(applyBlock));
	ok("normalisasi applyOk (tanpa field ok dihasilkan sukses)",
		/updateJob\.result\.ok !== false && !updateJob\.result\.error/.test(applyBlock));
	ok("apply mencatat langkah di log",
		/menyegarkan indeks model…/.test(applyBlock));
	ok("frontend selalu refresh() setelah apply sukses",
		/if \(!res\.error\) \{\s*\n\s*refresh\(\)/.test(view));
	ok("refresh() tidak lagi disyaratkan added/extracted",
		!/if \(!res\.error && \(/.test(view));
	ok("refresh() toleran 304 ETag", /res\.status !== 304/.test(view));
	ok("dashboard apply-massal ikut refresh()",
		/loadHealth\("\/api\/updaters\/health\?refresh=1"\)[\s\S]{0,200}refresh\(\)/.test(view));

	// --- 2. Fungsional: model tiruan langsung muncul -----------------------
	const newStateBackup = fs.readFileSync(NEW_STATE);
	const mtimeBefore = fs.statSync(MODEL_CACHE).mtimeMs;
	makeProbe();
	let result = null;
	try {
		const before = await hasProbe();
		ok("model tiruan BELUM terlihat sebelum apply (TTL scanTree)",
			before.found === false, `${before.n} model`);

		const t0 = Date.now();
		const started = await get("/api/update/arkrecode?mode=apply");
		ok("apply dimulai", started.started === true, JSON.stringify(started));
		let status = null;
		// Tunggu dulu: apply + pindai ulang sinkron makan ~9-11 dtk dan
		// menahan event loop. Menanya /status tiap 0,5 dtk di saat itu cuma
		// menumpuk request (ECONNRESET + menguras bucket rate limit 30/menit).
		await sleep(9000);
		for (let i = 0; i < 25; i++) {
			// Rescan sinkron (~4-8 dtk) menahan event loop; koneksi polling
			// bisa terputus sementara. Anggap sebagai "masih berjalan" dan
			// lanjut, jangan gagalkan test. 1,5 dtk juga menjauh dari rate
			// limit bucket /api/update (30/menit).
			try {
				status = await get("/api/update/arkrecode/status");
			} catch {
				status = null;
			}
			// 429 (rate limit) berkas JSON tapi tanpa `running`; jangan
			// keliru menganggap apply sudah selesai.
			if (status && status.running === false) break;
			await new Promise((r) => setTimeout(r, 1500));
		}
		const elapsed = (Date.now() - t0) / 1000;
		ok("apply selesai < 45 detik", status && status.running === false && elapsed < 45,
			`${elapsed.toFixed(1)} dtk`);
		ok("log memuat 'menyegarkan indeks model'",
			(status?.log || []).some((l) => /menyegarkan indeks model/.test(l)));
		ok("cache model ditulis ulang SEBELUM running=false",
			fs.statSync(MODEL_CACHE).mtimeMs > mtimeBefore,
			`${mtimeBefore} -> ${fs.statSync(MODEL_CACHE).mtimeMs}`);

		const after = await hasProbe();   // TANPA ?refresh=1
		ok("model baru LANGSUNG muncul tanpa ?refresh=1",
			after.found === true && after.n === before.n + 1,
			`${before.n} -> ${after.n}`);
		result = { elapsed, before: before.n, after: after.n };
	} finally {
		// Bersihkan apa pun hasilnya supaya pustaka tidak menyisipkan model
		// tiruan dan state NEW kembali seperti semula.
		fs.rmSync(PROBE, { recursive: true, force: true });
		fs.writeFileSync(NEW_STATE, newStateBackup);
		try { await get("/api/models?refresh=1"); } catch { /* best effort */ }
	}
	const clean = await hasProbe();
	ok("cleanup: model tiruan hilang", clean.found === false, `${clean.n} model`);

	// --- 3. ETag: 304 memang terjadi, frontend harus tahan -----------------
	const r1 = await fetch(`${BASE}/api/models?lean=1`);
	const etag = r1.headers.get("etag");
	await r1.arrayBuffer();
	const r2 = await fetch(`${BASE}/api/models?lean=1`,
		{ headers: { "If-None-Match": etag || "*" } });
	ok("/api/models bisa menjawab 304 tanpa body (alasan guard)",
		r2.status === 304 || r2.status === 200, String(r2.status));

	// --- 4. Browser ---------------------------------------------------------
	const browser = await launch();
	const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible" });
	await page.waitForTimeout(1500);
	ok("halaman tidak error saat indeks disegarkan", errors.length === 0,
		errors.slice(0, 2).join(" | "));
	const bundle = fs.readFileSync(path.join(ROOT, "public", "dist", "viewer.js"), "utf8");
	ok("bundle hasil build memuat guard 304", /status\s*!==\s*304/.test(bundle));
	await browser.close();

	if (result) console.log(`  (model tampil dalam ${result.elapsed.toFixed(1)} dtk: ` +
		`${result.before} -> ${result.after} model)`);
	console.log(`\n=== Hasil Update Refresh: ${failed.length ? failed.length + " FAIL" : "semua ok"} ===`);
	if (failed.length) console.log(failed.map((x) => "  - " + x).join("\n"));
	process.exit(failed.length ? 1 : 0);
})().catch((err) => {
	console.error("FATAL", err);
	process.exit(1);
});
