#!/usr/bin/env node
/**
 * Download Nikke thumbnails and normalise every image to a 128px PNG.
 *
 * Sources, best first (the host returns HTTP 200 + an HTML error page for
 * missing files, so responses are validated as real PNGs):
 *   /characters/si_<id>_00_s.png   128x128  - ideal, already thumb-sized
 *   /characters/<id>_00.png        419x881
 *   /characters_hq/<id>_00.png     780x1638 - last resort, downscaled hard
 *
 * Variants (c010/aim, c010/cover) reuse their root character's image.
 */
const fs = require("fs");
const path = require("path");
const https = require("https");
const sharp = require("sharp");

const API = "http://127.0.0.1:3000/api/models";
const DEST = "/srv/spine-viewer/public/thumbs/nikke";
const MANIFEST = path.join(DEST, "_manifest.json");
const MISSING_LIST = "/root/thumb-missing.txt";
const SIZE = 128;
const CONCURRENCY = 10;
const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

fs.mkdirSync(DEST, { recursive: true });

function getJSON(url) {
	return new Promise((resolve, reject) => {
		const mod = url.startsWith("https") ? https : require("http");
		mod
			.get(url, { timeout: 120000 }, (res) => {
				let d = "";
				res.on("data", (c) => (d += c));
				res.on("end", () => {
					try {
						resolve(JSON.parse(d));
					} catch (e) {
						reject(e);
					}
				});
			})
			.on("error", reject)
			.on("timeout", function () {
				this.destroy();
				reject(new Error("timeout"));
			});
	});
}

function isPng(buf) {
	if (!buf || buf.length < 24 || !buf.subarray(0, 8).equals(PNG_MAGIC)) return false;
	const w = buf.readUInt32BE(16);
	const h = buf.readUInt32BE(20);
	return w >= 16 && w <= 8192 && h >= 16 && h <= 8192;
}

function fetchBuf(url, redirects = 0) {
	return new Promise((resolve) => {
		if (redirects > 3) return resolve(null);
		const req = https.get(
			url,
			{ timeout: 30000, headers: { "User-Agent": "Mozilla/5.0" } },
			(res) => {
				if ([301, 302, 307, 308].includes(res.statusCode) && res.headers.location) {
					res.resume();
					return resolve(fetchBuf(res.headers.location, redirects + 1));
				}
				if (res.statusCode !== 200) {
					res.resume();
					return resolve(null);
				}
				const chunks = [];
				res.on("data", (c) => chunks.push(c));
				res.on("end", () => {
					const buf = Buffer.concat(chunks);
					resolve(isPng(buf) ? buf : null);
				});
			}
		);
		req.on("error", () => resolve(null));
		req.on("timeout", () => {
			req.destroy();
			resolve(null);
		});
	});
}

/** Centre on a transparent square canvas so portraits keep their aspect. */
async function normalise(buf) {
	return sharp(buf)
		.resize(SIZE, SIZE, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
		.png({ compressionLevel: 9 })
		.toBuffer();
}

function urlsFor(leaf) {
	return [
		`https://nkas.pages.dev/characters/si_${leaf}_00_s.png`,
		`https://nkas.pages.dev/characters/${leaf}_00.png`,
		`https://nkas.pages.dev/characters/si_${leaf}_01_s.png`,
		`https://nkas.pages.dev/characters_hq/${leaf}_00.png`,
	];
}

async function probe(id) {
	const leaf = id.split("/").pop();
	for (const u of urlsFor(leaf)) {
		const buf = await fetchBuf(u);
		if (buf) return { id, buf };
	}
	return { id, buf: null };
}

async function mapLimit(items, limit, fn) {
	const out = [];
	let i = 0;
	await Promise.all(
		Array.from({ length: Math.min(limit, items.length) }, async () => {
			while (i < items.length) {
				const idx = i++;
				out[idx] = await fn(items[idx]);
			}
		})
	);
	return out;
}

(async () => {
	console.log("sharp:", sharp.versions ? sharp.versions.sharp : "ok");

	const data = await getJSON(API);
	const nikke = data.models.filter((m) => (m.game || "") === "nikke");
	const roots = nikke.filter((m) => !m.family || m.family.root === m.id);
	console.log("model nikke :", nikke.length);
	console.log("root        :", roots.length);

	// existing manifest entries whose file still exists are already good
	const manifest = fs.existsSync(MANIFEST) ? JSON.parse(fs.readFileSync(MANIFEST, "utf8")) : {};
	const have = new Set(Object.values(manifest).filter((f) => fs.existsSync(path.join(DEST, f))));
	const existingByRoot = new Map();
	for (const [mid, file] of Object.entries(manifest)) {
		if (fs.existsSync(path.join(DEST, file))) existingByRoot.set(mid, file);
	}

	const todo = roots.filter((r) => !existingByRoot.has(r.id));
	console.log("sudah punya :", roots.length - todo.length);
	console.log("perlu unduh :", todo.length);

	let ok = 0;
	let fail = 0;
	if (todo.length) {
		const results = await mapLimit(todo, CONCURRENCY, async (m) => {
			const { buf } = await probe(m.id);
			if (!buf) return null;
			const out = path.join(DEST, `__${m.id.replace(/\//g, "_")}__.png`);
			try {
				fs.writeFileSync(out, await normalise(buf));
			} catch (e) {
				// unreadable source image — drop it rather than keep a broken file
				return null;
			}
			return { id: m.id, file: path.basename(out) };
		});
		for (const r of results) {
			if (r) {
				manifest[r.id] = r.file;
				ok++;
			} else fail++;
		}
		console.log("berhasil    :", ok);
		console.log("gagal       :", fail);
	}

	// normalise everything to SIZE x SIZE
	let resized = 0;
	for (const f of fs.readdirSync(DEST)) {
		if (!f.endsWith(".png")) continue;
		const p = path.join(DEST, f);
		const buf = fs.readFileSync(p);
		if (!isPng(buf)) continue;
		const w = buf.readUInt32BE(16);
		const h = buf.readUInt32BE(20);
		if (w === SIZE && h === SIZE) continue;
		try {
			fs.writeFileSync(p, await normalise(buf));
			resized++;
		} catch {
			/* leave as-is */
		}
	}
	console.log("di-resize   :", resized);

	// rebuild: root and all its variants share one image
	const final = {};
	const still = [];
	for (const m of nikke) {
		const root = (m.family && m.family.root) || m.id;
		if (manifest[root]) final[m.id] = manifest[root];
		else still.push(m.id);
	}
	fs.writeFileSync(MANIFEST, JSON.stringify(final));

	let bytes = 0;
	let files = 0;
	for (const f of fs.readdirSync(DEST)) {
		if (f.endsWith(".png")) {
			bytes += fs.statSync(path.join(DEST, f)).size;
			files++;
		}
	}
	console.log("\nfile gambar :", files);
	console.log("dengan thumb:", Object.keys(final).length);
	console.log("tanpa thumb :", still.length);
	console.log("total ukuran: " + (bytes / 1024 / 1024).toFixed(1) + " MB");
	fs.writeFileSync(MISSING_LIST, [...new Set(still)].sort().join("\n"));
	console.log("daftar miss : " + MISSING_LIST);
})();
