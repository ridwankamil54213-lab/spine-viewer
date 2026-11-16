"use strict";

/**
 * Unggah hasil `--apply` ke GDrive, langsung di job yang sama.
 *
 * Tujuannya: sekali klik "Terapkan" di UI, aset baru/berubah ikut ter-backup
 * ke Shared Drive (folder library 1zRly3eeewcrgdIe3bOUQUmyWUXXIwnzo). Dulu
 * ini harus dilakukan manual — itulah yang bikin BD2 kelewat saat diunduh
 * ulang dari repo.
 *
 * Cara kerja:
 *  1. Catat `sinceMs` = waktu apply dimulai.
 *  2. Sesudah apply sukses, cari root (folder tingkat-1 di assets/ atau
 *     public/thumbs/) yang punya berkas lebih baru dari `sinceMs`.
 *  3. Gabungkan dengan STATIC_ROOTS (peta eksplisit per updater) supaya
 *     berkas yang mtime-nya dipreservasi / sudah hilang di remote tetap
 *     terdeteksi rclone.
 *  4. Jalankan `rclone copy <root> <remote>:<tujuan>` per root, berurutan.
 *     `copy` (bukan `sync`) sengaja: TIDAK pernah menghapus berkas di remote.
 *     rclone membandingkan size + mtime, jadi root 9,3 GB tetap murah — cuma
 *     berkas yang benar-benar beda yang diunggah.
 *
 * Layout remote (satu --drive-root-folder-id):
 *   assets/<root>/...        -> gdrive:<root>/...
 *   public/thumbs/<root>/... -> gdrive:thumbs/<root>/...
 *
 * Konfigurasi lewat env (semua punya default yang aman):
 *   GDRIVE_UPLOAD=0                  matikan fitur
 *   GDRIVE_REMOTE=gdrive            nama remote rclone
 *   GDRIVE_ROOT_ID=<id>             folder library di Shared Drive
 *   RCLONE_BIN=/usr/bin/rclone      path absolut (PATH systemd bisa beda)
 *   GDRIVE_UPLOAD_TIMEOUT_MS=<ms>   timeout per root (default 45 menit)
 *   GDRIVE_UPLOAD_GLOBAL_MS=<ms>    pagar total semua root (default 90 menit)
 *
 * Kredensial TIDAK disimpan di sini: rclone memakai config milik user
 * (~/.config/rclone/rclone.conf, 0600) lewat HOME proses.
 */
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const RCLONE = process.env.RCLONE_BIN || "/usr/bin/rclone";
const REMOTE = process.env.GDRIVE_REMOTE || "gdrive";
const ROOT_ID = process.env.GDRIVE_ROOT_ID || "1zRly3eeewcrgdIe3bOUQUmyWUXXIwnzo";
const ENABLED = process.env.GDRIVE_UPLOAD !== "0";
// Batas per-root. Root berisi ribuan berkas kecil (klip audio) butuh jatah
// sendiri; dulu satu deadline 30 mnt dipakai bareng sehingga root TERAKHIR
// selalu kehabisan waktu. Pagar global tetap ada supaya totalnya terikat.
const TIMEOUT_MS = Number(process.env.GDRIVE_UPLOAD_TIMEOUT_MS) || 45 * 60 * 1000;
const GLOBAL_MS = Number(process.env.GDRIVE_UPLOAD_GLOBAL_MS) || 90 * 60 * 1000;

const RCLONE_ARGS = [
	"--fast-list",
	"--transfers", "8",
	"--checkers", "16",
	"--drive-chunk-size", "64M",
	"--retries", "5",
	"--low-level-retries", "20",
	"--stats", "15s",
	"--stats-one-line",
	// Tanpa ini stats rclone berada di level INFO dan panel log terasa beku
	// selama upload besar (tidak ada baris baru selama beberapa menit).
	"--log-level", "INFO",
];

/**
 * Root yang DITULIS tiap updater. Ini bukan daftar semua game — cuma folder
 * yang perlu dicek ke remote meski tidak ada berkas yang mtime-nya berubah
 * (mis. unduhan yang mempertahankan timestamp asli). Root yang baru muncul
 * (game yang belum punya aset) tetap terdeteksi lewat changedRoots().
 */
const STATIC_ROOTS = {
	arkrecode: { assets: ["arkrecode", "arkrecode-cg"] },
	shoujoukaisen: { assets: ["shoujoukaisen"] },
	pokerfate: { assets: ["pokerfate"] },
	"mitao-utopia": { assets: ["mitao-utopia"], thumbs: ["mitao-utopia"] },
	crosscore: {
		assets: ["crosscore", "crosscore-cg"],
		// crosscore-render = potret hasil render-tools, bukan unduhan sumber.
		thumbs: ["crosscore", "crosscore-render"],
		// media = folder di bawah public/, tujuannya gdrive:<path> yang sama.
		media: ["audio/crosscore"],
	},
	catshinobi: { assets: ["catshinobi"] },
	bd2: { assets: ["bd2", "bd2-char"], thumbs: ["bd2"] },
	azurlane: { assets: ["azurlane"] },
	"azurlane-l2d": { assets: ["azurlane-l2d"] },
	nikke: { assets: ["nikke"], thumbs: ["nikke"] },
	alliancesages: { assets: ["alliancesages", "alliancesages-cg"] },
	mcs18: { assets: ["mcs18"] },
	ivntight: { assets: ["ivntight"] },
	arknights: { assets: ["arknights"] },
	stellasora: { assets: ["stellasora", "stellasora-l2d"] },
	"stellasora-3d": { assets: ["stellasora-3d"] },
	zonenova: { assets: ["zonenova"] },
	girlwars: { assets: ["girlwars", "girlwars-l2d"] },
	lostsword: { assets: ["lostsword"], thumbs: ["lostsword"] },
	"lostsword-video": { assets: ["lostsword-video"] },
	eroera: { assets: ["eroera"], thumbs: ["eroera"] },
	mercenary: { assets: ["mercenary"] },
	dragontravelers: { assets: ["dragontravelers"] },
	"mad-drama": { assets: ["mad-drama"] },
	muvluv: { assets: ["muvluv"] },
	epic7: { assets: ["epic7", "epic7-combat", "epic7-skill", "epic7-wallpaper"] },
	chaoszero: {
		assets: ["chaoszero", "czn-cards"],
		thumbs: ["chaoszero", "czn-ui"],
	},
};

function staticRoots(game) {
	const r = STATIC_ROOTS[game] || {};
	return {
		assets: new Set(r.assets || []),
		thumbs: new Set(r.thumbs || []),
		media: new Set(r.media || []),
	};
}

/** Root dengan berkas yang mtime-nya >= sinceMs (satu proses `find`). */
function changedRoots(sinceMs) {
	const out = { assets: new Set(), thumbs: new Set() };
	const ref = path.join(os.tmpdir(), `spine-upload-ref-${process.pid}.tmp`);
	try {
		fs.writeFileSync(ref, "");
		// Mundur 2 dtk supaya berkas yang ditulis tepat di detik mulai apply
		// tidak terlewat karena pembulatan timestamp.
		const sec = (sinceMs - 2000) / 1000;
		fs.utimesSync(ref, sec, sec);
		const r = spawnSync(
			"find", ["assets", "public/thumbs", "-type", "f", "-newer", ref, "-print"],
			{ cwd: ROOT, encoding: "utf8", maxBuffer: 64 * 1024 * 1024, timeout: 120000 },
		);
		if (r.error) return out;
		for (const line of String(r.stdout || "").split(/\r?\n/)) {
			const p = line.trim().split("/");
			if (p[0] === "assets" && p.length > 2) out.assets.add(p[1]);
			else if (p[0] === "public" && p[1] === "thumbs" && p.length > 3) out.thumbs.add(p[2]);
		}
	} catch {
		/* find gagal -> tetap pakai STATIC_ROOTS */
	} finally {
		try { fs.unlinkSync(ref); } catch { /* abaikan */ }
	}
	return out;
}

function buildJobs(game, sinceMs) {
	const roots = staticRoots(game);
	const dyn = changedRoots(sinceMs);
	for (const r of dyn.assets) roots.assets.add(r);
	for (const r of dyn.thumbs) roots.thumbs.add(r);
	const jobs = [];
	for (const r of [...roots.assets].sort()) {
		const src = path.join(ROOT, "assets", r);
		if (fs.existsSync(src)) jobs.push({ src, dst: `${REMOTE}:${r}`, label: `assets/${r}` });
	}
	for (const r of [...roots.thumbs].sort()) {
		const src = path.join(ROOT, "public", "thumbs", r);
		if (fs.existsSync(src)) {
			jobs.push({ src, dst: `${REMOTE}:thumbs/${r}`, label: `thumbs/${r}` });
		}
	}
	// Klip suara / media lain di bawah public/ (bukan assets/).
	for (const r of [...roots.media].sort()) {
		const src = path.join(ROOT, "public", r);
		if (fs.existsSync(src)) {
			jobs.push({ src, dst: `${REMOTE}:${r}`, label: `public/${r}` });
		}
	}
	return jobs;
}

function runRclone(job, onLine, timeoutMs) {
	const started = Date.now();
	return new Promise((resolve) => {
		const args = [
			"copy", job.src, job.dst,
			"--drive-root-folder-id", ROOT_ID,
			...RCLONE_ARGS,
		];
		let child;
		try {
			child = spawn(RCLONE, args, {
				cwd: ROOT,
				env: { ...process.env, HOME: os.homedir() },
			});
		} catch (err) {
			resolve({ ok: false, code: null, errors: [err.message], lastStats: "" });
			return;
		}
		let buf = "";
		let emitted = 0;
		const errors = [];
		let lastStats = "";
		let timedOut = false;
		let settled = false;
		const feed = (chunk) => {
			buf += String(chunk);
			const lines = buf.split(/\r?\n/);
			buf = lines.pop() ?? "";
			for (const raw of lines) {
				const t = raw.trim();
				if (!t) continue;
				if (/ERROR/i.test(t)) errors.push(t.slice(0, 200));
				if (/Transferred:|Checks:/.test(t)) lastStats = t.slice(0, 200);
				// Batasi kebisingan: 40 baris pertama + semua baris penting.
				if (emitted < 40 || /ERROR|Transferred:|Checks:/i.test(t)) onLine(t);
				emitted += 1;
			}
		};
		child.stdout?.on("data", feed);
		child.stderr?.on("data", feed);
		const timer = setTimeout(() => {
			timedOut = true;
			child.kill("SIGTERM");
		}, timeoutMs);
		const done = (code) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			if (buf.trim()) onLine(buf.trim().slice(0, 200));
			resolve({
				ok: !timedOut && code === 0 && errors.length === 0,
				code, timedOut, errors: errors.slice(0, 3), lastStats,
				seconds: Math.round((Date.now() - started) / 100) / 10,
			});
		};
		child.on("error", (err) => { errors.push(err.message); done(null); });
		child.on("close", (code) => done(code));
	});
}

/**
 * Dipanggil dari handler /api/update/:game?mode=apply SETELAH apply sukses.
 * `onLine` menerima satu baris teks untuk panel log. Tidak pernah melempar:
 * kegagalan upload tidak boleh membatalkan apply yang sudah berhasil di disk.
 */
async function uploadAfterApply(game, sinceMs, onLine) {
	if (!ENABLED) {
		onLine("[gdrive] dilewati: GDRIVE_UPLOAD=0");
		return { ok: true, skipped: true, reason: "GDRIVE_UPLOAD=0", jobs: [] };
	}
	if (!fs.existsSync(RCLONE)) {
		onLine(`[gdrive] GAGAL: ${RCLONE} tidak ada`);
		return { ok: false, error: `rclone tidak ditemukan: ${RCLONE}`, jobs: [] };
	}
	const jobs = buildJobs(game, sinceMs);
	if (!jobs.length) {
		onLine("[gdrive] tidak ada root yang perlu diunggah, dilewati");
		return { ok: true, jobs: [], roots: 0 };
	}
	const t0 = Date.now();
	// Pagar global mencegah total upload melampaui GDRIVE_UPLOAD_GLOBAL_MS,
	// tapi tiap root tetap dapat jatah TIMEOUT_MS penuh (dipangkas sisa pagar).
	const deadline = Date.now() + GLOBAL_MS;
	const results = [];
	for (const job of jobs) {
		const remaining = deadline - Date.now();
		onLine(`[gdrive] ${job.label} -> ${job.dst} …`);
		if (remaining <= 0) {
			onLine(`[gdrive] ${job.label}: GAGAL (batas waktu upload habis)`);
			results.push({ root: job.label, ok: false, code: null,
				timedOut: true, errors: ["batas waktu global habis"], stats: "", seconds: 0 });
			continue;
		}
		const slice = Math.min(remaining, TIMEOUT_MS);
		const r = await runRclone(job, (l) => onLine("[gdrive]   " + l), slice);
		results.push({
			root: job.label,
			ok: r.ok,
			code: r.code,
			timedOut: r.timedOut,
			errors: r.errors,
			stats: r.lastStats,
			seconds: r.seconds,
		});
		onLine(`[gdrive] ${job.label}: ${r.ok ? "ok" : "GAGAL"}${r.lastStats ? " | " + r.lastStats : ""}`);
	}
	const ok = results.every((r) => r.ok);
	const summary = {
		ok,
		roots: jobs.length,
		okRoots: results.filter((r) => r.ok).length,
		failed: results.filter((r) => !r.ok).map((r) => r.root),
		seconds: Math.round((Date.now() - t0) / 100) / 10,
		jobs: results,
	};
	onLine(`[gdrive] selesai: ${summary.okRoots}/${summary.roots} root, ` +
		`${summary.seconds} dtk${ok ? "" : " — ADA YANG GAGAL, cek baris di atas."}`);
	return summary;
}

module.exports = { uploadAfterApply, buildJobs, changedRoots, STATIC_ROOTS };
