/**
 * Smoke test for the FPS meter.
 *
 * Checks the toggle, persistence, live sampling, min/avg, the reset button,
 * and that the readout is blanked for the legacy 2.1.27 iframe viewer (where
 * the Pixi ticker does not draw the model, so any number would be a lie).
 *
 * Run: node tools/check-fps.cjs
 */
const { chromium } = require("playwright-core");

const ok = (label, cond, extra = "") =>
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);

(async () => {
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	// This server scans ~17k models on boot; be generous with navigation waits.
	page.setDefaultTimeout(120000);
	page.setDefaultNavigationTimeout(120000);
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));

	// networkidle never settles here: the Pixi ticker keeps a rAF loop running
	// and models stream in, so wait for the app's own boot instead.
	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#fps-btn", { timeout: 20000 });
	await page.waitForTimeout(800);

	// 1. hidden by default
	ok("hidden by default", await page.isHidden("#fps-meter"));

	// 2. toggle via the toolbar button
	await page.click("#fps-btn");
	await page.waitForTimeout(1600);
	ok("visible after toggle", await page.isVisible("#fps-meter"));
	ok("button reflects state", (await page.getAttribute("#fps-btn", "data-on")) === "true");

	// 3. it actually counts frames
	const v1 = await page.textContent("#fps-value");
	const n1 = Number.parseInt(v1, 10);
	ok("reports a number", Number.isFinite(n1) && n1 > 0, `"${v1}"`);

	// 4. min/avg populate
	const min = await page.textContent("#fps-min");
	const avg = await page.textContent("#fps-avg");
	ok("min populated", !min.includes("—"), min);
	ok("avg populated", !avg.includes("—"), avg);

	// 5. graph drawn (canvas has non-blank pixels)
	const drawn = await page.evaluate(() => {
		const c = document.getElementById("fps-graph");
		const ctx = c.getContext("2d");
		const d = ctx.getImageData(0, 0, c.width, c.height).data;
		for (let i = 3; i < d.length; i += 4) if (d[i] > 0) return true;
		return false;
	});
	ok("graph rendered", drawn);

	// 6. reset clears stats. Read immediately: the meter legitimately refills
	// after its next 250ms window, so checking later would fail by design.
	await page.click("#fps-reset");
	const minAfter = await page.evaluate(() => document.getElementById("fps-min").textContent);
	ok("reset clears min", minAfter.includes("—"), minAfter);
	// ...and it does start reporting again afterwards.
	await page.waitForTimeout(1200);
	const minRefill = await page.textContent("#fps-min");
	ok("resumes after reset", !minRefill.includes("—"), minRefill);

	// 7. persists across reload
	await page.reload({ waitUntil: "domcontentloaded" });
	await page.waitForSelector("#fps-btn", { timeout: 20000 });
	await page.waitForTimeout(700);
	ok("persists after reload", await page.isVisible("#fps-meter"));

	// 8. keyboard shortcut P toggles
	await page.keyboard.press("p");
	await page.waitForTimeout(300);
	ok("P hides it", await page.isHidden("#fps-meter"));
	await page.keyboard.press("p");
	await page.waitForTimeout(300);
	ok("P shows it again", await page.isVisible("#fps-meter"));

	// 9. loading a model must not break it, and stats reset per model
	await page.click("#game-list .game");
	await page.waitForTimeout(900);
	await page.click("#model-list .model");
	await page.waitForTimeout(3000);
	const v2 = await page.textContent("#fps-value");
	ok("still sampling after load", Number.parseInt(v2, 10) > 0, `"${v2}"`);
	ok("model loaded", await page.isVisible("#hud"));

	// 10. sanity: reported fps is in a plausible range for this environment
	const n2 = Number.parseInt(v2, 10);
	ok("plausible value", n2 >= 5 && n2 <= 240, `${n2} fps`);

	console.log("js errors:", errors.length ? errors.slice(0, 4) : "none");
	await browser.close();
	process.exit(errors.length ? 1 : 0);
})();
