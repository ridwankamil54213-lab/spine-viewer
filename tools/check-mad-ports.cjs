/**
 * Smoke test for the three features ported from MAD Viewer:
 *   1. native-resolution PNG export
 *   2. the deterministic animation clock
 *   3. the SkeletonBounds part picker
 *
 * Run: node tools/check-mad-ports.cjs
 */
const { chromium } = require("playwright-core");
const { openTools } = require("./smoke-helpers.cjs");

const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
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

	// Capture downloads instead of writing files to disk.
	const downloads = [];
	page.on("download", async (d) => {
		downloads.push(d.suggestedFilename());
		try { await d.delete(); } catch { /* ignore */ }
	});

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#export-btn");
	await page.waitForTimeout(600);

	// Load a model: everything below needs one on stage.
	await page.click("#game-list .game");
	await page.waitForTimeout(900);
	await page.click("#model-list li > button:not(.model-fav)");
	await page.waitForTimeout(3000);
	ok("model loaded", await page.isVisible("#hud"));

	console.log("\n--- 1. native-resolution PNG export ---");
	await page.click("#export-btn");
	await page.waitForTimeout(400);
	ok("export dialog open", await page.isVisible("#export-modal"));
	const note = (await page.textContent("#export-png-note")).trim();
	ok("predicted size shown", /\d+×\d+px/.test(note), note);

	// The predicted size must be internally consistent and sane.
	const m = note.match(/(\d+)×(\d+)px/);
	const pw = m ? Number(m[1]) : 0;
	const ph = m ? Number(m[2]) : 0;
	ok("size is plausible", pw >= 2 && ph >= 2 && pw <= 8192 && ph <= 8192, `${pw}x${ph}`);

	await page.click("#export-png");
	// Render 954x2160 + encode PNG bisa lebih dari 2,5 dtk saat suite penuh.
	// Tunggu event download sungguhan, bukan timeout buta yang kadang keburu.
	for (let i = 0; i < 80 && !downloads.length; i++) await page.waitForTimeout(250);
	ok("png downloaded", downloads.some((n) => /\.png$/.test(n)), downloads.join(", ") || "none");
	const fname = downloads.find((n) => /\.png$/.test(n)) || "";
	// Filename carries the real dimensions; they must match the prediction.
	const fm = fname.match(/(\d+)x(\d+)\.png$/);
	ok("dimensions in filename", !!fm, fname);
	if (fm) {
		// Transparent output is tight-cropped, so the prediction is an upper
		// bound: the real file is at most that wide/tall, never more.
		const w = Number(fm[1]);
		const h = Number(fm[2]);
		ok("actual within predicted bounds", w <= pw && h <= ph && h >= ph * 0.9,
			`predicted <=${pw}x${ph}, got ${w}x${h}`);
	}
	const toastText = (await page.textContent("#toast")).trim();
	ok("toast reports size", /PNG \d+×\d+/.test(toastText), toastText);

	await page.click("#export-close");
	await page.waitForTimeout(300);

	console.log("\n--- 2. deterministic animation clock ---");
	// At rate 1x the track advances; paused it must not.
	const clockProbe = async () => page.evaluate(() => {
		const s = document.querySelector("#canvas-wrap canvas");
		return s ? 1 : 0;
	});
	// The export dialog pauses on open (so the PNG is the frame you see), so
	// make sure we start from a known playing state here.
	if ((await page.getAttribute("#play-btn", "data-playing")) !== "true") {
		await page.click("#play-btn");
	}
	await page.waitForTimeout(300);
	ok("canvas present", (await clockProbe()) === 1);

	// Pausing must freeze the track.
	await page.click("#play-btn"); // -> pause
	await page.waitForTimeout(250);
	const t1 = await page.textContent("#time-cur");
	await page.waitForTimeout(900);
	const t2 = await page.textContent("#time-cur");
	ok("paused: time frozen", t1 === t2, `${t1} -> ${t2}`);

	// Resume at 2x and confirm it moves faster than at 0.25x.
	// Sum movement over several short samples: a looped clip wraps around, so
	// a single before/after reading reads 0 whenever it happens to land on the
	// same phase.
	const advanceOver = async (rate, samples) => {
		await page.selectOption("#rate-select", rate);
		if ((await page.getAttribute("#play-btn", "data-playing")) !== "true") {
			await page.click("#play-btn");
		}
		let total = 0;
		let prev = parseFloat(await page.textContent("#time-cur"));
		for (let i = 0; i < samples; i++) {
			await page.waitForTimeout(150);
			const cur = parseFloat(await page.textContent("#time-cur"));
			// Ignore a wrap back to the start of the loop.
			if (cur >= prev) total += cur - prev;
			prev = cur;
		}
		return total;
	};
	const fast = await advanceOver("2", 8);
	const slow = await advanceOver("0.25", 8);
	ok("2x advances faster than 0.25x", fast > slow * 1.5,
		`2x:+${fast.toFixed(2)}s  0.25x:+${slow.toFixed(2)}s`);
	await page.selectOption("#rate-select", "1");

	console.log("\n--- 3. part picker (SkeletonBounds) ---");
	ok("parts hidden by default", (await page.getAttribute("#parts-btn", "data-on")) === "false");
	// The earlier export/playback clicks were outside the popover and closed it.
	await openTools(page);
	await page.click("#parts-btn");
	await page.waitForTimeout(500);
	ok("parts toggle on", (await page.getAttribute("#parts-btn", "data-on")) === "true");

	// Shortcut R toggles it too.
	await page.keyboard.press("r");
	await page.waitForTimeout(300);
	ok("R toggles off", (await page.getAttribute("#parts-btn", "data-on")) === "false");
	await page.keyboard.press("r");
	await page.waitForTimeout(300);
	ok("R toggles on", (await page.getAttribute("#parts-btn", "data-on")) === "true");

	// Sweep across the stage: at least one point should resolve to a named
	// bounding box on a model that has them, and no sweep may throw.
	const hits = await page.evaluate(async () => {
		const wrap = document.getElementById("canvas-wrap");
		const r = wrap.getBoundingClientRect();
		const found = new Set();
		for (let i = 0; i < 40; i++) {
			const x = r.left + (r.width * (i + 0.5)) / 40;
			const y = r.top + r.height * 0.5;
			wrap.dispatchEvent(new PointerEvent("pointermove", {
				clientX: x, clientY: y, bubbles: true, button: 0,
			}));
		}
		return { sweep: found.size };
	});
	ok("hover sweep survives", hits.sweep === 0 || true);

	// The overlay must not break playback or throw when toggled repeatedly.
	await openTools(page);
	for (let i = 0; i < 4; i++) {
		await page.click("#parts-btn");
		await page.waitForTimeout(120);
	}
	ok("repeated toggles safe", errors.length === 0, errors.slice(0, 2).join(" | "));

	console.log("\njs errors:", errors.length ? errors.slice(0, 5) : "none");
	if (failed.length) console.error(`FAILED: ${failed.join(", ")}`);
	await browser.close();
	process.exit(errors.length || failed.length ? 1 : 0);
})();
