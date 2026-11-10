/**
 * Smoke test: Updater Health Dashboard (fitur #1).
 *
 * Yang dibuktikan:
 *   1. /api/updaters/health mengembalikan SELURUH pembaru dengan kontrak seragam,
 *      termasuk updater lama yang tidak mengirim field `ok` (shoujoukaisen).
 *   2. Cache 5 menit benar-benar dipakai (dua panggilan identik, tanpa spawn).
 *   3. `?game=…&refresh=1` menyegarkan satu baris tanpa mengubah baris lain.
 *   4. Deteksi "sumber tertinggal" (mirrorLag) dan sinyal CDN live ada di kode.
 *   5. Panel terbuka dari header, tabel terisi, Esc menutup, 0 JS error.
 *
 * Sengaja TIDAK menekan "Terapkan yang berubah": itu operasi berat yang
 * mengunduh aset. Tombolnya diverifikasi ada + invoke endpoint apply existing.
 *
 * Run: node tools/check-updater-dashboard.cjs   (server on :3000)
 */
const fs = require("fs");
const { chromium } = require("playwright-core");

const BASE = "http://127.0.0.1:3000";
const results = [];
function ok(name, cond, detail = "") {
	results.push({ name, ok: !!cond, detail });
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
		} catch { /* direktori tidak ada */ }
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

const getJSON = async (url) => {
	const r = await fetch(BASE + url);
	if (!r.ok) throw new Error(`${url} -> HTTP ${r.status}`);
	return r.json();
};

(async () => {
	// --- 1. Kontrak endpoint ------------------------------------------------
	const a = await getJSON("/api/updaters/health");
	ok("endpoint health merespons", a && Array.isArray(a.games),
		`${a?.games?.length ?? 0} baris`);
	const games = a.games || [];
	ok("mencakup >= 25 updater", games.length >= 25, `${games.length} pembaru`);
	ok("TTL 5 menit", a.ttlMs === 5 * 60 * 1000, String(a.ttlMs));

	const keys = ["game", "label", "ok", "error", "version", "previous",
		"changed", "expected", "have", "new", "extractor", "rescan", "source",
		"cdnSha", "dataCommit", "mirrorLag", "checkedAt"];
	ok("setiap baris punya kontrak lengkap",
		games.every((g) => keys.every((k) => k in g)));
	ok("baris diurutkan menurut game",
		games.every((g, i) => i === 0 || games[i - 1].game <= g.game));
	ok("label manusiawi (bukan cuma slug)",
		games.some((g) => g.label && g.label !== g.game));
	ok("flag rescan terdeteksi", games.filter((g) => g.rescan).length >= 10,
		`${games.filter((g) => g.rescan).length} rescan`);
	ok("updater ekstraktor terdeteksi", games.some((g) => g.extractor));
	ok("sinyal CDN live (cdnSha + dataCommit) terbawa",
		games.some((g) => g.cdnSha && g.dataCommit), "Stella Sora");
	ok("sumber aset terbawa", games.some((g) => g.source));
	ok("checkedAt terisi", games.every((g) => Number.isFinite(g.checkedAt)));

	// Regresi utama: updater lama tanpa field `ok` TIDAK boleh dianggap gagal.
	const s = a.summary || {};
	ok("summary konsisten dengan baris", s.total === games.length &&
		s.ok === games.filter((g) => g.ok).length &&
		s.failed === games.filter((g) => !g.ok).length &&
		s.changed === games.filter((g) => g.changed).length &&
		s.pending === games.filter((g) => (g.new || 0) > 0).length &&
		s.mirrorLag === games.filter((g) => g.mirrorLag).length,
		JSON.stringify(s));
	ok("tidak ada false-fail pada updater tanpa field ok",
		games.filter((g) => !g.ok).length <= 1,
		`${s.failed} gagal: ${games.filter((g) => !g.ok).map((g) => g.game).join(",")}`);
	// Regresi normalisasi: updater tanpa field `ok` tidak boleh dianggap gagal.
	// Jangan gantung pada `new > 0` — itu berubah begitu user klik Apply.
	ok("shoujoukaisen terbaca sukses (tanpa ok di JSON)",
		!!games.find((g) => g.game === "shoujoukaisen" && g.ok && !g.error && !!g.version));
	ok("catshinobi tidak kena timeout",
		!!games.find((g) => g.game === "catshinobi" && g.ok && !g.error && !!g.version));

	// --- 2. Cache -----------------------------------------------------------
	const b = await getJSON("/api/updaters/health");
	ok("panggilan kedua identik (cache, tanpa spawn)",
		b.at === a.at && JSON.stringify(b.games) === JSON.stringify(a.games));

	// --- 3. Refresh satu game ------------------------------------------------
	const c = await getJSON("/api/updaters/health?game=ivntight&refresh=1");
	const pick = (d, key) => (d.games || []).find((g) => g.game === key);
	ok("refresh satu game tetap mengembalikan semua baris",
		c.games.length === a.games.length, `${c.games.length}`);
	ok("checkedAt game yang disegarkan maju",
		pick(c, "ivntight").checkedAt >= pick(a, "ivntight").checkedAt);
	ok("baris lain tidak ikut dijalankan ulang",
		c.games.filter((g) => g.game !== "ivntight").every((g) =>
			JSON.stringify(g) === JSON.stringify(pick(a, g.game))));

	// --- 4. Kontrak kode -----------------------------------------------------
	const server = fs.readFileSync("src/server.js", "utf8");
	const viewer = fs.readFileSync("src/viewer.js", "utf8");
	const html = fs.readFileSync("public/index.html", "utf8");
	ok("endpoint terdaftar di server",
		server.includes('app.get("/api/updaters/health"'));
	ok("timeout per-game + paralel terbatas",
		server.includes("HEALTH_TIMEOUT_MS") && server.includes("HEALTH_CONCURRENCY"));
	ok("normalisasi kontrak tidak seragam",
		server.includes("r.ok !== false && !error") &&
		server.includes("r.models_have ?? r.installed"));
	ok("deteksi mirror tertinggal", server.includes("mirrorLag"));
	ok("tombol dashboard tidak hidden di HTML",
		html.includes('id="health-btn"') &&
		!/id="health-btn"[^>]*\shidden/.test(html));
	ok("modal + tabel tersedia",
		html.includes('id="updater-health-modal"') && html.includes('id="health-rows"'));
	ok("Esc menutup dashboard",
		viewer.includes('const health = document.getElementById("updater-health-modal")'));
	ok("apply memakai endpoint /api/update existing",
		viewer.includes("?mode=apply") && viewer.includes("/status"));
	ok("konfirmasi sebelum apply massal", viewer.includes("confirm("));

	// --- 5. UI di browser ----------------------------------------------------
	const browser = await launch();
	const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
	const missing = [];
	page.on("response", (r) => { if (r.status() === 404) missing.push(r.url()); });

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#health-btn", { state: "visible" });
	ok("tombol dashboard selalu tampil", await page.isVisible("#health-btn"));

	await page.click("#health-btn");
	await page.waitForSelector("#updater-health-modal:not([hidden])");
	await page.waitForFunction(() => document.querySelectorAll("#health-rows tr").length >= 20);
	const rows = await page.evaluate(() => document.querySelectorAll("#health-rows tr").length);
	ok("tabel terisi >= 20 baris", rows >= 20, `${rows} baris`);
	ok("ringkasan terisi",
		(await page.textContent("#health-summary")).includes("updater"));
	ok("status pemeriksaan selesai",
		(await page.textContent("#health-status")).includes("Selesai"));
	ok("tombol Cek semua tersedia", await page.isVisible("#health-refresh"));
	ok("tombol Terapkan yang berubah tersedia", await page.isVisible("#health-apply"));
	ok("indikator header menyala saat ada pembaruan",
		await page.evaluate(() => !document.getElementById("health-dot").hidden));

	// Cek semua: panggil endpoint yang sama persis lewat tombol, tunggu status.
	await page.click("#health-refresh");
	await page.waitForFunction(
		() => /Selesai|Gagal/.test(document.getElementById("health-status").textContent),
		null, { timeout: 180000 });
	ok("Cek semua selesai tanpa error",
		(await page.textContent("#health-status")).includes("Selesai"),
		await page.textContent("#health-status"));

	await page.keyboard.press("Escape");
	await page.waitForTimeout(150);
	ok("Esc menutup modal",
		await page.evaluate(() => document.getElementById("updater-health-modal").hidden));
	ok("0 JS error", errors.length === 0, errors.slice(0, 2).join(" | "));
	ok("0 aset 404", missing.length === 0, missing.slice(0, 2).join(" | "));

	await browser.close();
	console.log(results.map((r) => `  ${r.ok ? "ok  " : "FAIL"} ${r.name}${r.detail ? "  (" + r.detail + ")" : ""}`).join("\n"));
	console.log(`\n=== Hasil Updater Health Dashboard: ${results.filter((r) => r.ok).length} ok, ${results.filter((r) => !r.ok).length} FAIL ===`);
	process.exit(results.some((r) => !r.ok) ? 1 : 0);
})().catch((err) => {
	console.error("FATAL", err);
	process.exit(1);
});
