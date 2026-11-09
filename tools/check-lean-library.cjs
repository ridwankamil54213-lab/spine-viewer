/**
 * Smoke test for the two-level model library.
 *
 * Boot loads `GET /api/models?lean=1` (index only); opening a model fetches
 * `GET /api/models/:id` and merges the full record into the SAME object, so
 * variants / A/B / permalinks that look models up by id keep working.
 *
 * Also covers the keyboard shortcuts that used to be dead because their case
 * labels duplicated an earlier case in the keydown switch (X, V, Y, Shift+E).
 *
 * Run: node tools/check-lean-library.cjs   (server on :3000)
 */
const { chromium } = require("playwright-core");

const checks = [];
const ok = (label, cond, extra = "") => {
	checks.push({ label, cond: !!cond });
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

(async () => {
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(120000);
	page.setDefaultNavigationTimeout(120000);
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));

	const indexUrls = [];
	const detailUrls = [];
	page.on("request", (r) => {
		const u = r.url();
		if (!u.includes("/api/models")) return;
		(u.includes("/api/models/") ? detailUrls : indexUrls).push(u);
	});

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible" });

	// 1. boot uses exactly one lean index request, no per-model detail yet
	ok("one index request at boot", indexUrls.length === 1, indexUrls[0] || "none");
	ok("index is lean", indexUrls[0]?.includes("lean=1"));
	ok("no detail request at boot", detailUrls.length === 0, `${detailUrls.length}`);

	// Baca bentuk payload dari Node, bukan lewat CDP: body ~11 MB ini sering
	// ke-evict dari cache inspector sebelum halaman selesai merender.
	const idx = await fetch("http://127.0.0.1:3000/api/models?lean=1").then((r) => r.json());
	ok("index response readable", !!idx && Array.isArray(idx.models));
	const first = idx?.models?.[0] || {};
	// Jangan hardcode jumlah model: game bisa ditambah/dihapus. Invariant yang
	// penting justru indeks ringan TIDAK BOLEH kehilangan entri dibanding respons penuh.
	const full = await fetch("http://127.0.0.1:3000/api/models").then((r) => r.json());
	ok("lean index covers every model",
		(idx?.models?.length || 0) > 0 && idx.models.length === full.models.length,
		`lean ${idx?.models?.length || 0} vs full ${full.models.length}`);
	ok("index carries animCount", typeof first.animCount === "number", String(first.animCount));
	ok("index omits skeleton detail", !("skeletonFile" in first) && !("animations" in first));
	ok("index keeps family/variants", !!first.family || (idx?.models || []).some((m) => m.family?.members?.length));

	// 2. opening a model pulls its full record into the card's object
	await page.click("#game-list .game");
	await page.waitForSelector("#model-list li > button:not(.model-fav)", { state: "visible" });
	await page.click("#model-list li > button:not(.model-fav)");
	await page.waitForFunction(() => !!window.spineStage?.model?.id, null, { timeout: 60000 });

	const loaded = await page.evaluate(() => {
		const m = window.spineStage.model;
		return {
			id: m.id,
			hasAnimations: Array.isArray(m.animations),
			hasAnimCount: typeof m.animCount === "number",
			hasSpine: !!window.spineStage.spine?.skeleton,
		};
	});
	ok("one detail request after opening", detailUrls.length === 1, detailUrls[0] || "none");
	ok("detail merged into the same object", loaded.hasAnimations, JSON.stringify(loaded));
	ok("model actually rendered", loaded.hasSpine);

	// 3. A/B loads model B the same way (it may come from another game).
	// Objek { id } sengaja dipakai: di permalink A/B memang cuma punya id,
	// jadi ini menguji bahwa ensureModelDetail() menghidrasi objek baru.
	const idB = await page.evaluate(() => {
		const cards = document.querySelectorAll("#model-list li > button:not(.model-fav)");
		return cards[1]?.dataset.id || window.spineStage.model.id;
	});
	await page.evaluate(async (id) => { await window.spineStage.abStart({ id }); }, idB);
	await page.waitForTimeout(600);
	const ab = await page.evaluate(() => ({
		on: window.spineStage.ab.on,
		hasB: !!window.spineStage.ab.model.B,
		animsB: Array.isArray(window.spineStage.ab.model.B?.animations),
	}));
	ok("A/B started", ab.on);
	ok("model B got its detail", ab.animsB, JSON.stringify(ab));
	ok("second detail request for B", detailUrls.length === 2, String(detailUrls.length));
	await page.evaluate(() => window.spineStage.abTeardown());

	// 4. shortcut dispatch — every one of these used to be shadowed
	const blur = () => page.evaluate(() => document.activeElement?.blur?.());
	const flag = (sel) => page.getAttribute(sel, "data-on");
	const gridOn = () => page.evaluate(() =>
		document.getElementById("view-grid-btn").classList.contains("is-on"));

	await blur();
	const grid0 = await gridOn();
	await page.keyboard.press("x");
	ok("X toggles library layout", (await gridOn()) !== grid0, `${grid0} -> ${await gridOn()}`);
	await page.keyboard.press("x");
	ok("X toggles back", (await gridOn()) === grid0);

	const vtx0 = await page.evaluate(() => window.__spineStage.vtx.on);
	await page.keyboard.press("v");
	ok("V toggles vertex editor", (await page.evaluate(() => window.__spineStage.vtx.on)) !== vtx0);
	await page.keyboard.press("v");

	const tip0 = await flag("#slot-tip-btn");
	await page.keyboard.press("y");
	ok("Y toggles slot names", (await flag("#slot-tip-btn")) !== tip0, `${tip0} -> ${await flag("#slot-tip-btn")}`);
	await page.keyboard.press("y");

	const bone0 = await flag("#bone-edit-btn");
	await page.keyboard.press("Shift+E");
	ok("Shift+E toggles bone editor", (await flag("#bone-edit-btn")) !== bone0, `${bone0} -> ${await flag("#bone-edit-btn")}`);
	await page.keyboard.press("Shift+E");

	const tl0 = await flag("#timeline-btn");
	await page.keyboard.press("t");
	ok("T still toggles timeline", (await flag("#timeline-btn")) !== tl0);
	await page.keyboard.press("t");

	await page.keyboard.press("e");
	ok("E still opens export", await page.isVisible("#export-modal"));
	await page.keyboard.press("Escape");

	console.log("\njs errors:", errors.length ? errors.join(" | ") : "none");
	await browser.close();
	const failed = checks.filter((c) => !c.cond);
	if (failed.length || errors.length) {
		console.error(`FAILED: ${failed.length} check(s), ${errors.length} js error(s)`);
		process.exit(1);
	}
	console.log(`\nlean library ok (${checks.length} checks)`);
})().catch((err) => {
	console.error(err);
	process.exit(1);
});
