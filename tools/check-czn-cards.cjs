/**
 * Smoke test for CZN skill cards (sumber data: /api/czn/cards/list wiki e7bot).
 *
 * Verifies:
 *   - index.json hasil tools/czn/refresh-cards.py terbaca 39 karakter
 *   - metadata wiki (name/ego/rarity/cost) ikut ke API
 *   - ilustrasi .webp, animasi .webm, dan frame ego/rarity semuanya 200
 *   - tombol Kartu muncul untuk model CZN, shortcut K membuka panel,
 *     petak kartu tampil dengan nama kartu sebagai tooltip
 *
 * Run: node tools/check-czn-cards.cjs   (server on :3000)
 */
const { chromium } = require("playwright-core");

const BASE = "http://127.0.0.1:3000";
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

(async () => {
	const summary = await fetch(`${BASE}/api/czn-cards`).then((r) => r.json());
	const ids = Object.keys(summary.chars || {});
	ok("39 karakter punya kartu", ids.length === 39, String(ids.length));
	ok("id numerik + nama + ego", ids.every((id) =>
		/^\d+$/.test(id) && summary.chars[id].name && summary.chars[id].ego));
	ok("semua karakter punya kartu", ids.every((id) => summary.chars[id].count > 0));

	const det = await fetch(`${BASE}/api/czn-cards/1003`).then((r) => r.json());
	ok("detail Nia berisi kartu", det.cards.length > 0, String(det.cards.length));
	ok("metadata wiki lengkap", det.cards.every((c) =>
		c.name && c.ego && c.rarity && c.url && typeof c.cost === "number"));
	ok("deskripsi wiki ikut ke API", det.cards.every((c) =>
		c.desc && c.descHtml && Array.isArray(c.descs) && c.descs.length > 0));
	ok("markup warna wiki diterjemahkan", det.cards.some((c) =>
		/span style="color:#FF8C00"/.test(c.descHtml)));
	ok("varian epiphany tersimpan", det.cards.some((c) => c.descCount > 1),
		`maks ${Math.max(...det.cards.map((c) => c.descCount || 0))} varian`);
	ok("HTML deskripsi aman", det.cards.every((c) =>
		!/<script|onerror=|javascript:/i.test(c.descHtml)));
	ok("ada versi animasi", det.cards.some((c) => c.video && c.videoUrl));

	const imgRes = await fetch(BASE + det.cards[0].url);
	ok("ilustrasi .webp 200", imgRes.status === 200 &&
		/image\/webp/.test(imgRes.headers.get("content-type") || ""),
		`${imgRes.status} ${imgRes.headers.get("content-type")}`);
	const vid = det.cards.find((c) => c.video);
	if (vid) {
		const vr = await fetch(BASE + vid.videoUrl);
		ok("animasi .webm 200", vr.status === 200 &&
			/video\/webm/.test(vr.headers.get("content-type") || ""),
			`${vr.status} ${vr.headers.get("content-type")}`);
	} else ok("animasi .webm 200", false, "tidak ada kartu video");

	const framePaths = [
		...["instinct", "norms", "love", "creed", "narcissism"]
			.map((e) => `/czn-frame/card_ego_${e}.webp`),
		...["common", "rare", "legend", "unique"]
			.map((r) => `/czn-frame/card_rarity_${r}.webp`),
	];
	const frameCodes = await Promise.all(framePaths.map(async (p) =>
		(await fetch(BASE + p)).status));
	ok("9 frame ego/rarity 200", frameCodes.every((s) => s === 200),
		frameCodes.join(","));

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(120000);
	const errors = [];
	const missing = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|webm|png)(\?|$)/.test(r.url()))
			missing.push(`${r.status()} ${r.url()}`);
	});

	await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible" });
	await page.evaluate(() =>
		document.querySelector('#game-list .game[data-key="czn-rigs"]').click());
	await page.waitForSelector("#model-list li > button:not(.model-fav)", { state: "visible" });
	const targetId = await page.evaluate((ids) => {
		const set = new Set(ids);
		const cards = [...document.querySelectorAll("#model-list li > button:not(.model-fav)")];
		return cards.find((b) => {
			const nums = (b.dataset.id || "").match(/\d{3,6}/g) || [];
			return nums.some((n) => set.has(n));
		})?.dataset.id || null;
	}, ids);
	ok("ada model CZN yang punya kartu", !!targetId, targetId || "tidak ada");

	await page.click(`#model-list li > button:not(.model-fav)[data-id="${targetId}"]`);
	await page.waitForFunction(() => !!window.spineStage?.model?.id, null, { timeout: 90000 });
	await page.waitForFunction(() => {
		const b = document.getElementById("cards-btn");
		return b && !b.hidden;
	}, null, { timeout: 20000 });
	ok("tombol Kartu muncul", true);

	await page.evaluate(() => document.activeElement?.blur?.());
	await page.keyboard.press("k");
	ok("shortcut K membuka panel kartu", await page.locator("#cards-modal").isVisible());
	await page.waitForSelector("#cards-grid .card-tile", { state: "visible" });
	const tiles = await page.evaluate(() =>
		[...document.querySelectorAll("#cards-grid .card-tile")].map((f) => ({
			title: f.title,
			aria: f.getAttribute("aria-label"),
			media: f.querySelector("img, video")?.getAttribute("src") || "",
			frame: f.querySelector(".ct-frame")?.style.backgroundImage || "",
			rar: f.querySelector(".ct-rarity")?.getAttribute("src") || "",
			caption: f.querySelector(".ct-caption")?.textContent?.trim() || "",
			desc: f.querySelector(".ct-desc")?.textContent?.trim() || "",
			descHtml: f.querySelector(".ct-desc")?.innerHTML || "",
			more: !!f.querySelector(".ct-more"),
		})));
	ok("petak kartu tampil", tiles.length > 0, String(tiles.length));
	ok("nama kartu wiki jadi tooltip", tiles.every((t) => t.title && t.title.length > 2),
		tiles[0]?.title.slice(0, 40) || "");
	ok("tooltip memuat deskripsi", tiles.every((t) => t.title.includes("\n")));
	ok("caption deskripsi tampil", tiles.every((t) => t.caption && t.desc),
		tiles[0]?.desc.slice(0, 60) || "");
	ok("warna oranye wiki ter-render", tiles.some((t) => t.descHtml.includes("color:")));
	ok("frame ego + rarity terpasang", tiles.every((t) =>
		t.frame.includes("card_ego_") && t.rar.includes("card_rarity_")),
		`${tiles[0]?.frame} | ${tiles[0]?.rar}`);
	const moreCount = await page.locator("#cards-grid .ct-more").count();
	ok("tombol varian tersedia", moreCount > 0, String(moreCount));
	if (moreCount) {
		await page.locator("#cards-grid .ct-more").first().click();
		const panel = await page.evaluate(() => {
			const p = document.querySelector("#cards-grid .card-tile.is-expanded .ct-variants");
			return { visible: !!p && p.offsetParent !== null,
				items: p ? p.querySelectorAll("p").length : 0 };
		});
		ok("panel varian terbuka & berisi deskripsi",
			panel.visible && panel.items > 1, JSON.stringify(panel));
	}
	ok("tidak ada aset kartu 404", missing.length === 0, missing.slice(0, 3).join(" | "));
	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	await browser.close();

	if (errors.length) failed.push("js errors");
	if (missing.length) failed.push("aset 404");
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nkartu skill CZN ok");
})().catch((err) => {
	console.error(err);
	process.exit(1);
});
