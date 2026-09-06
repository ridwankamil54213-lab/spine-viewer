// Verify a Stellar Affinity model actually RENDERS: real skeleton in the
// stage, non-blank pixels on the canvas, and no console errors.
const { chromium } = require("playwright-core");

(async () => {
	const modelId = process.argv[2] || "stellaraffinity/c00001_01";
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage"],
	});
	const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

	const errors = [];
	page.on("console", (m) => {
		if (m.type() === "error") errors.push(m.text());
	});
	page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

	await page.goto("http://127.0.0.1:3000/#" + modelId, { waitUntil: "networkidle", timeout: 60000 });
	await page.waitForTimeout(12000);

	const res = await page.evaluate(() => {
		const out = {};
		const canvases = Array.from(document.querySelectorAll("canvas"));
		out.canvasCount = canvases.length;
		out.canvasSizes = canvases.map((c) => c.width + "x" + c.height);

		// Is anything actually drawn? Sample the largest canvas.
		let best = null, bestArea = 0;
		for (const c of canvases) {
			const a = c.width * c.height;
			if (a > bestArea) { bestArea = a; best = c; }
		}
		if (best) {
			try {
				const ctx = best.getContext("webgl2") || best.getContext("webgl");
				if (ctx) {
					const px = new Uint8Array(4 * best.width * best.height);
					ctx.readPixels(0, 0, best.width, best.height, ctx.RGBA, ctx.UNSIGNED_BYTE, px);
					let nonBlank = 0;
					for (let i = 0; i < px.length; i += 4) {
						if (px[i] || px[i + 1] || px[i + 2] || px[i + 3]) nonBlank++;
					}
					out.totalPixels = best.width * best.height;
					out.nonBlankPixels = nonBlank;
					out.renderer = ctx instanceof WebGL2RenderingContext ? "webgl2" : "webgl";
				} else {
					out.renderer = "no-webgl-context";
				}
			} catch (e) {
				out.pixelError = e.message;
			}
		}

		// Read the HUD: runtime + spine version + bone/slot/anim counts
		const t = document.body.innerText || "";
		out.bodyText = t;
		return out;
	});

	console.log("=== " + modelId + " ===");
	console.log("canvas        :", res.canvasCount, res.canvasSizes.join(", "));
	console.log("renderer      :", res.renderer);
	if (res.nonBlankPixels !== undefined) {
		const pct = ((res.nonBlankPixels / res.totalPixels) * 100).toFixed(2);
		console.log("non-blank px  :", res.nonBlankPixels, "/", res.totalPixels, "(" + pct + "%)");
	}
	if (res.pixelError) console.log("pixel error   :", res.pixelError);

	// Pull the interesting HUD lines out of the page text
	const lines = (res.bodyText || "").split("\n").map((l) => l.trim()).filter(Boolean);
	const keys = ["Runtime", "Spine", "Bone", "Slot", "Anim", "Skin", "Tulang", "c00001_01", "a01001"];
	console.log("");
	console.log("--- HUD lines ---");
	let shown = 0;
	for (let i = 0; i < lines.length && shown < 25; i++) {
		const l = lines[i];
		if (keys.some((k) => l.includes(k))) { console.log("  " + l); shown++; }
	}

	console.log("");
	console.log("--- console errors (" + errors.length + ") ---");
	errors.slice(0, 10).forEach((e) => console.log("  !", e.slice(0, 200)));

	await browser.close();
})().catch((e) => {
	console.error("FATAL:", e.message);
	process.exit(1);
});
