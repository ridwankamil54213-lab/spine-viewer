// Verify every game card actually renders its icon (not the letter badge).
const { chromium } = require("playwright-core");

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));

	// Track which /thumbs/_game/ URLs the browser actually fetched, and
	// whether each one 200'd.
	const hits = [];
	page.on("response", (r) => {
		const u = r.url();
		if (u.includes("/thumbs/_game/")) {
			hits.push({ file: u.split("/").pop(), status: r.status() });
		}
	});

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });
	await page.waitForTimeout(3000);

	console.log("=== icon requests ===");
	for (const h of hits) console.log(`  ${String(h.status).padEnd(4)} ${h.file}`);
	const bad = hits.filter((h) => h.status !== 200);
	console.log("total:", hits.length, "| non-200:", bad.length);

	// Check the two new games specifically: does an <img> resolve to real art?
	const check = await page.evaluate(() => {
		const out = {};
		for (const key of ["stellaraffinity", "hazereverb"]) {
			const img = document.querySelector(`img[src*="_game/${key}.png"]`);
			if (!img) { out[key] = { found: false }; continue; }
			out[key] = {
				found: true,
				complete: img.complete,
				naturalW: img.naturalWidth,
				naturalH: img.naturalHeight,
			};
		}
		return out;
	});
	console.log("\n=== new game icons ===");
	for (const [k, v] of Object.entries(check)) {
		console.log(`  ${k.padEnd(18)}`, JSON.stringify(v));
	}
	console.log("\npage errors:", errors.length);
	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
