#!/usr/bin/env node
/**
 * Thumbnails for the `favorite_c###` Nikke models.
 *
 * These are Favorite Item scenes, not characters, so they have no entry under
 * /characters/ — they live under /favorites/ and are named after the model's
 * own texture file:
 *
 *   nikke/favorite_c192/FavoriteItemScene_c192_00.png
 *     -> https://nkas.pages.dev/favorites/FavoriteItemScene_c192_00_mi.png
 *
 * `_mi` is 256x512 and `_si` is 128x128; we take _mi per request and normalise
 * everything to SIZE x SIZE so the grid stays uniform with the other thumbs.
 *
 * The host answers HTTP 200 + an HTML error page for missing files, so every
 * response is validated as a real PNG before being kept.
 */
const fs = require("fs");
const path = require("path");
const https = require("https");
const sharp = require("sharp");

const API = "http://127.0.0.1:3000/api/models";
const DEST = "/srv/spine-viewer/public/thumbs/nikke";
const MANIFEST = path.join(DEST, "_manifest.json");
const SIZE = 128;
const CONCURRENCY = 6;
const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

fs.mkdirSync(DEST, { recursive: true });

function getJSON(url) {
	return new Promise((resolve, reject) => {
		require("http")
			.get(url, { timeout: 180000 }, (res) => {
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

async function normalise(buf) {
	return sharp(buf)
		.resize(SIZE, SIZE, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
		.png({ compressionLevel: 9 })
		.toBuffer();
}

/** Candidate URLs for a favorite model id, best first. */
function urlsFor(leaf) {
	// favorite_c192 -> FavoriteItemScene_c192_00_mi.png
	const m = /^favorite_(c\d+)(?:_(\d+))?$/.exec(leaf);
	if (!m) return [];
	const base = `FavoriteItemScene_${m[1]}_${(m[2] || "00").padStart(2, "0")}`;
	return [
		`https://nkas.pages.dev/favorites/${base}_mi.png`,
		`https://nkas.pages.dev/favorites/${base}_si.png`,
	];
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
	const data = await getJSON(API);
	const nikke = data.models.filter((m) => (m.game || "") === "nikke");
	const roots = nikke.filter((m) => !m.family || m.family.root === m.id);
	const fav = roots.filter((m) => m.id.split("/").pop().startsWith("favorite_"));
	console.log("root favorite_* :", fav.length);

	const manifest = fs.existsSync(MANIFEST) ? JSON.parse(fs.readFileSync(MANIFEST, "utf8")) : {};
	const todo = fav.filter((m) => !manifest[m.id] || !fs.existsSync(path.join(DEST, manifest[m.id])));
	console.log("sudah punya     :", fav.length - todo.length);
	console.log("perlu unduh     :", todo.length);

	let ok = 0;
	let fail = 0;
	const results = await mapLimit(todo, CONCURRENCY, async (m) => {
		const leaf = m.id.split("/").pop();
		for (const u of urlsFor(leaf)) {
			const buf = await fetchBuf(u);
			if (!buf) continue;
			const out = path.join(DEST, `__${m.id.replace(/\//g, "_")}__.png`);
			try {
				fs.writeFileSync(out, await normalise(buf));
			} catch {
				return { id: m.id, file: null };
			}
			return { id: m.id, file: path.basename(out), from: u.split("/").pop() };
		}
		return { id: m.id, file: null };
	});

	for (const r of results) {
		if (r?.file) {
			manifest[r.id] = r.file;
			ok++;
			console.log(`  OK   ${r.id.padEnd(20)} <- ${r.from}`);
		} else {
			fail++;
			console.log(`  GAGAL ${r?.id || "?"}`);
		}
	}
	console.log("berhasil :", ok, "| gagal :", fail);

	// rebuild manifest: root + variants share the image
	const final = {};
	let covered = 0;
	for (const m of nikke) {
		const root = (m.family && m.family.root) || m.id;
		if (manifest[root]) {
			final[m.id] = manifest[root];
			covered++;
		}
	}
	fs.writeFileSync(MANIFEST, JSON.stringify(final));
	console.log("\nmodel dengan thumbnail :", covered, "/", nikke.length);
})();
