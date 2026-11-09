/**
 * Smoke test for the Chaos Zero Nightmare library.
 *
 * Verifies the whole chain built by tools/czn/refresh.py + capture-thumbs.cjs:
 *   - only rigs belonging to the wiki roster (combatants + partners) exist
 *   - names come from the wiki, rigs are grouped into families with variants
 *   - every model has a 260x460 thumbnail that actually loads
 *   - a model really renders on the stage with no missing assets / JS errors
 *
 * Run: node tools/check-czn.cjs   (server on :3000)
 */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

(async () => {
	const api = await fetch("http://127.0.0.1:3000/api/models?game=czn-rigs").then((r) => r.json());
	const models = api.models || [];
	const roster = JSON.parse(fs.readFileSync(path.join(ROOT, "assets/czn-rigs/_names.json"), "utf8"));
	const ids = new Set(Object.keys(roster).map((s) => `czn-rigs/${s}`));
	ok("322 rig terpasang", models.length === 322, String(models.length));
	ok("semua rig punya nama katalog", models.every((m) => ids.has(m.id)));
	ok("nama berasal dari wiki", models.some((m) => m.character?.name === "Nia"),
		(models.find((m) => m.character?.name === "Nia") || {}).name || "tidak ada");
	const families = models.filter((m) => m.family?.members?.length > 1);
	ok("varian terkelompok per karakter", families.length > 0, `${families.length} keluarga`);

	const thumbsDir = path.join(ROOT, "public/thumbs/czn-rigs");
	const manifest = JSON.parse(fs.readFileSync(path.join(thumbsDir, "_manifest.json"), "utf8"));
	ok("manifest mencakup semua rig", Object.keys(manifest).length === models.length,
		`${Object.keys(manifest).length} vs ${models.length}`);
	ok("file thumbnail ada semua", Object.values(manifest).every((f) => fs.existsSync(path.join(thumbsDir, f))));

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(120000);
	const errors = [];
	const missingAssets = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|png|atlas|json|skel)(\?|$)/.test(r.url()))
			missingAssets.push(`${r.status()} ${r.url()}`);
	});

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible" });
	const gameCard = page.locator('#game-list .game[data-key="czn-rigs"]');
	ok("kartu game CZN tampil", await gameCard.count() === 1);
	await gameCard.click();
	await page.waitForSelector("#model-list li > button:not(.model-fav)", { state: "visible" });
	const thumbOk = await page.evaluate(() => {
		const img = document.querySelector("#model-list li > button:not(.model-fav) img");
		return !!img && img.complete && img.naturalWidth === 260 && img.naturalHeight === 460;
	});
	ok("thumbnail terbuka 260x460", thumbOk);
	await page.click("#model-list li > button:not(.model-fav)");
	await page.waitForFunction(() => !!window.spineStage?.spine?.skeleton, null, { timeout: 90000 });
	const st = await page.evaluate(() => ({
		id: window.spineStage.model?.id,
		name: window.spineStage.model?.name,
		anims: document.querySelectorAll("#anim-select option").length,
		variants: window.spineStage.model?.family?.members?.length || 0,
		alt: document.querySelector("#variant-select")?.options?.length || 0,
	}));
	ok("model Spine benar-benar ter-render", !!st.id, JSON.stringify(st));
	ok("animasi tersedia", st.anims > 0, String(st.anims));
	ok("dropdown varian terisi", st.alt > 1, String(st.alt));
	ok("tidak ada aset 404", missingAssets.length === 0, missingAssets.slice(0, 3).join(" | "));

	// --- default galeri + tab/filter Combatants-Partner -------------------
	const isGrid = await page.evaluate(() =>
		document.getElementById("model-list").classList.contains("is-gallery") &&
		document.getElementById("view-grid-btn").classList.contains("is-on"));
	ok("default tampilan galeri (grid)", isGrid);
	ok("panel filter CZN tampil", await page.locator("#czn-filters").isVisible());
	const iconUi = await page.evaluate(() => ({
		selects: document.querySelectorAll("#czn-filters select").length,
		icons: document.querySelectorAll("#czn-filters .czn-icon").length,
		imgs: document.querySelectorAll("#czn-filters .czn-icon img").length,
		broken: [...document.querySelectorAll("#czn-filters .czn-icon img")]
			.filter((i) => !i.complete || !i.naturalWidth).length,
	}));
	ok("filter berupa ikon, bukan dropdown",
		iconUi.selects === 0 && iconUi.icons === 14, JSON.stringify(iconUi));
	ok("semua ikon termuat", iconUi.imgs > 0 && iconUi.broken === 0, JSON.stringify(iconUi));
	const counts = await page.evaluate(() =>
		Object.fromEntries([...document.querySelectorAll("#czn-filters .czn-tab-count")]
			.map((s) => [s.dataset.count, Number(s.textContent)])));
	ok("jumlah tab 89 / 39 / 50",
		counts.all === 89 && counts.combatant === 39 && counts.partner === 50,
		JSON.stringify(counts));

	const byId = new Map(models.map((m) => [m.id, m]));
	const visibleIds = () => page.evaluate(() =>
		[...document.querySelectorAll("#model-list li > button:not(.model-fav)")].map((b) => b.dataset.id));
	const checkGroup = async (group, want) => {
		await page.click(`#czn-filters .czn-tab[data-group="${group}"]`);
		const ids = await visibleIds();
		ok(`tab ${group}: hanya ${want}`,
			ids.length > 0 && ids.every((id) => byId.get(id)?.charType === want),
			`${ids.length} kartu`);
	};
	await checkGroup("combatant", "CHAR_COMBATANT");
	await checkGroup("partner", "CHAR_SUPPORTER");
	await page.click('#czn-filters .czn-tab[data-group="all"]');

	const egoIcon = '#czn-filters .czn-icon[data-kind="ego"][data-value="instinct"]';
	await page.click(egoIcon);
	let shown = await visibleIds();
	ok("filter ikon ego=instinct", shown.length > 0 && shown.every((id) => byId.get(id)?.ego === "instinct"),
		`${shown.length} kartu`);
	await page.click(egoIcon);
	shown = await visibleIds();
	ok("klik lagi mematikan filter", shown.length === 89, `${shown.length} kartu`);

	await page.click('#czn-filters .czn-icon[data-kind="rarity"][data-value="5"]');
	shown = await visibleIds();
	ok("filter ikon rarity 5★", shown.length > 0 && shown.every((id) => String(byId.get(id)?.rarity) === "5"),
		`${shown.length} kartu`);
	await page.click("#czn-reset");
	shown = await visibleIds();
	ok("reset mengembalikan semua", shown.length === 89, `${shown.length} kartu`);
	const rarityOrder = shown.map((id) => Number(byId.get(id)?.rarity) || 0);
	ok("urut rarity menurun",
		rarityOrder.every((v, i) => i === 0 || rarityOrder[i - 1] >= v),
		rarityOrder.slice(0, 12).join(","));
	ok("kartu pertama 5★", rarityOrder[0] === 5, String(rarityOrder[0]));

	await page.click("#back-btn");
	ok("panel filter hilang di daftar game", await page.locator("#czn-filters").isHidden());
	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	if (errors.length) failed.push("js errors");
	if (missingAssets.length) failed.push("aset 404");
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log(`\nCZN ok`);
})().catch((err) => {
	console.error(err);
	process.exit(1);
});
