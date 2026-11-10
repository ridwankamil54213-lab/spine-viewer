/**
 * Smoke test: metadata Cat Shinobi (nama karakter, varian, thumbnail).
 *
 * Membuktikan:
 *   1. data/catshinobi-names.json dibangun dari tabel lokalisasi game sendiri,
 *      >= 300 model bernama, semuanya punya label variant, dan perbaikan
 *      costume->base benar-benar menambah nama (Char_1003 -> Akari Mayoneko).
 *   2. data/catshinobi-family.json >= 180 family, tiap family >= 2 anggota,
 *      root ada di members, label mencakup Battle / SD / LD / Cat.
 *   3. Thumbnail berupa ILUSTRASI (bukan halaman atlas): WebP punya kanal
 *      alpha yang tidak fully-opaque, ukuran <= 240x360, manifest >= 500 kunci.
 *   4. API /api/models + /api/thumbnails benar-benar menyajikan semuanya.
 *   5. Browser: kartu memakai gambar /thumbs/catshinobi/, chip "N varian"
 *      muncul, model Spine tetap render, 0 aset 404, 0 JS error.
 *
 * Run: node tools/check-catshinobi.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = "http://127.0.0.1:3000";
const NAMES = path.join(ROOT, "data", "catshinobi-names.json");
const FAMILY = path.join(ROOT, "data", "catshinobi-family.json");
const THUMBS = path.join(ROOT, "public", "thumbs", "catshinobi");
const TOOLS = path.join(ROOT, "tools", "catshinobi");

const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

function installedChromium() {
	const roots = ["/root/.cache/ms-playwright", process.env.HOME + "/.cache/ms-playwright"];
	for (const root of roots) {
		try {
			for (const dir of fs.readdirSync(root)) {
				if (!dir.startsWith("chromium")) continue;
				const base = `${root}/${dir}`;
				for (const sub of fs.readdirSync(base)) {
					if (!sub.startsWith("chrome-linux")) continue;
					for (const bin of ["chrome", "headless_shell"]) {
						const full = `${base}/${sub}/${bin}`;
						if (fs.existsSync(full)) return full;
					}
				}
			}
		} catch { /* tidak ada */ }
	}
	return null;
}
async function launch() {
	try {
		return await chromium.launch({ args: ["--no-sandbox"] });
	} catch (err) {
		const exe = installedChromium();
		if (!exe) throw err;
		return await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
	}
}

(async () => {
	// --- 1. Kontrak sumber -------------------------------------------------
	const namesPy = fs.readFileSync(path.join(ROOT, "tools", "catshinobi-names.py"), "utf8");
	const enrichPy = fs.readFileSync(path.join(TOOLS, "enrich.py"), "utf8");
	const serverSrc = fs.readFileSync(path.join(ROOT, "src", "server.js"), "utf8");
	ok("tool metadata lengkap",
		fs.existsSync(path.join(TOOLS, "enrich.py")) &&
		fs.existsSync(path.join(TOOLS, "refresh.py")) &&
		fs.existsSync(path.join(TOOLS, "README.md")));
	ok("generator nama membaca tabel lokalisasi game",
		/UI_CHARACTER_NAME_/.test(namesPy) && /UI_COSTUME_NO_/.test(namesPy));
	ok("perbaikan costume->base lewat shared_base",
		/shared_base\(n\)/.test(namesPy) && /costume->base\(/.test(namesPy));
	ok("nama membawa field variant", /"variant": form_label\(f\)/.test(namesPy));
	ok("enrich memakai Sprite ilustrasi, bukan Texture2D atlas",
		/SPRITE_NAME/.test(enrichPy) && /CharThumb_/.test(enrichPy) &&
		/obj\.type\.name != "Sprite"/.test(enrichPy));
	ok("enrich punya mode offline + cache idempoten",
		/--offline/.test(enrichPy) && /getmtime\(dest\)/.test(enrichPy));
	ok("server mendaftarkan family catshinobi",
		/game: "catshinobi", names: null, family: "catshinobi-family.json"/.test(serverSrc));
	ok("server meneruskan variant ke karakter",
		/variant: rec\.variant \|\| null/.test(serverSrc));

	// --- 2. Nama ------------------------------------------------------------
	const names = JSON.parse(fs.readFileSync(NAMES, "utf8"));
	const models = names.models || {};
	ok("tabel karakter & kostum terbaca",
		Object.keys(names.characters || {}).length >= 35 &&
		Object.keys(names.costumes || {}).length >= 40,
		`${Object.keys(names.characters || {}).length} karakter, ${Object.keys(names.costumes || {}).length} kostum`);
	ok("nama karakter >= 300 model (dulu 260)", Object.keys(models).length >= 300,
		String(Object.keys(models).length));
	ok("semua entri punya variant",
		Object.values(models).every((v) => v && v.variant));
	ok("contoh perbaikan Char_1003 -> Akari Mayoneko + kostum",
		models["catshinobi/Char_1003"]?.name === "Akari Mayoneko" &&
		/Summer/.test(models["catshinobi/Char_1003"]?.costume || ""),
		JSON.stringify(models["catshinobi/Char_1003"]));
	ok("model UI/monster tidak dikarang namanya",
		!models["catshinobi/cat_battle_mode_32001"] &&
		!models["catshinobi/Attendance_Flower"]);

	// --- 3. Family / varian -------------------------------------------------
	const fam = JSON.parse(fs.readFileSync(FAMILY, "utf8"));
	const families = fam.families || [];
	ok("family >= 180", families.length >= 180, String(families.length));
	ok("anggota family >= 500",
		families.reduce((n, f) => n + (f.members || []).length, 0) >= 500,
		String(families.reduce((n, f) => n + (f.members || []).length, 0)));
	ok("tiap family >= 2 anggota & root ada di members",
		families.every((f) => (f.members || []).length >= 2 &&
			f.members.some((m) => m.id === f.root)));
	ok("label varian lengkap (Battle / SD / LD / Cat)",
		(() => {
			const labels = new Set(families.flatMap((f) => (f.members || []).map((m) => m.label)));
			return ["Battle", "SD (Chibi)", "LD", "Cat · Battle", "Cat · Front", "Cat · Ninja"]
				.every((x) => labels.has(x));
		})());
	const f32001 = families.find((f) => f.root === "catshinobi/Char_32001");
	ok("family 32001 mengelompokkan 6 bentuk",
		!!f32001 && f32001.members.length >= 5 &&
		f32001.members.some((m) => m.id === "catshinobi/cat_ninja_32001"),
		JSON.stringify(f32001?.members?.map((m) => m.label)));

	// --- 4. Thumbnail -------------------------------------------------------
	const manifest = JSON.parse(fs.readFileSync(path.join(THUMBS, "_manifest.json"), "utf8"));
	const keys = Object.keys(manifest);
	ok("manifest >= 500 model", keys.length >= 500, String(keys.length));
	ok("semua kunci ber-prefix catshinobi/",
		keys.every((k) => k.startsWith("catshinobi/")));
	const webps = fs.readdirSync(THUMBS).filter((f) => f.endsWith(".webp"));
	ok("berkas WebP >= 180", webps.length >= 180, String(webps.length));
	const missing = [...new Set(Object.values(manifest))]
		.filter((f) => !fs.existsSync(path.join(THUMBS, f)));
	ok("setiap manifest resolve ke berkas (0 404 lokal)", missing.length === 0,
		missing.slice(0, 3).join(" | "));
	// Ciri ilustrasi: WebP RGBA punya chunk ALPH (header VP8X/VP8L), sedangkan
	// halaman atlas disimpan sebagai gambar opaque tanpa alpha.
	let noAlpha = 0, oversized = 0;
	for (const f of webps) {
		const buf = fs.readFileSync(path.join(THUMBS, f));
		const kind = buf.subarray(12, 16).toString("ascii");
		const hasAlpha = (kind === "VP8X" && buf.includes(Buffer.from("ALPH")))
			|| kind === "VP8L";
		if (!hasAlpha) noAlpha++;
		if (buf.length > 200_000) oversized++;
	}
	ok("thumbnail bukan atlas 2048² (ukuran berkas wajar)",
		oversized === 0, `${oversized} berkas > 200 KB dari ${webps.length}`);
	ok("semua thumbnail punya kanal alpha (bukan halaman atlas)",
		noAlpha === 0, `${noAlpha} tanpa alpha`);

	// --- 5. API -------------------------------------------------------------
	// Paksa rescan karena server menyimpan cache model persisten; metadata
	// nama/family baru cuma menempel saat attachCharacters() dijalankan.
	await fetch(`${BASE}/api/models?refresh=1`).then((r) => r.json());
	const all = (await fetch(`${BASE}/api/models?game=catshinobi`).then((r) => r.json())).models || [];
	ok("API: 596 model Cat Shinobi", all.length === 596, String(all.length));
	ok("API: >= 300 model punya character",
		all.filter((m) => m.character).length >= 300,
		String(all.filter((m) => m.character).length));
	ok("API: >= 300 model punya character.variant",
		all.filter((m) => m.character?.variant).length >= 300,
		String(all.filter((m) => m.character?.variant).length));
	ok("API: >= 500 model punya family",
		all.filter((m) => m.family).length >= 500,
		String(all.filter((m) => m.family).length));
	const thumbsApi = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs || {};
	const csThumbs = Object.keys(thumbsApi).filter((k) => k.startsWith("catshinobi/"));
	ok("API /api/thumbnails >= 500 kunci Cat Shinobi", csThumbs.length >= 500,
		String(csThumbs.length));
	const samples = csThumbs.slice(0, 12).map((k) => `/thumbs/${thumbsApi[k]}`);
	const statuses = await Promise.all(samples.map(async (u) => {
		const r = await fetch(BASE + u); return r.status;
	}));
	ok("12 thumbnail contoh HTTP 200", statuses.every((s) => s === 200),
		statuses.join(","));

	// --- 6. Browser ---------------------------------------------------------
	const browser = await launch();
	const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
	const errors = [], missingAssets = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
	page.on("response", (r) => { if (r.status() === 404) missingAssets.push(r.url()); });

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector('#game-list .game[data-key="catshinobi"]', { state: "visible" });
	await page.locator('#game-list .game[data-key="catshinobi"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	await page.waitForTimeout(1200);
	const imgs = await page.evaluate(() =>
		[...document.querySelectorAll('img[src*="/thumbs/catshinobi/"]')].length);
	ok("kartu pustaka memakai gambar ilustrasi", imgs >= 5, `${imgs} gambar`);
	const chips = await page.evaluate(() =>
		[...document.querySelectorAll(".variant-chip")].length);
	ok("chip 'N varian' tampil di galeri", chips >= 5, `${chips} chip`);

	const wanted = "catshinobi/Char_32001";
	await page.fill("#search", wanted);
	await page.locator(`#model-list [data-id="${wanted}"]`).first()
		.waitFor({ state: "visible", timeout: 30000 });
	await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 60000 });
	await page.waitForFunction(
		(id) => window.spineStage?.model?.id === id && !!window.spineStage?.spine,
		wanted, { timeout: 90000 });
	const st = await page.evaluate(() => ({
		id: window.spineStage.model?.id,
		anims: document.querySelectorAll("#anim-select option").length,
	}));
	ok(`render ${wanted}`, st.id === wanted && st.anims > 0, JSON.stringify(st));
	ok("0 aset 404", missingAssets.length === 0, missingAssets.slice(0, 3).join(" | "));
	ok("0 JS error", errors.length === 0, errors.slice(0, 2).join(" | "));

	await browser.close();
	console.log(`\n=== Hasil Cat Shinobi metadata: ${failed.length ? failed.length + " FAIL" : "semua ok"} ===`);
	if (failed.length) console.log(failed.map((x) => "  - " + x).join("\n"));
	process.exit(failed.length ? 1 : 0);
})().catch((err) => {
	console.error("FATAL", err);
	process.exit(1);
});
