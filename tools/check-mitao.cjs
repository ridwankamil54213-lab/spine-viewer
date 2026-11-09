#!/usr/bin/env node
/* Regresi updater Mitao Utopia (tools/update-mitao.py).

   Sejak 2026-11 updater memakai pipeline iOS (v2), karena kunci master
   manifest Android v3 disembunyikan di Obfuz VM. Yang dikunci di sini:
     - --check via endpoint HTTP asli: ok, path aset, have, versi iOS live.
     - --apply --manifest-only: manifest CDN benar-benar terdekrip & terparse,
       dan katalog yang dibaca sama dengan yang dilaporkan --check.
     - solver dekripsi v2 (iOS) dan v3 (bundle Android) lolos self-test.

   Sengaja TIDAK menjalankan --apply penuh (akan mengunduh ~1000 bundle).
*/
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.BASE_URL || "http://127.0.0.1:3000";
const ASSETS = path.join(ROOT, "assets", "mitao-utopia");
const UPDATER = path.join(ROOT, "tools", "update-mitao.py");
const PY = "/srv/venv-spine/bin/python";
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

const runPy = (args, timeout = 180000) => {
	try {
		return execFileSync(PY, [UPDATER, ...args], {
			encoding: "utf8", timeout, stdio: ["ignore", "pipe", "pipe"],
		});
	} catch (e) {
		return `GAGAL: ${e.message}`;
	}
};

(async () => {
	const t0 = Date.now();
	const chk = await fetch(`${BASE}/api/update/mitao-utopia?mode=check`).then((r) => r.json());
	const elapsed = (Date.now() - t0) / 1000;

	ok("--check lewat HTTP mengembalikan ok:true",
		chk.ok === true && !chk.error,
		JSON.stringify({ ok: chk.ok, error: chk.error }));
	ok("asset_dir menunjuk repo aktif", chk.asset_dir === ASSETS && fs.existsSync(ASSETS),
		String(chk.asset_dir));
	const dirs = fs.readdirSync(ASSETS)
		.filter((d) => fs.statSync(path.join(ASSETS, d)).isDirectory()).length;
	ok("have = jumlah folder model", chk.have === dirs && dirs > 0,
		`${chk.have} vs ${dirs}`);
	ok("previous tidak null (state dibootstrap)", !!chk.previous, String(chk.previous));
	ok("--check murah (< 12 dtk)", elapsed < 12, `${elapsed}s`);
	ok("updater memakai resource_type iOS",
		chk.resource_type === "ios_cn_release", String(chk.resource_type));

	const src = fs.readFileSync(UPDATER, "utf8");
	ok("tidak ada path /opt/spine-viewer hardcode",
		!/MITAO_OUT[^\n]*\/opt\/spine-viewer/.test(src));
	ok("preflight pemblokir Android v3 sudah dihapus",
		!/MAGIC_V3_HEX/.test(src) && !/probe_manifest_magic/.test(src));
	ok("pipeline memakai dekripsi v2 iOS",
		/import idol_v2 as v2/.test(src) && /RESOURCE_TYPE = v2\.RESOURCE_TYPE/.test(src));
	ok("mode --replace + guard staging tersedia",
		/add_argument\("--replace"/.test(src) && /len\(good\) < 50/.test(src));

	// Versi iOS live bisa naik (pernah 1.6.2 -> 1.7.3). Yang dikunci bukan
	// angkanya, tapi format semver, konsistensi release_id, dan kesamaan
	// katalog antara --check dengan --apply --manifest-only.
	if (chk.version) {
		ok("versi live iOS valid & konsisten dengan release_id",
			/^\d+\.\d+\.\d+$/.test(String(chk.version)) &&
			String(chk.release_id || "").includes(String(chk.version)),
			JSON.stringify({ v: chk.version, rid: chk.release_id }));
		ok("changed berupa boolean", typeof chk.changed === "boolean",
			String(chk.changed));
	}

	// Manifest-only: bukti nyata rantai CDN -> dekrip v2 -> parse YooAsset.
	const mo = runPy(["--apply", "--manifest-only"]);
	let manifestOk = false, manifestInfo = "";
	try {
		const d = JSON.parse(mo);
		manifestOk = d.ok === true && d.catalog === chk.version &&
			d.bundles > 3000 && d.skeleton > 1000 &&
			d.resource_type === "ios_cn_release";
		manifestInfo = JSON.stringify({ catalog: d.catalog, bundles: d.bundles,
			skeleton: d.skeleton, todo: d.todo });
	} catch (e) {
		manifestInfo = String(mo).slice(0, 160);
	}
	ok("--apply --manifest-only mendekrip manifest iOS", manifestOk, manifestInfo);

	// Solver bundle v3 Android (tetap dipelihara untuk referensi/RE lanjutan).
	let selfV3 = "";
	try {
		selfV3 = execFileSync("/usr/bin/python3",
			[path.join(ROOT, "tools", "mitao", "idol_rs_v3.py"), "--self-test"],
			{ encoding: "utf8", timeout: 60000 }).trim();
	} catch (e) { selfV3 = `GAGAL: ${e.message}`; }
	ok("dekripsi IDOLNAB3 v3 lolos self-test", /^oke:/.test(selfV3),
		selfV3.slice(0, 140));

	// Solver v2 iOS: fallback openssl, jalan di venv service.
	let selfV2 = "";
	try {
		selfV2 = execFileSync(PY,
			[path.join(ROOT, "tools", "mitao", "idol_v2.py"), "--self-test"],
			{ encoding: "utf8", timeout: 60000 }).trim();
	} catch (e) { selfV2 = `GAGAL: ${e.message}`; }
	ok("dekripsi IDOLAB2 v2 (iOS) lolos self-test", /^oke:/.test(selfV2),
		selfV2.slice(0, 140));

	console.log(`\n${failed.length ? "GAGAL: " + failed.join(" | ") : "Mitao Utopia updater ok"}`);
	process.exit(failed.length ? 1 : 0);
})().catch((e) => {
	console.error(e);
	process.exit(1);
});
