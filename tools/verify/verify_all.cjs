// Render every Stellar Affinity model and count WebGL draw calls, so we can
// prove all 97 actually draw (not just parse) under runtime 4.2.
const { chromium } = require("playwright-core");

const GAME = "stellaraffinity";
const LABEL = "Stellar Affinity";

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });
	for (const it of await page.$$("button, .game, aside button")) {
		if (((await it.textContent()) || "").includes(LABEL)) { await it.click(); break; }
	}
	await page.waitForTimeout(2500);

	const ids = await page.evaluate(() =>
		[...document.querySelectorAll("button.model")].map((b) => b.dataset.id).filter(Boolean)
	);
	console.log("models found:", ids.length);

	// Install the draw-call counter once; reset it per model.
	await page.evaluate(() => {
		window.__dc = { calls: 0, verts: 0 };
		for (const c of document.querySelectorAll("canvas")) {
			const gl = c.getContext("webgl2") || c.getContext("webgl");
			if (!gl) continue;
			const od = gl.drawElements.bind(gl);
			const oa = gl.drawArrays.bind(gl);
			gl.drawElements = function (...a) { window.__dc.calls++; window.__dc.verts += a[1]; return od(...a); };
			gl.drawArrays = function (...a) { window.__dc.calls++; window.__dc.verts += a[2]; return oa(...a); };
		}
	});

	const rows = [];
	for (const id of ids) {
		await page.evaluate(() => { window.__dc = { calls: 0, verts: 0 }; });
		errors.length = 0;
		const btn = await page.$(`button.model[data-id="${id}"]`);
		if (!btn) { rows.push({ id, ok: false, reason: "no card" }); continue; }
		await btn.click();
		await page.waitForTimeout(2600);
		const dc = await page.evaluate(() => window.__dc);
		const hud = await page.evaluate(() => {
			const t = document.body.innerText || "";
			return {
				runtime: (t.match(/runtime\s+([\d.]+)/) || [])[1] || null,
				spine: (t.match(/Spine\s+([\d.]+)/) || [])[1] || null,
			};
		});
		rows.push({ id, calls: dc.calls, verts: dc.verts, ...hud, err: errors[0] || null });
		console.log(`${id.padEnd(34)} calls=${String(dc.calls).padStart(4)} verts=${String(dc.verts).padStart(7)} rt=${hud.runtime} spine=${hud.spine}${errors[0] ? " ERR:" + errors[0] : ""}`);
	}

	const drawn = rows.filter((r) => r.calls > 0);
	console.log("\n=== SUMMARY ===");
	console.log("total   :", rows.length);
	console.log("draws>0 :", drawn.length);
	console.log("zero    :", rows.length - drawn.length);
	if (rows.length - drawn.length) {
		console.log("zero-draw models:", rows.filter((r) => !r.calls).map((r) => r.id).join(", "));
	}
	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
