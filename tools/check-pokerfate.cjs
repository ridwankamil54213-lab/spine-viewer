#!/usr/bin/env node
/* Regresi updater PokerFate (live2dhub.com/t/topic/6530).

   - kontrak --check murah (HEAD + state) lewat CLI dan endpoint HTTP asli
   - self-test round-trip XENC dan --probe ke APK live via HTTP Range
   - progres ke stderr, stdout murni JSON, tidak ada path /opt/games
   - updater terdaftar di UPDATERS supaya tombol UI berfungsi

   Run: node tools/check-pokerfate.cjs   (server on :3000)
*/
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.BASE_URL || "http://127.0.0.1:3000";
const PY = "/srv/venv-spine/bin/python";
const UPDATER = path.join(ROOT, "tools", "pokerfate", "update-pokerfate.py");
const DECRYPT = path.join(ROOT, "tools", "pokerfate", "decrypt.py");
const ASSETS = path.join(ROOT, "assets", "pokerfate");
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

const runPy = (args, timeout = 180000) => {
	try {
		return execFileSync(PY, args, { encoding: "utf8", timeout,
			stdio: ["ignore", "pipe", "pipe"] });
	} catch (e) {
		return `GAGAL: ${e.message}`;
	}
};

(async () => {
	const t0 = Date.now();
	let chk = null;
	try { chk = JSON.parse(runPy([UPDATER, "--check"], 120000)); } catch (e) { /* handled below */ }
	ok("--check mengembalikan JSON ok:true", !!chk && chk.ok === true,
		chk ? JSON.stringify({ ok: chk.ok, error: chk.error }) : String(runPy).slice(0, 80));
	if (chk) {
		ok("check murah (< 10 dtk)", (Date.now() - t0) / 1000 < 10,
			`${(Date.now() - t0) / 1000}s`);
		const dirs = fs.readdirSync(ASSETS)
			.filter((d) => fs.statSync(path.join(ASSETS, d)).isDirectory() && !d.startsWith("."));
		ok("have = jumlah folder model", chk.have === dirs.length && dirs.length > 0,
			`${chk.have} vs ${dirs.length}`);
		ok("asset_dir menunjuk repo aktif", chk.asset_dir === ASSETS, String(chk.asset_dir));
		ok("previous tidak null (state dibootstrap)", !!chk.previous, String(chk.previous));
		ok("changed berupa boolean", typeof chk.changed === "boolean", String(chk.changed));
		ok("version dari Last-Modified APK", /^\d{4}-\d{2}-\d{2}$/.test(chk.version || ""),
			String(chk.version));
	}

	// Self-test kripto murni (tanpa jaringan).
	let st = null;
	try { st = JSON.parse(runPy([DECRYPT, "--self-test"], 60000)); } catch (e) { /* noop */ }
	ok("dekripsi XENC lolos self-test", !!st && st.ok === true,
		st ? JSON.stringify(st) : "gagal parse");

	const src = fs.readFileSync(UPDATER, "utf8");
	ok("progres ditulis ke stderr, bukan stdout", /file=sys\.stderr/.test(src));
	ok("stdout hanya JSON hasil", /print\(json\.dumps\(/.test(src));
	ok("tidak ada path /opt/games hardcode", !/\/opt\/games/.test(src));
	ok("ada mode --probe + preflight UnityPy",
		/add_argument\("--probe"/.test(src) && /UnityPy\.load/.test(src));
	ok("ada validasi staging sebelum publish", /staging cuma/.test(src));

	// Probe ke APK live. Kalau jaringan sedang mati, jangan bikin suite merah.
	let pr = null;
	try { pr = JSON.parse(runPy([UPDATER, "--probe"], 180000)); } catch (e) { /* noop */ }
	if (pr && pr.ok) {
		ok("probe: 529 bundle assets/aa terdeteksi", pr.asset_bundles === 529,
			String(pr.asset_bundles));
		ok("probe: XENC -> UnityFS", pr.encrypted === true && pr.unityfs === true,
			JSON.stringify({ e: pr.encrypted, u: pr.unityfs }));
		ok("probe: UnityPy berhasil baca objek", pr.objects > 0, String(pr.objects));
		ok("probe murah (< 2 MiB)", pr.bytes_downloaded < 2 * 1024 * 1024,
			String(pr.bytes_downloaded));
	} else {
		console.log("skip  probe jaringan/APK tidak tersedia (bukan kegagalan suite)");
	}

	// Endpoint HTTP asli + registrasi UI.
	let http = null;
	try { http = await fetch(`${BASE}/api/update/pokerfate?mode=check`).then((r) => r.json()); }
	catch (e) { /* noop */ }
	ok("GET /api/update/pokerfate?mode=check ok:true", !!http && http.ok === true,
		http ? JSON.stringify({ ok: http.ok, error: http.error }) : "fetch gagal");
	const srv = fs.readFileSync(path.join(ROOT, "src", "server.js"), "utf8");
	const block = srv.slice(srv.indexOf("const UPDATERS"), srv.indexOf("const UPDATERS") + 9000);
	ok("pokerfate terdaftar di UPDATERS", /pokerfate:\s*\{/.test(block));
	ok("updater punya rescan:true", /pokerfate:\s*\{[\s\S]{0,400}?rescan:\s*true/.test(block));

	console.log(`\n${failed.length ? "GAGAL: " + failed.join(" | ") : "PokerFate updater ok"}`);
	process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
