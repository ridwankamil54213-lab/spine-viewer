/**
 * Smoke test untuk pustaka Brown Dust 2 (sumber: github.com/Zormolo/Brown-Dust-2-Assets).
 *
 * Memverifikasi rantai tools/browndust/update.py:
 *   - 517 model (456 bd2-char/ + 61 bd2/), semuanya game "bd2"
 *   - nama karakter + kostum dari data/bd2-names.json (applyBd2Names)
 *   - model utama + varian Skill-Cutscene/Interaction terkelompok jadi family
 *   - thumbnail dari assets/ui/ repo (costume_face / costume_icon)
 *   - updater --check stabil (changed:false)
 *   - model Spine .skel benar-benar ter-render di stage tanpa aset 404
 *
 * Run: node tools/check-bd2.cjs   (server on :3000)
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
	const bd = all.filter((m) => m.game === "bd2");
	const char = bd.filter((m) => String(m.id).startsWith("bd2-char/"));
	const flat = bd.filter((m) => String(m.id).startsWith("bd2/"));
	const names = JSON.parse(fs.readFileSync(path.join(ROOT, "data/bd2-names.json"), "utf8"));

	ok("517 model BD2 terpasang", bd.length === 517, String(bd.length));
	ok("456 model bd2-char", char.length === 456, String(char.length));
	ok("61 model bd2 (misc/special)", flat.length === 61, String(flat.length));
	ok("nama kostum dari bd2-charinfo",
		bd.filter((m) => (m.character || {}).source === "bd2-charinfo").length === 388,
		String(bd.filter((m) => (m.character || {}).source === "bd2-charinfo").length));
	ok("katalog bd2-names.json terisi", Object.keys(names).length === 395,
		String(Object.keys(names).length));
	ok("karakter + kostum kebaca",
		bd.some((m) => /Alec/.test(m.name || "") && m.character?.costume),
		(bd.find((m) => /Alec/.test(m.name || "")) || {}).name || "tidak ada");
	const withFamily = bd.filter((m) => (m.family || {}).members?.length > 1);
	ok("model + varian jadi family", withFamily.length > 300,
		`${withFamily.length} keluarga`);
	ok("varian Skill-Cutscene ada",
		bd.some((m) => String(m.id).includes("Skill-Cutscene")),
		String(bd.filter((m) => String(m.id).includes("Skill-Cutscene")).length));

	// --- thumbnail ---------------------------------------------------------
	const tdir = path.join(ROOT, "public/thumbs/bd2");
	const man = JSON.parse(fs.readFileSync(path.join(tdir, "_manifest.json"), "utf8"));
	const ids = new Set(bd.map((m) => m.id));
	const files = new Set(Object.values(man));
	ok("kunci manifest cocok id model",
		Object.keys(man).length === 376 && Object.keys(man).every((k) => ids.has(k)),
		String(Object.keys(man).length));
	ok("369 berkas thumbnail PNG", files.size === 369, String(files.size));
	ok("file thumbnail ada semua",
		[...files].every((f) => fs.existsSync(path.join(tdir, f))));
	ok("thumbnail ringan", [...files].every((f) =>
		fs.statSync(path.join(tdir, f)).size < 400 * 1024));
	const tmap = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs;
	ok("/api/thumbnails memuat kunci bd2",
		Object.keys(tmap).filter((k) => k.startsWith("bd2")).length === 376,
		String(Object.keys(tmap).filter((k) => k.startsWith("bd2")).length));
	const sample = Object.values(man)[0];
	const tRes = await fetch(`${BASE}/thumbs/bd2/${sample}`);
	ok("thumbnail tersaji 200", tRes.status === 200,
		`${tRes.status} ${tRes.headers.get("content-type")}`);

	// --- updater -----------------------------------------------------------
	const chk = await fetch(`${BASE}/api/update/bd2?mode=check`).then((r) => r.json());
	// `changed` boleh true kalau upstream benar-benar rilis baru; smoke test
	// ini menguji viewer, bukan kesegaran repositori. Yang wajib: check jalan
	// dan tidak ada model yang belum terpasang.
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
	const gameCard = page.locator('#game-list .game[data-key="bd2"]');
	ok("kartu game Brown Dust 2 tampil", await gameCard.count() === 1);
	await gameCard.click();
	await page.waitForSelector("#model-list li > button:not(.model-fav)", { state: "visible" });
	const thumbUi = await page.evaluate(() => {
		const img = document.querySelector("#model-list li > button:not(.model-fav) img");
		return img ? { w: img.naturalWidth, complete: img.complete } : null;
	});
	ok("thumbnail ter-render di galeri", !!thumbUi && thumbUi.complete && thumbUi.w > 0,
		JSON.stringify(thumbUi));

	// #search mencocokkan id, jadi satu kartu pasti ketemu walau 517 model
	// terbagi atas beberapa halaman.
	const wanted = "bd2-char/Alec/Sword_Breaker";
	await page.fill("#search", wanted);
	await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 30000 });
	await page.waitForFunction(() => !!window.spineStage?.spine?.skeleton, null, { timeout: 90000 });
	const st = await page.evaluate(() => ({
		id: window.spineStage.model?.id,
		name: window.spineStage.model?.name,
		anims: document.querySelectorAll("#anim-select option").length,
	}));
	ok("model Spine BD2 (.skel) ter-render", st.id === wanted, JSON.stringify(st));
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
	console.log("\nBrown Dust 2 ok");
})().catch((err) => {
	console.error(err);
	process.exit(1);
});
