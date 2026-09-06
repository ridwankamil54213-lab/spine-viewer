// Verify a model renders by screenshotting the stage element and measuring
// how much of it is non-background. readPixels() on a Pixi canvas returns an
// already-cleared buffer, so measure the composited screenshot instead.
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

(async () => {
	const modelId = process.argv[2] || "stellaraffinity/c00001_01";
	const outPng = process.argv[3] || null;

	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

	const errors = [];
	page.on("console", (m) => {
		if (m.type() === "error") errors.push(m.text());
	});
	page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

	await page.goto("http://127.0.0.1:3000/#" + modelId, { waitUntil: "networkidle", timeout: 60000 });
	await page.waitForTimeout(12000);

	// Screenshot just the stage area (right of the sidebar), where the canvas is.
	const canvas = await page.$("canvas");
	if (!canvas) {
		console.log("NO CANVAS");
		await browser.close();
		process.exit(1);
	}
	const shot = await canvas.screenshot();
	if (outPng) fs.writeFileSync(outPng, shot);

	// Decode PNG dimensions + crude "is it blank" via zlib on raw is overkill;
	// instead use the browser itself to analyse the pixels.
	const stats = await page.evaluate(async (b64) => {
		const img = new Image();
		await new Promise((r) => { img.onload = r; img.src = "data:image/png;base64," + b64; });
		const cv = document.createElement("canvas");
		cv.width = img.width; cv.height = img.height;
		const ctx = cv.getContext("2d");
		ctx.drawImage(img, 0, 0);
		const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
		const seen = new Map();
		let nonTransparent = 0;
		for (let i = 0; i < d.length; i += 4) {
			const a = d[i + 3];
			if (a > 8) nonTransparent++;
			const k = (d[i] >> 4) + "," + (d[i + 1] >> 4) + "," + (d[i + 2] >> 4);
			seen.set(k, (seen.get(k) || 0) + 1);
		}
		return {
			w: img.width, h: img.height,
			total: d.length / 4,
			nonTransparent,
			distinctColors: seen.size,
			topColors: [...seen.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4),
		};
	}, shot.toString("base64"));

	const pct = ((stats.nonTransparent / stats.total) * 100).toFixed(2);
	console.log("=== " + modelId + " ===");
	console.log("canvas      :", stats.w + "x" + stats.h);
	console.log("drawn px    :", stats.nonTransparent, "/", stats.total, "(" + pct + "%)");
	console.log("distinct col:", stats.distinctColors);
	console.log("top colors  :", stats.topColors.map((c) => c[0] + " x" + c[1]).join("  "));
	console.log("errors      :", errors.length);
	errors.slice(0, 8).forEach((e) => console.log("  !", e.slice(0, 200)));
	if (outPng) console.log("saved       :", outPng);

	await browser.close();
})().catch((e) => {
	console.error("FATAL:", e.message);
	process.exit(1);
});
