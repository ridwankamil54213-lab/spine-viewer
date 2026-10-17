"use strict";

/* Satu kali jalan menyusuri assets/ untuk tiga hal sekaligus: tanda tangan
 * perubahan (mtime termuda + jumlah file + total ukuran), ukuran tiap folder,
 * dan peta id model -> folder fisiknya.
 *
 * Fungsi ini dipakai dari dua tempat:
 *   - src/server.js, untuk jalur sinkron (boot dan ?refresh=1);
 *   - src/scan-tree-worker.js, supaya jalur biasa tidak pernah memblokir
 *     event loop. Jalan menyusuri 141 ribu file menahan loop utama ~2,2
 *     detik (terukur), jadi ia harus berjalan di thread terpisah.
 *
 * Peta id->folder ada di sini karena id model BUKAN path foldernya:
 * scanModels() membangun id dari path.relative() lalu mengganti semua
 * karakter di luar [\w.-/] dengan minus ("hazereverb/...chongji1--").
 * Transformasi itu tidak bisa dibalik, jadi foldernya harus dicatat saat
 * jalan menyusuri — memakai regex yang sama persis dengan scanModels(). */

const fs = require("fs");
const path = require("path");

/** Fingerprint of the scan config, mixed into the cache signature.
 *
 * scanModels() output depends on GAME_ROOTS (label, spineRuntime, pmaDefault)
 * as much as on the files. Mixing this in means a GAME_ROOTS edit busts the
 * cache with no asset write required. */
function configHash(s) {
	let h = 5381;
	for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
	return h.toString(36);
}

/**
 * @param {string} assets  absolute path of the asset root
 * @param {string} scanConfig  JSON fingerprint of GAME_ROOTS (see server.js)
 * @returns {{signature: string, sizes: Map<string, number>, dirs: Map<string, string>}}
 */
function walkAssets(assets, scanConfig) {
	let newest = 0;
	let files = 0;
	const sizes = new Map();
	const dirs = new Map();
	const walk = (d, depth) => {
		if (depth > 8) return 0;
		let entries;
		try {
			entries = fs.readdirSync(d, { withFileTypes: true });
		} catch {
			return 0;
		}
		let total = 0;
		for (const e of entries) {
			if (e.name === ".git") continue;
			const p = path.join(d, e.name);
			try {
				if (e.isDirectory()) {
					total += walk(p, depth + 1);
				} else if (e.isSymbolicLink()) {
					// follow symlinked asset folders
					const st = fs.statSync(p);
					if (st.isDirectory()) total += walk(p, depth + 1);
					else {
						total += st.size;
						files += 1;
						newest = Math.max(newest, st.mtimeMs);
					}
				} else {
					const st = fs.statSync(p);
					total += st.size;
					files += 1;
					newest = Math.max(newest, st.mtimeMs);
				}
			} catch {
				/* skip unreadable entries */
			}
		}
		sizes.set(d, total);
		if (d !== assets) {
			const rel = path.relative(assets, d).split(path.sep).join("/");
			// Regex yang sama dengan scanModels(): id = rel yang di-sanitize.
			dirs.set(rel.replace(/[^\w.\-/]+/g, "-"), d);
		}
		return total;
	};
	const total = walk(assets, 0);
	// Ukuran total + jumlah file ikut masuk signature: mtime termuda saja
	// tidak bisa mendeteksi penghapusan file yang bukan yang paling baru.
	const signature = `${newest}:${total}:${files}:${configHash(scanConfig)}`;
	return { signature, sizes, dirs };
}

module.exports = { walkAssets, configHash };