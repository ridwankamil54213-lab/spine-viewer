#!/usr/bin/env node
/**
 * Regresi ringan untuk src/gdrive-upload.js — TANPA jaringan / tanpa upload.
 *
 * Yang diuji: peta root lengkap untuk 27 updater, penggabungan root dinamis,
 * dan keberadaan remote rclone. Upload sungguhan diverifikasi terpisah lewat
 * endpoint /api/update/<game>?mode=apply (lihat README).
 *
 * Usage: node tools/check-gdrive-upload.cjs
 */
const assert = require("assert");
const { spawnSync } = require("child_process");
const { buildJobs, changedRoots, STATIC_ROOTS } = require("../src/gdrive-upload");

const ok = (m) => console.log("ok   " + m);

// 1. Tripwire: jumlah updater di registry == jumlah entri peta root.
const server = require("fs").readFileSync(
	require("path").resolve(__dirname, "../src/server.js"), "utf8");
const block = server.slice(
	server.indexOf("const UPDATERS = {"),
	server.indexOf("\n};", server.indexOf("const UPDATERS = {")));
const keys = [...block.matchAll(/^\t(?:"([\w-]+)"|([\w-]+)): \{/gm)]
	.map((m) => m[1] || m[2]);
assert.strictEqual(keys.length, 27, `registry updater: ${keys.length}`);
for (const k of keys) {
	assert.ok(STATIC_ROOTS[k], `STATIC_ROOTS belum punya ${k}`);
	assert.ok((STATIC_ROOTS[k].assets || []).length, `${k} tidak punya root aset`);
}
ok(`27 updater punya peta root (${Object.keys(STATIC_ROOTS).length} entri)`);

// 2. buildJobs menggabungkan static + dinamis, dan memetakan tujuan remote.
const since = Date.now() - 60 * 60 * 1000;
const jobs = buildJobs("chaoszero", since);
const byLabel = Object.fromEntries(jobs.map((j) => [j.label, j.dst]));
for (const label of ["assets/chaoszero", "assets/czn-cards",
	"thumbs/chaoszero", "thumbs/czn-ui"]) {
	assert.ok(byLabel[label], `root hilang: ${label}`);
}
assert.strictEqual(byLabel["assets/chaoszero"], "gdrive:chaoszero");
assert.strictEqual(byLabel["thumbs/chaoszero"], "gdrive:thumbs/chaoszero");
ok("chaoszero: 4 root + tujuan remote benar");

const bd2 = buildJobs("bd2", since).map((j) => j.label);
for (const label of ["assets/bd2", "assets/bd2-char", "thumbs/bd2"]) {
	assert.ok(bd2.includes(label), `bd2 root hilang: ${label}`);
}
ok("bd2: root multi-folder + thumbnail ikut terpetakan");

// 3. Deteksi dinamis mengembalikan bentuk yang diharapkan.
const dyn = changedRoots(since);
assert.ok(dyn.assets instanceof Set && dyn.thumbs instanceof Set);
ok(`deteksi dinamis: ${dyn.assets.size} root aset / ${dyn.thumbs.size} root thumbnail`);

// 4. rclone + remote tersedia (tanpa kontak jaringan).
const r = spawnSync("/usr/bin/rclone", ["listremotes"], { encoding: "utf8" });
assert.strictEqual(r.status, 0, "rclone tidak bisa dijalankan");
assert.ok(String(r.stdout).split(/\r?\n/).includes("gdrive:"),
	"remote gdrive: tidak ada di config rclone");
ok("rclone + remote gdrive: tersedia");

console.log("\nGDrive upload roots ok");
