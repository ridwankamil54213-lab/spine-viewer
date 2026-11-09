/**
 * Smoke test: thumbnail マブラヴ ガールズガーデンX dari game CG-nya.
 *
 * Memverifikasi:
 *   - 1107 thumbnail untuk 1243 rig (136 sisanya fallback huruf)
 *   - manifest & /api/thumbnails sinkron, semua berkas ada, valid WebP
 *   - aspect ratio UTUH (tidak di-crop), sisi maks 300 px
 *   - semua keluarga CG dipakai termasuk cg_h_ sesuai keputusan user
 *   - CSS object-fit: contain, gambar benar-benar ter-render di kartu
 *   - model tanpa CG tetap fallback badge (tidak 404)
 *   - updater --check stabil lewat endpoint HTTP asli
 *
 * Run: node tools/check-muvluv-thumbs.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { chromium } = require("playwright-core");

const BASE = "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const DIR = path.join(ROOT, "public/thumbs/muvluv");
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

function dims(file) {
	const out = execFileSync("ffprobe", [
		"-v", "error", "-select_streams", "v:0",
		"-show_entries", "stream=width,height", "-of", "csv=p=0", file,
	], { encoding: "utf8" }).trim();
	const [w, h] = out.split(",").map(Number);
	return { w, h };
}

(async () => {
	const models = (await fetch(`${BASE}/api/models?lean=1`).then((r) => r.json())).models || [];
	const mv = models.filter((m) => m.game === "muvluv");
	const ids = new Set(mv.map((m) => m.id));
	const thumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs || {};
	const man = JSON.parse(fs.readFileSync(path.join(DIR, "_manifest.json"), "utf8"));
	const srcMap = JSON.parse(
		fs.readFileSync(path.join(ROOT, "data/muvluv-thumb-sources.json"), "utf8"));

	ok("1243 model MuvLuv", mv.length === 1243, String(mv.length));
	ok("1107 thumbnail", Object.keys(man).length === 1107, String(Object.keys(man).length));
	ok("semua kunci manifest = id model valid",
		Object.keys(man).every((k) => ids.has(k)));
	ok("semua berkas thumbnail ada",
		Object.values(man).every((f) => fs.existsSync(path.join(DIR, f))));
	ok("/api/thumbnails memuat 1107 kunci muvluv",
		Object.keys(thumbs).filter((k) => k.startsWith("muvluv/")).length === 1107,
		String(Object.keys(thumbs).filter((k) => k.startsWith("muvluv/")).length));
	ok("galeri CG tidak butuh thumb terpisah (pakai imageFile)",
		!Object.keys(thumbs).some((k) => k.startsWith("muvluv-cg/")));
	ok("peta sumber 1107 entri", Object.keys(srcMap).length === 1107,
		String(Object.keys(srcMap).length));

	const kinds = {};
	for (const v of Object.values(srcMap)) {
		const tag = (v.cg.match(/^[a-z_]+/) || ["?"])[0];
		kinds[tag] = (kinds[tag] || 0) + 1;
	}
	ok("potret karakter jadi sumber utama",
		(kinds.illust_portrait_ || 0) + (kinds.illust_portrait_e || 0) +
		(kinds.illust_portrait_n || 0) >= 950, JSON.stringify(kinds));
	ok("CG H eksplisit ikut dipakai (sesuai pilihan user)",
		(kinds.cg_h_c || 0) + (kinds.cg_h_s || 0) >= 100,
		`cg_h_c=${kinds.cg_h_c || 0} cg_h_s=${kinds.cg_h_s || 0}`);

	// Bentuk: utuh tanpa crop, sisi maks 300, rasio mendekati sumber CG.
	const files = Object.values(man);
	ok("semua thumbnail ringan (<200 KB)",
		files.every((f) => fs.statSync(path.join(DIR, f)).size < 200 * 1024));
	const sample = files.slice(0, 14);
	let ratioOk = 0;
	for (const f of sample) {
		const id = f.replace(/\.webp$/, "");
		const src = srcMap[id]?.cg;
		if (!src) continue;
		const a = dims(path.join(DIR, f));
		const b = dims(path.join(ROOT, "assets/muvluv-cg", src));
		if (a.w <= 300 && a.h <= 300 &&
			Math.abs(a.w / a.h - b.w / b.h) < 0.02 &&
			(a.w === 300 || a.h === 300)) ratioOk++;
	}
	ok("14 sampel: aspect ratio utuh & sisi maks 300", ratioOk === sample.length,
		`${ratioOk}/${sample.length}`);

	const tRes = await fetch(`${BASE}/thumbs/muvluv/${files[0]}`);
	ok("thumbnail tersaji 200 image/webp", tRes.status === 200 &&
		(tRes.headers.get("content-type") || "").includes("webp"),
		`${tRes.status} ${tRes.headers.get("content-type")}`);

	const chk = await fetch(`${BASE}/api/update/muvluv?mode=check`).then((r) => r.json());
	ok("updater --check stabil via HTTP",
		chk.ok === true && chk.changed === false && chk.new === 0,
		JSON.stringify({ ok: chk.ok, changed: chk.changed, new: chk.new }));

	// --- browser -----------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(60000);
	const errors = [];
	const missing = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|png|atlas|json|skel)(\?|$)/.test(r.url()))
			missing.push(`${r.status()} ${r.url()}`);
	});

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector('#game-list .game[data-key="muvluv"]', { state: "visible" });
	await page.locator('#game-list .game[data-key="muvluv"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });

	const first = await page.evaluate(() => {
		const img = document.querySelector(".model-thumb, .gcard-img");
		if (!img || img.tagName !== "IMG") return null;
		return {
			src: img.getAttribute("src"), complete: img.complete, w: img.naturalWidth,
			fit: getComputedStyle(img).objectFit,
		};
	});
	ok("kartu pertama punya gambar ter-render",
		first && first.complete && first.w > 0 && /\/thumbs\/muvluv\//.test(first.src),
		JSON.stringify(first));
	ok("CSS object-fit: contain (utuh, sisi kosong disengaja)",
		first && first.fit === "contain", first ? first.fit : "?");

	// Model yang terpetakan: thumbnail tepat untuk id-nya.
	await page.fill("#search", "100001c");
	await page.locator('#model-list [data-id="muvluv/100001c"]')
		.first().waitFor({ state: "visible", timeout: 20000 });
	const matched = await page.evaluate(() =>
		document.querySelector('#model-list [data-id="muvluv/100001c"] img')?.getAttribute("src") || "");
	ok("100001c memakai thumbnail potretnya",
		matched.includes("/thumbs/muvluv/100001c.webp"), matched);

	// Model tanpa CG harus fallback huruf, bukan gambar 404.
	await page.fill("#search", "100002c");
	await page.locator('#model-list [data-id="muvluv/100002c"]')
		.first().waitFor({ state: "visible", timeout: 20000 });
	const fallback = await page.evaluate(() =>
		!!document.querySelector('#model-list [data-id="muvluv/100002c"] .model-thumb-none, #model-list [data-id="muvluv/100002c"] .gcard-none'));
	ok("100002c (tanpa CG) fallback badge huruf", fallback);

	ok("tidak ada aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));
	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	if (errors.length) failed.push("js errors");
	if (missing.length) failed.push("aset 404");
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nMuvLuv thumbnails ok");
})().catch((e) => { console.error(e); process.exit(1); });
