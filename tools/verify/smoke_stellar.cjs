// Smoke test: load a Stellar Affinity model in the viewer and confirm it
// actually renders (no console errors, real bone/anim counts in the DOM).
const { chromium } = require("playwright-core");

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH || undefined,
		args: ["--no-sandbox", "--disable-dev-shm-usage"],
	});
	const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

	const errors = [];
	page.on("console", (m) => {
		if (m.type() === "error") errors.push(m.text());
	});
	page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 60000 });

	// Pick a Stellar Affinity model via the API, then navigate straight to it.
	const modelId = process.argv[2] || "stellaraffinity/c00001_01";
	console.log("loading model:", modelId);

	await page.evaluate((id) => {
		// The viewer exposes a global for the stage; fall back to hash routing.
		if (window.location.hash !== "#" + id) window.location.hash = "#" + id;
	}, modelId);

	await page.waitForTimeout(9000);

	const state = await page.evaluate(() => {
		const txt = (sel) => document.querySelector(sel)?.textContent?.trim() || null;
		// The HUD/state panel holds runtime + version
		const body = document.body.innerText || "";
		return {
			hash: window.location.hash,
			hasCanvas: !!document.querySelector("canvas"),
			bodySnippet: body.slice(0, 1200),
		};
	});

	console.log("");
	console.log("hash      :", state.hash);
	console.log("canvas    :", state.hasCanvas);
	console.log("");
	console.log("--- visible page text (first 1200 chars) ---");
	console.log(state.bodySnippet);
	console.log("");
	console.log("--- console errors (" + errors.length + ") ---");
	errors.slice(0, 12).forEach((e) => console.log("  !", e.slice(0, 220)));

	await browser.close();
})().catch((e) => {
	console.error("FATAL:", e.message);
	process.exit(1);
});
