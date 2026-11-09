#!/usr/bin/env node
/**
 * Regresi updater イヴンタイト (IV-N-Tight) — tools/update-ivntight.py.
 *
 * Bug yang dikunci di sini:
 *   --check DULU cuma membaca katalog .json dari state.json, jadi walau game
 *   merilis katalog baru updater tetap bilang "up to date". Sekarang --check
 *   wajib membaca `catalog_0.0.1.hash` (2 GET x 32 byte) dari CDN dan
 *   mengunduh ulang katalog kalau hashnya berubah.
 *   --check juga DULU menimpa `version` di state, sehingga titik merah
 *   "ada pembaruan" hilang setelah satu kali klik walau belum Apply.
 *
 * Yang diuji:
 *   1. Fixture HTTP lokal + env override: hash berubah -> versi berubah,
 *      katalog diunduh ulang HANYA untuk tag yang berubah, cache dipakai
 *      kalau hash sama, dan --check TIDAK menyimpan `version`.
 *   2. Endpoint /api/update/ivntight?mode=check stabil & idempoten.
 *   3. Integritas 84 model: .json + .atlas + semua halaman atlas ada,
 *      tidak ada id dobel, nama Jepang dari data/ivntight-names.json.
 *   4. Browser: tile game, tombol updater, render Spine, 0 aset 404.
 *
 * Sengaja TIDAK menjalankan --apply penuh pada fixture (2507 bundle).
 * Run: node tools/check-ivntight.cjs   (server on :3000)
 */
const fs = require("fs");
const os = require("os");
const http = require("http");
const path = require("path");
const { execFile } = require("child_process");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.BASE_URL || "http://127.0.0.1:3000";
const PY = "/srv/venv-spine/bin/python";
const UPDATER = path.join(ROOT, "tools", "update-ivntight.py");
const SERVER_SRC = path.join(ROOT, "src", "server.js");
const ASSETS = path.join(ROOT, "assets", "ivntight");
const NAMES = path.join(ROOT, "data", "ivntight-names.json");
const STATE_FILE = process.env.IVN_STATE_DIR
	? path.join(process.env.IVN_STATE_DIR, "state.json")
	: "/srv/spine-assets/ivntight-update/state.json";
const CDN = "https://eventight-sb.webaccel.saikyo.biz/dmm4sb/Unity6";

const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

// HARUS async: server fixture jalan di event loop Node yang sama. execFileSync
// akan memblok loop itu sehingga permintaan katalog dari Python tak pernah
// dijawab (spawnSync ETIMEDOUT).
const runPy = (args, env = {}, timeout = 180000) => new Promise((resolve) => {
	execFile(PY, [UPDATER, ...args], {
		encoding: "utf8", timeout, maxBuffer: 32 * 1024 * 1024,
		env: { ...process.env, ...env },
	}, (err, stdout) => {
		if (err) return resolve({ error: String(err.message).slice(0, 200) });
		try { resolve(JSON.parse(stdout)); }
		catch (e) { resolve({ error: "stdout bukan JSON: " + String(stdout).slice(0, 120) }); }
	});
});

const atlasPages = (p) => [...new Set(fs.readFileSync(p, "utf8")
	.replace(/^\uFEFF/, "").split(/\r?\n/)
	.map((l) => l.trim().replace(/^\uFEFF/, "").trim())
	.filter((l) => /\.(png|webp|jpe?g)$/i.test(l) && !l.includes("/") && !l.includes("\\")))];

(async () => {
	// ---------------------------------------------------------------- 1 ---
	// Kontrak sumber: hash LIVE dipakai, --check tak menulis version, apply
	// memaksa rescan /api/models.
	const src = fs.readFileSync(UPDATER, "utf8");
	const srvSrc = fs.readFileSync(SERVER_SRC, "utf8");
	ok("updater membaca catalog_0.0.1.hash dari CDN",
		/CATALOG_HASH\s*=\s*"catalog_0\.0\.1\.hash"/.test(src) &&
		/def remote_catalog_hashes/.test(src));
	ok("versi menyertakan hash live", /"catalogs": sigs, "hashes": hashes/.test(src));
	ok("--check tidak menimpa version",
		!/if a\.check:[\s\S]{0,400}saved\["version"\]/.test(src));
	ok("updater menormalisasi folder warisan non-ASCII",
		/def normalize_folders/.test(src) && /renamed = normalize_folders\(\)/.test(src));
	ok("flag --rescan tersedia & dipakai untuk kandidat",
		/add_argument\(\s*"--rescan"/.test(src) &&
		/list\(jobs\) if a\.rescan/.test(src) && /"rescanned": len\(cand\)/.test(src));
	ok("apply menyimpan katalog segar (bukan load_state ulang)",
		/saved\.update\(\{"version": ver/.test(src));
	ok("server menandai updater ivntight rescan:true",
		/ivntight:\s*\{[\s\S]{0,260}?rescan:\s*true/.test(srvSrc));

	// Fixture katalog: ambil dari state lokal (cepat), fallback ke CDN.
	let catalogs = {};
	try {
		const st = JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
		for (const [tag, c] of Object.entries(st.catalogs || {}))
			catalogs[tag] = Buffer.from(c.b64, "base64");
	} catch (e) { /* fallback CDN di bawah */ }
	if (Object.keys(catalogs).length < 2) {
		catalogs = {};
		for (const tag of ["Test2", "Test3"]) {
			try {
				const r = await fetch(`${CDN}/Addressable_${tag}/WebGL/catalog_0.0.1.json`);
				if (r.ok) catalogs[tag] = Buffer.from(await r.arrayBuffer());
			} catch { /* ditangani assertion di bawah */ }
		}
	}
	ok("fixture punya 2 katalog Addressables",
		!!catalogs.Test2 && !!catalogs.Test3 && catalogs.Test2.length > 100000,
		`${Object.keys(catalogs).join("/")} ${(catalogs.Test2 || "").length}B`);

	if (catalogs.Test2 && catalogs.Test3) {
		const hashes = { Test2: "a".repeat(32), Test3: "b".repeat(32) };
		const hits = {};
		const server = http.createServer((req, res) => {
			const m = /^\/(Test2|Test3)\/(catalog_0\.0\.1\.(hash|json))$/.exec(req.url || "");
			if (!m) { res.writeHead(404); res.end(); return; }
			const key = `${m[1]}/${m[2]}`;
			hits[key] = (hits[key] || 0) + 1;
			if (m[2].endsWith(".hash")) {
				res.writeHead(200, { "content-type": "text/plain" });
				res.end(hashes[m[1]]);
			} else {
				res.writeHead(200, { "content-type": "application/json" });
				res.end(catalogs[m[1]]);
			}
		});
		await new Promise((r) => server.listen(0, "127.0.0.1", r));
		const port = server.address().port;
		const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ivn-smoke-"));
		const env = {
			IVN_CDN2: `http://127.0.0.1:${port}/Test2`,
			IVN_CDN3: `http://127.0.0.1:${port}/Test3`,
			IVN_STATE_DIR: tmp,
			IVN_OUT: path.join(tmp, "out"),
		};

		const r1 = await runPy(["--check"], env);
		ok("fixture --check#1 jalan", r1.ok === true && !r1.error,
			JSON.stringify({ ok: r1.ok, error: r1.error }));
		ok("--check#1 memuat 2507 job bundle", r1.total > 2000 && r1.new === r1.total,
			`${r1.total}/${r1.new}`);
		ok("--check#1 melaporkan hash live kedua tag",
			JSON.stringify(r1.catalogHashes) === JSON.stringify({ Test2: "a".repeat(12), Test3: "b".repeat(12) }),
			JSON.stringify(r1.catalogHashes));
		ok("--check#1 mengunduh 2 katalog",
			(hits["Test2/catalog_0.0.1.json"] || 0) === 1 &&
			(hits["Test3/catalog_0.0.1.json"] || 0) === 1,
			JSON.stringify(hits));

		const r2 = await runPy(["--check"], env);
		ok("--check#2 idempoten (versi & total sama)",
			r2.version === r1.version && r2.total === r1.total && r2.ok === true,
			`${r2.version} vs ${r1.version}`);
		ok("--check#2 pakai cache (tak unduh katalog lagi)",
			(hits["Test2/catalog_0.0.1.json"] || 0) === 1 &&
			(hits["Test3/catalog_0.0.1.json"] || 0) === 1,
			JSON.stringify(hits));
		ok("hash live tetap dibaca tiap --check",
			(hits["Test2/catalog_0.0.1.hash"] || 0) === 2 &&
			(hits["Test3/catalog_0.0.1.hash"] || 0) === 2);

		// Regresi inti: hash Test2 berubah -> versi berubah, HANYA Test2 yang
		// diunduh ulang, Test3 tetap dari cache.
		hashes.Test2 = "c".repeat(32);
		const r3 = await runPy(["--check"], env);
		ok("hash berubah -> versi berubah", r3.version !== r1.version && r3.changed === true,
			`${r1.version} -> ${r3.version}`);
		ok("hash berubah -> katalog tag itu diunduh ulang",
			(hits["Test2/catalog_0.0.1.json"] || 0) === 2 &&
			(hits["Test3/catalog_0.0.1.json"] || 0) === 1,
			JSON.stringify(hits));
		ok("state mencatat remoteHash baru",
			(JSON.parse(fs.readFileSync(path.join(tmp, "state.json"), "utf8"))
				.catalogs || {}).Test2?.remoteHash === "c".repeat(32));
		ok("--check TIDAK menyimpan version (titik merah tak hilang)",
			!("version" in JSON.parse(fs.readFileSync(path.join(tmp, "state.json"), "utf8"))) &&
			r3.previous === null,
			JSON.stringify({ previous: r3.previous }));

		server.close();
		fs.rmSync(tmp, { recursive: true, force: true });
	}

	// ---------------------------------------------------------------- 2 ---
	const chk = await fetch(`${BASE}/api/update/ivntight?mode=check`).then((r) => r.json());
	const chk2 = await fetch(`${BASE}/api/update/ivntight?mode=check`).then((r) => r.json());
	ok("endpoint --check ok:true", chk.ok === true && !chk.error, JSON.stringify(chk.error || ""));
	ok("dua --check berturut identik",
		chk.version === chk2.version && chk.changed === chk2.changed &&
		chk.new === chk2.new && chk.total === chk2.total);
	ok("kontrak check lengkap (total/installed/new/hash)",
		chk.total > 2000 && chk.installed > 0 && Number.isInteger(chk.new) &&
		/^[0-9a-f]{12}$/.test(chk.catalogHashes?.Test2 || "") &&
		/^[0-9a-f]{12}$/.test(chk.catalogHashes?.Test3 || ""),
		JSON.stringify({ total: chk.total, installed: chk.installed, new: chk.new,
			hashes: chk.catalogHashes }));
	ok("changed konsisten dengan previous",
		chk.changed === (chk.version !== chk.previous));
	// --check --rescan tidak mengubah aset, cuma melaporkan bahwa SEMUA job
	// akan dipindai ulang kalau di-apply.
	const rs = await runPy(["--check", "--rescan"]);
	ok("--check --rescan menandai semua bundle untuk dipindai ulang",
		rs.ok === true && rs.rescan === true && rs.new === rs.total && rs.total > 2000 &&
		rs.installed === chk.installed,
		JSON.stringify({ rescan: rs.rescan, new: rs.new, total: rs.total,
			installed: rs.installed }));
	try {
		const st = JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
		ok("state menyimpan remoteHash live kedua tag",
			(st.catalogs?.Test2?.remoteHash || "").startsWith(chk.catalogHashes.Test2) &&
			(st.catalogs?.Test3?.remoteHash || "").startsWith(chk.catalogHashes.Test3));
		ok("version state = versi terakhir yang di-APPLY (bukan check)",
			!!st.appliedAt && st.version === chk.version);
	} catch (e) {
		ok("state updater terbaca", false, String(e.message).slice(0, 100));
	}

	// ---------------------------------------------------------------- 3 ---
	const models = (await fetch(`${BASE}/api/models`).then((r) => r.json())).models || [];
	const ivn = models.filter((m) => m.game === "ivntight");
	const dirs = fs.readdirSync(ASSETS).filter((d) => fs.statSync(path.join(ASSETS, d)).isDirectory());
	ok("84 model ivntight terdaftar", ivn.length === dirs.length && ivn.length >= 80,
		`${ivn.length} model / ${dirs.length} folder`);
	ok("tidak ada id dobel", new Set(ivn.map((m) => m.id)).size === ivn.length);
	ok("semua folder bernama ASCII (id = folder)",
		dirs.every((d) => /^[\x20-\x7E]+$/.test(d)),
		dirs.filter((d) => !/^[\x20-\x7E]+$/.test(d)).join(" | ") || `${dirs.length} folder`);
	// Viewer menyusun URL dari `/assets/<id>/<skeletonFile>`; kalau nama
	// folder beda dengan id (kasus folder CJK warisan), semua aset jadi 404.
	let unresolvable = [];
	for (const m of ivn) {
		const leaf = m.id.split("/").pop();
		if (!dirs.includes(leaf) ||
			!fs.existsSync(path.join(ASSETS, leaf, m.skeletonFile)) ||
			!fs.existsSync(path.join(ASSETS, leaf, m.atlasFile)))
			unresolvable.push(m.id);
	}
	ok("URL aset setiap model resolve ke foldernya (0 404)",
		unresolvable.length === 0,
		unresolvable.slice(0, 4).join(" | ") || `${ivn.length} model`);
	ok("semua model punya nama", ivn.every((m) => !!m.name && m.name.length > 0));

	const names = JSON.parse(fs.readFileSync(NAMES, "utf8"));
	ok("data/ivntight-names.json >= 80 entri & kunci ASCII",
		Object.keys(names).length >= 80 &&
		Object.keys(names).every((k) => /^[A-Za-z0-9._-]+$/.test(k) && dirs.includes(k)),
		String(Object.keys(names).length));
	ok("nama Jepang dipakai server (bukan fallback slug)",
		ivn.some((m) => Object.values(names).includes(m.name)));

	let incomplete = [];
	for (const d of dirs) {
		const dir = path.join(ASSETS, d);
		const skel = path.join(dir, `${d}.json`);
		const atlas = path.join(dir, `${d}.atlas`);
		if (!fs.existsSync(skel) || !fs.existsSync(atlas)) {
			incomplete.push(`${d}: json/atlas`);
			continue;
		}
		for (const p of atlasPages(atlas)) {
			if (!fs.existsSync(path.join(dir, p))) incomplete.push(`${d}: ${p}`);
		}
		try {
			const j = JSON.parse(fs.readFileSync(skel, "utf8").replace(/^\uFEFF/, ""));
			if (!j.bones || !j.slots) incomplete.push(`${d}: JSON Spine tak valid`);
		} catch (e) { incomplete.push(`${d}: JSON tak terparse`); }
	}
	ok("semua folder lengkap (json + atlas + halaman)", incomplete.length === 0,
		incomplete.slice(0, 4).join(" | ") || `${dirs.length} folder`);

	// ---------------------------------------------------------------- 4 ---
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(90000);
	const errors = [];
	const missing = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(png|webp|atlas|json|skel)(\?|$)/.test(r.url()))
			missing.push(`${r.status()} ${r.url()}`);
	});

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector('#game-list .game[data-key="ivntight"]', { state: "visible" });
	await page.locator('#game-list .game[data-key="ivntight"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	const btn = await page.evaluate(() => {
		const b = document.getElementById("update-check");
		return b ? { hidden: b.hidden, title: b.title } : null;
	});
	ok("tombol Manual Update tampil untuk ivntight", btn && btn.hidden === false,
		JSON.stringify(btn));

	const picks = [...new Set([
		ivn.find((m) => names[m.id.split("/").pop()])?.id,
		ivn.find((m) => m.id.includes("000000_NPC"))?.id,
		ivn[Math.floor(ivn.length / 2)]?.id,
		ivn[ivn.length - 1]?.id,
	].filter(Boolean))];
	for (const wanted of picks) {
		await page.fill("#search", wanted);
		await page.locator(`#model-list [data-id="${wanted}"]`).first()
			.waitFor({ state: "visible", timeout: 30000 });
		await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 60000 });
		await page.waitForFunction(
			(id) => window.spineStage?.model?.id === id && !!window.spineStage?.spine?.skeleton,
			wanted, { timeout: 90000 });
		const st = await page.evaluate(() => ({
			id: window.spineStage.model?.id,
			anims: document.querySelectorAll("#anim-select option").length,
		}));
		ok(`render ${wanted}`, st.id === wanted && st.anims > 0, JSON.stringify(st));
	}

	ok("tidak ada aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));
	ok("tidak ada JS error", errors.length === 0, errors.slice(0, 2).join(" | "));
	await browser.close();

	console.log(`\n${failed.length ? "GAGAL: " + failed.join(" | ") : "IV-N-Tight updater ok"}`);
	process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
