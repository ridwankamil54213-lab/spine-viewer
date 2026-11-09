/**
 * Smoke test untuk Make Drama (sumber: https://mad.altterisk.cc/viewer/).
 *
 * Memverifikasi:
 *   - 143 model (12 baru dari katalog live 145 skin, 2 drama texture-only dilewati)
 *   - metadata karakter kaya dari characters.json (rarity, elemen, peran, CV, artis)
 *   - 136 thumbnail + manifest yang kuncinya valid
 *   - <select>/picker varian tetap jalan (63 family)
 *   - updater --check stabil, model .skel 4.2 benar-benar ter-render
 *
 * Run: node tools/check-mad-drama.cjs   (server on :3000)
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
	const mad = all.filter((m) => m.game === "mad-drama");
	const names = JSON.parse(fs.readFileSync(path.join(ROOT, "assets/mad-drama/_names.json"), "utf8"));

	ok("143 model Make Drama", mad.length === 143, String(mad.length));
	ok("katalog _names.json 145 entri", Object.keys(names).length === 145,
		String(Object.keys(names).length));
	ok("semua model punya metadata karakter", mad.every((m) => m.character?.name));
	ok("sumber metadata mad.altterisk.cc",
		mad.every((m) => m.character?.source === "mad.altterisk.cc"));
	ok("rarity/elemen/peran dari characters.json",
		mad.some((m) => m.character?.rarity?.includes("★")) &&
		mad.some((m) => m.character?.element) &&
		mad.some((m) => m.character?.class),
		JSON.stringify((mad[0] || {}).character || {}).slice(0, 160));
	ok("CV / artis / deskripsi ikut",
		mad.some((m) => m.character?.artist) && mad.some((m) => m.character?.cv) &&
		mad.some((m) => m.character?.desc));
	ok("63 family (standing + scene)", mad.filter((m) => (m.family || {}).members?.length).length === 63,
		String(mad.filter((m) => (m.family || {}).members?.length).length));
	ok("karakter baru CH0069 ada", mad.some((m) => m.character?.code === "CH0069"));

	// --- thumbnail ---------------------------------------------------------
	const tdir = path.join(ROOT, "public/thumbs/mad-drama");
	const man = JSON.parse(fs.readFileSync(path.join(tdir, "_manifest.json"), "utf8"));
	const ids = new Set(mad.map((m) => m.id));
	const files = new Set(Object.values(man));
	ok("134 kunci thumbnail valid", Object.keys(man).length === 134 &&
		Object.keys(man).every((k) => ids.has(k)), String(Object.keys(man).length));
	ok("134 berkas WebP", files.size === 134, String(files.size));
	ok("file thumbnail ada semua", [...files].every((f) => fs.existsSync(path.join(tdir, f))));
	ok("thumbnail ringan", [...files].every((f) =>
		fs.statSync(path.join(tdir, f)).size < 400 * 1024));
	const tmap = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs;
	ok("/api/thumbnails memuat kunci mad-drama",
		Object.keys(tmap).filter((k) => k.startsWith("mad-drama/")).length === 134,
		String(Object.keys(tmap).filter((k) => k.startsWith("mad-drama/")).length));
	const tRes = await fetch(`${BASE}/thumbs/mad-drama/${[...files][0]}`);
	ok("thumbnail tersaji 200", tRes.status === 200,
		`${tRes.status} ${tRes.headers.get("content-type")}`);

	// --- updater -----------------------------------------------------------
	const chk = await fetch(`${BASE}/api/update/mad-drama?mode=check`).then((r) => r.json());
	// `changed` boleh true kalau katalog upstream sah berubah; yang wajib
	// check jalan dan tidak ada model yang benar-benar belum terpasang.
	ok("updater --check stabil", chk.ok === true && chk.new === 0,
		JSON.stringify({ ok: chk.ok, changed: chk.changed, new: chk.new, drama: chk.drama,
			alasan: chk.alasan }));

	// --- browser -----------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(90000);
	const errors = [];
	const missingAssets = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|png|atlas|json|webm|skel)(\?|$)/.test(r.url()))
			missingAssets.push(`${r.status()} ${r.url()}`);
	});

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector('#game-list .game[data-key="mad-drama"]', { state: "visible" });
	await page.locator('#game-list .game[data-key="mad-drama"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	const thumbUi = await page.evaluate(() => {
		const img = document.querySelector("#model-list li > button:not(.model-fav) img, #model-list .gcard img");
		return img ? { w: img.naturalWidth, complete: img.complete } : null;
	});
	ok("thumbnail ter-render di galeri", !!thumbUi && thumbUi.complete && thumbUi.w > 0,
		JSON.stringify(thumbUi));

	// Root family CH0009 adalah rig standing, bukan affection — pustaka cuma
	// menampilkan root, jadi cari id itu (bukan af_ch0009__onestore).
	const wanted = "mad-drama/st_ch0009__onestore";
	await page.fill("#search", wanted);
	await page.locator(`#model-list [data-id="${wanted}"]`).first()
		.waitFor({ state: "visible", timeout: 20000 });
	await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 40000 });
	await page.waitForFunction(() => !!window.spineStage?.spine?.skeleton, null, { timeout: 90000 });
	const st = await page.evaluate(() => ({
		id: window.spineStage.model?.id,
		name: window.spineStage.model?.name,
		anims: document.querySelectorAll("#anim-select option").length,
		variants: document.querySelector("#variant-select")?.options?.length || 0,
		tabsHidden: document.querySelector("#variant-tabs")?.hidden,
		btnHidden: document.querySelector("#variant-btn")?.hidden,
	}));
	ok("model Spine 4.2 (.skel) ter-render", st.id === wanted, JSON.stringify(st));
	ok("animasi tersedia", st.anims > 0, String(st.anims));
	ok("picker varian tampil (tab atau popup)",
		st.variants > 1 && (st.tabsHidden === false || st.btnHidden === false),
		JSON.stringify({ variants: st.variants, tabsHidden: st.tabsHidden, btnHidden: st.btnHidden }));
	ok("tidak ada aset 404", missingAssets.length === 0, missingAssets.slice(0, 3).join(" | "));

	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	if (errors.length) failed.push("js errors");
	if (missingAssets.length) failed.push("aset 404");
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nMake Drama ok");
})().catch((err) => {
	console.error(err);
	process.exit(1);
});
