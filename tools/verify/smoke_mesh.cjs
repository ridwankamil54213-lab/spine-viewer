// Compare a WORKING (3.8) model against a 4.2 one: inspect the live Spine
// object's children/meshes to see why 4.2 draws nothing.
const { chromium } = require("playwright-core");

(async () => {
	const modelId = process.argv[2] || "stellaraffinity/c00001_01";
	const [game, name] = modelId.split("/");

	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	page.on("pageerror", (e) => console.log("[PAGEERROR]", e.message));

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });

	const label = { stellaraffinity: "Stellar Affinity", tenkafuma: "TenkaFuma" }[game] || game;
	for (const it of await page.$$("button, .game, aside button")) {
		if (((await it.textContent()) || "").includes(label)) { await it.click(); break; }
	}
	await page.waitForTimeout(2000);
	const s = await page.$("input[type=search], input[type=text], .search input");
	if (s) { await s.fill(name || ""); await page.waitForTimeout(2000); }
	const btn = await page.$(`button.model[data-id="${modelId}"]`);
	if (!btn) { console.log("card not found"); await browser.close(); process.exit(1); }
	await btn.click();
	await page.waitForTimeout(14000);

	// Walk the Pixi stage from the renderer's canvas. We don't have a direct
	// handle on `spine`, so inspect via the WebGL scene: count draw calls by
	// monkey-patching before the next frame instead. Simpler: read the DOM HUD.
	const hud = await page.evaluate(() => {
		const t = document.body.innerText || "";
		const grab = (re) => (t.match(re) || [])[0] || null;
		return {
			raw: t.slice(-400),
			slots: grab(/(\d+)\s+slot/),
			bones: grab(/(\d+)\s+tulang/),
			anims: grab(/(\d+)\s+animasi/),
			runtime: grab(/runtime\s+[\d.]+/),
			spine: grab(/Spine\s+[\d.]+/),
		};
	});
	console.log("=== " + modelId + " ===");
	console.log("HUD:", JSON.stringify({ slots: hud.slots, bones: hud.bones, anims: hud.anims, runtime: hud.runtime, spine: hud.spine }));

	// Count actual WebGL draw calls for one frame — the ground truth for
	// "did anything get rendered".
	const draws = await page.evaluate(() => new Promise((resolve) => {
		const canvases = document.querySelectorAll("canvas");
		let total = 0, calls = 0;
		for (const c of canvases) {
			const gl = c.getContext("webgl2") || c.getContext("webgl");
			if (!gl) continue;
			const od = gl.drawElements.bind(gl);
			const oa = gl.drawArrays.bind(gl);
			gl.drawElements = function (...a) { calls++; total += a[1]; return od(...a); };
			gl.drawArrays = function (...a) { calls++; total += a[2]; return oa(...a); };
		}
		requestAnimationFrame(() => requestAnimationFrame(() => resolve({ calls, total })));
	}));
	console.log("draw calls in 1 frame:", JSON.stringify(draws));

	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
