/**
 * Smoke test: unduh ulang Nikke dari ArtHub `nikki`.
 *
 * Membuktikan:
 *   - 2104 model, TANPA id duplikat (keluhan awal user)
 *   - tiap folder punya <id>.skel + <id>.atlas + semua halaman yang disebut atlas
 *   - nama & metadata dari _names.json / katalog ArtHub
 *   - model Spine 4.1.20 benar-benar ter-render, 0 aset 404
 *     (khususnya atlas ber-BOM dan Glass_Front yang sempat 500)
 *   - updater --check stabil lewat endpoint HTTP, updater lama tidak terdaftar
 *
 * Run: node tools/check-nikke.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const BASE = "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const ASSETS = path.join(ROOT, "assets/nikke");
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

const pageLines = (atlasPath) => {
	const text = fs.readFileSync(atlasPath, "utf8").replace(/^\uFEFF/, "");
	return [...new Set(text.split(/\r?\n/)
		.map((l) => l.trim().replace(/^\uFEFF/, "").trim())
		.filter((l) => /\.(png|webp|jpe?g)$/i.test(l) && !l.includes("/") && !l.includes("\\")))];
};

(async () => {
	const models = (await fetch(`${BASE}/api/models?lean=1`).then((r) => r.json())).models || [];
	const nikke = models.filter((m) => m.game === "nikke");
	const ids = nikke.map((m) => m.id);
	const names = JSON.parse(fs.readFileSync(path.join(ASSETS, "_names.json"), "utf8"));

	// Katalog NKAS bisa bertambah kapan saja. Angka 2104 adalah BASELINE, bukan
	// angka beku: yang wajib dijaga adalah tidak ada yang HILANG.
	ok(">= 2104 model Nikke", nikke.length >= 2104, String(nikke.length));
	ok("tidak ada id duplikat", new Set(ids).size === ids.length,
		`${new Set(ids).size} unik / ${ids.length}`);
	ok("tidak ada model legacy 2.1", nikke.every((m) => !m.needsLegacyViewer));
	ok("_names.json >= 2104 entri", Object.keys(names).length >= 2104,
		String(Object.keys(names).length));
	// tools/nikke/refresh.py menulis nama untuk SELURUH katalog NKAS, termasuk
	// model yang belum di-apply. Selisih kecil itu wajar; yang tidak boleh
	// terjadi adalah ada model TERPASANG tanpa nama.
	const dangling = Object.keys(names).filter((k) => !ids.includes(k));
	ok("semua model terpasang punya nama & selisih katalog <= 10",
		ids.every((k) => k in names) && dangling.length <= 10,
		`${dangling.length} kunci katalog belum terpasang`);
	ok("semua model bernama sumber NKAS /nikkes/",
		nikke.every((m) => /nkas\.pages\.dev\/nikkes/.test((m.character || {}).source || "")));
	// Nama karakter wajib Inggris: dulu 88 nama + 1055 label tipe masih Tionghoa.
	const CJK = /[\u4e00-\u9fff]/;
	const cjk = Object.entries(names).filter(([, v]) =>
		["name", "display", "characterName", "typeLabel"]
			.some((f) => CJK.test(String(v[f] || ""))));
	ok("0 aksara Tionghoa di 2104 nama", cjk.length === 0, JSON.stringify(cjk.slice(0, 3)));
	ok("nama dari NKAS /nikkes/",
		Object.values(names).filter((v) => /^nkas-/.test(v.nameSource)).length >= 1600,
		String(Object.values(names).filter((v) => /^nkas-/.test(v.nameSource)).length));
	ok("contoh nama Inggris", names["nikke/c010_00"].name === "Rapi" &&
		names["nikke/c013_00"].name === "Marian" &&
		names["nikke/c160_00"].name === "Yuni",
		[names["nikke/c010_00"].name, names["nikke/c013_00"].name,
			names["nikke/c160_00"].name].join("/"));
	// Regresi: url "eve" pernah nyangkut di prefix "EventScene" (123 kartu).
	ok("EventScene tidak jadi EVE, tanpa nama kode polos",
		names["nikke/EventScene_ACPUFreeze_01"].name.startsWith("EventScene") &&
		Object.values(names).filter((v) => v.name === "EVE").length === 14 &&
		!Object.values(names).some((v) => /^C\d{3}$/.test(v.name)),
		String(Object.values(names).filter((v) => v.name === "EVE").length));

	// Integritas berkas: skel + atlas + semua halaman yang dipanggil atlas.
	let incomplete = [];
	for (const id of ids) {
		const leaf = id.split("/").pop();
		const d = path.join(ASSETS, leaf);
		const skel = path.join(d, `${leaf}.skel`);
		const atlas = path.join(d, `${leaf}.atlas`);
		if (!fs.existsSync(skel) || !fs.existsSync(atlas)) {
			incomplete.push(`${leaf}: skel/atlas`);
			continue;
		}
		for (const p of pageLines(atlas)) {
			if (!fs.existsSync(path.join(d, p))) incomplete.push(`${leaf}: ${p}`);
		}
	}
	ok("2104 folder lengkap (skel + atlas + halaman)", incomplete.length === 0,
		incomplete.slice(0, 4).join(" | ") || `${ids.length} folder`);

	// Kasus yang sempat gagal saat unduh: atlas ber-BOM & HTTP 500.
	for (const leaf of ["c010_00", "Glass_Front", "Chapter4_Glass_Back2", "c011_cover_00"]) {
		ok(`kasus ${leaf} lengkap`, fs.existsSync(path.join(ASSETS, leaf, `${leaf}.skel`)) &&
			fs.existsSync(path.join(ASSETS, leaf, `${leaf}.atlas`)));
	}

	// --- varian aim / cover / skillcut -------------------------------------
	const withFamily = nikke.filter((m) => (m.family || {}).members?.length);
	const rootIds = new Set(withFamily.map((m) => m.family.root));
	ok("391 family karakter", rootIds.size === 391, String(rootIds.size));
	ok("1406 model jadi varian", withFamily.length === 1406, String(withFamily.length));
	ok("1089 kartu root di pustaka", nikke.length - withFamily.length + rootIds.size === 1089,
		String(nikke.length - withFamily.length + rootIds.size));
	const root = nikke.find((m) => m.id === "nikke/c010_00");
	const labels = (root?.family?.members || []).map((x) => x.label);
	ok("c010_00: Utama + Aim + Cover + Skill Cut",
		labels.some((l) => l === "Utama") && labels.some((l) => /^Aim/.test(l)) &&
		labels.some((l) => /^Cover/.test(l)) && labels.some((l) => /Skill Cut/.test(l)),
		JSON.stringify(labels));
	ok("aim/cover/skillcut bukan kartu root",
		["nikke/c010_aim_00", "nikke/c010_cover_00", "nikke/c011_00_skillcut"].every((id) =>
			(nikke.find((m) => m.id === id)?.family?.root || id) !== id));

	// --- thumbnail ---------------------------------------------------------
	const THUMBS = path.join(ROOT, "public/thumbs/nikke");
	const man = JSON.parse(fs.readFileSync(path.join(THUMBS, "_manifest.json"), "utf8"));
	const thumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs || {};
	ok("manifest >= 2104 thumbnail", Object.keys(man).length >= 2104,
		String(Object.keys(man).length));
	const danglingThumbs = Object.keys(man).filter((k) => !ids.includes(k));
	ok("kunci manifest valid (selisih katalog <= 10, coverage penuh)",
		danglingThumbs.length <= 10 && ids.filter((k) => k in man).length >= 2104,
		`${danglingThumbs.length} kunci katalog belum terpasang`);
	ok("semua berkas thumbnail ada",
		Object.values(man).every((f) => fs.existsSync(path.join(THUMBS, f))));
	ok("/api/thumbnails memuat >= 2104 kunci nikke",
		Object.keys(thumbs).filter((k) => k.startsWith("nikke/")).length >= 2104,
		String(Object.keys(thumbs).filter((k) => k.startsWith("nikke/")).length));

	const chk = await fetch(`${BASE}/api/update/nikke?mode=check`).then((r) => r.json());
	const chk2 = await fetch(`${BASE}/api/update/nikke?mode=check`).then((r) => r.json());
	// Katalog ArtHub bisa bertambah kapan saja (pernah 2104 -> 2110). Yang diuji
	// di sini KONTRAK endpointnya, bukan angka beku: dua --check berturut harus
	// identik, delta `new` harus sama dengan selisih katalog remote vs folder
	// lokal, dan ada model baru => wajib changed:true.
	ok("updater baru --check stabil via HTTP",
		chk.ok === true && chk2.ok === true &&
		chk.changed === chk2.changed && chk.new === chk2.new &&
		chk.expected === chk2.expected &&
		chk.new === Math.max(0, chk.expected - ids.length) &&
		(chk.new === 0 || chk.changed === true),
		JSON.stringify({ ok: chk.ok, changed: chk.changed, new: chk.new,
			expected: chk.expected, lokal: ids.length }));
	// Updater kini berpusat ke NKAS: daftar karakter kanonik ikut dipantau.
	ok("updater memantau sumber NKAS /nikkes/",
		chk.nkas?.sumber === "nkas.pages.dev/nikkes" &&
		chk.nkas.karakter === 206 && chk.nkas.kode === 206 &&
		chk.nkas.namaTerpakai >= 1600 && Array.isArray(chk.nkas.baru),
		JSON.stringify({ sumber: chk.nkas?.sumber, karakter: chk.nkas?.karakter,
			namaTerpakai: chk.nkas?.namaTerpakai }));
	ok("updater state menyimpan sidik NKAS terpisah",
		fs.existsSync(path.join(ROOT, "data/nikke-update-state.json")) &&
		/^[0-9a-f]{16}$/.test(
			JSON.parse(fs.readFileSync(path.join(ROOT, "data/nikke-update-state.json"),
				"utf8")).nkasSig || ""),
		"");

	// --- browser: buktikan render, bukan cuma terdaftar --------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(90000);
	const errors = [];
	const missing = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(png|webp|atlas|json|skel)(\?|$)/.test(r.url()))
			missing.push(`${r.status()} ${r.url()}`);
	});

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector('#game-list .game[data-key="nikke"]', { state: "visible" });
	await page.locator('#game-list .game[data-key="nikke"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });

	const cardThumb = await page.evaluate(() => {
		const img = document.querySelector(
			"#model-list li > button:not(.model-fav) img, #model-list .gcard img");
		return img ? { src: img.getAttribute("src"), complete: img.complete,
			w: img.naturalWidth } : null;
	});
	// Kartu karakter bisa memakai potret Prydwen (override manifest) atau
	// thumbnail ArtHub lama untuk aset non-karakter; dua-duanya valid.
	ok("thumbnail ter-render di kartu Nikke",
		cardThumb && cardThumb.complete && cardThumb.w > 0 &&
		/\/thumbs\/nikke(?:-prydwen)?\//.test(cardThumb.src), JSON.stringify(cardThumb));

	for (const wanted of ["nikke/c010_00", "nikke/Glass_Front", "nikke/Chapter4_Glass_Back2"]) {
		await page.fill("#search", wanted);
		await page.locator(`#model-list [data-id="${wanted}"]`).first()
			.waitFor({ state: "visible", timeout: 25000 });
		await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 60000 });
		// Jangan cuma tunggu skeleton: model sebelumnya masih keburu aktif
		// sesaat setelah klik, jadi tunggu id-nya benar-benar berganti.
		await page.waitForFunction(
			(id) => window.spineStage?.model?.id === id && !!window.spineStage?.spine?.skeleton,
			wanted, { timeout: 90000 });
		const st = await page.evaluate(() => ({
			id: window.spineStage.model?.id,
			anims: document.querySelectorAll("#anim-select option").length,
			ver: document.querySelector("#hud")?.textContent?.slice(0, 120) || "",
		}));
		ok(`render ${wanted}`, st.id === wanted, JSON.stringify(st));
		ok(`animasi ${wanted}`, st.anims > 0, String(st.anims));
	}

	// Picker varian: c010_00 punya 4 anggota -> popup (bukan tab segmented).
	await page.fill("#search", "nikke/c010_00");
	await page.locator('#model-list [data-id="nikke/c010_00"]').first()
		.waitFor({ state: "visible", timeout: 25000 });
	await page.locator('#model-list [data-id="nikke/c010_00"]').first().click({ timeout: 60000 });
	await page.waitForFunction(
		() => window.spineStage?.model?.id === "nikke/c010_00" &&
			!!window.spineStage?.spine?.skeleton, null, { timeout: 90000 });
	const vp = await page.evaluate(() => ({
		variants: document.querySelector("#variant-select")?.options?.length || 0,
		btnHidden: document.querySelector("#variant-btn")?.hidden,
		tabsHidden: document.querySelector("#variant-tabs")?.hidden,
	}));
	ok("picker varian: 4 varian, popup (bukan tab)",
		vp.variants === 4 && vp.btnHidden === false && vp.tabsHidden !== false,
		JSON.stringify(vp));
	await page.locator("#variant-btn").click();
	await page.waitForSelector("#variant-popup:not([hidden])", { state: "visible", timeout: 20000 });
	const pop = await page.evaluate(() => ({
		rows: document.querySelectorAll("#variant-popup .variant-item").length,
		thumbs: [...document.querySelectorAll("#variant-popup .variant-item img")]
			.filter((i) => i.complete && i.naturalWidth > 0).length,
		labels: [...document.querySelectorAll("#variant-popup .variant-item-label")]
			.map((n) => n.textContent.trim()),
	}));
	ok("popup varian 4 baris", pop.rows === 4, String(pop.rows));
	ok("popup memuat Aim / Cover / Skill Cut",
		pop.labels.some((l) => /Aim/.test(l)) && pop.labels.some((l) => /Cover/.test(l)) &&
		pop.labels.some((l) => /Skill Cut/.test(l)), JSON.stringify(pop.labels));
	ok("thumbnail varian termuat", pop.thumbs >= 3, String(pop.thumbs));

	ok("tidak ada aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));
	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	if (errors.length) failed.push("js errors");
	if (missing.length) failed.push("aset 404");
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nNikke (ArtHub) ok");
})().catch((e) => { console.error(e); process.exit(1); });
