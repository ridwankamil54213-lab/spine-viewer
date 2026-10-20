"use strict";

const path = require("path");
const fs = require("fs");
const fsp = require("fs/promises");
const express = require("express");
const multer = require("multer");
const compression = require("compression");
const zlib = require("zlib");
const crypto = require("crypto");
const { promisify } = require("util");
const { spawn, spawnSync } = require("child_process");
const { SkeletonBinary, AtlasAttachmentLoader } = require("@pixi-spine/runtime-4.1");
const { TextureAtlas } = require("@pixi-spine/base");
const { detectFromBinary, detectFromJson, pickRuntime } = require("./spine-version.cjs");
const { Worker } = require("worker_threads");
// Jalan menyusuri assets/ dipindah ke modul terpisah supaya bisa dipakai
// dari dua tempat: jalur sinkron di sini dan worker thread (lihat bawah).
const { walkAssets } = require("./scan-tree");

/** Same API surface across runtimes, so pick by detected version. */
const RUNTIMES = {
	"3.8": () => require("@pixi-spine/runtime-3.8"),
	"4.0": () => require("@pixi-spine/runtime-4.0"),
	"4.1": () => require("@pixi-spine/runtime-4.1"),
	// Genuine Spine 4.2. The 4.1 runtime predates the format, and the 4.3
	// runtime reads a `referenceScale` float in the header that 4.2 files do
	// not contain — both desync and return garbage strings.
	//
	// Take it from spine-pixi-v7-42, not a standalone spine-core: the renderer
	// bundles its own core and dispatches attachments with `instanceof`, so
	// using a separate copy makes every model render as nothing at all.
	"4.2": () => require("spine-pixi-v7-42"),
};

const ROOT = path.resolve(__dirname, "..");
const ASSETS = path.join(ROOT, "assets");
const THUMBS = path.join(ROOT, "public", "thumbs");
const DATA = path.join(ROOT, "data");
const PORT = Number(process.env.PORT) || 3000;
const HOST = process.env.HOST || "0.0.0.0";
const MAX_UPLOAD_MB = Number(process.env.MAX_UPLOAD_MB) || 64;

const SKEL_EXT = [".json", ".skel"];
const ATLAS_EXT = [".atlas", ".atlas.txt"];
const ATLAS_PAGE_EXT = [".png", ".webp", ".jpg", ".jpeg"];

const isSkel = (f) => SKEL_EXT.some((e) => f.toLowerCase().endsWith(e));
const isAtlas = (f) => ATLAS_EXT.some((e) => f.toLowerCase().endsWith(e));
const isPage = (f) => ATLAS_PAGE_EXT.some((e) => f.toLowerCase().endsWith(e));

/** Reads a Spine .json skeleton: animations, skins, version, bounds. Safe on .skel (binary). */
/**
 * Reads a Spine binary .skel using the SAME parser the browser viewer uses
 * (@pixi-spine SkeletonBinary), so server-side metadata can never disagree with
 * what actually renders. Textures are stubbed out — we only want the metadata.
 */
function probeSkelBinary(file, atlasFile) {
	const atlasText = fs.readFileSync(atlasFile, "utf8");
	// Stub page: satisfies the atlas without loading a single pixel.
	const atlas = new TextureAtlas(atlasText, (line, cb) => {
		cb({ width: 2048, height: 2048, valid: true, scaleMode: 1, setSize() {}, dispose() {} });
	});

	const raw = new Uint8Array(fs.readFileSync(file));

	// data.version from a runtime that can't parse the file is garbage read
	// from the wrong offset (a 3.8.99 skeleton through the 4.1 runtime yields
	// "jCsuDWsJ3kO2LTEQ+VY..."), so detect from the bytes and pick the matching
	// runtime instead of trusting whatever the parser hands back.
	const version = detectFromBinary(raw);
	const key = pickRuntime(version);
	// Detection from the bytes picks the matching runtime; the fallback order
	// then walks progressively OLDER runtimes. 4.2 is included because
	// Stellar Affinity ships 4.2.35, which no @pixi-spine runtime can read.
	const order = [key, "4.2", "4.1", "4.0", "3.8"];

	let data = null;
	let lastErr = null;
	let usedKey = null;
	for (const rt of order) {
		if (!RUNTIMES[rt]) continue;
		try {
			const mod = RUNTIMES[rt]();
			const parser = new mod.SkeletonBinary(new mod.AtlasAttachmentLoader(atlas));
			const d = parser.readSkeletonData(raw);
			if (d?.bones?.length) { data = d; usedKey = rt; break; }
		} catch (err) {
			lastErr = err;
		}
	}
	if (!data) throw lastErr || new Error("Skeleton tidak bisa diurai.");

	return {
		spine: version?.raw || null,
		// Report the runtime that actually parsed the file, not the one the
		// version string asked for — a mismatch here silently mislabels the
		// model in the UI.
		runtime: usedKey || key,
		width: data.width,
		height: data.height,
		bones: data.bones?.length ?? 0,
		slots: data.slots?.length ?? 0,
		animations: (data.animations || []).map((a) => a.name),
		skins: (data.skins || []).map((s) => s.name).filter(Boolean),
	};
}

/* ------------------------------------------------------------------ *
 * Per-file inspection memo (inspectSkeleton + countAtlasPages)
 *
 * A full scan parses ~32k .skel files — each one loads a Spine runtime and
 * walks the skeleton — and reads ~32k .atlas files. That parse, not the
 * directory walk (which is under a second), is what made a rescan take ~13
 * minutes. The result for one file depends on just two things: its size and
 * its mtime. So memoise it per path and persist to disk:
 *   - an updater that adds 80 models parses only those ~200 files;
 *   - a restart re-reads the cache instead of re-parsing everything.
 * A changed file (size/mtime differs) misses and is re-parsed, so the memo
 * can never serve a stale skeleton for a file that changed on disk.
 * ------------------------------------------------------------------ */
const MEMO_FILE = path.join(DATA, "scan-memo.json");
let inspectMemo = null;
let inspectMemoDirty = false;
let inspectMemoHits = 0;
let inspectMemoMiss = 0;

function diskFingerprint(p) {
	try {
		const st = fs.statSync(p);
		if (!st.isFile()) return null;
		return `${st.size}:${Math.floor(st.mtimeMs)}`;
	} catch {
		return null;
	}
}

function loadInspectMemo() {
	if (inspectMemo) return inspectMemo;
	inspectMemo = new Map();
	try {
		const raw = JSON.parse(fs.readFileSync(MEMO_FILE, "utf8"));
		for (const [k, v] of Object.entries(raw.entries || {})) {
			if (v && typeof v.fp === "string") {
				inspectMemo.set(k, { fp: v.fp, skel: v.skel ?? null, pages: v.pages });
			}
		}
	} catch {
		/* first run / unreadable — start empty */
	}
	return inspectMemo;
}

function saveInspectMemo() {
	if (!inspectMemoDirty || !inspectMemo) return;
	try {
		fs.mkdirSync(DATA, { recursive: true });
		const entries = {};
		for (const [k, v] of inspectMemo) entries[k] = v;
		const tmp = MEMO_FILE + ".tmp";
		fs.writeFileSync(tmp, JSON.stringify({ v: 1, entries }));
		fs.renameSync(tmp, MEMO_FILE);
		inspectMemoDirty = false;
	} catch (err) {
		console.warn("[memo] gagal menyimpan:", err.message);
	}
}

function memoGet(p) {
	const m = loadInspectMemo();
	const e = m.get(p);
	if (!e) {
		inspectMemoMiss++;
		return undefined;
	}
	if (diskFingerprint(p) !== e.fp) {
		m.delete(p);
		inspectMemoMiss++;
		return undefined;
	}
	inspectMemoHits++;
	return e;
}

function memoPut(p, patch) {
	const fp = diskFingerprint(p);
	if (fp == null) return;
	const m = loadInspectMemo();
	const e = m.get(p) || {};
	m.set(p, { ...e, fp, ...patch });
	inspectMemoDirty = true;
}

/** Buang entri untuk berkas yang sudah tidak ada; jaga memo tetap ramping. */
function pruneInspectMemo() {
	const m = loadInspectMemo();
	let removed = 0;
	for (const p of m.keys()) {
		if (!fs.existsSync(p)) {
			m.delete(p);
			removed++;
		}
	}
	if (removed) inspectMemoDirty = true;
	return { kept: m.size, removed };
}

function inspectSkeleton(file, atlasFile) {
	const cached = memoGet(file);
	if (cached && cached.skel !== undefined) return cached.skel;
	const meta = inspectSkeletonUncached(file, atlasFile);
	memoPut(file, { skel: meta ?? null });
	return meta;
}

function inspectSkeletonUncached(file, atlasFile) {
	try {
		const buf = fs.readFileSync(file);
		if (buf.length < 8) return null;
		if (buf[0] === 0x7b) {
			// starts with '{' -> JSON skeleton
			const data = JSON.parse(buf.toString("utf8"));
			const skel = data.skeleton || {};
			const ver = String(skel.spine || "");
			const major = parseInt(ver.split(".")[0], 10);
			// The 2.x skip above only guarded BINARY skeletons. A Spine 2.1.27
			// skeleton exported to .json (every Epic Seven SCSP v2 model) fell
			// through to here, reported bones/animations fine, but never got
			// needsLegacyViewer — so the client handed it to pixi-spine, which
			// cannot draw 2.x, and the model rendered as nothing.
			// A .json skeleton that reports 2.x is NOT the same case as a
			// binary one. Binaries genuinely can't be parsed by any bundled
			// runtime, so they need the iframe viewer. But JSON — including
			// 2.1.27 JSON — is read fine by the 4.1 runtime (verified 250/250
			// on converted Project QT models), because the JSON layout is
			// close enough that the parser walks it without complaint.
			//
			// That's the whole point of tools/convert-spine2.py: turning
			// .skel into .json is what frees these models from the iframe.
			// Marking them legacy here would undo that and send them right
			// back to the viewer we were trying to escape.
			//
			// Only two things still need normalising at load time
			// (see src/spine2-normalize.js):
			//   1. events with no "name" — legal in 2.x, fatal in 3.8+
			//   2. `skins` as an object instead of an array
			const isJson = /\.json$/i.test(String(file || ""));
			const legacy = !isJson && Number.isFinite(major) && major > 0 && major < 3;
			// Spine 2.x stores `skins` as an OBJECT keyed by skin name
			// ({"default": {...}}); 3.x/4.x use an array of {name, ...}
			// records. `(data.skins || []).map(...)` threw on the object
			// form, and the surrounding try/catch swallowed it — the whole
			// inspect returned null, so every E7 model looked empty.
			const skinNames = Array.isArray(data.skins)
				? (data.skins || []).map((s) => s?.name).filter(Boolean)
				: Object.keys(data.skins || {});
			return {
				spine: skel.spine || null,
				width: skel.width ?? null,
				height: skel.height ?? null,
				bones: (data.bones || []).length,
				slots: (data.slots || []).length,
				animations: Object.keys(data.animations || {}),
				skins: skinNames,
				runtime: legacy ? "2.1.27" : null,
				needsLegacyViewer: legacy,
			};
		}
		if (!atlasFile) return null;
		// Spine 2.x binaries can't be read by any bundled runtime (3.8/4.0/4.1).
		// Probing them would report "no bones" and mark the model broken, when
		// it's actually fine — it just needs the 2.1.27 viewer. Detect the
		// version first and skip the probe for 2.x.
		const head = new Uint8Array(buf.slice(0, 512));
		const v = detectFromBinary(head);
		if (v && v.major < 3) {
			return {
				spine: v.raw,
				runtime: "2.1.27",
				width: null,
				height: null,
				bones: null,
				slots: null,
				animations: [],
				skins: [],
				// Flag rather than fail: the client switches renderers on this.
				needsLegacyViewer: true,
			};
		}
		return probeSkelBinary(file, atlasFile);
	} catch {
		return null;
	}
}

/** Counts atlas pages by reading the header block before the first region name. */
function countAtlasPages(file) {
	const cached = memoGet(file);
	if (cached && cached.pages !== undefined) return cached.pages;
	const pages = countAtlasPagesUncached(file);
	memoPut(file, { pages });
	return pages;
}

function countAtlasPagesUncached(file) {
	try {
		const lines = fs.readFileSync(file, "utf8").split(/\r?\n/);
		let pages = 0;
		for (const line of lines) {
			const s = line.trim();
			if (!s) continue;
			// Indented lines belong to the current page/region block.
			if (/^\s/.test(line)) continue;
			// A bare image filename is a page declaration. Pages can appear
			// again after region blocks (multi-page atlases), so keep scanning
			// the whole file instead of stopping at the first region.
			if (isPage(s) && /^[^:]+$/.test(s)) {
				pages++;
				continue;
			}
			// Any other non-indented line is either page metadata
			// (size/format/...) or the start of region definitions.
			if (/:/.test(s)) continue; // "size: 4096,4096" etc.

		}
		return pages;
	} catch {
		return 0;
	}
}

function dirBytes(dir) {
	// Sizes come from the single scanTree() walk; this is only a lookup.
	return dirBytesCache.get(dir) || 0;
}
/** Folder size cache, cleared whenever the asset tree changes. */
const dirBytesCache = new Map();

/**
 * Maps a top-level asset folder to the game it belongs to.
 * `label` is what the sidebar shows; `key` is the stable filter value.
 * Add a new entry here whenever a new asset root gets symlinked in.
 */
const GAME_ROOTS = [
	{ match: "nikke", key: "nikke", label: "Nikke: Goddess of Victory" },
	{ match: "lostsword-video", key: "lostsword-video", label: "Lost Sword — Video" },
	{ match: "lostsword", key: "lostsword", label: "Lost Sword" },
	{ match: "talesofangels", key: "talesofangels", label: "Tales of Angels" },
	{ match: "crosscore", key: "crosscore", label: "CrossCore" },
	{ match: "kink", key: "kink", label: "异种啪乐町 (Kink)" },
	{ match: "blissful", key: "blissful", label: "极乐深渊 (Blissful Abyss)", spineRuntime: "2.1.27", pmaDefault: false },
	// Longest prefix first: resolveGame matches with startsWith, so the more
	// specific "azurlane-chibi" must come before "azurlane" or every chibi
	// model gets absorbed into the main Azur Lane bucket.
	{ match: "azurlane-chibi", key: "azurlane-chibi", label: "Azur Lane — Chibi" },
	{ match: "azurlane-l2d", key: "azurlane-l2d", label: "Azur Lane — Live2D" },
	{ match: "azurlane", key: "azurlane", label: "Azur Lane" },
	// 禁果便利店 / 群交避难所 / 我的便利店竟成了美少女的避难所 (ERO LABS).
	// Addressables terbuka mcs18-client-resource-tw.1uhg.com; bundle
	// character* (arts/animation + spine_assets + storyanimation) berisi
	// .skel/.atlas/Texture2D. Lihat tools/mcs18/.
	{
		match: "mcs18",
		key: "mcs18",
		label: "禁果便利店",
		pmaDefault: false,
	},
	// Azure Taboo (EroLabs / pinkcore, NuTaku). Unity IL2CPP; the shipped APK
	// carries 15 hero Spine bundles (assets/prefab/hero/herospines/hero_<id>/
	// hero_<id>1.unity3d) plus 3 chouka_* UI Spine sets, all Spine 4.3.39-beta
	// with `pma:true`. Bundles are plain UnityFS (no fake header). Extracted via
	// tools/resdown.py; the rest of the catalogue streams from bb-download.pinkcore.net.
	{
		match: "azuretaboo",
		key: "azuretaboo",
		label: "Azure Taboo",
		spineRuntime: "4.3",
		pmaDefault: true,
	},
		// マブラヴ ガールズガーデンX (Muv-Luv Girls Garden X). Unity WebGL; spine
	// models live in the Addressables "spine_catalog" (BundleAssets/X/WebGL/
	// ASTC/<hash>.bundle). Extract via tools/muvluv/. Spine JSON 4.2.33.
	// マブラヴ ガールズガーデンX — CG / illust gallery. The game's CG art lives in
	// the Addressables "ui_catalog" (one bundle per image), NOT the spine
	// catalog: TMB (character CG), TCBX (explicit H CG), TFB (story CG), TMCB
	// (episode photos), TMGIB (mecha art) at 1920x1080, and ICV (character
	// portrait illust) at 360x640. Extracted as flat PNGs by
	// tools/muvluv/extract-muvluv-cg.py. Rendered by viewer.js's image stage
	// (format: "image"). Must precede "muvluv" (prefix match).
	{
		match: "muvluv-cg",
		key: "muvluv-cg",
		label: "マブラヴ ガールズガーデンX — CG",
	},
	{ match: "muvluv", key: "muvluv", label: "マブラヴ ガールズガーデンX" },
	// Sailor Girl (DMM, id 9970). YooAsset manifest + open Aliyun OSS bucket:
	// sailor-dev-dmm-sp.oss-ap-southeast-1.aliyuncs.com/sailorgirl_unity/android_ex/v7.0/
	// Bundles are fetched as "{md5}.bundle" (the bundle name itself 404s) and
	// hold plain TextAsset *.json/*.atlas + Texture2D. Spine 4.0.64, 73-324
	// bones, 107 models. Extractor: /opt/sailorgirl/extract.py.
	{
		match: "sailorgirl",
		key: "sailorgirl",
		label: "Sailor Girl (DMM)",
		spineRuntime: "4.0",
	},
	// Stellar Valkyries. Cocos Creator; spine assets are plain .skel/.atlas/.png
	// under assets/res/spine/<id>[/<scene>]/ in the APK (no decryption). Spine
	// binary 4.1.24. A few characters ship several CG scenes as subfolders
	// (family rule in attachFamilies). See tools/stellar/.
	{ match: "stellar", key: "stellar", label: "Stellar Valkyries" },
	// FREYA 夢姬 / Dream of Freya (developer LSJGAME, Bishōjo RPG ADV) — CDN
	// TERBUKA asset.peachhan.com (bucket m1productionasset) via tools/peachhan/.
	// Bundle = TextAsset *.skel/*.atlas + Texture2D; banyak karakter punya
	// varian CG (`<id>_CG1`, `_CG2`). CDN + alias game (梦娘\幻姬\梦姬\少女总裁\
	// Dream of Freya) ditemukan dari bongkaran '二游资源工具.exe' (tools/game-cdn-list.md).
	{ match: "peachhan", key: "peachhan", label: "FREYA 夢姬 (Dream of Freya)" },
	{ match: "girlwars-l2d", key: "girlwars-l2d", label: "Girl Wars — Live2D" },
	{ match: "girlwars", key: "girlwars", label: "Girl Wars" },
	{ match: "ivntight", key: "ivntight", label: "イヴンタイト (IV-N-Tight)" },
	{ match: "arkrecode-cg", key: "arkrecode-cg", label: "Ark Re:Code — Ilustrasi CG" },
	{ match: "arkrecode", key: "arkrecode", label: "Ark Re:Code" },
	// 蜜桃乌托邦 (Peach Utopia). Atlases carry no `pma:` line and the textures
	// are straight-alpha, BUT their fully-transparent texels still hold stale
	// near-white colour, which leaks as solid WHITE patches when drawn with
	// the plain straight-alpha blend. Default the game to "upload": Pixi
	// premultiplies each texel against its own alpha on upload, so an alpha-0
	// texel becomes black and stops contributing. See the PMA block in
	// viewer.js and the spine-viewer-pma skill.
	{
		match: "mitao-utopia",
		key: "mitao-utopia",
		label: "Mitao Utopia",
		pmaDefault: "upload",
	},
	// 决战僵尸舞娘 (Zombie Dancer). Cocos Creator 3.x (JS), Spine 3.8.99 —
	// unlike 蜜桃乌托邦 this one needs no decryption: the hot-update assets are
	// plain JSON/PNG. Atlases carry no `pma:` line and the textures are
	// RGBA8888 straight alpha, so Auto is left at the default.
	{
		match: "juezhan",
		key: "juezhan",
		label: "决战僵尸舞娘",
	},
	// 性界大战 (Xingjie Dazhan). Cocos Creator 2.x H5 build — assets served
	// directly over HTTP from h5.spj2web.com. The `sp.SkeletonData` JSON is
	// plain, but every raw texture arrives wrapped as
	//   "assets-encrypt-2022"+encriptSign + base64(PNG) + "=" + encriptKey
	// (see tools/xingjie/extract-xjdz.py). Atlases carry no `pma:` line and the
	// textures are RGBA8888 straight alpha, so PMA stays Auto.
	{
		match: "xingjie",
		key: "xingjie",
		label: "性界大战",
	},
	// Chaos Zero Nightmare — portraits / standees from the community model
	// library BenNoSleep/czn-animation-viewer. 1143 rigs, each a plain Spine
	// 3.8.79 JSON skeleton + .atlas + a .webp page (converted by tools/czn-rigs.py:
	// skeleton.json(gzip)-> <slug>.json, skeleton.atlas-> <slug>.atlas). The
	// repo's index.json names live in assets/czn-rigs/_names.json (slug -> name,
	// kind, subtype).
	//
	// This REPLACES the older game-side extraction (game key "chaoszero", the
	// Yuna .scsp/.sct pipeline in tools/chaoszero/) which has been removed from
	// the viewer — so Chaos Zero Nightmare now carries the plain game label.
	{
		match: "czn-rigs",
		key: "czn-rigs",
		label: "Chaos Zero Nightmare",
		spineRuntime: "3.8",
		pmaDefault: false,
	},
	// CZN cut-ins (FHD / collapse / UX) — 951 WebP stills from the same library.
	// A "-cg" folder, so it renders through the image-gallery path; thumbnails
	// live in public/thumbs/czn-cutins-cg.
	{
		match: "czn-cutins-cg",
		key: "czn-cutins-cg",
		label: "Chaos Zero Nightmare — Cut-ins",
	},
	// Make Drama (MAD) — standing / affection / desire / pleasure rigs from the
	// anyabot/MAD-Viewer community library. Each skin is a folder of loose files
	// (binary .skel + .atlas + PNG pages) fetched from the MAD-assets-1/2 GitHub
	// buckets and rewritten to assets/mad-drama/<unit>/ by tools/extract-mad-viewer.py.
	// Spine 4.2 (4.2.37) — the viewer has a dedicated 4.2 stack. Names come from
	// assets/mad-drama/_names.json (character name + kind).
	{
		match: "mad-drama",
		key: "mad-drama",
		label: "Make Drama",
		pmaDefault: false,
	},
	// Divine Throne: Idle RPG (com.luckystargame.jdxy.gp). Cocos Creator 2.x
	// again, but the spine data rides inside a Play Asset Delivery pack
	// (`split_install_time_asset_pack.apk`). Skeleton = the Cocos custom ".bin"
	// which is actually a plain Spine BINARY skeleton (3.8.99) — renamed to
	// .skel and the viewer auto-detects the runtime version. Atlas text is
	// inlined in the Cocos import JSON, and texture pages are custom-header
	// ASTC (tools/throne/).
	{
		match: "throne",
		key: "throne",
		label: "Divine Throne",
	},
	// 物华弥新 / Neo Artifacts (com.cipaishe.wuhua.google, v1.5.0). Unity 2018.4.
	// SmallPack*.apk bundles (assets/bundles/*.ab) are UnityFS but BLOCK-ENCRYPTED:
	//   key = data[51]; XOR data[50:end] ^= key   (per-file `end`; live2dhub #5896)
	// TextAsset .skel (Spine 3.8.95) + .atlas + Texture2D. The pack holds the
	// KV splash-art set + effects/UI/shaders/audio/lua; the collectible artifact
	// sprites are pulled from the CDN at runtime. See tools/wuhua/.
	{
		match: "wuhua",
		key: "wuhua",
		label: "物华弥新 (Neo Artifacts)",
	},
	// 钢岚 / Mecharashi (com.tentree.gp.mecharashi, v1.21.1). UnityFS + UnityCN.
	// Bundles at assets/ExportAssetBundle/*.b; UnityCN key (hex)
	// "31433743463543423144313841304630" (= bytes 1C7CF5CB1D18A0F0). Each pilot_*
	// bundle carries a complete Spine (3.8.76) .skel + .atlas + Texture2D.
	// See tools/mecharashi/.
	{
		match: "mecharashi",
		key: "mecharashi",
		label: "钢岚 (Mecharashi)",
	},
	// 白夜极光 / Alchemy Stars (com.tencent.baiyeint, v1.43.0). Assets live in FAT32
	// disk images (`fat32lib`) shipped as main.obb + patch.obb inside the XAPK:
	// mount both read-only, then read `*.bundle` (named `<md5>@<name>.bundle`).
	// Spine (3.8.94/3.8.99) is unencrypted — `*_spine_idle` / `*_spine_cg_idle`
	// bundles carry .skel + .atlas + Texture2D. See tools/alcherystars/.
	{
		match: "alcherystars",
		key: "alcherystars",
		label: "白夜极光 (Alchemy Stars)",
	},
	// 深蓝终末录 (Deep Blue). Unity 2021.3. APK (CloudFront signed URL) holds
	// assets/prefab/hero/herospines/hero_<id>/*.unity3d; each bundle is a plain
	// 深蓝终末录 — CG / illust gallery. The SAME APK also ships plain 2D art as
	// UnityFS bundles: Sprite + Texture2D, no skeleton. `assets/art/texture/
	// herobust/ill/` holds `cgs_<char>_<n>` (character CGs) + `main_avg_*`
	// (story CGs); `assets/art/texture/backgroud/` holds `cg_avg_*` (story/H
	// CGs) + `activity_avg_*` + battle/shop backgrounds. Extracted as flat PNGs
	// by tools/shenlan/extract-shenlan-cg.py. Rendered by viewer.js's still-image
	// path (format: "image"). Must precede "shenlan" (prefix match).
	{
		match: "shenlan-cg",
		key: "shenlan-cg",
		label: "深蓝终末录 (Deep Blue) — CG",
	},
	// UnityFS with a complete Spine (.skel + .atlas + 2048x2048 pages). All
	// atlases carry `pma: true`. See tools/shenlan/.
	{
		match: "shenlan",
		key: "shenlan",
		label: "深蓝终末录 (Deep Blue)",
		pmaDefault: true,
	},
	// 异世界后宫物语 (Isekai Harem Monogatari), com.luckystargame/18game build.
	// Cocos Creator 2.4 again. Assets under assets/assets/<bundle>/, encrypted:
	//   prefix "GenSanaSneG" + XOR (json/atlas) or XXTEA (png/jpg) with key
	//   "mygame!fuck@you~" (found in libcocos2djs.so strings). .bin skeletons
	//   are plain Spine binary and are NOT encrypted. See tools/ysjh/.
	{
		match: "ysjh",
		key: "ysjh",
		label: "异世界后宫物语",
	},
	// 梦琪领导 / President's Ambition - Project Beauty R (cgg4game Cocos 2.x).
	// Community download-script target from live2dhub topic 4603. Flow: query
	// city2ntk.cgg4game.com/webfyen/nutakupc.php -> 302 ?resVer=<hash> ->
	// h.cgg4game.com/.../resource/default.res.<resVer>.json (nested tree of
	// {<Name>.atlas, <Name>.json, <Name>} hashes) -> pull each file from the
	// cdnen.cgg4game.com CDN. Spine data is plain JSON (3.7.94), no encryption.
	// Atlases carry no `pma:` line; textures are straight alpha, so Auto stays.
	{
		match: "mengqi",
		key: "mengqi",
		label: "梦琪领导 (President's Ambition)",
	},
	// Everlusting Life (adult-chess.com / Nutaku). Assets come from a JSON
	// index (POST /ac/get_assets_with_als, state "ac-release-v<VER>") and each
	// entry is a plain UnityFS AssetBundle (Unity 2022.3.20f1) holding one
	// Spine model: TextAsset "<Name>.atlas" + TextAsset "<Name>" (plain JSON,
	// Spine 4.2.40) + Texture2D page. No decryption. See tools/everlusting/.
	{
		match: "everlusting",
		key: "everlusting",
		label: "Everlusting Life",
	},
	// 天啓パラドクスX / Tenkei Paradox X (KMS / EXNOA). Unity Addressables
	// build; bundles live under an Azure blob path whose `production<N>` prefix
	// (and a fixed uuid) changes with updates. Spines come as one plain
	// UnityFS bundle each: TextAsset "<id>.atlas" + TextAsset "<id>.skel"
	// (plain Spine BINARY 3.8.x, no decryption) + Texture2D page. Two sets:
	// `spines` (full) and `spineslight` (lighter LOD), 341 each. See
	// tools/tenkei/. Atlases carry no `pma:` line; textures straight alpha.
	{
		match: "tenkei",
		key: "tenkei",
		label: "天啓パラドクスX (Tenkei Paradox X)",
	},
	// Angelica Aster R (当归紫苑), DMM/FANZA. Unity Addressables; the catalog's
	// 43k bundle keys are plain `<md5>.bundle` hashes with OBFUSCATED group
	// names, so a spine bundle can only be found by downloading and scanning
	// its CONTENT. A spine bundle holds TextAsset "<name>.atlas" + TextAsset
	// "<name>.skel" (plain Spine BINARY 4.0.64) + Texture2D page. The Unity
	// version string is stripped from every bundle, so the extractor forces a
	// fallback version (2022.3.58f1). See tools/angelica/.
	{
		match: "angelica",
		key: "angelica",
		label: "Angelica Aster R (当归紫苑)",
	},
	// Same longest-prefix rule as Azur Lane: "alliancesages-cg" has to precede
	// "alliancesages" or every CG scene is swallowed by the character bucket.
	// pmaDefault: these atlases carry no `pma:` line but their textures ARE
	// premultiplied, so "Auto" has to assume PMA instead of falling back to
	// straight alpha (which shows as dark fringes around every sprite).
	// Model baru (22) di-refresh dari CDN hot-update TERBUKA euwv.0577ai.com
	// (dari bongkaran 二游资源工具.exe; alias di tool: 贤者同盟). Updater:
	// tools/update-alliancesages.py. (Alias "魔竞革命" di tool = game LAIN.)
	{
		match: "alliancesages-cg",
		key: "alliancesages-cg",
		label: "Alliance Sages — CG",
		pmaDefault: true,
	},
	{
		match: "alliancesages",
		key: "alliancesages",
		label: "Alliance Sages",
		pmaDefault: true,
	},
	// Brown Dust 2. Re-laid-out 2026-09-02 into one root (assets/bd2 -> a
	// symlink farm under /srv/spine-assets/bd2) mirroring
	// Jelosus2/BD2-L2D-Viewer: char/<costume>/ with cutscene/ and censored/
	// nested inside, so the character and its variants form a family.
	// Built by tools/relayout-bd2.py — rerun it after adding assets.
	{ match: "bd2", key: "bd2", label: "Brown Dust 2" },
	// Depose Girls (放置少女). Its atlases carry no `pma:` line. Sampling the
	// bundles showed spine-unity's `pmaVertexColors: true` (40/40, zero
	// false), i.e. the textures ARE premultiplied — but the user has the
	// default turned OFF, so "Auto" treats them as straight alpha. Use the
	// per-model PMA override in the viewer to switch a model back on.
	{
		match: "deposegirls",
		key: "deposegirls",
		label: "Depose Girls",
		pmaDefault: false,
	},
	// Shoujou Kaisen (少女廻戦). Spine 3.8.97, so pixi-spine reads these
	// directly — no conversion and no legacy viewer (unlike Project QT).
	// Extraction notes: tools/shoujoukaisen/README.md (junk header prefix,
	// textures sometimes in a separate `_texture.asset` bundle).
	{
		match: "shoujoukaisen",
		key: "shoujoukaisen",
		label: "Shoujou Kaisen",
		spineRuntime: null,
		pmaDefault: false,
	},
	// Project QT. Ships Spine 2.1.27 skeletons.
	//
	// These CANNOT be rendered by pixi-spine: its weighted-mesh path
	// desynchronises on the 5-11 bones-per-vertex these models use, throwing
	// vertices thousands of units away. Converting the data to 3.8 was proven
	// byte-faithful (triangles, UVs and weighted vertices all identical) yet
	// still scrambles, so the data was never the problem — the 3.8 runtime is.
	//
	// The original .skel renders correctly in a native 2.1.27 viewer (verified
	// on many models), so this game keeps its ORIGINAL files and the client
	// routes it to vendor/spine2127 instead of pixi-spine.
	//
	// Re-tested 2026-09-01: the 3.8 conversion was loaded through pixi-spine
	// again and STILL scramble as of this check, even though its numbers look
	// healthy (no exploded vertices, spans within bounds). Do not "optimise"
	// this back to pixi-spine on numeric evidence alone.
	{
		match: "epic7-wallpaper",
		key: "epic7-wallpaper",
		label: "Epic Seven — Wallpaper",
		pmaDefault: false,
		// Disembunyikan dari daftar Pustaka: isinya sudah menempel sebagai
		// varian di kartu Epic Seven. Modelnya TETAP dikirim ke klien,
		// karena switchVariant() mencari model berdasarkan id — kalau
		// dihapus dari daftar, variannya tidak bisa dibuka.
		hiddenGame: true,
	},
	{
		match: "epic7-skill",
		key: "epic7-skill",
		label: "Epic Seven — Skill",
		pmaDefault: false,
		hiddenGame: true,
	},
	// Epic Seven — rig COMBAT (animasi skill), sumber assets.e7codex.com.
	//
	// Berkas terpisah dari rig lobby: host-nya assets.e7codex.com dan
	// path-nya <id>/combat/<id>.{json,atlas,png} (bukan e7codex.com/assets/…,
	// yang memberi 404). Isinya ~20 animasi per karakter (idle, run, skill1,
	// skill2, skill3, attacked, down, …) versus hanya "idle" di rig lobby.
	// Hanya 463 dari 848 model yang punya rig ini (flag has_combat).
	// Entri "epic7-combat" harus mendahului "epic7" karena resolveGame
	// memakai startsWith.
	{
		match: "epic7-combat",
		key: "epic7-combat",
		label: "Epic Seven — Combat",
		pmaDefault: false,
		// Lihat catatan epic7-wallpaper: disembunyikan dari Pustaka, tetap
		// dikirim agar varian Combat bisa dibuka dari kartu Epic Seven.
		hiddenGame: true,
	},
	// Epic Seven — sumber: e7codex.com (tools/download-e7codex.py).
	//
	// Model campuran: Spine 2.1.27 (217), 3.8.95 (30), dan 3.8.99 (601),
	// jadi spineRuntime TIDAK dipatok — versi dideteksi per model dari
	// isi skeleton. Sebelumnya folder epic7-v3 (SCSP v3) memakai entri
	// terpisah dengan match lebih panjang; sumber baru ini memakai satu
	// pohon assets/epic7/ sehingga entri epic7-v3 dihapus.
	{
		match: "epic7",
		key: "epic7",
		label: "Epic Seven",
		pmaDefault: false,
	},
	// Cherry Tale (88kongque).
	//
	// Daftar bundle-nya (bundleMap.txt) berbentuk "assetID|bundleName",
	// bukan katalog Addressables. Diunduh oleh tools/extract-cherrytale.py.
	//
	// 212 model, hampir semuanya skeleton BINER .skel versi 4.0.55 (143) dan
	// 4.0.64 (68). Runtime 4.0/4.1 membaca keduanya, jadi tidak perlu
	// konversi apa pun.
	//
	// Tidak perlu dekripsi untuk bundle dari CDN ini — magic UnityFS ada di
	// offset 0 dan versinya sudah benar. (Script CherryTaleDecrypt.py yang
	// beredar menukar tiga byte dan mengganti string versi 2018.3.5f1; itu
	// diperlukan untuk berkas yang diambil dari perangkat, bukan dari sini.)
	//
	// Deteksi versi per berkas sudah cukup — jangan paksa spineRuntime.
	{
		match: "cherrytale",
		key: "cherrytale",
		label: "Cherry Tale",
		pmaDefault: false,
	},
	// Star Lust (Erolabs / pinkcore).
	//
	// Katalog Addressables-nya berbentuk JSON (bukan biner seperti Megaha:Re),
	// dan bundle-nya TIDAK dienkripsi — magic UnityFS langsung di offset 0.
	// Diunduh oleh tools/extract-starlust.py.
	//
	// 178 model, semuanya Spine 4.0.64: 87 skeleton ber-JSON, 91 berbentuk
	// .skel biner. Keduanya bisa dibaca runtime 4.0/4.1 yang sudah ada, jadi
	// tidak perlu konversi maupun jalur 2.1.
	//
	// Terbagi dua: characterspine (karakter) dan cgcharacterspine (CG).
	// Deteksi versi per berkas sudah cukup — jangan paksa spineRuntime.
	{
		match: "starlust",
		key: "starlust",
		label: "Star Lust",
		pmaDefault: false,
	},
	// Project QT.
	//
	// Model diambil utuh dari gdrive (folder id 1HmKSMyHrXmkIvQqwevDmtjVM8n3FR0Kz;
	// 1863 folder, 5627 berkas: <nama>.json + .atlas + .png). Sebagian besar
	// sudah dikonversi ke 3.8.99 (1795 model) sehingga dimuat langsung oleh
	// pixi-spine — tanpa iframe legacy.
	//
	// Sisa 68 folder masih berisi JSON 2.1.27 (karena Drive menyertakan .json
	// 2.1 + .skel): 38 punya sibling .json dan dirender jalur kanvas 2.1
	// (viewer memakai .json sibling itu — lihat loadLegacyModel), 29 hanya
	// berisi .skel biner dan belum dikonversi (tampil error yang memandu, bukan
	// crash). Deteksi versi per berkas: 2.x -> kanvas 2.1, sisanya -> pixi-spine.
	// Karena itu entri ini TIDAK memaksa spineRuntime — biarkan deteksi bekerja.
	{
		match: "projectqt",
		key: "projectqt",
		label: "Project QT",
		pmaDefault: false,
	},
	// Cat Shinobi (ねこ親方 / com.cookapps.catshinobi). Unity Addressables
	// build; 526 skeletons all at Spine 4.1.24, so pixi-spine reads them
	// directly — no conversion, no legacy runtime (unlike Project QT).
	//
	// Extracted from split_UnityDataAssetPack.apk by
	// tools/extract-catshinobi.py (run it with /srv/venv-spine). Skeletons
	// live in one 461 MB Addressables bundle and name themselves
	// Char_* / Char_SD_* (chibi) / Char_LD_* / cat_battle_mode_* /
	// monster_LD_*. Atlases carry no `pma:` line and the bundle's
	// pmaVertexColors flag is mixed (711 false / 218 true) with no per-model
	// reference to resolve it, so the default is a visual call. User picked
	// straight alpha: "Auto" now resolves to OFF. Flip pmaDefault below to
	// switch the whole game — it is the single source of truth.
	{
		match: "catshinobi",
		key: "catshinobi",
		label: "Cat Shinobi",
		spineRuntime: null,
		pmaDefault: false,
	},
	// Poker Fate (com.pokerfate.play). Unity Addressables, 139 character
	// skeletons at Spine 4.1.24 (137) / 4.1.23 (2) — pixi-spine reads them
	// directly, no legacy runtime.
	//
	// Extracted by tools/extract-unity-spine.py from the rolespine bundles
	// (assets/aa/Android/gameresrolespine_assets_rolespine/*.bundle), which
	// are named <charId>_<variant>_<md5>.bundle.
	//
	// pmaDefault: true — UNLIKE Cat Shinobi this needs no judgement call:
	// all 139/139 atlases carry an explicit `pma: true` line, so the viewer
	// would resolve it from the atlas anyway. Set here for clarity.
	{
		match: "pokerfate",
		key: "pokerfate",
		label: "Poker Fate",
		spineRuntime: null,
		pmaDefault: true,
	},
	// Echocalypse (com.yoozoo.jgame.us, published by YOOZOO). NOT a Unity
	// bundle game: Spine models ship as plain files, one folder per model
	// (.skel + .atlas + .png), so extraction is a plain unzip.
	//
	// SOURCES — the APK is only the base layer. Most characters come from the
	// downloaded/hot-updated data, applied in this order (later wins):
	//     base.apk                       assets/res/common/knight_spine
	//     files/obb/res/common/knight_spine
	//     files/upgrade/res/common/knight_spine
	// See tools/merge-echocalypse-knight.py. The APK alone yielded 13 knight
	// models; merging all three gives 318 folders / 605 skeletons.
	//
	// Only knight_spine is wired up (characters = what people want). The other
	// families (effect/pet/back/unite_token/secretary/buff) are merged by
	// tools/merge-echocalypse.py into /srv/spine-assets/echocalypse-merged
	// if wanted later; the no-longer-wired all-family tree is kept at
	// /srv/spine-assets/echocalypse-all-old.
	//
	// TEXTURES ARE ENCRYPTED with the game's "UF" format:
	//     UF header -> XOR (33-byte table) -> CCZ! -> zlib -> PVR/ETC2A8 -> PNG
	// Decrypted with tools/decryptUF.py (needs `pip install texture2ddecoder`).
	// The decryptor un-premultiplies to straight alpha on export.
	//
	// Spine 3.8.99 / 3.8.86: pixi-spine reads these directly.
	// pmaDefault: false — the exported PNGs are straight alpha.
	{
		match: "echocalypse",
		key: "echocalypse",
		label: "Echocalypse",
		spineRuntime: null,
		pmaDefault: false,
	},
	// Haze Reverb (com.tingzhou.cwcxtw.qooapp). Unity + IL2CPP + YooAsset.
	//
	// The APK is only a shell (954 files); all art is downloaded to
	// /sdcard/Android/data/<pkg>/files/yoo/ResPackage/CacheFiles/<2hex>/<hash>/
	// as `__data` (UnityFS) + `__info` — 12 GB across 4,004 bundles.
	//
	// Extracted by tools/extract-hazereverb.py, after
	//   tools/hazereverb-find.sh  (grep binary `.skel` -> 300/4,004 bundles)
	//   tools/hazereverb-pull.sh  (pull those to /srv/spine-assets/hazereverb-raw)
	//
	// DIFFERENCES FROM TENKAFUMA — do not copy that script's assumptions:
	//   - Bundles are clean UnityFS. No stray byte before the magic, so the
	//     extractor tries skip=0 first (skip=1 is only a fallback).
	//   - No separate `_alpha` textures. Verified with
	//     tools/hazereverb-probe.py: each page already carries its own alpha
	//     (e.g. lihui_aertaiya_dz is 54.9% fully transparent), so NO mask
	//     compositing is needed here.
	//
	// Asset naming:
	//   dongzuo_juese_<name>.skel  characters (动作角色)
	//   lihui_<name>_dz.skel       illustrations / CG (立绘)
	// One bundle can hold several skeletons, so skeletons are paired to
	// atlases by exact stem — a prefix match would swap
	// `dongzuo_juese_aertaiya` with `dongzuo_juese_aertaiya_a` and scramble
	// every region (the same trap TenkaFuma hit).
	//
	// Spine 3.8.99 — pixi-spine reads these directly.
	// pmaDefault: false — atlases carry no `pma:` line and the PNGs are
	// straight alpha.
	{
		match: "hazereverb",
		key: "hazereverb",
		label: "Haze Reverb",
		spineRuntime: null,
		pmaDefault: false,
	},
	// TenkaFuma (com.pinkcore.tkfm.erolabs). Unity IL2CPP + Addressables, but
	// the APK carries almost nothing: the real art is 7.3 GB of bundles under
	// /sdcard/Android/data/<pkg>/files/data/ (1,794 bundles). Only cb*/cg*/
	// cf*/scg*/ln* hold skeletons; sound* (788) is audio.
	//
	// Extracted by tools/extract-tenkafuma.py.
	//
	// GOTCHA: every bundle here starts with ONE stray byte before the real
	// "UnityFS" magic, and UnityPy then returns ZERO objects WITHOUT raising.
	// Load with that byte stripped (the script tries skip=1 then skip=0 and
	// sanity-checks the object count).
	//
	// pmaDefault: false — the atlases carry no `pma:` line, and this is a
	// visual call.
	//
	// It was `true` for a while, but that was compensating for a BUG, not a
	// blending preference: the extractor used to export only the colour
	// texture and drop its `_alpha` twin, so every page had no alpha at all
	// and PMA-on was the least-bad way to hide the garbage.
	//
	// extract-tenkafuma.py now composites <page> + <page>_alpha into a real
	// RGBA PNG, so the textures carry genuine straight alpha and PMA is no
	// longer needed. User's call: PMA off.
	{ match: "tenkafuma", key: "tenkafuma", label: "TenkaFuma", spineRuntime: null, pmaDefault: false },

	// Dragon Travelers / 龙魂旅人 (com.gametree.lhlr.gp, GameTree).
	// Pulled from the device at:
	//   /sdcard/Android/data/com.gametree.lhlr.gp/files/res_update/model/*.b
	//
	// GOTCHA (cost me a while): these bundles carry a NESTED fake header —
	// the string "UnityFS" appears TWO or THREE times, and the real one is
	// the LAST occurrence. Stripping only up to the second signature leaves
	// a bogus header behind and UnityPy fails with the misleading
	// "Position cannot be negative", which looks like encryption but is not.
	// Use raw.rfind(b"UnityFS"), not find(..., 1).
	//
	// There is NO UnityCN encryption here — once the fake header is stripped
	// correctly, all 53 bundles parse. (UnityPy's brute_force_key returns
	// None for this game; the "assetbundle_decrypt_key" hints are red flags
	// from the truncated header, not real encryption.)
	//
	// Skeleton (.skel/.atlas, as TextAsset) and page (.png, as Texture2D)
	// live in SEPARATE bundles, so extraction must join them by name.
	// Spine 4.1.23. Extracted by /root/dt/extract_lhlr.py.
	{
		match: "dragontravelers",
		key: "dragontravelers",
		label: "Dragon Travelers",
		spineRuntime: "4.1",
		pmaDefault: false,
	},

	// Stellar Affinity (com.himefun.stellaraffinity.erolabs, Erolabs).
	// Unity Addressables pulled live from the device's own data dir:
	//   /sdcard/Android/data/<pkg>/files/Android/Data/data/*_skeletondata.ab
	// 97 skeleton bundles (~158 MB), extracted by tools/extract-stellar-affinity.py
	// into assets/stellaraffinity/<model>/{<model>.skel,.atlas,N pages}.
	//
	// Spine 4.2.35 — NEWER than any @pixi-spine runtime ships (they stop at
	// 4.1). Loaded through @esotericsoftware/spine-pixi-v7 instead; see
	// SPINE_42_RUNTIME in spine-version.js.
	//
	// pmaDefault: true — every one of the 97 atlases declares `pma:true`.
	//
	// Multi-page is the norm, not the exception: c00001_01 declares 5 pages
	// (2048²x2 + 1024²x3). Save every declared page.
	//
	// 20 models (a01*, some a05*) ship half-resolution pages — the atlas
	// declares 512² while the texture is 256². That is a clean 2x integer
	// ratio, so the viewer's upscale path handles it. Do NOT "fix" it by
	// stretching.

	// OrisRies / 萬源聖魔錄 (com.erolabs.orisries).
	// Unity + Addressables. The APK's own assets/aa/Android bundles are plain
	// UnityFS, but the ~2.8 GB of hot-update bundles under
	//   /sdcard/Android/data/<pkg>/files/data/
	// are AES-encrypted: key b"wiki is transfer", CBC, with the 16-byte IV
	// appended and its length as a trailing LE u32. Decrypted by
	// tools/decrypt-orisries.py (scheme from live2dhub.com/t/topic/3323).
	// Spine models live in `spinechar_*` bundles as TextAsset .skel/.atlas
	// plus Texture2D pages; extracted by tools/extract-unity-spine.py.
	// NOTE: 20/230 models ship textures padded to power-of-two (atlas declares
	// 2048x1828, PNG is 2048x2048). The viewer reads the atlas, so pages
	// resolve correctly despite the padding.
	//
	// pmaDefault: false. Only 13/301 atlases spell out `pma:true`; the other
	// ~288 carry no pma: line at all, so the flag alone can't decide it — and
	// the majority therefore get the non-premultiplied default. The viewer
	// still reads an explicit `pma:true` in an atlas, and the per-model PMA
	// toggle in the UI overrides this for the 13 that declare it.
	{
		match: "orisries",
		key: "orisries",
		label: "OrisRies",
		pmaDefault: false,
	},
	{
		match: "stellaraffinity",
		key: "stellaraffinity",
		label: "Stellar Affinity",
		spineRuntime: "4.2",
		pmaDefault: true,
	},
	// DotAbyss (jp.co.fanzagames.dotabyss_x_a). Unity IL2CPP + Addressables,
	// but the bundles are NOT under files/aa/ like most Addressables titles —
	// they are UnityWebRequest cache entries:
	//   /sdcard/Android/data/<pkg>/files/UnityCache/Shared/<hash>/<hash>/__data
	// 668 of those (~187 MB). Filenames carry no extension, so find them by
	// their UnityFS magic.
	//
	// Extracted with the upstream tool at
	//   github.com/tengwan7/DataTable -> DotAbyss/{UnityCatalogReader,ExtractSpine}.py
	// UnityCatalogReader turns the binary catalog into assets.json (71k keys),
	// which ExtractSpine uses to name output folders.
	//
	// Spine 4.1.23 — the LAST format @pixi-spine supports, so no extra runtime
	// is needed here (unlike Stellar Affinity's 4.2).
	//
	// pmaDefault: true — all 66 atlases declare `pma:true`.
	//
	// Quirk: some skeletons keep their .skel in a different bundle from their
	// .atlas, so a single pass leaves folders half-empty. 11 models still have
	// no texture at all (the game never downloaded those units), and are
	// skipped rather than imported broken.
	{
		match: "dotabyss",
		key: "dotabyss",
		label: "DotAbyss",
		spineRuntime: "4.1",
		pmaDefault: true,
	},
	// DotAbyss Live2D Cubism models, extracted from the game's Addressables
	// bundles (see /root/dotabyss/LIVE2D-FINDINGS.md). Cubism 4 models are
	// rendered by pixi-live2d-display, not pixi-spine, so `format: "live2d"`
	// is set by the scanner and the viewer routes them separately.
	{
		match: "dotabyss-l2d",
		key: "dotabyss-l2d",
		label: "DotAbyss Live2D",
	},
	// Bundled sample models. They live directly under assets/ and are not from
	// any game — grouping them keeps "Lainnya" from meaning "demo".
	{ match: "spineboy", key: "demo", label: "Demo" },
	{ match: "raptor", key: "demo", label: "Demo" },
	{ match: "coin", key: "demo", label: "Demo" },
];

function resolveGame(rootRel, id) {
	const top = (rootRel || id.split("/")[0] || "").toLowerCase();
	// Longest match wins. "dotabyss-l2d" would otherwise fall into "dotabyss",
	// and "alliancesages-cg" into "alliancesages", because both are prefixes
	// of the more specific root.
	let best = null;
	for (const g of GAME_ROOTS) {
		if (!top.startsWith(g.match)) continue;
		if (!best || g.match.length > best.match.length) best = g;
	}
	if (best) {
		return {
			game: best.key,
			gameLabel: best.label,
			// pmaDefault is a full mode ("auto"|"on"|"off"|"upload"), but older
			// entries only set a boolean. Normalise booleans → "on", and let
			// "on"/"off"/"upload" strings through unchanged.
			pmaDefault:
				typeof best.pmaDefault === "string"
					? best.pmaDefault
					: !!best.pmaDefault,
			spineRuntime: best.spineRuntime || null,
			hiddenGame: !!best.hiddenGame,
		};
	}
	// Unrecognised roots (uploads, demo models) get a tidy label of their own.
	const raw = rootRel || id.split("/")[0] || "";
	return {
		game: raw.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "lainnya",
		gameLabel: raw.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) || "Lainnya",
	};
}

/**
 * Groups a model with its sibling variants. Nikke ships each character as a
 * folder that is itself a model AND holds variants underneath it:
 *
 *   nikke/c010          <- the model
 *   nikke/c010/aim      <- variant
 *   nikke/c010/cover    <- variant
 *
 * A family is a root id plus every id nested directly beneath it. Returns
 * `{ root, label, members }` where `label` is "Utama" for the root itself and
 * the folder name ("Aim", "Cover") for each variant — 0 label collisions in
 * the current asset set, so labels are safe to use as option text.
 */
function attachFamilies(models) {
	const ids = new Set(models.map((m) => m.id));

	// Longest id that is a prefix of `id` — that's the variant's parent.
	//
	// NOTE ON COSTUME-LESS BD2 VARIANTS: the relayout writes a character's
	// Light Novel Talk as `<Char>/Light-Novel-Talk` when the reference repo
	// has no costume for it. `<Char>` holds no .skel of its own, so it can
	// never be a family root here — those models stay standalone. That is
	// fine: they already sit in the character's `subgroup` in the sidebar.
	const rootOf = (id) => {
		const parts = id.split("/");
		for (let i = parts.length - 1; i > 0; i--) {
			const p = parts.slice(0, i).join("/");
			if (ids.has(p)) return p;
		}
		return id;
	};

	const groups = new Map();
	for (const m of models) groups.set(rootOf(m.id), []);
	for (const m of models) groups.get(rootOf(m.id)).push(m.id);

	const title = (s) => s.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	// The BD2 relayout nests cutscene/ and censored/ inside the character
	// folder, so variant labels are English words — render them in Indonesian
	// to match the rest of the UI.
	const VARIANT_LABELS = { cutscene: "Cutscene", censored: "Tersensor" };

	// Echocalypse groups variants inside ONE folder rather than in nested
	// subfolders: folder 200000 holds 200000.skel (main) and 200000_bg.skel
	// (the character's background plate). The generic rootOf() below looks
	// for a parent FOLDER id, so it would find none and every variant would
	// render as a separate top-level model. Group these by folder first.
	//
	// Root = the skeleton whose stem equals the folder name; everything else
	// is a variant named by its suffix (_bg -> "Background").
	const ecGroups = new Map();
	for (const m of models) {
		if ((m.game || "") !== "echocalypse") continue;
		const seg = m.id.split("#");
		const folder = (seg[0].split("/")[1] || "").toLowerCase();
		const stem = (seg[1] || "").toLowerCase();
		if (!folder) continue;
		if (!ecGroups.has(folder)) ecGroups.set(folder, []);
		ecGroups.get(folder).push({ id: m.id, stem, isRoot: stem === folder });
	}
	const EC_LABELS = { bg: "Background" };
	for (const [, members] of ecGroups) {
		if (members.length < 2) continue;
		const root =
			(members.find((x) => x.isRoot) || members[0]).id;
		const labelFor = (x) => {
			if (x.id === root) return "Utama";
			const rootStem = root.split("#")[1] || "";
			const suffix = x.stem.startsWith(rootStem)
				? x.stem.slice(rootStem.length).replace(/^[-_]+/, "")
				: x.stem;
			return EC_LABELS[suffix] || title(suffix) || title(x.stem);
		};
		for (const x of members) {
			const m = models.find((mm) => mm.id === x.id);
			if (!m) continue;
			m.family = {
				root,
				label: labelFor(x),
				members: members
					.map((y) => ({ id: y.id, label: labelFor(y) }))
					.sort((a, b) =>
						a.label === "Utama" ? -1 : b.label === "Utama" ? 1 : a.label.localeCompare(b.label)
					),
			};
		}
	}


	// Stellar Valkyries (stellar): a handful of characters ship their CG scenes
	// as SUBFOLDERS rather than files directly in the model folder, e.g.
	//   stellar/10501/cg2_spine1 … cg2_spine4
	// The container folder (10501) is NOT itself a model, so rootOf() finds no
	// parent and each CG would surface as a separate top-level card. Group
	// them: container = one family, first scene (sorted) = "Utama".
	const svGroups = new Map();
	for (const m of models) {
		if ((m.game || "") !== "stellar") continue;
		const parts = m.id.split("/");
		if (parts.length < 3) continue; // stellar/<container>/<scene>
		const container = parts.slice(0, -1).join("/");
		if (ids.has(container)) continue; // container is itself a model
		if (!svGroups.has(container)) svGroups.set(container, []);
		svGroups.get(container).push(m.id);
	}
	for (const [, membersRaw] of svGroups) {
		const members = [...membersRaw].sort();
		if (members.length < 2) continue;
		const root = members[0];
		const labelFor = (id) => {
			if (id === root) return "Utama";
			const seg = id.split("/").pop() || id;
			return title(seg);
		};
		for (const id of members) {
			const m = models.find((mm) => mm.id === id);
			if (!m) continue;
			m.family = {
				root,
				label: labelFor(id),
				members: members.map((y) => ({ id: y, label: labelFor(y) })),
			};
		}
	}

	for (const m of models) {
		// Already grouped by the Echocalypse / Stellar rules above — the generic
		// folder-prefix rule would overwrite it with null.
		if (m.family) continue;
		const root = rootOf(m.id);
		const members = groups.get(root) || [m.id];
		if (members.length < 2) {
			m.family = null;
			continue;
		}
		// "Utama" for the root; a known variant folder gets its translated
		// name, anything else is title-cased as before.
		const labelFor = (id) => {
			if (id === root) return "Utama";
			// A folder holding several models carries a "#<stem>" suffix
			// (Skill-Cutscene#cutscene_char004091). The stem distinguishes
			// siblings in the library but reads as noise in the dropdown, so
			// show only what sets them apart: the "_1" / "_c" tail of the
			// stem. Twins then read "Skill Cutscene" and "Skill Cutscene C".
			const seg = id.slice(root.length + 1).split("#")[0];
			const stem = id.split("#")[1] || "";
			// Only a SHORT tail is a variant marker ("_1", "_c"); a long one
			// is part of the asset id itself (cutscene_char004091), and
			// printing it produced "Skill Cutscene CHAR004091".
			const tail = stem.match(/_([a-z0-9]{1,2})$/i);
			if (tail) {
				// A "_c" tail is the CENSORED twin of the same cutscene, not a
				// numbered sequel — label it as such instead of "… C".
				if (tail[1].toLowerCase() === "c") {
					return VARIANT_LABELS.censored;
				}
				// "_1" is a second take of the same cutscene.
				if (/^\d+$/.test(tail[1])) {
					return `${title(seg)} ${Number(tail[1]) + 1}`;
				}
			}
			const label = tail ? `${seg} ${tail[1].toUpperCase()}` : seg;
			return VARIANT_LABELS[label.toLowerCase()] || title(label);
		};

		m.family = {
			root,
			label: labelFor(m.id),
			members: members
				.map((id) => ({ id, label: labelFor(id) }))
				// "Utama" first, then the rest alphabetically — stable ordering
				// means the dropdown doesn't reshuffle between variants.
				.sort((a, b) => (a.label === "Utama" ? -1 : b.label === "Utama" ? 1 : a.label.localeCompare(b.label))),
		};
	}
	return models;
}

/**
 * Pair each skeleton with the atlas it belongs to.
 *
 * A folder can hold several models (Azur Lane ships bailongB / bailongM /
 * bailongT, each with its own skeleton + atlas). Exact stem matches win;
 * anything left over falls back to the remaining atlases so a lone skeleton
 * still gets paired rather than dropped.
 */
function pairSkeletonAtlas(skels, atlases) {
	const stem = (f) => f.replace(/\.(skel|json|atlas)$/i, "");
	const isBinary = (f) => /\.skel$/i.test(f);
	// A folder can ship the same skeleton twice: a binary .skel and a
	// text .json export of it (BD2's char066402 does exactly this). Both
	// parse fine, so the folder turned into two models with identical ids —
	// one of them with no animations at all, which is what the sidebar
	// showed. Prefer the binary when both describe the same stem: it is
	// the authoritative export and carries the full animation list.
	const skelList = skels.filter((s) => {
		if (isBinary(s)) return true;         // keep every .skel
		// Drop a .json only when a .skel with the same stem exists.
		return !skels.some((o) => o !== s && isBinary(o) && stem(o) === stem(s));
	});

	const pool = atlases.slice();
	const out = [];

	for (const sk of skelList) {
		const key = stem(sk);
		let i = pool.findIndex((a) => stem(a) === key);
		if (i === -1) i = 0; // fallback: take whatever is left
		// More skeletons than atlases: pair the remainder with the first atlas
		// rather than emitting an undefined path (crashed path.join).
		if (pool.length === 0) {
			if (!atlases.length) break;
			out.push({ skel: sk, atlas: atlases[0] });
			continue;
		}
		out.push({ skel: sk, atlas: pool[i] });
		pool.splice(i, 1);
	}
	return out;
}

/**
 * Lost Sword variants: one character = one card, with everything about that
 * character in the dropdown.
 *
 * The game scatters a single character across THREE places:
 *   - unit/<base>            the battle / sprite model (plus monster/effect
 *                            siblings inside the same folder: `<folder>#<stem>`)
 *   - lobbyunit/<base>[_x]    the lobby painting and its costume/daily variants,
 *                            often split across folders (`bedivere`, `_bunny`,
 *                            `_jin`, `_jin_bunny`)
 *   - pet/<base>_01           the pet
 * and its cutscenes live under a DIFFERENT root entirely
 * (`lostsword-video/...`, extracted from VideoClip objects, named
 * `Pc_<Char>_NN[_Special|_Memorial]`).
 *
 * Left alone a character with four costumes and three movies showed up as a
 * dozen unrelated tiles. This merges them all — skeleton models AND videos —
 * into one family whose root is the plain unit model, so the stage's "Varian"
 * dropdown lists them together.
 *
 * Only characters that HAVE a unit model are merged, so monsters with a shared
 * word but no plain folder (`goblin_archer`, `fishman_*`) and lobby-only NPCs
 * stay standalone.
 */
function attachLostSwordFamilies(models, videos) {
	const ls = models.filter((m) => (m.game || "") === "lostsword");
	if (!ls.length) return models;

	const TAG = /^(lobby_|pc_|npc_|bg_|ps_|pet_)/i;
	const stripTag = (name) => name.replace(TAG, "");
	const baseOf = (name) => stripTag(name).split("_")[0].toLowerCase();
	const title = (s) => s.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	const folderOf = (id) => id.split("#")[0];
	const partsOf = (id) => folderOf(id).split("/"); // [game, group, folderName]

	// "<group>|<base>" -> { group, base, models: [] }
	const buckets = new Map();
	for (const m of ls) {
		const [, group, fname] = partsOf(m.id);
		const base = baseOf(fname);
		const key = `${group}|${base}`;
		if (!buckets.has(key)) buckets.set(key, { group, base, models: [] });
		buckets.get(key).models.push(m);
	}

	// Videos indexed by character base (Summon_*/Prologue have none → skip).
	const vidsByBase = new Map();
	for (const v of videos || []) {
		const name = v.id.split("/").pop();
		if (/^Summon_/i.test(name)) continue;
		const mm = name.match(/^(?:Pc|Eb)_([A-Za-z0-9]+)/);
		if (!mm) continue;
		const base = mm[1].toLowerCase();
		if (!vidsByBase.has(base)) vidsByBase.set(base, []);
		vidsByBase.get(base).push(v);
	}

	// Build one family from a flat list of models. `base` strips the character
	// prefix off labels; `rootModel` leads the dropdown as "Utama".
	const makeFamily = (all, base, rootModel, prop = false) => {
		if (all.length < 2) return;
		const labelFor = (m) => {
			if (m.id === rootModel.id) return "Utama";
			const [, group, fname] = partsOf(m.id);
			const stem = m.id.split("#")[1] || "";
			if (m.game === "lostsword-video") {
				// `<Quality> › <Category…>`; keep the category + the clip's own
				// suffix so several movies of one character stay distinct.
				const [quality, ...rest] = m.subgroup.split(" › ");
				let sfx = m.id.split("/").pop().replace(/^(?:Pc|Eb)_/i, "");
				if (sfx.toLowerCase().startsWith(base)) sfx = sfx.slice(base.length);
				sfx = sfx.replace(/[-_]+/g, " ").trim();
				const lbl = [rest.join(" "), title(sfx)].filter(Boolean).join(" ").trim();
				return (lbl || "Video") + (quality === "Low" ? " (Low)" : "");
			}
			// A prop part is named by its own skeleton stem (Carriage B 01,
			// Abyss Fog B, Kraken Front), which stays unique across halves.
			if (prop && stem) return title(stem);
			const tag = fname.match(TAG);
			const tagWord = tag ? tag[0].replace(/_$/, "") : "";
			const ps = /^ps_/i.test(fname);
			const eff = stripTag(fname).toLowerCase(); // base + qualifier
			let s = eff.startsWith(base) ? eff.slice(base.length) : eff;
			// A sibling skeleton inside a shared folder (`<folder>#<stem>`) is
			// distinguished by its stem, not the folder.
			if (stem && eff === base) {
				const se = stripTag(stem).toLowerCase();
				s = se.startsWith(base) ? se.slice(base.length) : se;
			}
			s = s.replace(/^[-_]+/, "");
			if (!s) s = tagWord || stem || fname;
			const label = title(s) || "Varian";
			let prefix = "";
			if (ps) prefix = "PS ";
			else if (group === "pet") prefix = "Pet ";
			else if (tagWord && s.toLowerCase() !== tagWord.toLowerCase()) prefix = title(tagWord) + " ";
			return prefix + label;
		};

		// Disambiguate repeated labels: a folder holds the same pose from two
		// angles (`#Lobby_Kei_Awakening_B` / `_F`) which would both read
		// "Lobby Awakening"; append the discriminating tail (B, F…).
		const counts = new Map();
		for (const x of all) counts.set(labelFor(x), (counts.get(labelFor(x)) || 0) + 1);
		const finalLabel = (m) => {
			let label = labelFor(m);
			if (counts.get(label) > 1) {
				const leaf = m.id.split("#")[1] || m.id.split("/").pop();
				const tail = leaf.split(/[-_]/).pop();
				if (tail && !label.toLowerCase().endsWith(tail.toLowerCase())) {
					label = `${label} ${title(tail)}`;
				}
			}
			return label;
		};

		const members = all
			.map((x) => ({ id: x.id, label: finalLabel(x) }))
			.sort((a, b) => (a.label === "Utama" ? -1 : b.label === "Utama" ? 1 : a.label.localeCompare(b.label)));
		for (const m of all) m.family = { root: rootModel.id, label: finalLabel(m), members };
	};

	// Character merge: a character's unit + lobbyunit + pet + its cutscene
	// videos. Only when a unit FOLDER named exactly the base exists —
	// otherwise a shared word like "goblin"/"dragon" would merge unrelated
	// models (goblin_archer, goblin_king, dragon_gold, dragon_green).
	for (const [, bucket] of buckets) {
		if (bucket.group !== "unit") continue;
		const base = bucket.base;
		const plainFolder = `lostsword/unit/${base}`;
		const plain =
			bucket.models.find(
				(m) =>
					folderOf(m.id) === plainFolder &&
					(m.id.split("#")[1] || "").toLowerCase() === base
			) || bucket.models.find((m) => folderOf(m.id) === plainFolder);
		if (!plain) continue;
		const all = [...bucket.models];
		for (const g of ["lobbyunit", "pet"]) {
			const b = buckets.get(`${g}|${base}`);
			if (b) all.push(...b.models);
		}
		if (vidsByBase.has(base)) all.push(...vidsByBase.get(base));
		makeFamily(all, base, plain);
	}

	// Prop merge: a unit FOLDER with several skeletons is one entity whose
	// parts are named by their stems (Abyss + fog + effects; Goblin_Carriage
	// + _b/_u halves; Kraken Far/Mid/Front). Group per FOLDER, never across the
	// whole base bucket — otherwise unrelated dragons/goblins that merely share
	// a first word (`dragon_gold` / `dragon_green`, `goblin_archer` /
	// `goblin_carriage`) would fuse into one card.
	const byFolder = new Map();
	for (const m of ls) {
		const f = folderOf(m.id);
		if (!byFolder.has(f)) byFolder.set(f, []);
		byFolder.get(f).push(m);
	}
	for (const [folder, group] of byFolder) {
		if (group.length < 2 || group.some((m) => m.family)) continue;
		const [, , fname] = folder.split("/");
		const base = baseOf(fname);
		const rootModel =
			group.find((m) => (m.id.split("#")[1] || "").toLowerCase() === base) || group[0];
		makeFamily(group, base, rootModel, true);
	}
	return models;
}

function scanModels() {
	if (!fs.existsSync(ASSETS)) return [];
	const models = [];

	// Walk the asset tree so nested layouts (e.g. spine/char/<id>/) are all found.
	// `rootRel` is the top-level asset folder (nikke, bd2-char, …) — it's stripped
	// from generated names, otherwise every Nikke model reads "Nikke › C010 › Aim".
	const walk = (dir, depth, rootRel = null) => {
		if (depth > 8) return;
		let entries = [];
		try {
			entries = fs.readdirSync(dir, { withFileTypes: true });
		} catch {
			return;
		}

		// Symlinked asset folders (e.g. assets/bd2-char -> /…/spine/char) show up
		// as symlinks, not directories, so resolve them explicitly or they're skipped.
		const dirs = [];
		const files = [];
		for (const e of entries) {
			if (e.name === ".git") continue;
			let isDir = e.isDirectory();
			if (!isDir && e.isSymbolicLink()) {
				try {
					isDir = fs.statSync(path.join(dir, e.name)).isDirectory();
				} catch {
					continue; // broken symlink
				}
			}
			if (isDir) dirs.push(e.name);
			else if (e.isFile() || e.isSymbolicLink()) files.push(e.name);
		}

		const skel = files.filter(isSkel);
		const atlas = files.filter(isAtlas);

		// Live2D Cubism: a .moc3 plus its textures, with no .skel/.atlas.
		// The game ships no .model3.json, so we synthesise the settings in the
		// browser from the folder contents.
		const moc3 = files.filter((f) => f.toLowerCase().endsWith(".moc3"));
		if (moc3.length) {
			const textures = files.filter((f) => /\.(png|jpe?g|webp)$/i.test(f));
			// Synthesised .motion3.json files live in a motions/ subfolder,
			// which the flat `files` list above does not see — read it
			// directly or every Cubism model reports zero animations.
			let motions = [];
			const mdir = path.join(dir, "motions");
			try {
				if (fs.statSync(mdir).isDirectory()) {
					motions = fs
						.readdirSync(mdir)
						.filter((f) => f.toLowerCase().endsWith(".motion3.json"))
						.sort();
				}
			} catch {
				motions = [];
			}
			// Cubism expressions, when the model ships them. Exposed through
			// the Skin dropdown in the browser (Cubism has no Spine skins).
			let expressions = [];
			const edir = path.join(dir, "expressions");
			try {
				if (fs.statSync(edir).isDirectory()) {
					expressions = fs
						.readdirSync(edir)
						.filter((f) => f.toLowerCase().endsWith(".exp3.json"))
						.map((f) => f.replace(/\.exp3\.json$/i, ""))
						.sort();
				}
			} catch {
				expressions = [];
			}
			const rel = path.relative(ASSETS, dir).split(path.sep).join("/");
			const id = rel.replace(/[^\w.\-/]+/g, "-");
			const inner =
				rootRel && (rel === rootRel || rel.startsWith(rootRel + "/"))
					? rel.slice(rootRel.length).replace(/^\//, "")
					: rel;
			const parts = inner ? inner.split("/").filter(Boolean) : [path.basename(dir)];
			const title = (s) => s.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
			const { game, gameLabel } = resolveGame(rootRel, id);
			// Sort so texture_00 precedes texture_01; the browser re-orders
			// them against the moc3's real indices anyway.
			models.push({
				id,
				game,
				gameLabel,
				format: "live2d",
				subgroup: parts.slice(0, -1).join(" › "),
				name: parts.map(title).join(" › "),
				group: rel.split("/").slice(0, -1).join(" / ") || "",
				skeletonFile: moc3[0],
				textureFiles: textures.sort(),
				// Names only; the loader prefixes the motions/ folder.
				motionFiles: motions.map((f) => f.split("/").pop()),
				files: files.sort(),
				bytes: dirBytes(dir),
				// One entry per synthesised motion so the dropdown is useful.
				animations: motions.length
					? motions.map((f) => f.split("/").pop().replace(/\.motion3\.json$/, ""))
					: ["idle"],
				// Cubism expressions (shown via the Skin dropdown); the browser
				// also rebuilds this from the live model, so it is a hint.
				expressions,
				skins: expressions.length ? ["(diam)", ...expressions] : [],
				spine: null,
				runtime: "cubism4",
				bones: null,
				slots: null,
			});
		}

		if (skel.length && atlas.length) {
			const rel = path.relative(ASSETS, dir).split(path.sep).join("/");
			// IDs must stay URL-safe and unique across the whole tree.
			const id = rel.replace(/[^\w.\-/]+/g, "-");
			// Strip the top-level root so nested variants stay readable:
			// nikke/c010/aim -> "C010 › Aim", not "Nikke › C010 › Aim".
			const inner =
				rootRel && (rel === rootRel || rel.startsWith(rootRel + "/"))
					? rel.slice(rootRel.length).replace(/^\//, "")
					: rel;
			const parts = inner ? inner.split("/").filter(Boolean) : [path.basename(dir)];
			const title = (s) => s.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
			// BD2's story/event "special animations" are named after their
			// asset id alone (illust_special18, specialillust143) because the
			// reference repo carries no character data for them. Reading
			// "Illust › Illust Special › Illust Special18" in the sidebar is
			// noise, so collapse the redundant pair of path segments into one
			// "Special Animation N" label.
			const isBd2Special =
				parts.length >= 2 &&
				parts[parts.length - 2] === "illust_special" &&
				/^(illust_special|specialillust)/i.test(parts[parts.length - 1]);
			const labelParts = isBd2Special
				? parts
						.slice(0, -2)
						.concat([
							"Special Animation " +
								(parts[parts.length - 1].match(/(\d+)/)?.[1] ||
									parts[parts.length - 1]),
						])
				: parts;
			const { game, gameLabel, pmaDefault, spineRuntime, hiddenGame } = resolveGame(rootRel, id);
			// Sub-category is what sits between the game root and the model. For
			// nikke/c010/aim that's "c010" — a character, not a category, so it's
			// exposed as `subgroup` and kept OUT of the game filter.
			const subParts = parts.slice(0, -1);

			// A folder can hold SEVERAL models (Azur Lane ships bailongB /
			// bailongM / bailongT in one folder). Pair each skeleton with the
			// atlas of the same stem; only then fall back to a sibling atlas.
			// Pairing "skel[0] with atlas[0]" silently hid most of them.
			const pairs = pairSkeletonAtlas(skel, atlas);
			const multi = pairs.length > 1;

			for (const { skel: sk, atlas: at } of pairs) {
				const stem = sk.replace(/\.(skel|json)$/i, "");
				const meta = inspectSkeleton(path.join(dir, sk), path.join(dir, at));
				// With several models in one folder the id and name must differ
				// per model, otherwise they collide into a single entry.
				const modelId = multi ? `${id}#${stem}` : id;
				const modelName = multi
					? [...labelParts, stem].map(title).join(" › ")
					: labelParts.map(title).join(" › ");
				models.push({
					id: modelId,
					game,
					gameLabel,
					pmaDefault,
					hiddenGame,
					// Which renderer the browser must use. Non-null only for
					// Project QT (2.1.27), which pixi-spine cannot draw.
					spineRuntime,
					subgroup: subParts.join(" › "),
					name: modelName,
					group: rel.split("/").slice(0, -1).join(" / ") || "",
					skeletonFile: sk,
					atlasFile: at,
					files: files.sort(),
					bytes: dirBytes(dir),
					atlasPages: countAtlasPages(path.join(dir, at)),
					spine: meta?.spine ?? null,
					runtime: meta?.runtime ?? null,
					size: meta ? { width: meta.width, height: meta.height } : null,
					bones: meta?.bones ?? null,
					slots: meta?.slots ?? null,
					animations: meta?.animations ?? [],
					skins: meta?.skins ?? [],
					// Spine 2.x: readable only by the vendored 2.1.27 viewer,
					// so the client must not hand it to pixi-spine.
					needsLegacyViewer: !!meta?.needsLegacyViewer,
					needsProbe: !meta,
				});
			}
			// Keep descending: a folder can be a model *and* hold variants
			// (Nikke ships c010/ plus c010/aim/ and c010/cover/). Skipping the
			// recursion would hide every one of those.
		}

		for (const name of dirs) {
			const child = path.join(dir, name);
			walk(child, depth + 1, rootRel || (dir === ASSETS ? name : rootRel));
		}
	};

	walk(ASSETS, 0, null);
	const sorted = models.sort((a, b) => a.name.localeCompare(b.name));
	scanVideos(models);
	// CG / illust galleries: flat PNG folders (a "<game>-cg" GAME_ROOTS entry)
	// that no skeleton scan would surface. One entry per image, format "image".
	scanImageGalleries(models);
	// CZN rigs/cutins come from a community model library; label each model with
	// its character name (slug -> name from assets/<game>/_names.json).
	applyCznNames(models);
	// Fold each CZN character's rigs (model / portrait / live event / skin /
	// battle) into ONE card with a variant dropdown.
	attachCznFamilies(models);
	// Make Drama: name each skin from the library catalog and fold a character's
	// standing/affection/desire rigs into one card with a variant dropdown.
	applyMadNames(models);
	// Epic Seven: nama + rarity/elemen/kelas dari katalog e7codex
	// (assets/epic7/_names.json, ditulis tools/fetch-e7codex-meta.py).
	applyEpic7Names(models);
	// Lost Sword: fold each character's unit + lobby + pet + cutscene videos
	// into one family so the "Varian" dropdown carries them all. Videos stay in
	// `models` (the client resolves variant ids against it) but only the family
	// root is listed, so they never appear as separate cards.
	const lsVideos = models.filter((m) => (m.game || "") === "lostsword-video");
	return attachLostSwordFamilies(attachCharacters(attachFamilies(sorted)), lsVideos);
}

/**
 * Lost Sword movies are plain .mp4/.m4v files (skill / summon / quest
 * cutscenes) that no skeleton scan would ever surface. Walk
 * assets/lostsword-video/ and add one entry per file with format "video" so
 * the viewer can list and play them; `bytes` gives the size for the badge.
 */
function scanVideos(models) {
	scanVideoFolder(models, "lostsword-video", "Lost Sword — Video");
	// Epic Seven wallpaper animation (tools/download-e7wallpapers.py).
	// Berkasnya .webm VP9 sampai 4K; metadata judul/units dibaca dari
	// _lobby_anims.json yang disalin ke folder oleh skrip yang sama.
	scanVideoFolder(models, "epic7-wallpaper", "Epic Seven — Wallpaper");
}

/**
 * Daftarkan semua berkas video di assets/<game>/ sebagai model
 * `format: "video"` (video stage memutarnya lewat <video>).
 *
 * @param {string} game  nama folder di bawah assets/ sekaligus nilai `game`
 * @param {string} label label game yang tampil di pustaka
 */
function scanVideoFolder(models, game, label) {
	const root = path.join(ASSETS, game);
	if (!fs.existsSync(root)) return;
	const files = [];
	const walkV = (dir, depth) => {
		if (depth > 6) return;
		let entries = [];
		try {
			entries = fs.readdirSync(dir, { withFileTypes: true });
		} catch {
			return;
		}
		for (const e of entries) {
			const full = path.join(dir, e.name);
			if (e.isDirectory()) walkV(full, depth + 1);
			else if (/\.(mp4|m4v|webm|mov)$/i.test(e.name)) files.push(full);
		}
	};
	walkV(root, 0);
	for (const full of files) {
		const rel = path.relative(root, full).split(path.sep).join("/");
		const id = game + "/" + rel.replace(/\.[^.]+$/, "");
		let bytes = 0;
		try {
			bytes = fs.statSync(full).size;
		} catch {
			/* keep 0 */
		}
		const parts = rel.replace(/\.[^.]+$/, "").split("/");
		const title = (s) => s.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
		models.push({
			id,
			game,
			gameLabel: label,
			hiddenGame: !!resolveGame(game, game).hiddenGame,
			format: "video",
			subgroup: parts.slice(0, -1).join(" › "),
			name: parts.map(title).join(" › "),
			group: game + " / " + parts.slice(0, -1).join(" / "),
			videoFile: `/${game}/${rel.split("/").map(encodeURIComponent).join("/")}`,
			files: [path.basename(full)],
			bytes,
			size: null,
			spine: null,
			runtime: null,
			bones: null,
			slots: null,
			animations: [],
			skins: [],
		});
	}
}

/**
 * CZN (Chaos Zero Nightmare) rigs and cut-in galleries come from the community
 * library BenNoSleep/czn-animation-viewer, which provides a name catalog written
 * to assets/<game>/_names.json (slug -> {name,kind,subtype}). Fold that name
 * into each model's `name` and add a `character` link so the card reads
 * "Nia" instead of "portrait 1003 front".
 */
function applyCznNames(models) {
	const prettyRigName = (slug) =>
		slug
			.replace(/^liveevent_/, "Live Event ")
			.replace(/_battle_ready$/, " Battle Ready")
			.replace(/^model_/, "Model ")
			.replace(/^portrait_/, "Portrait ")
			.replace(/^battle_/, "Battle ")
			.replace(/^npc_/, "NPC ")
			.replace(/^god_/, "God ")
			.replace(/_/g, " ")
			.replace(/\b\w/g, (c) => c.toUpperCase())
			.trim();
	for (const game of ["czn-rigs", "czn-cutins-cg"]) {
		let map;
		try {
			map = JSON.parse(fs.readFileSync(path.join(ASSETS, game, "_names.json"), "utf8"));
		} catch {
			continue;
		}
		for (const m of models) {
			if (m.game !== game) continue;
			const slug = String(m.id || "").slice(game.length + 1);
			const rec = map[slug] || map[slug.replace(/^.*\//, "")];
			if (!rec || !rec.name) {
				// No catalog name (monsters / effects / unnamed events): still tidy
				// the slug so the card never reads "Liveevent 9999".
				if (game === "czn-rigs") m.name = prettyRigName(slug);
				continue;
			}
			const kind = rec.kind || "";
			m.name = kind && kind !== "cutin" ? `${rec.name} — ${kind}` : rec.name;
			m.character = { name: rec.name, source: "czn-animation-viewer", skin: rec.subtype || null };
		}
	}
}

/**
 * Epic Seven — nama + metadata dari katalog e7codex.
 *
 * Sumbernya https://e7codex.com/data/units.json; tools/fetch-e7codex-meta.py
 * merangkumnya jadi assets/epic7/_names.json (id -> {name, kind, rarity,
 * element, class, slug, ...}). Tanpa ini kartu hanya menampilkan kode
 * ("C1001") padahal katalognya tahu itu "Ras", 3★, Fire, Knight.
 *
 * Penamaan mengikuti pola applyCznNames/applyMadNames: `name` dipakai untuk
 * label kartu, `character` untuk tooltip dan baris kedua. `kind` (unit /
 * npc / monster) ditempel di nama karena tanpa itu NPC dan monster ikut
 * terbaca seperti hero.
 */
function applyEpic7Names(models) {
	const e7 = models.filter((m) => (m.game || "") === "epic7");
	if (!e7.length) return;
	let map;
	try {
		map = JSON.parse(fs.readFileSync(path.join(ASSETS, "epic7", "_names.json"), "utf8"));
	} catch {
		return; // katalog belum dibuat — kartu tetap memakai id
	}
	const kindSuffix = (kind) => {
		if (!kind || kind === "unit") return "";
		return kind === "npc" ? " (NPC)" : kind === "monster" ? " (Monster)" : ` (${kind})`;
	};
	for (const m of e7) {
		const key = String(m.id || "").slice("epic7/".length);
		const rec = map[key];
		if (!rec || !rec.name) continue;
		const suffix = kindSuffix(rec.kind);
		m.name = rec.name + suffix;
		// `character` adalah bentuk yang sudah dipahami UI: name + rarity +
		// class + element tampil di baris kedua, sisanya di tooltip.
		m.character = {
			name: rec.name,
			plain: rec.name,
			source: "e7codex.com",
			rarity: rec.rarity || null,
			class: rec.class || null,
			element: rec.element || null,
			skin: rec.hero && rec.hero !== rec.name ? rec.hero : null,
			code: key,
		};
		if (rec.slug) m.slug = rec.slug;
		if (rec.released) m.released = rec.released;
		m.kind = rec.kind || "unit";
	}

	// Rig combat memakai id yang sama di bawah game "epic7-combat", jadi
	// katalognya dipakai ulang. Nama diberi akhiran "Combat" supaya jelas
	// ini rig pertarungan (20 animasi skill), bukan pose lobby.
	const combat = models.filter((m) => (m.game || "") === "epic7-combat");
	for (const m of combat) {
		const key = String(m.id || "").slice("epic7-combat/".length);
		const rec = map[key];
		if (!rec || !rec.name) continue;
		m.name = `${rec.name} — Combat`;
		m.character = {
			name: rec.name,
			plain: rec.name,
			source: "e7codex.com",
			rarity: rec.rarity || null,
			class: rec.class || null,
			element: rec.element || null,
			code: key,
			rig: "combat",
		};
		m.kind = rec.kind || "unit";
	}

	// Gabungkan rig combat ke kartu lobby sebagai VARIAN, bukan game
	// terpisah: satu karakter muncul sekali di pustaka, dengan pilihan
	// "Lobby" / "Combat" di dropdown varian. Tanpa ini daftar berisi dua
	// entri untuk karakter yang sama (Ras dan Ras — Combat).
	attachEpic7CombatFamilies(models);

	// Animasi skill (animated WebP) — id berbentuk
	// "epic7-skill/<karak>_skill<n>/<namaberkas>" karena scanImageGalleries
	// memakai path relatif termasuk nama berkas. Ambil segmen PERTAMA saja,
	// lalu beri nama karakter supaya kartunya terbaca "Elena — Skill 3",
	// bukan "C1091 Skill3 › Skill Sk C1091 3".
	for (const m of models) {
		if ((m.game || "") !== "epic7-skill") continue;
		const rel = String(m.id).slice("epic7-skill/".length);
		const folder = rel.split("/")[0];
		const mm = /^(.*)_skill(\d+)$/.exec(folder);
		if (!mm) continue;
		const rec = map[mm[1]];
		const who = rec?.name || mm[1];
		m.name = `${who} — Skill ${mm[2]}`;
		m.character = {
			name: who,
			plain: who,
			source: "e7codex.com",
			rarity: rec?.rarity || null,
			class: rec?.class || null,
			element: rec?.element || null,
			code: mm[1],
			rig: "skill",
			skillNo: Number(mm[2]),
		};
	}

	// Skill juga masuk dropdown varian, bukan game terpisah. Formatnya beda
	// (image, bukan skeleton) tapi switchVariant() hanya memanggil
	// loadModel(), yang sudah memilih jalur render sesuai model.format —
	// jadi campuran skeleton + gambar aman dalam satu family.
	attachEpic7SkillFamilies(models);

	// Wallpaper animation (.webm) — judul dari _lobby_anims.json, lalu
	// ditempelkan sebagai varian ke kartu karakter yang disebut di `units`.
	applyEpic7Wallpapers(models);
}

/**
 * Epic Seven: wallpaper animation (klip .webm) dari lobby_anims.json.
 *
 * Dua hal dikerjakan:
 *   1. memberi judul yang enak dibaca (id mentah seperti
 *      "vsu5aa_2_lobby" diganti judul dari katalog), dan
 *   2. menjadikan klip itu VARIAN dari kartu karakter di field `units`.
 *
 * Satu klip bisa menyebut beberapa unit (vsu4aa2 punya 4), dan satu
 * karakter bisa punya beberapa klip. Karena family hanya punya satu root,
 * kelompokkan per karakter lalu bangun satu family berisi semua anggotanya
 * (lobby, combat, skill, wallpaper). Karakter yang tidak punya model lain
 * tetap mendapat family — root-nya wallpaper itu sendiri.
 *
 * Klip yang tidak menyebut unit mana pun (8 dari 24) dibiarkan berdiri
 * sendiri di game "Epic Seven — Wallpaper".
 */
function applyEpic7Wallpapers(models) {
	const wp = models.filter((m) => (m.game || "") === "epic7-wallpaper");
	if (!wp.length) return;
	let meta;
	try {
		meta = JSON.parse(fs.readFileSync(path.join(ASSETS, "epic7-wallpaper", "_lobby_anims.json"), "utf8"));
	} catch {
		return; // tanpa metadata: kartu tetap memakai id
	}
	const byId = new Map(meta.map((x) => [x.id, x]));
	const byModelId = new Map(models.map((m) => [m.id, m]));

	// 1) Judul + durasi.
	for (const m of wp) {
		// id berbentuk "epic7-wallpaper/<id>/<id>" (scanVideoFolder memakai
		// path relatif termasuk nama berkas), jadi ambil segmen PERTAMA.
		const key = String(m.id).slice("epic7-wallpaper/".length).split("/")[0];
		const rec = byId.get(key);
		if (!rec) continue;
		m.name = rec.title || m.name;
		if (rec.duration_s) m.duration = rec.duration_s;
		if (rec.note) m.note = rec.note;
		m.kind = "wallpaper";
	}

	// 2) Kelompokkan per karakter (dari field units).
	const perChar = new Map();
	for (const m of wp) {
		const key = String(m.id).slice("epic7-wallpaper/".length).split("/")[0];
		const rec = byId.get(key);
		for (const unit of rec?.units || []) {
			if (!perChar.has(unit)) perChar.set(unit, []);
			perChar.get(unit).push(m);
		}
	}

	for (const [unit, clips] of perChar) {
		// Katalog wallpaper kadang menyebut id dasar ("c5147") padahal
		// skeleton-nya terdaftar dengan sufiks ("c5147_1"). Tanpa cadangan
		// ini klip "Epic Dash 2026 — Fumyr" tidak menempel ke kartu mana pun
		// dan hanya muncul sebagai entri lepas di game Wallpaper.
		const lobby = byModelId.get(`epic7/${unit}`) || byModelId.get(`epic7/${unit}_1`);
		const combat = byModelId.get(`epic7-combat/${unit}`) || byModelId.get(`epic7-combat/${unit}_1`);
		const root = lobby || combat;
		if (!root) continue;

		// Anggota awal: family yang sudah ada, atau root sendirian.
		const members = root.family?.members
			? [...root.family.members]
			: [{ id: root.id, label: "Lobby" }];
		const have = new Set(members.map((x) => x.id));
		for (const c of clips) {
			if (have.has(c.id)) continue;
			have.add(c.id);
			members.push({ id: c.id, label: c.name.length > 34 ? c.name.slice(0, 32) + "…" : c.name });
		}
		const family = { root: root.id, label: root.family?.label || "Lobby", members };
		for (const mem of members) {
			const target = byModelId.get(mem.id);
			if (target) target.family = { root: root.id, label: mem.label, members };
		}
	}
}

/**
 * Epic Seven: jadikan animasi skill (WebP) varian dari kartu karakter.
 *
 * Kelompokkan per id karakter (bukan per berkas), lalu urutkan skill
 * menaik (Skill 1, 2, 3). Karakter yang tidak punya rig lobby tetap
 * dibiarkan berdiri sendiri supaya tidak hilang dari pustaka.
 *
 * Dipanggil SETELAH attachEpic7CombatFamilies(), yang sudah memasang
 * family berisi Lobby + Combat untuk karakter yang punya keduanya. Di sini
 * family itu DIPERLUAS, bukan ditimpa — kalau ditimpa, varian Combat
 * hilang dari dropdown.
 */
function attachEpic7SkillFamilies(models) {
	// Kumpulkan id karakter -> daftar model skill, urut nomor skill.
	const byChar = new Map();
	for (const m of models) {
		if ((m.game || "") !== "epic7-skill") continue;
		const code = m.character?.code;
		if (!code) continue;
		if (!byChar.has(code)) byChar.set(code, []);
		byChar.get(code).push(m);
	}
	if (!byChar.size) return;

	// Indeks model per id, supaya bisa menemukan root lobby maupun combat.
	const byId = new Map(models.map((m) => [m.id, m]));

	for (const [code, skills] of byChar) {
		skills.sort((a, b) => (a.character?.skillNo || 0) - (b.character?.skillNo || 0));
		const lobby = byId.get(`epic7/${code}`);
		const combat = byId.get(`epic7-combat/${code}`);
		// Root = lobby kalau ada (punya thumbnail potret), kalau tidak combat.
		const root = lobby || combat;
		if (!root) continue; // skill tanpa karakter: biarkan berdiri sendiri

		// Ambil anggota family yang sudah ada (Lobby + Combat), lalu tambah skill.
		const existing = root.family?.members || [{ id: root.id, label: "Lobby" }];
		const members = [...existing];
		for (const s of skills) {
			const no = s.character?.skillNo || 0;
			members.push({ id: s.id, label: `Skill ${no}` });
		}
		const family = { root: root.id, label: root.family?.label || "Lobby", members };
		for (const mem of members) {
			const target = byId.get(mem.id);
			if (!target) continue;
			target.family = { root: root.id, label: mem.label, members };
		}
	}
}

/**
 * Epic Seven: jadikan rig combat sebagai varian dari kartu lobby.
 *
 * Root-nya selalu model lobby (assets/epic7/<id>), karena itu yang punya
 * thumbnail potret dan pose berdiri. Rig combat menjadi anggota kedua
 * dengan label "Combat (20 animasi)".
 *
 * Model combat yang TIDAK punya pasangan lobby (mis. c1046_s02_1 yang hanya
 * ada di rig combat) dibiarkan berdiri sendiri dengan nama "... — Combat",
 * supaya tidak hilang dari daftar.
 */
function attachEpic7CombatFamilies(models) {
	const lobby = new Map();
	for (const m of models) {
		if ((m.game || "") !== "epic7") continue;
		lobby.set(String(m.id).slice("epic7/".length), m);
	}
	if (!lobby.size) return;
	const paired = new Set();
	for (const m of models) {
		if ((m.game || "") !== "epic7-combat") continue;
		const key = String(m.id).slice("epic7-combat/".length);
		const root = lobby.get(key);
		if (!root) continue; // combat tanpa lobby: biarkan berdiri sendiri
		paired.add(root.id);
		// Root menampung semua anggota; label dipakai di dropdown.
		const members = [
			{ id: root.id, label: "Lobby" },
			{ id: m.id, label: `Combat (${m.animations?.length || 0} animasi)` },
		];
		root.family = { root: root.id, label: "Lobby", members };
		m.family = { root: root.id, label: members[1].label, members };
	}
	// Root tanpa combat tetap tanpa family (biar label kartu apa adanya).
	for (const id of paired) void id;
}

/**
 * Make Drama (MAD) names + variants.
 *
 * Names come from assets/mad-drama/_names.json (unit -> {name, kind, store,
 * character}), built by tools/extract-mad-viewer.py out of the library's
 * characters.json. One character ships as several rigs (a standing rig plus an
 * affection / desire / pleasure scene, and often a google + onestore build of
 * the same art), all carrying the same `character` code. Fold them into one
 * card whose root is the standing rig, with the scenes as dropdown variants.
 */
function applyMadNames(models) {
	const mad = models.filter((m) => (m.game || "") === "mad-drama");
	if (!mad.length) return;
	let map;
	try {
		map = JSON.parse(fs.readFileSync(path.join(ASSETS, "mad-drama", "_names.json"), "utf8"));
	} catch {
		return;
	}
	const cap = (s) => String(s || "").replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).trim();
	for (const m of mad) {
		const unit = String(m.id).split("/").pop();
		const rec = map[unit];
		if (!rec) continue;
		const kind = cap(rec.kind);
		m.name = `${rec.name} — ${kind}`;
		m.character = { name: rec.name, plain: rec.name, source: "anyabot/MAD-Viewer", skin: rec.kind, code: rec.character };
		m.store = rec.store || null;
	}
	// Group per character; the standing rig is the card, scenes its variants.
	const byChar = new Map();
	for (const m of mad) {
		if (!m.character?.code) continue;
		if (!byChar.has(m.character.code)) byChar.set(m.character.code, []);
		byChar.get(m.character.code).push(m);
	}
	const rank = (m) => ({ standing: 0, affection: 1, desire: 2, pleasure: 3, drama: 4 }[m.character?.skin] ?? 5);
	const label = (m) => {
		const k = cap(m.character.skin);
		return m.store === "onestore" ? `${k} (ONE)` : m.store === "google" ? `${k} (GP)` : k;
	};
	for (const [, members] of byChar) {
		if (members.length < 2) {
			// Standalone (a character with a single scene): keep the kind in the
			// card name so "Desire" doesn't read as the standing art.
			members[0].character.name = `${members[0].character.plain} — ${cap(members[0].character.skin)}`;
			continue;
		}
		const root = [...members].sort((a, b) => rank(a) - rank(b) || String(a.id).localeCompare(b.id))[0];
		const ordered = [root, ...members.filter((m) => m !== root)];
		const used = new Map();
		const membersList = ordered.map((m) => {
			if (m.id === root.id) return { id: m.id, label: "Utama" };
			const b = label(m);
			const n = (used.get(b) || 0) + 1;
			used.set(b, n);
			return { id: m.id, label: n === 1 ? b : `${b} ${n}` };
		});
		const byId = new Map(membersList.map((x) => [x.id, x.label]));
		for (const m of members) {
			m.family = { root: root.id, label: byId.get(m.id) || "Utama", members: membersList };
			m.character.name = m.character.plain; // the card reads just the character
		}
	}
}

/**
 * Chaos Zero Nightmare rig variants. One character ships as several rigs, all
 * carrying the same display name (e.g. Rei = model_1056, portrait_1056,
 * liveevent_1056, 1056_01, model_1056_battle_ready …). Group them into one
 * family whose ROOT is the plain character model (`model_<id>`, else the first
 * rig), with every other rig as a dropdown variant — so "Rei" is one card, not
 * seven. Applies to czn-rigs only (cut-ins stay a gallery).
 */
function attachCznFamilies(models) {
	const czn = models.filter((m) => (m.game || "") === "czn-rigs");
	if (czn.length < 2) return;
	// Group by the character's numeric id parsed from the slug (portrait_1056,
	// liveevent_1028, model_1001002 … all share their id). The name catalog only
	// covers ~107 characters; grouping by id folds the other ~1000 rigs too.
	const idOf = (m) => {
		const slug = String(m.id).split("/").pop();
		const mm = slug.match(/(\d{3,})/);
		return mm ? mm[1] : (m.character?.name || null);
	};
	const byChar = new Map();
	for (const m of czn) {
		const key = idOf(m);
		if (!key) continue;
		if (!byChar.has(key)) byChar.set(key, []);
		byChar.get(key).push(m);
	}
	const cap = (s) => s.replace(/[-_]+/g, " ").trim().replace(/\b\w/g, (c) => c.toUpperCase());
	const baseLabel = (slug) => {
		if (/^\d+_\d+$/.test(slug)) return "Skin";
		if (/^liveevent_/.test(slug)) return "Live Event";
		if (/_battle_ready$/.test(slug)) return "Battle Ready";
		let m;
		if ((m = slug.match(/^portrait_(?:.*?)_(\w+)$/))) return `Portrait ${cap(m[1])}`;
		if (/^portrait_/.test(slug)) return "Portrait";
		if ((m = slug.match(/^model_.*?_(\w+)$/))) return cap(m[1]);
		if (/_battle$/.test(slug)) return "Battle";
		if (/^npc_/.test(slug)) return "NPC";
		if (/^god_/.test(slug)) return "God";
		return cap(slug.replace(/^[a-z]+_/, "")) || "Varian";
	};
	const rootRank = (m) => {
		const slug = String(m.id).split("/").pop();
		if (/^model_\d+$/.test(slug)) return 0;
		if (m.kind === "model" && !/_battle_ready$/.test(slug)) return 1;
		if (/^battle_/.test(slug)) return 2;
		if (/^model_/.test(slug)) return 3;
		if (/^liveevent_/.test(slug)) return 4;
		if (/^portrait_/.test(slug)) return 5;
		return 6;
	};
	for (const [, members] of byChar) {
		if (members.length < 2) continue;
		const root = [...members].sort((a, b) => rootRank(a) - rootRank(b) || String(a.id).localeCompare(b.id))[0];
		const ordered = [root, ...members.filter((m) => m !== root)];
		const used = new Map();
		const membersList = ordered.map((m) => {
			if (m.id === root.id) return { id: m.id, label: "Utama" };
			const b = baseLabel(String(m.id).split("/").pop());
			const n = (used.get(b) || 0) + 1;
			used.set(b, n);
			return { id: m.id, label: n === 1 ? b : `${b} ${n}` };
		});
		const byId = new Map(membersList.map((x) => [x.id, x.label]));
		for (const m of members) {
			m.family = { root: root.id, label: byId.get(m.id) || "Utama", members: membersList };
		}
		// The card reads just the character name when the catalog has one.
		if (root.character?.name) root.name = root.character.name;
	}
}

/**
 * CG / illust galleries. Some games ship their 2D still art as plain
 * <game>-cg/ folders full of flat PNGs (no skeleton, no atlas) — e.g.
 * 深蓝终末录's character/story CGs, extracted by tools/shenlan/. No skeleton
 * scan would ever surface them, so add one entry per image with format
 * "image"; the client draws it as a still on the stage (pan/zoom + export).
 *
 * A folder is treated as a gallery when its top-level name ends in "-cg" AND a
 * GAME_ROOTS entry declares it (so it gets a proper game label) — that keeps
 * this from swallowing unrelated PNGs elsewhere in the tree.
 */
function scanImageGalleries(models) {
	let tops = [];
	try {
		tops = fs.readdirSync(ASSETS, { withFileTypes: true });
	} catch {
		return;
	}
	for (const t of tops) {
		const top = t.name;
		// "-cg" = galeri CG/ilustrasi; "-skill" = animasi skill (animated
		// WebP) seperti Epic Seven. Keduanya sama-sama kumpulan berkas gambar
		// tanpa skeleton, jadi jalur pemuatannya identik.
		const isSkill = /-skill$/i.test(top);
		if (!/-cg$/i.test(top) && !isSkill) continue;
		const dir = path.join(ASSETS, top);
		let stat;
		try {
			stat = fs.statSync(dir);
		} catch {
			continue;
		}
		if (!stat.isDirectory()) continue;
		const { game, gameLabel, hiddenGame } = resolveGame(top, top);
		const imgs = [];
		const walkImg = (d, depth) => {
			if (depth > 6) return;
			let entries = [];
			try {
				entries = fs.readdirSync(d, { withFileTypes: true });
			} catch {
				return;
			}
			for (const e of entries) {
				const full = path.join(d, e.name);
				if (e.isDirectory()) walkImg(full, depth + 1);
				else if (/\.(png|jpe?g|webp)$/i.test(e.name)) imgs.push(full);
			}
		};
		walkImg(dir, 0);
		imgs.sort();
		const title = (s) => s.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
		for (const full of imgs) {
			const rel = path.relative(dir, full).split(path.sep).join("/");
			// id lives IN the gallery folder (e.g. shenlan-cg/cgs_11000101_1),
			// so the client's id->URL mapping is identical to a spine model.
			const id = top + "/" + rel.replace(/\.[^.]+$/, "");
			let bytes = 0;
			try {
				bytes = fs.statSync(full).size;
			} catch {
				/* keep 0 */
			}
			const parts = rel.replace(/\.[^.]+$/, "").split("/");
			models.push({
				id,
				game,
				gameLabel,
				hiddenGame,
				format: "image",
				subgroup: parts.slice(0, -1).join(" › "),
				name: parts.map(title).join(" › "),
				group: top + " / " + parts.slice(0, -1).join(" / "),
				imageFile: `/assets/${top}/${rel.split("/").map(encodeURIComponent).join("/")}`,
				files: [path.basename(full)],
				bytes,
				size: null,
				spine: null,
				runtime: null,
				bones: null,
				slots: null,
				animations: [],
				skins: [],
			});
		}
	}
}

const app = express();
app.disable("x-powered-by");

// --- security headers (viewer loads only same-origin assets) ---
app.use((req, res, next) => {
	res.setHeader("X-Content-Type-Options", "nosniff");
	res.setHeader("Referrer-Policy", "same-origin");
	res.setHeader("X-Frame-Options", "SAMEORIGIN");
	next();
});

/* Kompresi untuk semua respons teks. Terukur di host ini /api/models (27 MB)
 * turun ke ~2,3 MB dan /dist/viewer.js (4 MB) ke ratusan KB kalau di-gzip.
 * Tekstur PNG/JPEG tidak ikut — filter bawaan melewatkan tipe biner — jadi
 * alur render model tidak berubah sama sekali. /api/models sendiri sudah
 * membawa Buffer gzip hasil cache, dan middleware ini melewati respons yang
 * sudah punya Content-Encoding. */
app.use(compression());

app.use(express.json({ limit: "2mb" }));

/* The app has no accounts, so anyone who can reach the port can ask it to
 * spawn ffmpeg or a downloader. A tiny in-process rate limit keeps a public
 * deployment from being trivially turned into a CPU/disk hog. It is per-IP
 * and intentionally generous: it only stops hammering, not real use. */
const RATE_LIMITED_PREFIXES = ["/api/update", "/api/export/finish", "/api/export/cancel", "/api/models"];
// Exporting a video POSTs ONE REQUEST PER FRAME, so /api/export/frame must not
// share the 30/min ceiling meant to stop hammering: any export longer than ~1s
// at 30fps tripped it with "Terlalu banyak permintaan" even though the user did
// nothing wrong. Frames are cheap (a file write) and the client sends them
// sequentially, so they get a generous tier of their own; the expensive steps
// (ffmpeg in /finish, updater downloads) keep the strict one.
const RATE_LIMIT_MAX = Number(process.env.RATE_LIMIT_MAX) || 30;
const FRAME_LIMIT_MAX = Number(process.env.FRAME_LIMIT_MAX) || 3000;
// Unggah bisa menulis puluhan MB per panggilan ke disk yang sama, jadi
// pantasnya punya langkah sendiri yang jauh lebih ketat daripada 30/menit.
const UPLOAD_LIMIT_MAX = Number(process.env.UPLOAD_LIMIT_MAX) || 6;
const RATE_LIMIT_WINDOW_MS = 60_000;
const rateBuckets = new Map();

function rateLimit(req, res, next) {
	const isFrame = req.path.startsWith("/api/export/frame");
	const isUpload = req.path.startsWith("/api/upload");
	if (!isFrame && !isUpload && !RATE_LIMITED_PREFIXES.some((p) => req.path.startsWith(p))) return next();
	const max = isFrame ? FRAME_LIMIT_MAX : isUpload ? UPLOAD_LIMIT_MAX : RATE_LIMIT_MAX;
	const now = Date.now();
	// Separate bucket per tier: otherwise a long export would burn the strict
	// budget and then block /finish.
	const key = (req.ip || req.socket?.remoteAddress || "unknown") + "|" + (isFrame ? "frame" : isUpload ? "upload" : "strict");
	let bucket = rateBuckets.get(key);
	if (!bucket || now > bucket.resetAt) {
		bucket = { count: 0, resetAt: now + RATE_LIMIT_WINDOW_MS };
		rateBuckets.set(key, bucket);
	}
	bucket.count += 1;
	if (bucket.count > max) {
		res.setHeader("Retry-After", Math.ceil((bucket.resetAt - now) / 1000));
		return res.status(429).json({ error: "Terlalu banyak permintaan. Coba lagi sebentar." });
	}
	next();
}

// Bound the map so a flood of distinct source addresses cannot grow it forever.
const rateSweeper = setInterval(() => {
	const now = Date.now();
	for (const [key, bucket] of rateBuckets) if (now > bucket.resetAt) rateBuckets.delete(key);
}, RATE_LIMIT_WINDOW_MS);
if (rateSweeper.unref) rateSweeper.unref();

app.use(rateLimit);

/* Parsing 500+ .skel files on every request would be slow, so cache the scan
 * and invalidate it whenever anything under assets/ changes.
 *
 * The cache is also persisted to disk (data/models-cache.json). Without that
 * every restart rescans all ~17k models — about 2 minutes of 100% CPU before
 * the server answers its first request. The signature is still checked on
 * boot, so a persisted cache is only used when the tree actually matches. */
let cache = { models: null, mtime: 0, signature: "" };

const CACHE_FILE = path.join(DATA, "models-cache.json");

/**
 * Load a persisted scan cache. Returns null when unusable — missing,
 * unreadable, or written by a build whose scan output looked different.
 *
 * The signature is what guards correctness: it is derived from the newest
 * mtime under assets/, so a cache is only reused when nothing changed since
 * it was written. A wrong-but-plausible cache would silently hide models,
 * so anything unexpected is discarded rather than trusted.
 */
function loadPersistedCache() {
	try {
		const raw = JSON.parse(fs.readFileSync(CACHE_FILE, "utf8"));
		if (!raw || !Array.isArray(raw.models) || !raw.models.length) return null;
		if (typeof raw.signature !== "string" || !raw.signature) return null;
		return { models: raw.models, signature: raw.signature, mtime: raw.mtime || 0 };
	} catch {
		return null;
	}
}

/**
 * Persist the scan cache. Best-effort: a failure here only costs a slower
 * next boot, never correctness, so it must never break the request path.
 */
function savePersistedCache(sig, models) {
	try {
		fs.mkdirSync(DATA, { recursive: true });
		const tmp = CACHE_FILE + ".tmp";
		// Write to a temp file then rename: a crash mid-write would otherwise
		// leave a truncated cache that fails to parse on every boot after it.
		fs.writeFileSync(tmp, JSON.stringify({
			signature: sig,
			mtime: Date.now(),
			models,
		}));
		fs.renameSync(tmp, CACHE_FILE);
	} catch (err) {
		console.warn("[cache] gagal menyimpan cache model:", err.message);
	}
}

/**
 * One pass over assets/ that produces both the change signature and the size
 * of every folder.
 *
 * This used to be two walks — treeSignature() stat()ing ~14.9k files, then
 * dirBytes() re-stat()ing each model folder — which cost ~1m45s per rescan
 * once the 193 Cubism models (1.2 GB) were added. Doing both in a single pass
 * makes the same work rougly twice as cheap and, more importantly, keeps it
 * from growing again.
 */
/**
 * Fingerprint of the SCAN CONFIG, mixed into the cache signature.
 *
 * scanModels() output depends on GAME_ROOTS (label, spineRuntime, pmaDefault)
 * as much as on the files. But the signature was derived from assets/ mtimes
 * alone — so editing a game entry (e.g. adding `spineRuntime: "2.1.27"` to
 * route a new game to the legacy viewer) did NOT invalidate the persisted
 * cache. The server kept serving the old models and the config silently never
 * took effect. Mixing this in means a GAME_ROOTS edit busts the cache, no
 * asset write required.
 */
const SCAN_CONFIG = JSON.stringify(
	GAME_ROOTS.map((g) => [g.match, g.key, g.label, g.spineRuntime ?? null, g.pmaDefault ?? null]),
);


/* Hasil walk di-memo sementara.
 *
 * scanTree() me-walk seluruh assets/ — 141.266 file / ~100 GB di-stat di
 * host ini — dan semuanya SYNCHRONOUS. Dulu ia dipanggil di SETIAP request
 * /api/models, jadi satu request daftar model menahan event loop ~2,4 detik
 * dan file PNG yang biasanya dijawab 304 dalam <1 ms ikut melambat sampai
 * ~2 detik selama request itu berjalan (terukur). TTL membuat walk hanya
 * terjadi paling cepat tiap SCAN_TREE_TTL_MS, dan handler yang benar-benar
 * mengubah isi assets/ memanggil invalidateScan() supaya tidak perlu
 * menunggu TTL. */
let scanTreeMemo = { signature: "", sizes: null, at: 0 };
/* Peta id model -> folder fisiknya di disk.
 *
 * Id model BUKAN path foldernya: scanModels() membangun id dari
 * path.relative() lalu mengganti semua karakter di luar [\w.-/] dengan
 * tanda minus ("hazereverb/dongzuo_yuanzui_chongji1--"). Transformasi itu
 * tidak bisa dibalik, jadi DELETE /api/models/:id tidak bisa menebak
 * foldernya dari id. Peta ini diisi di dalam walk scanTree yang memang
 * sudah melewati setiap folder — tanpa I/O tambahan — memakai regex yang
 * sama persis dengan milik scanModels(). */
let modelDirs = new Map();
const SCAN_TREE_TTL_MS = Number(process.env.SCAN_TREE_TTL_MS) || 15000;

function invalidateScan() {
	/* Tandai basi, jangan dibuang: isinya tetap dipakai sampai worker
	 * membawa yang baru. Menghapusnya akan memaksa jalur sinkron di request
	 * berikutnya dan membekukan event loop ~2 detik (dulu: setiap upload
	 * atau hapus model langsung memicu walk + pindai penuh di dalam
	 * request). */
	scanTreeMemo = { ...scanTreeMemo, at: 0 };
	refreshScanTree();
}

function scanTree({ fresh = false } = {}) {
	const now = Date.now();
	const has = !!scanTreeMemo.sizes;
	const age = has ? now - scanTreeMemo.at : Infinity;

	if (!fresh && has && age < SCAN_TREE_TTL_MS) {
		return { signature: scanTreeMemo.signature, sizes: scanTreeMemo.sizes };
	}
	if (!fresh && has && age < SCAN_TREE_TTL_MS * 10) {
		/* Memo basi tapi masih layak dipakai: hasilnya dipakai dulu untuk
		 * request ini lalu diganti worker di latar. Di sinilah letak
		 * perbaikan terbesarnya — jalan menyusuri 141 ribu file memakai
		 * ~2,2 detik sinkron dan membekukan semua request lain (termasuk
		 * pemuatan tekstur) selama itu. Kalau memo kosong (boot) atau
		 * memang diminta segar (?refresh=1), barulah jalan sinkron. */
		refreshScanTree();
		return { signature: scanTreeMemo.signature, sizes: scanTreeMemo.sizes };
	}
	const res = walkAssets(ASSETS, SCAN_CONFIG);
	applyScanResult(res);
	return { signature: res.signature, sizes: res.sizes };
}

/** Terapkan hasil jalan menyusuri (dari worker maupun jalur sinkron). */
function applyScanResult(res) {
	scanTreeMemo = { signature: res.signature, sizes: res.sizes, at: Date.now() };
	modelDirs = new Map(res.dirs);
}

let scanWorkerBusy = false;

/** Jalankan pemeriksaan ulang assets/ di thread terpisah. */
function refreshScanTree() {
	if (scanWorkerBusy) return;
	scanWorkerBusy = true;
	let w;
	try {
		w = new Worker(path.join(__dirname, "scan-tree-worker.js"), {
			workerData: { assets: ASSETS, scanConfig: SCAN_CONFIG },
		});
	} catch (err) {
		scanWorkerBusy = false;
		console.error("[scan] worker tidak bisa dijalankan:", err.message);
		return;
	}
	w.on("message", applyScanResult);
	w.on("error", (err) => console.error("[scan] worker gagal:", err.message));
	// 'exit' dipakai untuk melepas kunci, apa pun hasilnya, supaya satu
	// kegagalan tidak mengunci pemeriksaan berikutnya selamanya.
	w.on("exit", () => {
		scanWorkerBusy = false;
	});
	w.unref();
}


function getModels({ force = false } = {}) {
	const { signature: sig, sizes } = scanTree({ fresh: force });

	// Memory cache first — it is free and always current within a run.
	if (!force && cache.models && cache.signature === sig) return cache.models;

	// Then the persisted cache. This is what turns a ~2 minute cold boot into
	// an instant one. The signature came from the same scanTree() walk, so a
	// hit here means assets/ really has not changed since the last save.
	if (!force && !cache.models) {
		const persisted = loadPersistedCache();
		if (persisted && persisted.signature === sig) {
			// dirBytes still has to be populated: it is filled from the size
			// half of the walk, which is not persisted (it changes with content
			// inside folders that a mtime signature may not catch).
			dirBytesCache.clear();
			for (const [k, v] of sizes) dirBytesCache.set(k, v);
			cache = { models: persisted.models, mtime: persisted.mtime, signature: sig };
			console.log(`[cache] memakai cache ${persisted.models.length} model`);
			return cache.models;
		}
	}

	// Signature berbeda dari cache (assets/ berubah) atau ada paksaan.
	if (!force && cache.models) {
		/* Ada daftar lama yang masih bisa ditampilkan, jadi pindainya di
		 * latar. scanModels() makan ~3,4 detik sinkron (67 ribu parse memo);
		 * dijalankan di dalam request, semua request lain berhenti selama
		 * itu — termasuk pemuatan tekstur. Konsekuensinya: klien menerima
		 * daftar yang telat beberapa detik, yang jauh lebih baik daripada
		 * server yang membeku. */
		scheduleScan(sig, sizes);
		return cache.models;
	}
	// Boot atau ?refresh=1: memang harus sinkron karena belum ada apa pun
	// yang bisa ditampilkan (jalur boot) atau pengguna meminta hasil segar
	// sekarang juga (jalur admin, sudah masuk rate limit).
	return runScan(sig, sizes);
}

let scanBusy = false;

/** Jadwalkan pindai penuh di luar jalur request, satu dalam satu waktu. */
function scheduleScan(sig, sizes) {
	if (scanBusy) return;
	scanBusy = true;
	setImmediate(() => {
		try {
			runScan(sig, sizes);
		} catch (err) {
			console.error("[scan] gagal memindai ulang:", err);
		}
		scanBusy = false;
	});
}

function runScan(sig, sizes) {
	// The tree changed, so cached folder sizes are stale too. scanModels()
	// reads dirBytes(), so publish the fresh sizes before it runs.
	dirBytesCache.clear();
	for (const [k, v] of sizes) dirBytesCache.set(k, v);
	inspectMemoHits = 0;
	inspectMemoMiss = 0;
	const t0 = Date.now();
	const models = scanModels();
	const scanMs = Date.now() - t0;
	cache = { models, mtime: Date.now(), signature: sig };
	savePersistedCache(sig, models);
	// Drop memo entries for files that vanished, then persist so the next
	// rescan only parses what actually changed.
	pruneInspectMemo();
	saveInspectMemo();
	console.log(
		`[scan] ${models.length} model dalam ${(scanMs / 1000).toFixed(1)}s ` +
		`(memo hit=${inspectMemoHits} miss=${inspectMemoMiss})`,
	);
	recordNewModels(models);
	return cache.models;
}

/* --- pelacak "model baru" ------------------------------------------- *
 * Sumber kebenaran = server, bukan browser. Setiap id yang muncul di hasil
 * pemindaian tetapi belum pernah terlihat diberi timestamp di sini, sehingga
 * model yang ditambahkan lewat updater CLI (tombol di browser tidak dipakai)
 * tetap mendapat badge NEW, dan flag-nya ikut ke semua browser.
 */
const NEW_FILE = path.join(DATA, "new-models.json");
const NEW_TTL_MS = 7 * 24 * 60 * 60 * 1000; // seminggu

function loadNewState() {
	try {
		const raw = JSON.parse(fs.readFileSync(NEW_FILE, "utf8"));
		return {
			// known === null berarti file belum pernah ada (jalan pertama).
			known: Array.isArray(raw.known) ? new Set(raw.known) : null,
			flagged: raw.flagged && typeof raw.flagged === "object" ? raw.flagged : {},
		};
	} catch {
		return { known: null, flagged: {} };
	}
}

function saveNewState(state) {
	const tmp = NEW_FILE + ".tmp";
	fs.writeFileSync(tmp, JSON.stringify({ known: [...state.known], flagged: state.flagged }));
	fs.renameSync(tmp, NEW_FILE);
}

/** Tandai id yang baru muncul; buang yang kedaluwarsa / sudah tak ada. */
function recordNewModels(models) {
	try {
		const state = loadNewState();
		const cur = models.map((m) => m.id);
		if (state.known === null) {
			// Jalan pertama: anggap semua yang ada sekarang "sudah dikenal"
			// supaya 29rb model tidak sekaligus diberi badge NEW.
			state.known = new Set(cur);
			saveNewState(state);
			return;
		}
		const now = Date.now();
		const curSet = new Set(cur);
		for (const id of cur) {
			if (!state.known.has(id)) {
				state.flagged[id] = now;
				state.known.add(id);
			}
		}
		for (const [id, ts] of Object.entries(state.flagged)) {
			if (now - ts > NEW_TTL_MS || !curSet.has(id)) delete state.flagged[id];
		}
		saveNewState(state);
	} catch (err) {
		console.error("[new-models] gagal mencatat:", err.message);
	}
}

app.get("/api/new-models", (_req, res) => {
	try {
		const state = loadNewState();
		const now = Date.now();
		const out = {};
		for (const [id, ts] of Object.entries(state.flagged || {})) {
			if (now - ts <= NEW_TTL_MS) out[id] = ts;
		}
		res.json({ new: out });
	} catch (err) {
		res.status(500).json({ error: err.message });
	}
});

app.post("/api/new-models/dismiss", (req, res) => {
	try {
		const body = req.body || {};
		const ids = Array.isArray(body.ids) ? body.ids : body.id ? [body.id] : [];
		const state = loadNewState();
		let changed = false;
		for (const id of ids) {
			const base = String(id).split("#")[0];
			for (const k of Object.keys(state.flagged || {})) {
				if (k === id || k.split("#")[0] === base) {
					delete state.flagged[k];
					changed = true;
				}
			}
		}
		if (changed) saveNewState(state);
		res.json({ ok: true, removed: changed });
	} catch (err) {
		res.status(500).json({ error: err.message });
	}
});

// --- API ---
/* Respons /api/models berbobot 27 MB untuk 38.515 model (terukur). Baik
 * JSON.stringify (88 ms) maupun gzip (411 ms CPU) mahal kalau diulang tiap
 * request, jadi keduanya dihitung SEKALI per signature dan hasilnya
 * disimpan di memori. ETag-nya ikut dihitung sekali, sehingga muat-ulang
 * yang tidak berubah dijawab 304 tanpa menyentuh body sama sekali. */
const gzipAsync = promisify(zlib.gzip);
let modelsPayload = { key: "", body: null, gzPromise: null, etag: "" };

function buildModelsPayload(models) {
	const key = `${cache.signature}:${models.length}`;
	if (modelsPayload.key === key && modelsPayload.body) return modelsPayload;
	const body = JSON.stringify({ models });
	modelsPayload = {
		key,
		body,
		gzPromise: null,
		etag: `W/"${body.length.toString(36)}-${crypto.createHash("sha1").update(body).digest("base64url").slice(0, 27)}"`,
	};
	return modelsPayload;
}

app.get("/api/models", (req, res) => {
	try {
		const models = getModels({ force: req.query.refresh === "1" });

		// Filter per game. README sudah lama menjanjikan ?game=, tapi
		// query-nya dilempar dan 38.515 model selalu dikirim utuh.
		const game = typeof req.query.game === "string" ? req.query.game.trim() : "";
		if (game) {
			const sub = models.filter((m) => m.game === game || m.gameLabel === game);
			return res.json({ models: sub, game, total: models.length });
		}

		const payload = buildModelsPayload(models);
		res.setHeader("ETag", payload.etag);
		res.setHeader("Cache-Control", "no-cache");
		if (req.headers["if-none-match"] === payload.etag) return res.status(304).end();

		const wantsGzip = /\bgzip\b/i.test(String(req.headers["accept-encoding"] || ""));
		if (!wantsGzip) {
			res.type("application/json");
			return res.send(payload.body);
		}
		if (!payload.gzPromise) payload.gzPromise = gzipAsync(payload.body, { level: 6 });
		payload.gzPromise.then(
			(gz) => {
				// Content-Encoding sudah diisi manual sehingga middleware
				// compression melewati respons ini — gzip-nya memang hasil cache.
				res.setHeader("Content-Encoding", "gzip");
				res.setHeader("Vary", "Accept-Encoding");
				res.type("application/json");
				res.send(gz);
			},
			(err) => {
				// Kompresi gagal bukan alasan mematahkan halaman.
				console.error("[api] gagal mengompres /api/models:", err.message);
				res.type("application/json");
				res.send(payload.body);
			},
		);
	} catch (err) {
		console.error("[api] gagal menyusun /api/models:", err);
		res.status(500).json({ error: "Gagal memindai folder aset." });
	}
});

/* --- favorites ------------------------------------------------------- *
 * Optional server-side mirror of the browser's starred-model list, so the
 * same favourites follow the user across browsers/machines. localStorage
 * stays the source of truth — this is best-effort and never blocks the UI. */
const FAV_FILE = path.join(DATA, "favorites.json");

app.get("/api/favorites", (_req, res) => {
	try {
		const raw = JSON.parse(fs.readFileSync(FAV_FILE, "utf8"));
		res.json({ favorites: Array.isArray(raw.favorites) ? raw.favorites : [] });
	} catch {
		res.json({ favorites: [] });
	}
});

app.put("/api/favorites", express.json({ limit: "1mb" }), (req, res) => {
	const list = req.body && Array.isArray(req.body.favorites) ? req.body.favorites : null;
	if (!list) return res.status(400).json({ error: "Daftar favorit tidak valid." });
	// Cap it: this is a convenience store, not a database.
	const clean = [...new Set(list.filter((x) => typeof x === "string"))].slice(0, 5000);
	try {
		fs.writeFileSync(FAV_FILE, JSON.stringify({ favorites: clean }, null, 2));
		res.json({ ok: true, count: clean.length });
	} catch (err) {
		res.status(500).json({ error: "Gagal menyimpan favorit: " + err.message });
	}
});

// --- thumbnails ----------------------------------------------------------
/* Built offline by tools/fetch-thumbs.js. The manifest maps model id -> file
 * name; it's read once and cached because it only changes when the fetcher
 * runs again. Missing entries simply render the initial-letter fallback. */
let thumbCache = { map: null, mtime: 0 };

function thumbManifest() {
	// Merge every per-game manifest in public/thumbs/<game>/_manifest.json.
	// Keys are already fully-qualified model ids, so a flat merge is safe and
	// adding a new game needs no code change here.
	const combined = {};
	let newest = 0;
	try {
		for (const game of fs.readdirSync(THUMBS)) {
			const file = path.join(THUMBS, game, "_manifest.json");
			let st;
			try {
				st = fs.statSync(file);
			} catch {
				continue; // game dir without a manifest
			}
			if (thumbCache.map && thumbCache.mtime === st.mtimeMs) {
				Object.assign(combined, thumbCache.map);
				continue;
			}
			try {
				const raw = JSON.parse(fs.readFileSync(file, "utf8"));
				for (const [k, v] of Object.entries(raw)) {
					// Older manifests (Nikke) store a bare filename; newer ones
					// may already be game-prefixed. Normalise to "<game>/<file>"
					// so /thumbs/ can serve either without duplication.
					const rel = typeof v === "string" && v.startsWith(game + "/")
						? v
						: `${game}/${v}`;
					combined[k] = rel;
				}
				newest = Math.max(newest, st.mtimeMs);
			} catch {
				/* unreadable manifest — skip it */
			}
		}
	} catch {
		return {};
	}
	if (newest) thumbCache = { map: combined, mtime: newest };
	return combined;
}

/** Keys of the game icons that actually exist, so the UI never fires a 404. */
function gameIconMap() {
	const dir = path.join(THUMBS, "_game");
	try {
		return fs
			.readdirSync(dir)
			.filter((f) => /\.png$/i.test(f))
			.reduce((acc, f) => {
				acc[f.replace(/\.png$/i, "")] = `/thumbs/_game/${encodeURIComponent(f)}`;
				return acc;
			}, {});
	} catch {
		return {};
	}
}

app.get("/api/game-icons", (req, res) => {
	res.json({ icons: gameIconMap() });
});

/**
 * Character names for Nikke, merged from three sources. Order matters —
 * the first hit wins the NAME:
 *
 * 1. data/nikke-l2d-nkas.json — nkas-l2d.pages.dev/characters.json, 549 entries
 *    keyed "c010_01" (note: the base character is "c010_00", not "c010").
 *    Chosen as authoritative by the user: it's far more complete and its
 *    variant numbering is correct (see the conflict note below).
 * 2. data/nikke-l2d-names.json — l2d.json from the asset repo, keyed by folder
 *    name (c010, c010_01). Covers 257 roots source 1 misses.
 * 3. data/nikke-characters.json — nkas.pages.dev, keyed by THUMBNAIL slug
 *    (si_c010_00_s). Name used only as a last resort; mainly supplies
 *    squad / rarity / class / element metadata.
 *
 * CONFLICT: sources 1 and 2 disagree on 65 entries because they number costume
 * variants differently — e.g. c010_02 is "Rapi White Promise" in l2d.json but
 * "Rapi - Classic Vacation" in nkas-l2d (which puts White Promise on c010_01).
 * They are off by one, so one of them is simply wrong; we follow the user's
 * call and trust nkas-l2d.
 */
let charCache = { data: null, mtime: 0 };

/** Model id -> the thumbnail slug it would use (mirrors tools/fetch-thumbs.js). */
function thumbSlugForId(id) {
	const leaf = id.split("/").pop();
	const m = /^(.*?)_(\d{1,2})$/.exec(leaf);
	if (m) return `si_${m[1]}_${String(parseInt(m[2], 10)).padStart(2, "0")}_s`;
	return `si_${leaf}_00_s`;
}

/**
 * nkas-l2d keys the base character as "c010_00" while our folder is "c010".
 * Anything already carrying a _NN suffix is used as-is.
 */
function nkasL2dKey(leaf) {
	return /_(\d{1,2})$/.test(leaf) ? leaf : `${leaf}_00`;
}

function readJson(file) {
	try {
		return { raw: JSON.parse(fs.readFileSync(file, "utf8")), mtime: fs.statSync(file).mtimeMs };
	} catch {
		return { raw: null, mtime: 0 };
	}
}

function loadCharacterData() {
	const a = readJson(path.join(DATA, "nikke-l2d-nkas.json")); // source 1
	const b = readJson(path.join(DATA, "nikke-l2d-names.json")); // source 2
	const c = readJson(path.join(DATA, "nikke-characters.json")); // source 3
	// Cache on the newest mtime — any file changing invalidates the merge.
	const mtime = Math.max(a.mtime, b.mtime, c.mtime);
	if (charCache.data && charCache.mtime === mtime) return charCache.data;

	// "c010_01" -> "Rapi - White Promise"  (base character is "c010_00")
	const byNkasL2d = new Map();
	if (a.raw && !Array.isArray(a.raw)) for (const [k, v] of Object.entries(a.raw)) {
		if (typeof v === "string" && v.trim()) byNkasL2d.set(k, v.trim());
	}

	// "c010_01" -> "Rapi White Promise" (folder name key)
	const byFolder = new Map();
	for (const e of b.raw || []) if (e && e.id && e.name) byFolder.set(e.id, e.name);

	// "si_c010_00_s" -> full character record (metadata)
	const bySlug = new Map();
	for (const x of c.raw || []) if (x && x.img) bySlug.set(x.img, x);

	charCache = { data: { byNkasL2d, byFolder, bySlug }, mtime };
	return charCache.data;
}

/* Azur Lane ship + skin names, from data.nagami.moe/spine/index.json.
 * Keyed by the asset name, which is exactly the folder under azurlane/. */
let azCache = { map: null, mtime: 0 };

function loadAzurLaneNames() {
	const file = path.join(DATA, "azurlane-names.json");
	try {
		const st = fs.statSync(file);
		if (azCache.map && azCache.mtime === st.mtimeMs) return azCache.map;
		const raw = JSON.parse(fs.readFileSync(file, "utf8"));
		azCache = { map: raw, mtime: st.mtimeMs };
		return raw;
	} catch {
		return {};
	}
}

/* Brown Dust 2 character + costume names, from
 * github.com/myssal/Brown-Dust-2-Asset — CharInfo(Dropped).json.
 * Keyed by the spine/cutscene asset name, which is exactly the model folder
 * under bd2-char/ and bd2-cutscenes/ (e.g. "char000101").
 * NOTE: the upstream JSON is malformed (a missing comma after some
 * "censored_spine" values), so it was repaired at conversion time — the
 * on-disk file here is clean JSON. */
let bd2Cache = { map: null, mtime: 0 };

function loadBd2Names() {
	const file = path.join(DATA, "bd2-names.json");
	try {
		const st = fs.statSync(file);
		if (bd2Cache.map && bd2Cache.mtime === st.mtimeMs) return bd2Cache.map;
		const raw = JSON.parse(fs.readFileSync(file, "utf8"));
		bd2Cache = { map: raw, mtime: st.mtimeMs };
		return raw;
	} catch {
		return {};
	}
}

/* Cat Shinobi character names, from the game's OWN Unity Localization string
 * tables (tools/catshinobi-names.py). Keyed by the full model id
 * ("catshinobi/Char_10001") because the folder ids only partially overlap the
 * character table — the script decides which matches are trustworthy and
 * leaves the rest out rather than guessing.
 *
 * Only ~60% of folders get a name. The unnamed ones keep their folder name,
 * which is still shown and searchable in the UI.
 *
 * NOTE: there is no fansite dump for this game, so this file is the only
 * source of real names. Run the extraction script to regenerate it. */
let csCache = { map: null, mtime: 0 };

function loadCatShinobiNames() {
	const file = path.join(DATA, "catshinobi-names.json");
	try {
		const st = fs.statSync(file);
		if (csCache.map && csCache.mtime === st.mtimeMs) return csCache.map;
		const raw = JSON.parse(fs.readFileSync(file, "utf8"));
		csCache = { map: raw, mtime: st.mtimeMs };
		return raw;
	} catch {
		return {};
	}
}

/**
 * Resolve a model id to its BD2 asset key.
 *
 * After the 2026-09-02 relayout the folders no longer carry the asset name:
 *
 *   bd2/char/char000101            -> "char000101"
 *   bd2/char/char000101/cutscene   -> "char000101"   (not "cutscene")
 *   bd2/char/char000502/censored   -> "char000502_c" (not "censored")
 *
 * so the nested variant folders have to be folded back onto their parent.
 * Some ids also carry a "#<stem>" suffix (several models sharing one folder).
 */
function bd2AssetKey(modelId, skeletonFile) {
	// After the per-character relayout the folders are named after the
	// CHARACTER and COSTUME ("Justia/Blood_Glutton/Skill-Cutscene"), not
	// after the asset, so the folder name no longer resolves against
	// bd2-names.json. The skeleton's own filename still carries the real
	// asset id ("cutscene_char000203.skel"), so prefer it when present.
	if (skeletonFile) {
		const stem = skeletonFile.replace(/\.(skel|json)$/i, "");
		if (stem) return stem;
	}
	const parts = modelId.split("/").map((p) => p.split("#")[0]);
	const leaf = parts[parts.length - 1];
	if (leaf === "cutscene") return parts[parts.length - 2] || leaf;
	if (leaf === "censored") return `${parts[parts.length - 2]}_c`;
	return leaf;
}

/** Attach name + metadata to every model we can identify. */
function attachCharacters(models) {
	const { byNkasL2d, byFolder, bySlug } = loadCharacterData();
	let hits = 0;
	if (byNkasL2d.size || byFolder.size || bySlug.size) {
		for (const m of models) {
			if ((m.game || "") !== "nikke") continue;
		// variants inherit their root character's identity
		const root = (m.family && m.family.root) || m.id;
		const leaf = root.split("/").pop();
		// first hit wins: nkas-l2d > l2d.json > nkas (name only)
		const fromNkasL2d = byNkasL2d.get(nkasL2dKey(leaf));
		const fromFolder = byFolder.get(leaf);
		const fromSlug = bySlug.get(thumbSlugForId(root));
		const name = fromNkasL2d || fromFolder || fromSlug?.name;
		if (!name) continue;

		m.character = {
			name,
			source: fromNkasL2d ? "nkas-l2d" : fromFolder ? "l2d" : "nkas",
			// metadata only exists in source 3
			squad: fromSlug?.squad || null,
			rarity: fromSlug?.rarity || null,
			class: fromSlug?.class || null,
			element: fromSlug?.element || null,
			manufacturer: fromSlug?.manufacturer || null,
			url: fromSlug?.url || null,
		};
		// `name` is what the HUD/delete dialog show — make it the real name,
		// keeping the id visible in parentheses so c010 is still findable.
		m.name = `${name} (${leaf})`;
		hits++;
		}
	}

	// --- Azur Lane: real ship + skin names -------------------------------
	// data.nagami.moe/spine/index.json keys by the asset name, which is the
	// folder under azurlane/. Models whose id carries a "#<stem>" suffix
	// (several models sharing one folder) resolve back to that folder name.
	const az = loadAzurLaneNames();
	let azHits = 0;
	for (const m of models) {
		if ((m.game || "") !== "azurlane") continue;
		const leaf = m.id.split("/").pop().split("#")[0];
		const rec = az[leaf];
		if (!rec) continue;
		const ship = (rec.shipName || "").trim();
		const skin = (rec.skinName || "").trim();
		if (!ship && !skin) continue;

		m.character = {
			name: ship || skin,
			source: "nagami-moe",
			skin: skin || null,
			skinId: rec.id || null,
			type: rec.type || null,
			squad: null,
			rarity: null,
			class: null,
			element: null,
			manufacturer: null,
			url: null,
		};
		// HUD/delete dialog show `name`; keep the folder id in parentheses so
		// it stays searchable, and append the skin for multi-skin characters.
		m.name = skin && ship ? `${ship} — ${skin} (${leaf})` : `${ship || skin} (${leaf})`;
		azHits++;
	}

	if (azHits) console.log(`  azur lane : ${azHits} model diberi nama kapal`);

	// --- Azur Lane Live2D: nama kapal (pinyin -> Tionghoa) + varian -------
	// Folder = pinyin + "_<variant>" (+ "_hx" utk versi HQ/"harmoni").
	// Nama asli dari data/azurlane-l2d-names.json (MrKLLM ship_name_map.py).
	{
		const azl = (() => {
			try {
				return JSON.parse(fs.readFileSync(path.join(DATA, "azurlane-l2d-names.json"), "utf8"));
			} catch {
				return {};
			}
		})();
		let azlHits = 0;
		for (const m of models) {
			if ((m.game || "") !== "azurlane-l2d") continue;
			const leaf = m.id.split("/").pop().split("#")[0];
			const rec = azl[leaf];
			if (!rec) continue;
			const ship = (rec.ship || "").trim();
			const variant = rec.variantName || (rec.variant ? `varian ${rec.variant}` : "");
			const hx = rec.hx ? "HQ" : "";
			const extra = [variant, hx].filter(Boolean).join(" · ");
			m.character = { name: ship || rec.pinyin, source: "ship-name-map", skin: extra || null };
			m.name = extra ? `${ship} — ${extra} (${leaf})` : `${ship || leaf} (${leaf})`;
			azlHits++;
		}
		if (azlHits) console.log(`  azur-l2d  : ${azlHits} model diberi nama kapal`);
	}

	// --- イヴンタイト (IV-N-Tight): nama asli Jepang ------------------------
	// Folder sengaja dibuat ASCII (mis. "1004_78c6e6") karena id model di-slug
	// server (CJK -> "-"); nama tampilan aslinya disimpan di
	// data/ivntight-names.json hasil tools/update-ivntight.py.
	{
		const ivn = (() => {
			try {
				return JSON.parse(fs.readFileSync(path.join(DATA, "ivntight-names.json"), "utf8"));
			} catch {
				return {};
			}
		})();
		let ivnHits = 0;
		for (const m of models) {
			if ((m.game || "") !== "ivntight") continue;
			const leaf = m.id.split("/").pop().split("#")[0];
			const rec = ivn[leaf];
			if (!rec) continue;
			m.name = rec;
			ivnHits++;
		}
		if (ivnHits) console.log(`  ivntight  : ${ivnHits} model diberi nama Jepang`);
	}

	// --- Girl Wars (少女ウォーズ): nama karakter + kostum -------------------
	// Folder = id numerik; nama asli disimpan di data/girlwars-names.json
	// hasil tools/update-girlwars.py. Berlaku utk Spine (girlwars/) maupun
	// Live2D (girlwars-l2d/), id-nya sama.
	{
		const gw = (() => {
			try {
				return JSON.parse(fs.readFileSync(path.join(DATA, "girlwars-names.json"), "utf8"));
			} catch {
				return {};
			}
		})();
		let gwHits = 0;
		for (const m of models) {
			if (m.game !== "girlwars" && m.game !== "girlwars-l2d") continue;
			const leaf = m.id.split("/")[1].split("#")[0];
			const rec = gw[leaf];
			if (!rec) continue;
			m.character = { name: rec.name || leaf, skin: rec.costume || null, source: "gw-l2d-viewer" };
			m.name = rec.display || rec.name || leaf;
			gwHits++;
		}
		if (gwHits) console.log(`  girl wars : ${gwHits} model diberi nama karakter`);
	}

	// --- Brown Dust 2: character + costume names ------------------------
	// Keyed by asset name (char000101). Cutscene models reuse the same key
	// with a "cutscene_" prefix, which the data file also indexes.
	const bd2 = loadBd2Names();
	let bd2Hits = 0;
	for (const m of models) {
		if ((m.game || "") !== "bd2") continue;
		const leaf = bd2AssetKey(m.id, m.skeletonFile);
		const rec = bd2[leaf];
		if (!rec) continue;
		const char = (rec.char || "").trim();
		const costume = (rec.costume || "").trim();
		if (!char && !costume) continue;

		m.character = {
			name: char || costume,
			source: "bd2-charinfo",
			costume: costume || null,
			costumeId: rec.costumeId || null,
			rarity: rec.rarity ?? null,
			squad: null,
			class: null,
			element: null,
			manufacturer: null,
			url: null,
		};
		// HUD/delete dialog show `name`; keep the real asset id in parentheses
		// so it stays searchable, and append the costume name.
		//
		// The id in parentheses must come from the MODEL PATH, not the lookup
		// key: after the relayout bd2AssetKey folds cutscene/censored onto the
		// parent, and NPC folders (npc000001) resolve through a char* key, so
		// rebuilding it from costumeId printed nonsense like
		// "Roche (Npc) (char000001)" for a model whose folder is npc000001.
		// Fall back to the model's own folder name.
		// The per-character relayout already names every folder after the
		// character and costume ("Anastasia/Fire_Graffiti"), so the generated
		// name would just repeat the path -- "Anastasia — Fire Graffiti
		// (Fire_Graffiti)". Keep the readable path for that tree and only
		// substitute real names on the original id-based layout.
		// A variant folder (Skill-Cutscene) has no asset name of its own, so
		// show the character name it resolved to instead of its folder.
		const inCharTree = m.id.startsWith("bd2-char/");
		if (inCharTree) {
			const segs = m.id.split("/").map((p) => p.split("#")[0]);
			const leaf = segs[segs.length - 1];
			const isVariant = leaf.startsWith("Skill-") || leaf.startsWith("Light-")
				|| leaf === "Interaction" || leaf === "NPC" || leaf === "Tersensor";
			const pretty = (s) => s.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
			m.name = isVariant
				? `${char} — ${costume ? costume + " · " : ""}${pretty(leaf)}`
				: segs.slice(1).map(pretty).join(" › ");
		} else {
			// A variant folder (cutscene/, censored/) has no asset name of its
			// own, so use the parent folder plus the variant name —
			// "char000101/cutscene" -> "cutscene_char000101".
			const parts = m.id.split("/").map((p) => p.split("#")[0]);
			const suffix = parts[parts.length - 1];
			const shown =
				suffix === "cutscene"
					? `cutscene_${parts[parts.length - 2]}`
					: suffix === "censored"
						? `${parts[parts.length - 2]}_c`
						: suffix;
			m.name = costume && char ? `${char} — ${costume} (${shown})` : `${char || costume} (${shown})`;
		}
		bd2Hits++;
	}

	// --- BD2 JP voices --------------------------------------------------
	// Attached here (not in scanModels) because the audio tree lives outside
	// assets/ and is only meaningful once the model's game is known.
	let audioHits = 0;
	for (const m of models) {
		const a = audioForModel(m);
		if (!a) continue;
		m.audio = a;
		audioHits++;
	}

	// --- Cat Shinobi: character names ----------------------------------
	// Keyed by full model id, because the folder ids only partially overlap
	// the character table. Unnamed folders keep their folder name (still
	// shown and searchable in the UI) rather than a guessed one.
	const csData = loadCatShinobiNames();
	const cs = csData.models || {};
	let csHits = 0;
	for (const m of models) {
		if ((m.game || "") !== "catshinobi") continue;
		const rec = cs[m.id];
		if (!rec) continue;
		const name = (rec.name || "").trim();
		const costume = (rec.costume || "").trim();
		if (!name && !costume) continue;

		m.character = {
			name: name || costume,
			source: "catshinobi-localization",
			costume: costume || null,
			ja: rec.ja || null,
			match: rec.match || null,
			squad: null,
			rarity: null,
			class: null,
			element: null,
			manufacturer: null,
			url: null,
		};
		// HUD/delete dialog show `name`; keep the folder id in parentheses so
		// it stays searchable, and append the costume when there is one.
		const leaf = m.id.split("/").pop().split("#")[0];
		m.name = costume && name ? `${name} — ${costume} (${leaf})` : `${name || costume} (${leaf})`;
		csHits++;
	}
	if (csHits) console.log(`  cat shinobi: ${csHits} model diberi nama karakter`);

	const total = hits + azHits + bd2Hits + csHits;
	if (total) console.log(`  karakter  : ${total} model diberi nama`);
	if (audioHits) console.log(`  bd2 audio : ${audioHits} model punya suara JP`);
	if (bd2Hits) console.log(`  brown dust: ${bd2Hits} model diberi nama kostum`);
	return models;
}

/* --- Brown Dust 2 media: JP voice lines + character icons ---------------
 * Fetched from Jelosus2/BD2-L2D-Viewer by tools/fetch-bd2-media.py into
 * /srv/spine-assets/bd2-media. KR voices are deliberately NOT downloaded —
 * the user asked for JP only.
 *
 *   audio/<costumeId>/<n>.webm   3 BattleReady variants per costume
 *   icons/<assetKey>.png         128x128
 *
 * A costume id is the 6-digit id inside the asset name (char000101 -> 000101);
 * variant folders (cutscene/, censored/) inherit their parent's id, so the
 * character and its variants share one voice set.
 */
const MEDIA = process.env.BD2_MEDIA || "/srv/spine-assets/bd2-media";
const AUDIO_DIR = path.join(MEDIA, "audio");

let bd2AudioCache = { map: null, mtime: 0 };

function loadBd2Audio() {
	// The directory layout IS the manifest: each subdirectory is a costume id.
	try {
		const st = fs.statSync(AUDIO_DIR);
		if (bd2AudioCache.map && bd2AudioCache.mtime === st.mtimeMs) return bd2AudioCache.map;
		const map = {};
		for (const d of fs.readdirSync(AUDIO_DIR, { withFileTypes: true })) {
			if (!d.isDirectory()) continue;
			const files = fs
				.readdirSync(path.join(AUDIO_DIR, d.name))
				.filter((f) => /^\d+\.webm$/i.test(f))
				.sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
			if (files.length) map[d.name] = files;
		}
		bd2AudioCache = { map, mtime: st.mtimeMs };
		return map;
	} catch {
		return {};
	}
}

/** Voice tracks available for one model, or null. */
function audioForModel(m) {
	if ((m.game || "") !== "bd2") return null;
	const parts = m.id.split("/").map((p) => p.split("#")[0]);
	const leaf = parts[parts.length - 1];
	// cutscene/ and censored/ reuse their parent's voice set.
	const base = leaf === "cutscene" || leaf === "censored" ? parts[parts.length - 2] : leaf;
	const mm = /(\d{6})/.exec(base || "");
	if (!mm) return null;
	const files = loadBd2Audio()[mm[1]];
	if (!files?.length) return null;
	return { costumeId: mm[1], lang: "JP", tracks: files.map((f) => `/bd2-audio/${mm[1]}/${f}`) };
}

/*
 * OrisRies audio.
 *
 * Unlike BD2 there is no per-costume folder: the game ships a flat set of
 * BGM (bgm001..bgm042) and SFX (se-prefixed) tracks, extracted from the
 * AudioClip objects inside the bgm and se bundles by
 * tools/extract-orisries-audio.py. They are FSB5 (FMOD) containers holding
 * Vorbis, rebuilt to .ogg there — ffmpeg cannot read FSB5.
 *
 * Nothing in the asset names ties a track to a specific model, so the
 * viewer exposes them as a game-level soundtrack instead of per-model
 * voices: /api/orisries-audio lists everything, grouped by kind.
 */
// Bisa dialihkan seperti BD2_MEDIA; path default mengikuti konvensi
// /srv/spine-assets yang dipakai tools/ ekstraksi di repo ini.
const OR_AUDIO_DIR = process.env.OR_AUDIO_DIR || "/srv/spine-assets/orisries/audio";

let orAudioCache = { list: null, mtime: 0 };

function loadOrisriesAudio() {
	try {
		const st = fs.statSync(OR_AUDIO_DIR);
		if (orAudioCache.list && orAudioCache.mtime === st.mtimeMs) return orAudioCache.list;
		const list = [];
		for (const f of fs.readdirSync(OR_AUDIO_DIR)) {
			if (!/\.(ogg|mp3|wav)$/i.test(f)) continue;
			list.push({ file: f, kind: /^bgm/i.test(f) ? "bgm" : "sfx" });
		}
		list.sort((a, b) => a.file.localeCompare(b.file, "en", { numeric: true }));
		orAudioCache = { list, mtime: st.mtimeMs };
		return list;
	} catch {
		return [];
	}
}

app.get("/api/orisries-audio", (_req, res) => {
	const all = loadOrisriesAudio();
	res.json({
		tracks: all.map((t) => ({ ...t, url: `/orisries-audio/${t.file}` })),
		bgm: all.filter((t) => t.kind === "bgm").map((t) => `/orisries-audio/${t.file}`),
		sfx: all.filter((t) => t.kind === "sfx").map((t) => `/orisries-audio/${t.file}`),
	});
});

app.get("/api/bd2-audio", (req, res) => {
	// Not per-model: the client already knows the model, but a single call lets
	// it grey the button out for models with no voices.
	const id = String(req.query.id || "");
	if (!id) return res.json({ tracks: [] });
	const m = getModels().find((x) => x.id === id);
	// Id yang sudah tidak ada (model dihapus atau diganti nama) dulunya
	// membuat audioForModel melempar TypeError -> 500 + tumpukan di journal.
	if (!m) return res.json({ tracks: [] });
	res.json(audioForModel(m) || { tracks: [] });
});

/*
 * Asset updater.
 *
 * Ark Re:Code is the only game wired up so far: it is unencrypted, its
 * router tells us the live catalog, and the bundles are public. The work
 * is done by tools/update-arkrecode.py — spawned here so the scan/catalog
 * state lives in one place and the UI just shows the result.
 *
 * Only --check runs synchronously (a few seconds: fetch catalog, diff).
 * Downloads run in the background and are polled through the same
 * job handle as /api/update/arkrecode/status.
 */
const UPDATERS = {
	arkrecode: {
		script: path.join(ROOT, "tools", "update-arkrecode.py"),
		py: "/srv/venv-spine/bin/python",
	},
	shoujoukaisen: {
		script: path.join(ROOT, "tools", "update-shoujoukaisen.py"),
		py: "/srv/venv-spine/bin/python",
	},
	"mitao-utopia": {
		script: path.join(ROOT, "tools", "update-mitao.py"),
		py: "/srv/venv-spine/bin/python",
	},
	crosscore: {
		script: path.join(ROOT, "tools", "update-crosscore.py"),
		py: "/srv/venv-spine/bin/python",
	},
	catshinobi: {
		script: path.join(ROOT, "tools", "update-catshinobi.py"),
		py: "/srv/venv-spine/bin/python",
	},
	bd2: {
		script: path.join(ROOT, "tools", "update-browndust.py"),
		py: "/srv/venv-spine/bin/python",
	},
	azurlane: {
		script: path.join(ROOT, "tools", "update-azurlane.py"),
		py: "/srv/venv-spine/bin/python",
	},
	nikke: {
		script: path.join(ROOT, "tools", "update-nikke.py"),
		py: "/srv/venv-spine/bin/python",
	},
	// 贤者同盟 / Alliance Sages: CDN hot-update terbuka
	// (euwv.0577ai.com/ob/update/android). --check cukup baca `filelist`;
	// --apply unduh hanya bundle spine yang ukurannya berubah.
	// Lihat tools/update-alliancesages.py.
	alliancesages: {
		script: path.join(ROOT, "tools", "update-alliancesages.py"),
		py: "/srv/venv-spine/bin/python",
	},
	// 禁果便利店 (mcs18): Addressables terbuka, bundle karakter spine.
	mcs18: {
		script: path.join(ROOT, "tools", "update-mcs18.py"),
		py: "/srv/venv-spine/bin/python",
	},
	ivntight: {
		script: path.join(ROOT, "tools", "update-ivntight.py"),
		py: "/srv/venv-spine/bin/python",
	},
	girlwars: {
		script: path.join(ROOT, "tools", "update-girlwars.py"),
		py: "/srv/venv-spine/bin/python",
	},
	// Lost Sword video extractor: rows videos out of UnityDataAssetPack.
	lostsword: {
		script: path.join(ROOT, "tools", "update-lostsword.py"),
		py: "/srv/venv-spine/bin/python",
	},
	"lostsword-video": {
		script: path.join(ROOT, "tools", "extract-lostsword-video.py"),
		py: "/srv/venv-spine/bin/python",
		// The extractor has no --check; the button runs it directly.
		noCheck: true,
	},
	dragontravelers: {
		script: path.join(ROOT, "tools", "extract-dragontravelers.py"),
		py: "/srv/venv-spine/bin/python",
		// Pulls the game's res_update tree + APK split from redroid, then
		// re-extracts. No --check either; the button runs --pull directly.
		noCheck: true,
		applyArgs: ["--pull"],
	},
	// Chaos Zero Nightmare: the source is the community model library
	// BenNoSleep/czn-animation-viewer, not a game CDN. --check = git fetch +
	// diff index.json; --apply = git pull, convert the new rigs, copy new
	// cut-ins + thumbnails. One updater serves both czn-rigs and czn-cutins-cg.
	// See tools/update-czn.py.
	"czn-rigs": {
		script: path.join(ROOT, "tools", "update-czn.py"),
		py: "/srv/venv-spine/bin/python",
	},
	"czn-cutins-cg": {
		script: path.join(ROOT, "tools", "update-czn.py"),
		py: "/srv/venv-spine/bin/python",
	},
	// Make Drama: source is the community MAD-Viewer catalogue repo; --check
	// diffs skin keys, --apply pulls and extracts the new skins. See update-mad.py.
	"mad-drama": {
		script: path.join(ROOT, "tools", "update-mad.py"),
		py: "/srv/venv-spine/bin/python",
	},
	// Epic Seven — satu pembaru untuk EMPAT sumber e7codex (lobby, combat,
	// skill, wallpaper) plus katalog nama + thumbnail, karena semuanya harus
	// tetap sinkron. --check membandingkan katalog daring dengan isi disk,
	// --apply mengunduh yang belum ada. Lihat tools/update-epic7.py.
	epic7: {
		script: path.join(ROOT, "tools", "update-epic7.py"),
		py: "/srv/venv-spine/bin/python",
	},
};

let updateJob = null; // { game, running, result, log, startedAt }
const UPDATE_LOG_MAX = 400; // baris yang disimpan per job
// stdout pembaru ditahan utuh lalu di-JSON.parse; pembaru yang nyangkut dan
// terus menulis akan menggembungkan heap tanpa batas.
const UPDATE_STDOUT_MAX = 4 * 1024 * 1024;
const UPDATE_TIMEOUT_MS = Number(process.env.UPDATE_TIMEOUT_MS) || 30 * 60 * 1000;

function runUpdater(game, args, onLog) {
	const cfg = UPDATERS[game];
	if (!cfg) return null;
	return new Promise((resolve) => {
		// A missing interpreter or script emits an 'error' event on the child.
		// Without a listener Node treats it as unhandled and kills the whole
		// process, so a single unauthenticated GET /api/update/<game> took the
		// server down (and the restart loop took it down again on every retry).
		const fail = (message) => resolve({ error: message });
		let child;
		try {
			child = spawn(cfg.py, [cfg.script, ...args], { cwd: ROOT });
		} catch (err) {
			return fail(`Tidak bisa menjalankan pembaru: ${err.message}`);
		}
		// stdout carries the final JSON result, stderr carries progress lines.
		// Stream both to `onLog`, but stop at the JSON block (the first line
		// that is just "{" / "[") so the pretty-printed result doesn't flood
		// the log.
		let stdout = "";
		let stdoutFull = false;
		let jsonStarted = false;
		const emit = (chunk, isStdout) => {
			for (const line of String(chunk).split(/\r?\n/)) {
				const t = line.trim();
				if (!t) continue;
				if (isStdout) {
					if (jsonStarted) continue;
					if (t === "{" || t === "[") {
						jsonStarted = true;
						continue;
					}
				}
				if (onLog) onLog(line);
			}
		};
		let settled = false;
		const finish = (value) => {
			if (settled) return;
			settled = true;
			resolve(value);
		};
		child.on("error", (err) => finish({ error: `Pembaru tidak bisa dijalankan: ${err.message}` }));
		// Pembaru yang tidak pernah selesai jangan menahan job selamanya.
		const timer = setTimeout(() => {
			try {
				child.kill("SIGKILL");
			} catch {
				/* sudah mati */
			}
			finish({ error: `Pembaru melebihi batas waktu ${Math.round(UPDATE_TIMEOUT_MS / 60000)} menit.` });
		}, UPDATE_TIMEOUT_MS);
		if (timer.unref) timer.unref();
		child.on("close", () => clearTimeout(timer));
		child.stdout.on("data", (d) => {
			if (!stdoutFull) {
				stdout += d;
				if (stdout.length >= UPDATE_STDOUT_MAX) {
					stdoutFull = true;
					stdout = stdout.slice(0, UPDATE_STDOUT_MAX);
				}
			}
			emit(d, true);
		});
		child.stderr.on("data", (d) => emit(d, false));
		child.on("close", () => {
			const start = stdout.indexOf("{");
			if (start === -1) return finish({ error: "Pembaru tidak mengembalikan JSON.", raw: stdout.slice(-800) });
			try {
				finish(JSON.parse(stdout.slice(start)));
			} catch {
				finish({ error: "Gagal membaca hasil pembaruan.", raw: stdout.slice(-800) });
			}
		});
	});
}

app.get("/api/update/:game", async (req, res) => {
	const game = req.params.game;
	const cfg = UPDATERS[game];
	if (!cfg) return res.status(404).json({ error: `Tidak ada pembaru untuk ${game}.` });
	// Extractor-only jobs (e.g. Lost Sword video) have no --check; a "check"
	// just reports what is already on disk so the button can be offered.
	if (cfg.noCheck && req.query.mode !== "apply") {
		res.json({ ok: true, extractor: true, new: 0, log: [`Pembaru ${game} hanya punya mode terapkan.`] });
		return;
	}
	const mode = req.query.mode === "apply" ? "apply" : "check";
	// A check is quick; a download is not, so it goes to the background.
	if (mode === "check") {
		const log = [];
		const result = await runUpdater(game, ["--check"], (l) => log.length < UPDATE_LOG_MAX && log.push(l));
		res.json({ ...result, log });
		return;
	}
	if (updateJob?.running) {
		res.json({ started: false, reason: "Pembaruan masih berjalan." });
		return;
	}
	updateJob = { game, running: true, result: null, log: [], startedAt: Date.now() };
	res.json({ started: true });
	updateJob.result = await runUpdater(game, cfg.applyArgs || ["--apply"], (l) => {
		updateJob.log.push(l);
		if (updateJob.log.length > UPDATE_LOG_MAX) updateJob.log.shift();
	});
	updateJob.running = false;
	updateJob.finishedAt = Date.now();
});

app.get("/api/update/:game/status", (_req, res) => {
	if (!updateJob) return res.json({ running: false, result: null, log: [] });
	res.json({
		game: updateJob.game,
		running: updateJob.running,
		result: updateJob.result,
		log: updateJob.log,
		startedAt: updateJob.startedAt,
		finishedAt: updateJob.finishedAt || null,
	});
});

app.get("/api/thumbnails", (req, res) => {
	res.json({ thumbs: thumbManifest() });
});

/**
 * Kartu skill Chaos Zero Nightmare, per karakter.
 *
 * Kartu tidak punya indeks daring, jadi daftarnya dibangun dengan memindai
 * nama berkas (tools/download-czn-cards.py) dan disimpan di
 * assets/czn-cards/index.json: { "<charid>": { name, cards: [{kind,file}] } }.
 *
 * `<charid>` adalah id numerik yang sama dengan prefiks id rig
 * (czn-rigs/1056_01) dan nama berkas thumb di _names.json ("1056.png"),
 * sehingga klien bisa menautkan model -> kartu tanpa tabel tambahan.
 */
let cznCardCache = { at: 0, data: null };

// Daftar id karakter yang punya kartu — dipakai klien untuk memetakan id
// model (portrait_1003_front, model_1003, 1056_01, ...) ke id karakter tanpa
// menebak-nebak.
app.get("/api/czn-cards", (_req, res) => {
	if (!cznCardCache.data || Date.now() - cznCardCache.at > 30000) {
		try {
			const raw = fs.readFileSync(path.join(ASSETS, "czn-cards", "index.json"), "utf8");
			cznCardCache = { at: Date.now(), data: JSON.parse(raw) };
		} catch {
			cznCardCache = { at: Date.now(), data: {} };
		}
	}
	// Hanya id + jumlah kartu; daftar berkas tetap di endpoint per karakter.
	const chars = {};
	for (const [id, rec] of Object.entries(cznCardCache.data)) {
		chars[id] = { name: rec.name || null, count: (rec.cards || []).length };
	}
	res.json({ chars });
});

app.get("/api/czn-cards/:charid", (req, res) => {
	const id = String(req.params.charid || "");
	// Hanya angka: nilainya dipakai untuk menyusun path berkas.
	if (!/^\d+$/.test(id)) return res.status(400).json({ error: "id karakter tidak valid." });
	// Cache 30 detik: berkas index hanya berubah saat script unduh dijalankan.
	if (!cznCardCache.data || Date.now() - cznCardCache.at > 30000) {
		try {
			const raw = fs.readFileSync(path.join(ASSETS, "czn-cards", "index.json"), "utf8");
			cznCardCache = { at: Date.now(), data: JSON.parse(raw) };
		} catch {
			cznCardCache = { at: Date.now(), data: {} };
		}
	}
	const rec = cznCardCache.data[id];
	if (!rec) return res.json({ charid: id, name: null, cards: [] });
	// URL disusun di server supaya klien tidak perlu tahu layout folder dan
	// setiap segmen di-encode (nama berkas memakai garis bawah, aman, tapi
	// tetap konsisten dengan endpoint lain).
	const cards = (rec.cards || []).map((c) => ({
		kind: c.kind,
		url: `/czn-cards/${id}/${encodeURIComponent(c.file)}`,
		file: c.file,
	}));
	res.json({ charid: id, name: rec.name || null, cards });
});

// --- upload: .json/.skel/.atlas/.png/.webp/... into assets/<folder>/ ---
const slug = (s) =>
	String(s)
		.normalize("NFKD")
		.replace(/[^\w.\-]+/g, "-")
		.replace(/^-+|-+$/g, "")
		.slice(0, 64) || "model";

const ALLOWED = new Set([".json", ".skel", ".atlas", ".txt", ".png", ".webp", ".jpg", ".jpeg"]);

const storage = multer.diskStorage({
	destination: async (req, file, cb) => {
		try {
			const folder = slug(req.body.folder || path.basename(file.originalname, path.extname(file.originalname)));
			// slug() mempertahankan titik, jadi slug("..") === ".." dan
			// path.join(ASSETS, "..") KELUAR dari assets/ — file bisa jatuh ke
			// root aplikasi (package.json dsb., yang berarti kode berjalan di
			// npm install berikutnya). Basename "...skel" pun menghasilkan
			// folder ".." tanpa perlu field folder sama sekali.
			const dest = path.resolve(ASSETS, folder);
			if (folder === "." || folder === ".." || !dest.startsWith(ASSETS + path.sep)) {
				return cb(new Error("Nama folder tidak valid."));
			}
			await fsp.mkdir(dest, { recursive: true });
			req.uploadFolder = folder;
			cb(null, dest);
		} catch (err) {
			cb(err);
		}
	},
	filename: (req, file, cb) => {
		const clean = slug(file.originalname);
		const ext = path.extname(clean).toLowerCase();
		if (!ALLOWED.has(ext)) return cb(new Error(`Tipe file tidak diizinkan: ${ext || "(tanpa ekstensi)"}`));
		cb(null, clean);
	},
});

const upload = multer({
	storage,
	limits: { fileSize: MAX_UPLOAD_MB * 1024 * 1024, files: 64 },
});

app.post("/api/upload", (req, res) => {
	upload.array("files", 64)(req, res, (err) => {
		if (err) {
			const msg =
				err.code === "LIMIT_FILE_SIZE"
					? `Ukuran file melebihi batas ${MAX_UPLOAD_MB} MB.`
					: err.message || "Unggahan gagal.";
			return res.status(400).json({ error: msg });
		}
		// Aset bertambah: buang memo scan supaya daftar model ikut segar
		// sekarang, bukan setelah TTL.
		invalidateScan();
		res.json({ ok: true, folder: req.uploadFolder || null });
	});
});

app.delete("/api/models/:id", async (req, res) => {
	/* Id model selalu "game/model" (variannya "game/model#varian"), dan yang
	 * dihapus adalah foldernya.
	 *
	 * Versi lama memanggil path.basename() lebih dulu, jadi "orisries/0000"
	 * berujung ke assets/0000 — direktori yang tidak pernah ada. rm -rf
	 * dengan force pada path yang tidak ada tetap dianggap berhasil, jadi
	 * tombol hapus di UI melapor sukses tanpa pernah menghapus apa pun.
	 * Sekarang id dicari di peta id->folder milik scan; kalau id itu bukan
	 * sebuah folder aset (mis. entri galeri per-file), jawabannya 404 yang
	 * jujur, bukan sukses palsu. */
	const models = getModels(); // memastikan peta id->folder sudah terisi
	const id = String(req.params.id).split("#")[0];
	if (!id || id === "." || id === ".." || /[\0-\x1f\\]/.test(id)) {
		return res.status(400).json({ error: "Nama model tidak valid." });
	}
	/* Peta id->folder berisi SETIAP folder di bawah assets/, termasuk induk
	 * sebuah game ("nikke" adalah induk ribuan model). Tanpa penjaga ini satu
	 * request bisa membuang seluruh game. Jadi id-nya harus benar-benar
	 * milik sebuah model — varian "#..." dianggap satu model yang sama. */
	if (!models.some((m) => m.id.split("#")[0] === id)) {
		return res.status(404).json({ error: "Id itu bukan sebuah model." });
	}
	const dir = modelDirs.get(id);
	if (!dir || !dir.startsWith(ASSETS + path.sep)) {
		// Id model yang bukan folder (entri galeri per-file) tidak punya
		// direktori untuk dibuang; bilang apa adanya, jangan pura-pura sukses.
		return res.status(404).json({ error: "Model ini berupa file individual, bukan sebuah folder." });
	}
	try {
		await fsp.rm(dir, { recursive: true, force: true });
		invalidateScan();
		res.json({ ok: true, removed: id });
	} catch (err) {
		console.error("[delete] gagal menghapus", dir, err);
		res.status(500).json({ error: "Gagal menghapus model." });
	}
});

/* ------------------------------------------------------------------ *
 * Live-wallpaper export
 * ------------------------------------------------------------------ *
 * The browser renders every frame deterministically (it already owns the
 * loaded skeleton and can seek the track exactly), uploads the PNG
 * sequence, and we stitch it with ffmpeg. Rendering offline instead of
 * capturing a live canvas is what makes the loop seamless — frame N-1 is
 * numerically one step from frame 0, not however long the encoder took.
 *
 * Verified against the ffmpeg on this box (8.0.1): its VP9 and VP8
 * encoders do NOT support alpha — asking for yuva420p silently produces
 * yuv420p and the transparency is gone. GIF is the only transparent
 * option here, so the alpha path is routed to GIF and the opaque path to
 * WebM. Calling that out rather than shipping a silently-broken "alpha
 * WebM" toggle.
 */
const EXPORT_TMP = path.join(DATA, "exports");
const EXPORT_DIR = path.join(ROOT, "public", "exports");
const EXPORT_MAX_MB = Number(process.env.EXPORT_MAX_MB) || 96;
const EXPORT_MAX_FRAMES = Number(process.env.EXPORT_MAX_FRAMES) || 600;

/* Batas kumulatif per job.
 *
 * Dulu EXPORT_MAX_MB dideklarasikan tapi tidak pernah dipakai, dan indeks
 * bingkai hanya dicek >= 0 — satu job dengan n=1 menerima file frame
 * sebanyak yang diinginkan (terukur: i=500 dengan n=1 tetap diterima), dan
 * rate limit 3000/menit x 24 MB berarti ~72 GB/menit bisa ditulis ke disk.
 * Direktori sisa juga tidak pernah dibersihkan: hanya /finish dan /cancel
 * yang menghapusnya, jadi ekspor yang ditinggalkan menumpuk selamanya. */
const exportJobs = new Map(); // job -> { bytes, files, count }
const EXPORT_TMP_TTL_MS = Number(process.env.EXPORT_TMP_TTL_HOURS || 2) * 60 * 60 * 1000;
// Video hasil sengaja diberi umur panjang: ini artefak yang dibuat
// pengguna, bukan sampah. Yang dibatasi cuma pertumbuhannya tanpa batas.
const EXPORT_OUT_TTL_MS = Number(process.env.EXPORT_OUT_TTL_HOURS || 168) * 60 * 60 * 1000;

const exportSweeper = setInterval(() => {
	const now = Date.now();
	const sweep = (root, ttl, rm) => {
		let names = [];
		try {
			names = fs.readdirSync(root);
		} catch {
			return;
		}
		for (const name of names) {
			if (name.startsWith(".") || (!/^[a-z0-9]{6,32}$/.test(name) && root === EXPORT_TMP)) continue;
			const target = path.join(root, name);
			try {
				if (now - fs.statSync(target).mtimeMs > ttl) rm(target);
			} catch {
				/* antre */
			}
		}
	};
	sweep(EXPORT_TMP, EXPORT_TMP_TTL_MS, (p) => {
		fs.rmSync(p, { recursive: true, force: true });
		exportJobs.delete(path.basename(p));
	});
	sweep(EXPORT_DIR, EXPORT_OUT_TTL_MS, (p) => fs.rmSync(p, { force: true }));
}, 10 * 60 * 1000);
if (exportSweeper.unref) exportSweeper.unref();

const ALLOWED_BG = new Set(["transparent", "black", "white", "#1a1620"]);

/**
 * Resolve the ffmpeg binary. `spawn("ffmpeg", …)` assumes it is on PATH, which
 * was true on the box this was built on but is NOT guaranteed — this host has
 * no system ffmpeg at all, and /api/export/capabilities silently reported
 * `false` for every format because of it. Fall back to the copy Playwright
 * downloads (it ships libvpx-vp9, libvpx, gif and libx264), and allow an
 * explicit override via FFMPEG_PATH.
 */
function ffmpegCandidates() {
	const out = [];
	const push = (c) => {
		if (c && !out.includes(c)) out.push(c);
	};
	push(process.env.FFMPEG_PATH);
	// Look for a full ffmpeg install under the usual tool dirs. Needed because
	// the PATH the systemd service runs with does not include the shell one,
	// and the "ffmpeg" that IS on disk here (ms-playwright's) is a cut-down
	// build with --disable-demuxer=image2, which cannot read "f%05d.png" at all.
	for (const base of ["/opt", "/root/.hermes/tools", "/root/.cache/ms-playwright", "/usr/local", "/usr"]) {
		try {
			for (const name of fs.readdirSync(base)) {
				for (const sub of ["bin/ffmpeg", "ffmpeg-linux", "ffmpeg"]) {
					const p = path.join(base, name, sub);
					try {
						if (fs.statSync(p).isFile()) push(p);
					} catch {
						/* not a file */
					}
				}
			}
		} catch {
			/* dir absent */
		}
	}
	for (const c of ["ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg"]) push(c);
	return out;
}

function ffmpegBin() {
	for (const c of ffmpegCandidates()) {
		try {
			const r = spawnSync(c, ["-hide_banner", "-loglevel", "error", "-version"], { encoding: "utf8" });
			if (r.status !== 0) continue;
			// /api/export/finish feeds ffmpeg a "%05d.png" sequence, which needs
			// the image2 DEMUXER. ms-playwright's ffmpeg only ships image2pipe
			// and file protocols, so it "runs" but fails every export with
			// "Error opening input" — require the demuxer the export needs.
			const cap = spawnSync(c, ["-hide_banner", "-loglevel", "error", "-h", "demuxer=image2"], { encoding: "utf8" });
			if (cap.status === 0) return c;
		} catch {
			/* not this one */
		}
	}
	return null;
}

let ffmpegBinCache;
function ffmpeg() {
	if (ffmpegBinCache === undefined) ffmpegBinCache = ffmpegBin();
	return ffmpegBinCache;
}

function ffmpegHas(encoder) {
	const bin = ffmpeg();
	if (!bin) return false;
	try {
		const r = spawnSync(bin, ["-hide_banner", "-loglevel", "error", "-h", "encoder=" + encoder], {
			encoding: "utf8",
		});
		return r.status === 0;
	} catch {
		return false;
	}
}

/** Which output formats this machine can actually produce. */
let capsCache = null;
function exportCapabilities() {
	// Tiap panggilan menjalankan spawnSync ffmpeg 2x, ~41 ms memblokir event
	// loop (terukur), dan hasilnya tidak berubah selama binarnya tidak
	// ganti. Cukup sekali.
	if (capsCache) return capsCache;
	capsCache = {
		ffmpeg: ffmpegHas("libvpx-vp9"),
		webm: ffmpegHas("libvpx-vp9"),
		gif: ffmpegHas("gif"),
	};
	return capsCache;
}

app.get("/api/export/capabilities", (req, res) => {
	res.json(exportCapabilities());
});

/** Stream one frame to the job's temp dir. Frames arrive in order.
 *  Accepts PNG (transparent exports) and JPEG (opaque exports). Frames are
 *  written with a .png/.jpg extension that ffmpeg's image2 demuxer picks up
 *  via a glob pattern. */
app.post("/api/export/frame",
	express.raw({ type: ["image/png", "image/jpeg"], limit: "24mb" }),
	async (req, res) => {
	const job = String(req.query.job || "");
	const index = Number(req.query.i);
	const count = Number(req.query.n);
	// job is a server-generated id; reject anything that isn't, so it can
	// never be used to walk the filesystem.
	if (!/^[a-z0-9]{6,32}$/.test(job)) return res.status(400).json({ error: "Id ekspor tidak valid." });
	if (!Number.isInteger(index) || index < 0) return res.status(400).json({ error: "Indeks bingkai tidak valid." });
	if (!Number.isInteger(count) || count <= 0 || count > EXPORT_MAX_FRAMES) {
		return res.status(400).json({ error: "Jumlah bingkai tidak valid." });
	}
	if (!Buffer.isBuffer(req.body) || !req.body.length) return res.status(400).json({ error: "Bingkai kosong." });

	const jobState = exportJobs.get(job) || { bytes: 0, files: 0, count };
	if (jobState.count !== count) {
		return res.status(400).json({ error: "Jumlah bingkai berubah di tengah ekspor." });
	}
	if (index >= count) return res.status(400).json({ error: "Indeks bingkai melebihi jumlah bingkai." });
	if (jobState.files >= EXPORT_MAX_FRAMES) {
		return res.status(413).json({ error: `Ekspor melebihi ${EXPORT_MAX_FRAMES} bingkai.` });
	}
	if (jobState.bytes + req.body.length > EXPORT_MAX_MB * 1024 * 1024) {
		return res.status(413).json({ error: `Ekspor melebihi batas ${EXPORT_MAX_MB} MB.` });
	}

	// Trust the magic bytes, not the client's Content-Type.
	const isJpeg = req.body[0] === 0xff && req.body[1] === 0xd8;
	const isPng = req.body[0] === 0x89 && req.body[1] === 0x50;
	if (!isJpeg && !isPng) return res.status(400).json({ error: "Format bingkai tidak dikenal." });

	const dir = path.join(EXPORT_TMP, job);
	try {
		await fsp.mkdir(dir, { recursive: true });
		const ext = isJpeg ? "jpg" : "png";
		await fsp.writeFile(path.join(dir, `f${String(index).padStart(5, "0")}.${ext}`), req.body);
		exportJobs.set(job, { bytes: jobState.bytes + req.body.length, files: jobState.files + 1, count });
		res.json({ ok: true, index, count });
	} catch (err) {
		res.status(500).json({ error: "Gagal menyimpan bingkai: " + err.message });
	}
});

/** Stitch the uploaded frames into WebM or GIF and hand back a URL. */
app.post("/api/export/finish", express.json({ limit: "1mb" }), async (req, res) => {
	const { job, format, background, fps, width, height, name } = req.body || {};
	if (!/^[a-z0-9]{6,32}$/.test(String(job || ""))) {
		return res.status(400).json({ error: "Id ekspor tidak valid." });
	}
	const fmt = format === "gif" ? "gif" : "webm";
	const bg = ALLOWED_BG.has(background) ? background : "black";
	const rate = Math.min(60, Math.max(1, Number(fps) || 30));
	const transparent = bg === "transparent";

	const dir = path.join(EXPORT_TMP, String(job));
	let frames;
	try {
		frames = (await fsp.readdir(dir))
			.filter((f) => /^f\d{5}\.(png|jpg)$/.test(f))
			.sort();
	} catch {
		return res.status(400).json({ error: "Bingkai tidak ditemukan — ekspor dibatalkan." });
	}
	if (!frames.length) return res.status(400).json({ error: "Tidak ada bingkai untuk digabung." });

	// Catch a truncated sequence before it becomes a short, jumpy video:
	// the client tells us how many frames it meant to send.
	const expected = Number(req.body?.frames);
	if (Number.isInteger(expected) && expected > 0 && frames.length < expected) {
		fsp.rm(dir, { recursive: true, force: true }).catch(() => {});
		return res.status(400).json({
			error: `Bingkai tidak lengkap (${frames.length} dari ${expected}). Ekspor dibatalkan.`,
		});
	}
	const pattern = /\.jpg$/.test(frames[0]) ? "f%05d.jpg" : "f%05d.png";

	// Transparency only survives in GIF on this ffmpeg, so honour the
	// request by switching format rather than silently dropping alpha.
	const outFmt = transparent ? "gif" : fmt;
	const caps = exportCapabilities();
	if (outFmt === "gif" && !caps.gif) return res.status(500).json({ error: "Encoder GIF tidak tersedia." });
	if (outFmt === "webm" && !caps.webm) return res.status(500).json({ error: "Encoder VP9 tidak tersedia." });

	// Di luar try/catch yang ada di bawah: Express 4 tidak meneruskan
	// rejected promise ke middleware error, jadi kegagalan di sini dulu
	// berujung unhandledRejection dan proses mati (disk penuh cukup untuk
	// memicunya).
	try {
		await fsp.mkdir(EXPORT_DIR, { recursive: true });
	} catch (err) {
		console.error("[export] gagal menyiapkan folder hasil:", err);
		return res.status(500).json({ error: "Folder hasil ekspor tidak bisa dibuat." });
	}
	const safeName = slug(String(name || "wallpaper")).slice(0, 48) || "wallpaper";
	const file = `${safeName}-${job}.${outFmt}`;
	const out = path.join(EXPORT_DIR, file);

	const args = ["-hide_banner", "-loglevel", "error", "-y", "-framerate", String(rate),
		"-i", path.join(dir, pattern)];

	if (outFmt === "gif") {
		// palettegen/use keeps the alpha channel; reserve_transparent is what
		// stops the transparent background from being remapped to a colour.
		args.push(
			"-filter_complex",
			`[0:v] split [a][b]; [a] palettegen=reserve_transparent=1 [p]; [b][p] paletteuse=alpha_threshold=128`,
			"-loop", "0", out
		);
	} else {
		args.push("-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-crf", "30", "-b:v", "0",
			"-auto-alt-ref", "0", "-lag-in-frames", "0", "-an", out);
	}

	try {
		await new Promise((resolve, reject) => {
			const bin = ffmpeg();
			if (!bin) return reject(new Error("ffmpeg tidak ditemukan di server."));
			const p = spawn(bin, args);
			let err = "";
			p.stderr.on("data", (d) => { err += d.toString(); });
			// 'error' fires when the binary cannot be executed at all; without
			// this listener Node would crash the process instead of rejecting.
			p.on("error", (e) => reject(new Error(`ffmpeg gagal dijalankan: ${e.message}`)));
			p.on("close", (code) => (code === 0 ? resolve() : reject(new Error(err.slice(-500) || `ffmpeg keluar ${code}`))));
		});
		const stat = await fsp.stat(out).catch(() => null);
		if (!stat || !stat.size) throw new Error("Berkas hasil kosong.");
		return res.json({
			ok: true,
			url: `/exports/${file}`,
			format: outFmt,
			frames: frames.length,
			size: stat.size,
			alpha: transparent,
			// Set when the requested format couldn't carry transparency.
			formatSwitched: transparent && fmt !== outFmt,
		});
	} catch (err) {
		return res.status(500).json({ error: "Gagal membuat video: " + err.message });
	} finally {
		fsp.rm(dir, { recursive: true, force: true }).catch(() => {});
		exportJobs.delete(String(job));
	}
});

/** Drop the temp frames if the user cancels halfway through. */
app.post("/api/export/cancel", express.json({ limit: "1kb" }), async (req, res) => {
	const job = String(req.body?.job || "");
	if (!/^[a-z0-9]{6,32}$/.test(job)) return res.status(400).json({ error: "Id ekspor tidak valid." });
	await fsp.rm(path.join(EXPORT_TMP, job), { recursive: true, force: true }).catch(() => {});
	exportJobs.delete(job);
	res.json({ ok: true });
});

// --- static ---
// Tekstur jarang berubah (hanya saat sebuah model di-ekstrak ulang), tapi
// tanpa Cache-Control setiap file di-revalidate: satu RTT per tekstur untuk
// 38 ribu file. 1 hari cukup untuk pemakaian harian dan tetap pulih cepat
// setelah aset diganti — sengaja tidak immutable, karena ekstrak ulang
// menimpa nama file yang sama.
app.use("/assets", express.static(ASSETS, { fallthrough: false, maxAge: "1d" }));
app.use(
	"/thumbs",
	express.static(THUMBS, { fallthrough: false, maxAge: "7d", immutable: true })
);
app.use("/dist", express.static(path.join(ROOT, "public", "dist")));
// Vendored Spine 2.1.27 viewer (Kurumifans/spine, Spine Runtimes License).
// Served under /legacy-spine/ so the client can iframe it for models whose
// skeletons no pixi-spine runtime can read.
app.use(
	"/legacy-spine",
	express.static(path.join(ROOT, "vendor", "spine2127"), {
		fallthrough: false,
		maxAge: "7d",
	})
);

// Runtime Spine 2.1 official. Dimuat sebagai tag <script> oleh
// src/spine21-stage.js, jadi harus bisa diambil dari /vendor/spine21/.
// Bukan modul: spine.js 2.1 mendefinisikan global `spine` dan tidak
// mengerti import/export.
app.use(
	"/vendor/spine21",
	express.static(path.join(ROOT, "vendor", "spine21"), {
		fallthrough: false,
		maxAge: "7d",
	})
);
app.use("/exports", express.static(EXPORT_DIR, { fallthrough: false, maxAge: "1h" }));
// BD2 JP voice lines. Served under its own prefix so a missing directory can
// never shadow /assets or /thumbs.
app.use(
	"/bd2-audio",
	express.static(AUDIO_DIR, { fallthrough: false, maxAge: "7d", immutable: true })
);
// OrisRies soundtrack: flat .ogg files, served with the same caching rules.
app.use(
	"/orisries-audio",
	express.static(OR_AUDIO_DIR, { fallthrough: false, maxAge: "7d", immutable: true })
);
// Lost Sword cutscene videos (skill / summon / quest .mp4|.m4v). Served under
// its own prefix so a missing folder can never shadow /assets.
app.use(
	"/lostsword-video",
	express.static(path.join(ASSETS, "lostsword-video"), {
		fallthrough: false,
		maxAge: "7d",
		immutable: true,
	})
);
// Epic Seven wallpaper animation (.webm, sampai 186 MB per berkas).
// Prefix sendiri, sama alasannya dengan lostsword-video di atas.
app.use(
	"/epic7-wallpaper",
	express.static(path.join(ASSETS, "epic7-wallpaper"), {
		fallthrough: false,
		maxAge: "7d",
		immutable: true,
	})
);
// Ilustrasi kartu skill Chaos Zero Nightmare (WebP, ~30 KB per kartu).
app.use(
	"/czn-cards",
	express.static(path.join(ASSETS, "czn-cards"), {
		fallthrough: false,
		maxAge: "7d",
		immutable: true,
	})
);
app.use(express.static(path.join(ROOT, "public")));

app.use((req, res) => res.status(404).json({ error: "Endpoint tidak ditemukan." }));

/* Safety net: an exception that escapes a synchronous route must not take
 * the process down with it. Log it and answer 500 instead.
 *
 * Catatan jujur: handler async yang melempar rejected promise TIDAK
 * diteruskan Express 4 ke middleware empat argumen ini — ia jadi
 * unhandledRejection, dan di Node 20+ itu mengakhiri proses. Itulah gunanya
 * penjaga tingkat proses di bawah, sekaligus alasan setiap handler async
 * di file ini tetap dibungkus try/catch sendiri. */
// eslint-disable-next-line no-unused-vars -- Express identifies error middleware by arity (4 args).
app.use((err, req, res, next) => {
	if (res.headersSent) return next(err);
	const status = Number(err && (err.status || err.statusCode));
	/* Client errors must keep their status. express.static({fallthrough:false})
	 * reports a missing file as an ENOENT error carrying status 404 — turning
	 * that into a 500 (as an earlier version of this handler did) breaks every
	 * not-found case in the UI.
	 *
	 * The underlying message is never echoed back: for a static miss it is the
	 * absolute path on disk. */
	if (Number.isInteger(status) && status >= 400 && status < 500) {
		const message =
			status === 400 ? "Permintaan tidak valid."
			: status === 404 ? "Tidak ditemukan."
			: "Permintaan tidak dapat dipenuhi.";
		return res.status(status).json({ error: message });
	}
	console.error("[spine-stage] unhandled route error:", err);
	res.status(500).json({ error: "Kesalahan internal server." });
});

/* Penjaga tingkat proses. Tanpa ini satu rejected promise dari handler async
 * (Express 4 tidak meneruskannya ke middleware error) cukup untuk mematikan
 * service — pernah terbukti pada /api/export/finish yang mkdir-nya gagal. */
process.on("unhandledRejection", (err) => {
	console.error("[spine-stage] unhandledRejection:", err);
});
process.on("uncaughtException", (err) => {
	// Keadaan proses sudah tidak bisa dipercaya: keluar rapi dan biarkan
	// systemd (Restart=on-failure) yang menyalakan ulang.
	console.error("[spine-stage] uncaughtException, mematikan proses:", err);
	process.exit(1);
});

app.listen(PORT, HOST, () => {
	// getModels(), NOT scanModels(): the former checks the persisted cache
	// first. Calling scanModels() directly made every restart rescan all
	// ~17k models (~2 min of 100% CPU) even when nothing had changed, which
	// defeated the whole point of the cache.
	const models = getModels();
	console.log(`\n  Spine Stage  →  http://${HOST}:${PORT}`);
	console.log(`  aset         :  ${ASSETS}`);
	// Listing 16.9k ids floods the journal; the count plus a few examples is
	// enough to confirm the scan and keeps `journalctl` readable.
	console.log(`  model        :  ${models.length} (${models.slice(0, 5).map((m) => m.id).join(", ")} …)\n`);
});