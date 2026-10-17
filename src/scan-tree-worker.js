"use strict";

/* Entry point untuk worker thread: jalan menyusuri assets/ di thread
 * terpisah lalu mengirim hasilnya kembali ke proses utama.
 *
 * Alasan worker, bukan setTimeout: jalan menyusuri 141 ribu file memakai
 * ~2,2 detik CPU sinkron. Dijalankan di thread utama, satu request daftar
 * model akan membekukan SEBARIS semua request lain — termasuk pemuatan
 * tekstur — selama dua detik penuh. Lihat src/scan-tree.js. */

const { parentPort, workerData } = require("worker_threads");
const { walkAssets } = require("./scan-tree");

if (!parentPort) {
	throw new Error("scan-tree-worker harus dijalankan sebagai worker thread.");
}

const { signature, sizes, dirs } = walkAssets(workerData.assets, workerData.scanConfig);
parentPort.postMessage({
	signature,
	// Map tidak dikirim utuh: pasangan jauh lebih murah lewat structured
	// clone dan bebas isu prototype saat dibangun ulang di penerima.
	sizes: [...sizes],
	dirs: [...dirs],
});