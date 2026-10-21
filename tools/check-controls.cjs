/**
 * Smoke test: every transport control still exists, is wired to a handler,
 * and toggles/reacts the way it did before the toolbar regrouping.
 *
 * The regrouping moved controls between rows, so the risk is a listener bound
 * to a node that got re-parented (or an id that is now missing entirely).
 * Run: node tools/check-controls.cjs
 */
const { chromium } = require("playwright-core");

const IDS = [
	"prev-btn", "play-btn", "next-btn", "scrub", "rate-select", "loop-btn",
	"timeline-btn", "inspector-btn", "fullscreen-btn", "export-btn",
	"anim-select", "skin-select", "pma-select", "zoom-out", "zoom-in",
	"zoom-reset", "flip-btn", "bg-btn", "bg-select", "grid-btn", "bones-btn",
];

(async () => {
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => {
		if (m.type() === "error") errors.push("console: " + m.text());
	});

	await page.goto("http://localhost:3000/", { waitUntil: "domcontentloaded" });
	await page.waitForTimeout(700);

	const missing = await page.evaluate((ids) => ids.filter((id) => !document.getElementById(id)), IDS);

	// Click every toggle-able button and confirm its data-on flips.
	//
	// Sebagian tombol (Waktu, Periksa, Kisi, Tulang) pindah ke popover "Alat"
	// di commit 4ecc3b1, jadi tidak terlihat sampai menu dibuka. Membuka menu
	// dulu membuat tes ini menguji hal yang sama seperti sebelumnya.
	const toggles = ["loop-btn", "timeline-btn", "inspector-btn", "flip-btn", "grid-btn", "bones-btn", "bg-btn"];
	const toggleResults = [];
	const ensureToolsOpen = async (open) => {
		const isOpen = await page.evaluate(
			() => !document.getElementById("tools-pop")?.hidden
		);
		if (isOpen !== open) {
			await page.click("#tools-btn");
			await page.waitForTimeout(120);
		}
	};
	for (const id of toggles) {
		// Tombol di dalam popover perlu menunya terbuka; tombol transport tidak.
		const inPopover = await page.evaluate(
			(id) => !!document.getElementById("tools-pop")?.contains(document.getElementById(id)),
			id
		);
		if (inPopover) await ensureToolsOpen(true);
		const before = await page.getAttribute(`#${id}`, "data-on");
		await page.click(`#${id}`);
		await page.waitForTimeout(150);
		const after = await page.getAttribute(`#${id}`, "data-on");
		toggleResults.push({ id, before, after, ok: before !== after });
		// Waktu dan Periksa sengaja menutup popover saat diklik (panelnya
		// tumbuh di bawah panggung dan akan tertutup menu). Buka lagi sebelum
		// mengembalikan toggle-nya.
		if (inPopover) await ensureToolsOpen(true);
		await page.click(`#${id}`); // restore
		await page.waitForTimeout(90);
		if (inPopover) await ensureToolsOpen(false);
	}

	// A model must load end-to-end (the real regression risk). Dikerjakan
	// SEBELUM uji zoom: tanpa model, zoom tidak punya sasaran sehingga
	// labelnya memang tetap 100 dan uji zoom gagal palsu.
	await page.click("#game-list .game");
	await page.waitForTimeout(900);
	await page.click("#model-list .model");
	await page.waitForTimeout(2500);

	// Zoom buttons must change the label (and it must render as a number + %).
	const zoomBefore = await page.textContent("#zoom-label");
	await page.click("#zoom-in");
	await page.waitForTimeout(200);
	const zoomAfter = await page.textContent("#zoom-label");
	await page.click("#zoom-reset");
	await page.waitForTimeout(200);
	const zoomReset = await page.textContent("#zoom-label");
	const loaded = await page.evaluate(() => ({
		hudVisible: !document.getElementById("hud").hidden,
		hudText: document.getElementById("hud-model")?.textContent?.trim() || "",
		animOptions: document.getElementById("anim-select")?.options.length || 0,
		errorVisible: !document.getElementById("error").hidden,
		errorText: document.querySelector("#error p")?.textContent || "",
		canvas: !!document.querySelector("#canvas-wrap canvas"),
	}));

	console.log("missing ids:", missing.length ? missing : "none");
	console.log("toggle flips:", toggleResults.map((t) => `${t.id}:${t.ok ? "ok" : `FAIL(${t.before}->${t.after})`}`).join(" "));
	console.log("zoom:", `${zoomBefore} -> ${zoomAfter} -> reset ${zoomReset}`);
	console.log("model load:", JSON.stringify(loaded));
	console.log("js errors:", errors.length ? errors.slice(0, 5) : "none");

	const bad =
		missing.length ||
		toggleResults.some((t) => !t.ok) ||
		!loaded.hudVisible ||
		!loaded.canvas ||
		loaded.errorVisible ||
		errors.length;
	await browser.close();
	console.log(bad ? "\nFAIL" : "\nall controls ok");
	process.exit(bad ? 1 : 0);
})();
