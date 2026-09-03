#!/usr/bin/env node
/**
 * Parse every extracted Lost Sword skeleton with the SAME runtime the browser
 * viewer uses, so we only keep models that actually render.
 *
 * Textures are stubbed out — we want metadata (bones, animations), not pixels.
 */
const fs = require("fs");
const path = require("path");
const { SkeletonBinary, AtlasAttachmentLoader } = require("@pixi-spine/runtime-4.1");
const { TextureAtlas } = require("@pixi-spine/base");

const ROOT = "/root/lostsword-apk";

function walk(dir, out = []) {
	for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
		const p = path.join(dir, e.name);
		if (e.isDirectory()) walk(p, out);
		else out.push(p);
	}
	return out;
}

function foldersWithSpine(root) {
	const found = [];
	for (const group of fs.readdirSync(root)) {
		const gp = path.join(root, group);
		if (!fs.statSync(gp).isDirectory()) continue;
		for (const model of fs.readdirSync(gp)) {
			const mp = path.join(gp, model);
			if (!fs.statSync(mp).isDirectory()) continue;
			const files = fs.readdirSync(mp);
			const skel = files.find((f) => f.toLowerCase().endsWith(".skel"));
			const atlas = files.find((f) => f.toLowerCase().endsWith(".atlas"));
			if (skel && atlas) found.push({ dir: mp, group, model, skel, atlas, files });
		}
	}
	return found;
}

const folders = foldersWithSpine(ROOT);
console.log("folder dengan skel+atlas:", folders.length);

let ok = 0;
const bad = [];
const stats = { bones: 0, anims: 0, withAnim: 0 };

for (const f of folders) {
	try {
		const atlasText = fs.readFileSync(path.join(f.dir, f.atlas), "utf8");
		const atlas = new TextureAtlas(atlasText, (line, cb) =>
			cb({ width: 2048, height: 2048, valid: true, scaleMode: 1, setSize() {}, dispose() {} })
		);
		const parser = new SkeletonBinary(new AtlasAttachmentLoader(atlas));
		const buf = fs.readFileSync(path.join(f.dir, f.skel));
		const d = parser.readSkeletonData(new Uint8Array(buf));
		ok++;
		stats.bones += d.bones.length;
		stats.anims += d.animations.length;
		if (d.animations.length) stats.withAnim++;
	} catch (e) {
		bad.push(`${f.group}/${f.model}: ${String(e.message).slice(0, 70)}`);
	}
}

console.log("berhasil di-parse :", ok);
console.log("gagal            :", bad.length);
console.log("rata-rata tulang :", ok ? Math.round(stats.bones / ok) : 0);
console.log("rata-rata animasi:", ok ? (stats.anims / ok).toFixed(1) : 0);
console.log("punya animasi    :", stats.withAnim);
if (bad.length) {
	console.log("\ncontoh gagal:");
	for (const b of bad.slice(0, 12)) console.log("   ", b);
}
