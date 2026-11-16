/**
 * Smoke test for the active Chaos Zero Nightmare library (assets/chaoszero/).
 *
 * Root komunitas `czn-rigs` / `czn-cutins-cg` sudah dipensiunkan dan dihapus;
 * test ini sengaja memakai `chaoszero`, sumber model game-side sekarang.
 * Angka jumlah model diambil dari API/UI, bukan hardcode, supaya updater bisa
 * menambah karakter tanpa bikin test kolot.
 *
 * Run: node tools/check-czn.cjs   (server on :3000)
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
	const api = await fetch(`${BASE}/api/models?game=chaoszero&lean=1`)
		.then((r) => r.json());
	const models = api.models || [];
	const named = models.filter((m) => m.character?.source === "e7bot wiki");
	const withFamily = models.filter((m) => (m.family?.members || []).length > 1);
	ok("model CZN aktif terpasang", models.length >= 1500, String(models.length));
	ok("metadata berasal dari wiki", named.length > 100 && withFamily.length > 100,
		`${named.length} bernama · ${withFamily.length} ber-varian`);
	ok("Nia ada di pustaka", models.some((m) => m.name === "Nia"));

	const thumbsDir = path.join(ROOT, "public", "thumbs", "chaoszero");
	const manifest = JSON.parse(fs.readFileSync(path.join(thumbsDir, "_manifest.json"), "utf8"));
	const thumbIds = Object.keys(manifest);
	const modelIds = new Set(models.map((m) => m.id));
	ok("manifest thumbnail valid", thumbIds.length > 100 &&
		thumbIds.every((id) => modelIds.has(id)), `${thumbIds.length} entri`);
	ok("berkas thumbnail ada semua", Object.values(manifest).every((f) =>
		fs.existsSync(path.join(thumbsDir, f))));

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(120000);
	const errors = [], missingAssets = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|png|atlas|json|skel)(\?|$)/.test(r.url()))
			missingAssets.push(`${r.status()} ${r.url()}`);
	});

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible", timeout: 90000 });
	const gameCard = page.locator('#game-list .game[data-key="chaoszero"]');
	ok("kartu game CZN tampil", await gameCard.count() === 1);
	await gameCard.click();
	await page.waitForSelector("#model-list li > button:not(.model-fav)",
		{ state: "visible", timeout: 90000 });
	await page.waitForTimeout(1200);

	const ui = await page.evaluate(() => ({
		isGrid: document.getElementById("model-list").classList.contains("is-gallery") &&
			document.getElementById("view-grid-btn").classList.contains("is-on"),
		filtersVisible: !document.querySelector("#czn-filters").hidden,
		selects: document.querySelectorAll("#czn-filters select").length,
		icons: document.querySelectorAll("#czn-filters .czn-icon").length,
		iconImgs: document.querySelectorAll("#czn-filters .czn-icon img").length,
		brokenIcons: [...document.querySelectorAll("#czn-filters .czn-icon img")]
			.filter((i) => !i.complete || !i.naturalWidth).length,
		tabs: Object.fromEntries([...document.querySelectorAll("#czn-filters .czn-tab-count")]
			.map((s) => [s.dataset.count, Number(s.textContent)])),
	}));
	ok("default tampilan galeri (grid)", ui.isGrid);
	ok("panel filter CZN tampil", ui.filtersVisible);
	ok("filter berupa ikon, bukan dropdown", ui.selects === 0 && ui.icons === 14,
		JSON.stringify({ selects: ui.selects, icons: ui.icons }));
	ok("semua ikon termuat", ui.iconImgs > 0 && ui.brokenIcons === 0,
		`${ui.iconImgs} ikon`);
	ok("tab all/combatant/partner terisi",
		ui.tabs.all > 100 && ui.tabs.combatant > 0 && ui.tabs.partner > 0,
		JSON.stringify(ui.tabs));

	const first = page.locator("#model-list li > button:not(.model-fav)").first();
	const thumbOk = await first.evaluate((b) => {
		const img = b.querySelector("img");
		return !!img && img.complete && img.naturalWidth > 0;
	});
	ok("thumbnail kartu termuat", thumbOk);
	await first.click();
	await page.waitForFunction(() => !!window.spineStage?.spine?.skeleton,
		null, { timeout: 90000 });
	const st = await page.evaluate(() => ({
		id: window.spineStage.model?.id,
		anims: document.querySelectorAll("#anim-select option").length,
		variants: window.spineStage.model?.family?.members?.length || 0,
		alt: document.querySelector("#variant-select")?.options?.length || 0,
	}));
	ok("model Spine benar-benar ter-render", !!st.id, JSON.stringify(st));
	ok("animasi tersedia", st.anims > 0, String(st.anims));
	ok("varian tersedia", st.alt > 1, String(st.alt));

	const visibleIds = () => page.evaluate(() =>
		[...document.querySelectorAll("#model-list li > button:not(.model-fav)")]
			.map((b) => b.dataset.id));
	const byId = new Map(models.map((m) => [m.id, m]));
	const checkGroup = async (group, want) => {
		await page.click(`#czn-filters .czn-tab[data-group="${group}"]`);
		const ids = await visibleIds();
		ok(`tab ${group}: hanya ${want}`, ids.length > 0 &&
			ids.every((id) => byId.get(id)?.charType === want), `${ids.length} kartu`);
	};
	await checkGroup("combatant", "CHAR_COMBATANT");
	await checkGroup("partner", "CHAR_SUPPORTER");
	await page.click('#czn-filters .czn-tab[data-group="all"]');
	// Pustaka sekarang >1000 kartu root, jadi grid cuma menampilkan satu halaman.
	// Bandingkan dengan jumlah yang terlihat, bukan total di counter.
	const baseShown = await visibleIds();

	const egoIcon = '#czn-filters .czn-icon[data-kind="ego"][data-value="instinct"]';
	await page.click(egoIcon);
	let shown = await visibleIds();
	ok("filter ikon ego=instinct", shown.length > 0 &&
		shown.every((id) => byId.get(id)?.ego === "instinct"), `${shown.length} kartu`);
	await page.click(egoIcon);
	shown = await visibleIds();
	ok("klik lagi mematikan filter", shown.length === baseShown.length,
		`${shown.length} vs ${baseShown.length} kartu`);

	await page.click("#czn-reset");
	shown = await visibleIds();
	ok("reset mengembalikan semua", shown.length === baseShown.length,
		`${shown.length} vs ${baseShown.length} kartu`);
	const rarityOrder = shown.map((id) => Number(byId.get(id)?.rarity) || 0);
	ok("urut rarity menurun", rarityOrder.every((v, i) =>
		i === 0 || rarityOrder[i - 1] >= v), rarityOrder.slice(0, 12).join(","));

	await page.click("#back-btn");
	ok("panel filter hilang di daftar game",
		await page.locator("#czn-filters").isHidden());
	ok("0 JS error", errors.length === 0, errors.slice(0, 2).join(" | "));
	ok("0 aset 404", missingAssets.length === 0, missingAssets.slice(0, 2).join(" | "));
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nCZN aktif (chaoszero) ok");
})().catch((err) => { console.error(err); process.exit(1); });
