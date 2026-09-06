// Is Assets.load() itself hanging for these pages?
const { chromium } = require("playwright-core");

(async () => {
	const modelId = process.argv[2] || "stellaraffinity/c00001_01";
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	page.on("pageerror", (e) => console.log("[PAGEERROR]", e.message));
	page.on("console", (m) => { if (m.type() === "error") console.log("[err]", m.text().slice(0, 200)); });

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });

	// The bundle is IIFE; reach Assets through a Pixi global if exposed, else
	// re-implement the load with plain Image to see if the file decodes at all.
	const res = await page.evaluate(async (id) => {
		const base = "/assets/" + id.split("/").map(encodeURIComponent).join("/") + "/";
		const pages = ["c00001_01.png", "c00001_01_2.png", "c00001_01_3.png", "c00001_01_4.png", "c00001_01_5.png"];
		const out = [];
		for (const p of pages) {
			const t0 = performance.now();
			try {
				const img = new Image();
				await new Promise((resolve, reject) => {
					img.onload = resolve;
					img.onerror = () => reject(new Error("decode failed"));
					img.src = base + encodeURIComponent(p);
					// hard timeout so a hang shows up as a value, not a freeze
					setTimeout(() => reject(new Error("timeout 20s")), 20000);
				});
				out.push({ p, ok: true, w: img.naturalWidth, h: img.naturalHeight, ms: Math.round(performance.now() - t0) });
			} catch (e) {
				out.push({ p, ok: false, err: e.message, ms: Math.round(performance.now() - t0) });
			}
		}
		return out;
	}, modelId);

	console.log("=== plain Image load test ===");
	res.forEach((r) => console.log("  " + r.p.padEnd(20), r.ok ? `OK ${r.w}x${r.h} (${r.ms}ms)` : `FAIL ${r.err} (${r.ms}ms)`));

	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
