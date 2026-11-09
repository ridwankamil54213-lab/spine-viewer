/**
 * Smoke test untuk pustaka CrossCore (sumber: github.com/Talors1225/arthub-viewer-web).
 *
 * Memverifikasi rantai tools/crosscore/update.py:
 *   - 502 model Spine + 325 model interaksi, semuanya di game "crosscore"
 *   - nama tampilan dari _names.json (bukan nama folder mentah)
 *   - 761 thumbnail WebP + dua manifest yang kuncinya valid
 *   - data interaksi /api/interaction/crosscore tetap tersaji
 *   - updater --check stabil (changed:false)
 *   - model Spine benar-benar ter-render di stage tanpa aset 404
 *
 * Run: node tools/check-crosscore.cjs   (server on :3000)
 */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const BASE = "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

(async () => {
	const all = (await fetch(`${BASE}/api/models?lean=1`).then((r) => r.json())).models || [];
	const cc = all.filter((m) => String(m.id).startsWith("crosscore/") ||
		String(m.id).startsWith("crosscore-interaction/"));
	const spine = cc.filter((m) => String(m.id).startsWith("crosscore/"));
	const inter = cc.filter((m) => String(m.id).startsWith("crosscore-interaction/"));
	const names = JSON.parse(fs.readFileSync(path.join(ROOT, "assets/crosscore/_names.json"), "utf8"));

	ok("827 model CrossCore terpasang", cc.length === 827, String(cc.length));
	ok("502 model Spine", spine.length === 502, String(spine.length));
	ok("325 model interaksi", inter.length === 325, String(inter.length));
	ok("semuanya masuk game crosscore", cc.every((m) => m.game === "crosscore"));

	const catalogNamed = cc.filter((m) => m.character?.source === "arthub-viewer-web");
	ok("nama ArtHub terpasang di model", catalogNamed.length >= 760,
		`${catalogNamed.length} dari ${cc.length}`);
	ok("katalog _names.json terisi", Object.keys(names).length >= 760,
		String(Object.keys(names).length));
	ok("nama interaksi memakai judul Tionghoa",
		inter.some((m) => /[一-龥]/.test(m.name || "")),
		(inter[0] || {}).name || "tidak ada");
	ok("metadata kategori ikut", catalogNamed.some((m) => m.character?.class),
		(catalogNamed.find((m) => m.character?.class) || {}).character?.class || "");

	// --- thumbnail ---------------------------------------------------------
	const dirs = {
		crosscore: path.join(ROOT, "public/thumbs/crosscore"),
		"crosscore-interaction": path.join(ROOT, "public/thumbs/crosscore-interaction"),
	};
	const ids = new Set(cc.map((m) => m.id));
	const allManifests = {};
	const allFiles = new Set();
	for (const [game, dir] of Object.entries(dirs)) {
		const man = JSON.parse(fs.readFileSync(path.join(dir, "_manifest.json"), "utf8"));
		Object.assign(allManifests, man);
		ok(`kunci manifest ${game} valid`,
			Object.keys(man).length > 200 && Object.keys(man).every((k) => ids.has(k)),
			String(Object.keys(man).length));
		for (const f of Object.values(man)) allFiles.add(path.join(dir, f));
	}
	ok("kunci manifest seluruhnya cocok id model",
		Object.keys(allManifests).length >= 761 &&
		Object.keys(allManifests).every((k) => ids.has(k)),
		`${Object.keys(allManifests).length} kunci`);
	ok("761 berkas thumbnail WebP", allFiles.size === 761, String(allFiles.size));
	ok("file thumbnail ada semua", [...allFiles].every((p) => fs.existsSync(p)));
	ok("thumbnail WebP ringan", [...allFiles].every((p) => fs.statSync(p).size < 400 * 1024));
	const tmap = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs;
	ok("/api/thumbnails memuat kunci crosscore",
		Object.keys(tmap).filter((k) => k.startsWith("crosscore")).length >= 700,
		String(Object.keys(tmap).filter((k) => k.startsWith("crosscore")).length));
	const sample = Object.values(JSON.parse(fs.readFileSync(
		path.join(dirs.crosscore, "_manifest.json"), "utf8")))[0];
	const tRes = await fetch(`${BASE}/thumbs/crosscore/${sample}`);
	ok("thumbnail tersaji 200", tRes.status === 200,
		`${tRes.status} ${tRes.headers.get("content-type")}`);

	// --- data interaksi (sudah ada sejak lama, harus tetap hidup) ----------
	const iData = await fetch(`${BASE}/api/interaction/crosscore`).then((r) => r.json());
	ok("katalog interaksi tersaji", Array.isArray(iData.models) && iData.models.length === 270,
		String(iData.models?.length));

	// --- updater -----------------------------------------------------------
	const chk = await fetch(`${BASE}/api/update/crosscore?mode=check`).then((r) => r.json());
	ok("updater --check stabil", chk.ok === true && chk.new === 0,
		JSON.stringify({ ok: chk.ok, changed: chk.changed, new: chk.new, alasan: chk.alasan }));

	// --- browser -----------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(120000);
	const errors = [];
	const missingAssets = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|png|atlas|json|webm|skel)(\?|$)/.test(r.url()))
			missingAssets.push(`${r.status()} ${r.url()}`);
	});

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible" });
	const gameCard = page.locator('#game-list .game[data-key="crosscore"]');
	ok("kartu game CrossCore tampil", await gameCard.count() === 1);
	await gameCard.click();
	await page.waitForSelector("#model-list li > button:not(.model-fav)", { state: "visible" });
	const thumbUi = await page.evaluate(() => {
		const img = document.querySelector("#model-list li > button:not(.model-fav) img");
		return img ? { w: img.naturalWidth, complete: img.complete } : null;
	});
	ok("thumbnail ter-render di galeri", !!thumbUi && thumbUi.complete && thumbUi.w > 0,
		JSON.stringify(thumbUi));

	// #search mencocokkan id, jadi satu kartu pasti ketemu walau 827 model
	// terbagi atas beberapa halaman.
	const wanted = "crosscore/10010_skin_alps03_spine";
	await page.fill("#search", wanted);
	await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 30000 });
	await page.waitForFunction(() => !!window.spineStage?.spine?.skeleton, null, { timeout: 90000 });
	const st = await page.evaluate(() => ({
		id: window.spineStage.model?.id,
		name: window.spineStage.model?.name,
		anims: document.querySelectorAll("#anim-select option").length,
	}));
	ok("model Spine CrossCore ter-render", st.id === wanted, JSON.stringify(st));
	ok("animasi tersedia", st.anims > 0, String(st.anims));
	ok("tidak ada aset 404", missingAssets.length === 0, missingAssets.slice(0, 3).join(" | "));

	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	if (errors.length) failed.push("js errors");
	if (missingAssets.length) failed.push("aset 404");
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nCrossCore ok");
})().catch((err) => {
	console.error(err);
	process.exit(1);
});
