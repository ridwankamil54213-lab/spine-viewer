#!/usr/bin/env node
/**
 * Parse seluruh 287 skeleton Lost Sword (.skel biner maupun .json) di
 * assets/lostsword/{standing,chibi,pet}/ menggunakan runtime @pixi-spine/runtime-4.1
 * yang sama dengan browser viewer.
 */
const fs = require("node:fs");
const path = require("node:path");
const { SkeletonBinary, SkeletonJson, AtlasAttachmentLoader } = require("@pixi-spine/runtime-4.1");
const { TextureAtlas } = require("@pixi-spine/base");

const ROOT = path.resolve(__dirname, "..", "assets", "lostsword");

function collectSkeletons(root) {
	const found = [];
	for (const group of ["standing", "chibi", "pet"]) {
		const gp = path.join(root, group);
		if (!fs.existsSync(gp) || !fs.statSync(gp).isDirectory()) continue;
		for (const model of fs.readdirSync(gp).sort()) {
			const mp = path.join(gp, model);
			if (!fs.statSync(mp).isDirectory()) continue;
			const files = fs.readdirSync(mp);
			const skels = files.filter((f) => /\.(skel|json)$/i.test(f));
			const atlases = files.filter((f) => /\.atlas$/i.test(f));
			for (const skel of skels) {
				const stem = skel.replace(/\.(skel|json)$/i, "");
				const atlas =
					atlases.find((a) => a.replace(/\.atlas$/i, "").toLowerCase() === stem.toLowerCase()) ||
					atlases[0];
				if (atlas) found.push({ dir: mp, group, model, skel, atlas });
			}
		}
	}
	return found;
}

const items = collectSkeletons(ROOT);
console.log("skeleton ditemukan:", items.length);

let ok = 0;
const bad = [];
const stats = { bones: 0, anims: 0, withAnim: 0 };

for (const f of items) {
	try {
		const atlasText = fs.readFileSync(path.join(f.dir, f.atlas), "utf8");
		const atlas = new TextureAtlas(atlasText, (_line, cb) =>
			cb({ width: 2048, height: 2048, valid: true, scaleMode: 1, setSize() {}, dispose() {} }),
		);
		const loader = new AtlasAttachmentLoader(atlas);
		let d;
		if (/\.json$/i.test(f.skel)) {
			const parser = new SkeletonJson(loader);
			d = parser.readSkeletonData(JSON.parse(fs.readFileSync(path.join(f.dir, f.skel), "utf8")));
		} else {
			const parser = new SkeletonBinary(loader);
			const buf = fs.readFileSync(path.join(f.dir, f.skel));
			d = parser.readSkeletonData(new Uint8Array(buf));
		}
		ok++;
		stats.bones += d.bones.length;
		stats.anims += d.animations.length;
		if (d.animations.length) stats.withAnim++;
	} catch (e) {
		bad.push(`${f.group}/${f.model}/${f.skel}: ${String(e.message).slice(0, 80)}`);
	}
}

console.log("berhasil di-parse :", ok);
console.log("gagal            :", bad.length);
console.log("rata-rata tulang :", ok ? Math.round(stats.bones / ok) : 0);
console.log("rata-rata animasi:", ok ? (stats.anims / ok).toFixed(1) : 0);
console.log("punya animasi    :", stats.withAnim);
if (bad.length) {
	console.error("\ncontoh gagal:");
	for (const b of bad.slice(0, 12)) console.error("   ", b);
	process.exit(1);
}
