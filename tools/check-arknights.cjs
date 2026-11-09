#!/usr/bin/env node
/**
 * Regresi 明日方舟 (Arknights) — tools/arknights/update.py.
 *
 * Sumber: isHarryh/Ark-Models (Spine 3.8), ArknightsGameData EN (nama),
 * yuanyan3060/ArknightsGameResource (thumbnail ilustrasi, BUKAN atlas).
 *
 * Yang dikunci:
 *   - folder/berkas ASCII: nama asli mengandung `#` (589 folder) dan server
 *     men-slug id -> tanpa sanitasi semua aset 404 (kasus yang sama dengan
 *     IV-N-Tight). Baris halaman .atlas ikut ditulis ulang.
 *   - 3.112 model, 0 id dobel, nama Inggris (0 aksara Tionghoa), family skin.
 *   - thumbnail dari portrait/enemy art (bukan potongan atlas), manifest
 *     lengkap, /api/thumbnails memuatnya, gambar benar-benar termuat di kartu.
 *   - updater --check lewat HTTP stabil; render Spine 3.8 + 0 aset 404.
 *
 * Sengaja TIDAK menjalankan --apply penuh (unduh zip 1,1 GB + 2.800 gambar).
 * Run: node tools/check-arknights.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.BASE_URL || "http://127.0.0.1:3000";
const ASSETS = path.join(ROOT, "assets", "arknights");
const THUMBS = path.join(ROOT, "public", "thumbs", "arknights");
const NAMES = path.join(ROOT, "data", "arknights-names.json");
const FAMILY = path.join(ROOT, "data", "arknights-family.json");
const UPDATER = path.join(ROOT, "tools", "arknights", "update.py");
const REFRESH = path.join(ROOT, "tools", "arknights", "refresh.py");

const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};
// Baris HALAMAN atlas selalu diikuti properti `size:`. Nama region yang
// kebetulan berakhiran `.png` (mis. F_Mouth_Sp_3.png) bukan halaman.
const atlasPages = (p) => {
	const lines = fs.readFileSync(p, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/);
	const out = [];
	for (let i = 0; i < lines.length; i++) {
		const s = lines[i].trim().replace(/^\uFEFF/, "").trim();
		if (!s || /^\s/.test(lines[i]) || !/\.(png|webp|jpe?g)$/i.test(s) ||
			s.includes("/") || s.includes("\\")) continue;
		const nxt = lines.slice(i + 1, i + 4).map((l) => l.trim()).find(Boolean) || "";
		if (/^size:/i.test(nxt)) out.push(s);
	}
	return [...new Set(out)];
};

(async () => {
	// --- kontrak sumber ----------------------------------------------------
	const src = fs.readFileSync(UPDATER, "utf8");
	ok("updater menyimpan metadata di cache (& mode --offline)",
		/--offline/.test(src) && /art-tree\.json/.test(src));
	ok("refresh.py membangun ulang dari cache",
		fs.existsSync(REFRESH) && /--apply", "--offline/.test(fs.readFileSync(REFRESH, "utf8")));
	ok("nama folder & berkas disanitasi + atlas ditulis ulang",
		/def safe_names/.test(src) && /def rewrite_atlas/.test(src) &&
		/rew = rewrite_atlas|rewrite_atlas\(raw, ren\)/.test(src));
	ok("thumbnail diambil dari portrait/avatar/enemy/skin",
		/resolve_art/.test(src) && /portrait\/char_/.test(src) && /enemy\/enemy_/.test(src));

	// --- endpoint updater --------------------------------------------------
	const chk = await fetch(`${BASE}/api/update/arknights?mode=check`).then((r) => r.json());
	const chk2 = await fetch(`${BASE}/api/update/arknights?mode=check`).then((r) => r.json());
	ok("--check via HTTP ok:true", chk.ok === true && !chk.error, String(chk.error || ""));
	ok("dua --check identik", chk.version === chk2.version &&
		chk.changed === chk2.changed && chk.new === chk2.new && chk.expected === chk2.expected);
	ok("kontrak check lengkap", /^[0-9a-f]{12}$/.test(chk.version || "") &&
		chk.expected > 3000 && chk.have === chk.expected &&
		chk.changed === (chk.version !== chk.previous),
		JSON.stringify({ v: chk.version, expected: chk.expected, have: chk.have,
			changed: chk.changed }));

	// --- integritas model --------------------------------------------------
	const models = (await fetch(`${BASE}/api/models`).then((r) => r.json())).models || [];
	const ark = models.filter((m) => m.game === "arknights");
	const dirs = fs.readdirSync(ASSETS).filter((d) => fs.statSync(path.join(ASSETS, d)).isDirectory());
	ok(">= 3000 model Arknights", ark.length >= 3000 &&
		ark.length >= dirs.length && ark.length - dirs.length <= 5,
		`${ark.length} model / ${dirs.length} folder`);
	ok("tidak ada id dobel", new Set(ark.map((m) => m.id)).size === ark.length);
	ok("semua folder bernama ASCII (id = folder)",
		dirs.every((d) => /^[A-Za-z0-9_.\-]+$/.test(d)),
		dirs.filter((d) => !/^[A-Za-z0-9_.\-]+$/.test(d)).slice(0, 3).join(" | ") || `${dirs.length} folder`);
	ok("tidak ada nama berkas ber-# (URL tak boleh ada fragment)",
		ark.every((m) => !String(m.skeletonFile).includes("#") && !String(m.atlasFile).includes("#")));

	let broken = [];
	for (const m of ark) {
		const leaf = String(m.id).split("/").pop().split("#")[0];
		const dir = path.join(ASSETS, leaf);
		if (!fs.existsSync(dir)) { broken.push(`${m.id}: folder`); continue; }
		const sk = path.join(dir, m.skeletonFile);
		const at = path.join(dir, m.atlasFile);
		if (!fs.existsSync(sk) || !fs.existsSync(at)) { broken.push(`${m.id}: skel/atlas`); continue; }
		for (const p of atlasPages(at)) {
			if (!fs.existsSync(path.join(dir, p))) broken.push(`${m.id}: ${p}`);
		}
	}
	ok("semua aset model resolve (0 404)", broken.length === 0,
		broken.slice(0, 4).join(" | ") || `${ark.length} model`);

	const names = JSON.parse(fs.readFileSync(NAMES, "utf8"));
	const CJK = /[\u4e00-\u9fff]/;
	const cjk = Object.entries(names).filter(([, v]) => CJK.test(String(v.name || "")));
	ok("nama tampilan 0 aksara Tionghoa", cjk.length === 0,
		cjk.slice(0, 2).map(([k, v]) => `${k}=${v.name}`).join(" | ") || `${Object.keys(names).length} nama`);
	ok("nama lengkap & bukan sekadar slug folder",
		Object.keys(names).length >= 3000 &&
		Object.entries(names).every(([k, v]) => !!v.name && v.name !== k && /^[A-Za-z0-9_.\-]+$/.test(k)),
		String(Object.keys(names).length));

	const fam = JSON.parse(fs.readFileSync(FAMILY, "utf8")).families || [];
	const ids = new Set(ark.map((m) => m.id));
	ok("family skin terbentuk (>= 100)", fam.length >= 100, String(fam.length));
	ok("semua anggota family = id model valid",
		fam.every((f) => ids.has(f.root) && (f.members || []).every((x) => ids.has(x.id))));

	// --- thumbnail ilustrasi ----------------------------------------------
	const man = JSON.parse(fs.readFileSync(path.join(THUMBS, "_manifest.json"), "utf8"));
	ok("manifest >= 2500 thumbnail", Object.keys(man).length >= 2500,
		String(Object.keys(man).length));
	ok("semua kunci manifest = id model valid", Object.keys(man).every((k) => ids.has(k)));
	ok("semua berkas WebP ada", Object.values(man).every((f) =>
		fs.existsSync(path.join(THUMBS, f))));
	ok("thumbnail BUKAN halaman atlas model",
		Object.values(man).every((f) => !/\.(atlas|skel)$/.test(f)));
	const apiThumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs || {};
	ok("/api/thumbnails memuat kunci arknights",
		Object.keys(apiThumbs).filter((k) => k.startsWith("arknights/")).length >= 2500,
		String(Object.keys(apiThumbs).filter((k) => k.startsWith("arknights/")).length));

	// --- browser -----------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(90000);
	const errors = [], missing = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(png|webp|atlas|json|skel)(\?|$)/.test(r.url()))
			missing.push(`${r.status()} ${r.url()}`);
	});
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector('#game-list .game[data-key="arknights"]', { state: "visible" });
	await page.locator('#game-list .game[data-key="arknights"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	const btn = await page.evaluate(() => {
		const b = document.getElementById("update-check");
		return b ? { hidden: b.hidden } : null;
	});
	ok("tombol Manual Update tampil untuk Arknights", btn && btn.hidden === false,
		JSON.stringify(btn));
	const card = await page.evaluate(() => {
		const img = document.querySelector(
			"#model-list li > button:not(.model-fav) img, #model-list .gcard img");
		return img ? { src: img.getAttribute("src"), w: img.naturalWidth, complete: img.complete } : null;
	});
	ok("thumbnail ilustrasi ter-render di kartu",
		card && card.complete && card.w > 0 && /\/thumbs\/arknights\//.test(card.src || ""),
		JSON.stringify(card));

	// Family skin diciutkan jadi satu kartu root, jadi cuma id root / model
	// tanpa family yang bisa dicari langsung lewat #search.
	const roots = ark.filter((m) => !m.family || m.family.root === m.id).map((m) => m.id);
	const picks = ["arknights/002_amiya",
		...roots.filter((id) => id !== "arknights/002_amiya")].slice(0, 3);
	for (const wanted of picks) {
		await page.fill("#search", wanted);
		await page.locator(`#model-list [data-id="${wanted}"]`).first()
			.waitFor({ state: "visible", timeout: 30000 });
		await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 60000 });
		await page.waitForFunction(
			(id) => window.spineStage?.model?.id === id && !!window.spineStage?.spine?.skeleton,
			wanted, { timeout: 90000 });
		const st = await page.evaluate(() => ({
			id: window.spineStage.model?.id,
			anims: document.querySelectorAll("#anim-select option").length,
		}));
		ok(`render ${wanted}`, st.id === wanted && st.anims > 0, JSON.stringify(st));
	}
	ok("tidak ada aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));
	// 364 family skin: kartu root wajib punya picker varian (popup atau tab).
	await page.fill("#search", "arknights/002_amiya");
	await page.locator('#model-list [data-id="arknights/002_amiya"]').first()
		.waitFor({ state: "visible", timeout: 30000 });
	await page.locator('#model-list [data-id="arknights/002_amiya"]').first().click({ timeout: 60000 });
	await page.waitForFunction(
		() => window.spineStage?.model?.id === "arknights/002_amiya" &&
			!!window.spineStage?.spine?.skeleton, null, { timeout: 90000 });
	const vp = await page.evaluate(() => ({
		variants: document.querySelector("#variant-select")?.options?.length || 0,
		btnHidden: document.querySelector("#variant-btn")?.hidden,
		tabsHidden: document.querySelector("#variant-tabs")?.hidden,
	}));
	ok("picker varian skin Arknights >= 2",
		vp.variants >= 2 && (vp.btnHidden === false || vp.tabsHidden === false),
		JSON.stringify(vp));
	ok("tidak ada JS error", errors.length === 0, errors.slice(0, 2).join(" | "));
	await browser.close();

	console.log(`\n${failed.length ? "GAGAL: " + failed.join(" | ") : "Arknights ok"}`);
	process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
