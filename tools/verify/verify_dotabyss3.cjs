// Render check for DotAbyss that classifies by what is actually on screen.
//
// Draw-call counting is useless here: the viewer runs a render loop, so every
// model scores ~183 calls whether it drew or threw. This instead reads pixels
// after freezing the animation, and decides from two signals:
//   nonblank  - fraction of canvas pixels that are not the background/grid
//   colors    - number of distinct colors, a proxy for real character art
// A model that errored out leaves the grid empty (nonblank ~0, colors ~0).
const { chromium } = require("playwright-core");
const fs = require("fs");

const LABEL = process.argv[2] || "DotAbyss";
const OUT = "/root/dotabyss_render2.jsonl";

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	let errors = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });
	await page.waitForTimeout(2500);

	for (const el of await page.$$("span.game-name")) {
		if (((await el.textContent()) || "").trim() === LABEL) { await el.click(); break; }
	}
	await page.waitForTimeout(4000);

	const ids = await page.evaluate(() =>
		[...document.querySelectorAll("button.model")].map((b) => b.dataset.id).filter(Boolean)
	);
	console.log("models found:", ids.length);

	// Freeze the render loop so a screenshot shows one stable frame. Canvas
	// reads also need the pixel buffer preserved.
	await page.evaluate(() => {
		window.__raf = window.requestAnimationFrame;
		window.requestAnimationFrame = () => 0;
	});

	fs.writeFileSync(OUT, "");
	const rows = [];
	for (const id of ids) {
		errors = [];
		const btn = await page.$(`button.model[data-id="${id}"]`);
		if (!btn) { rows.push({ id, nonblank: 0, colors: 0, err: "no card" }); continue; }

		// unfreeze while the model loads, then freeze again for the shot
		await page.evaluate(() => { window.requestAnimationFrame = window.__raf; });
		await btn.click();
		await page.waitForTimeout(2600);
		await page.evaluate(() => { window.requestAnimationFrame = () => 0; });
		await page.waitForTimeout(900);

		const stats = await page.evaluate(() => {
			const c = document.querySelector("canvas");
			if (!c) return null;
			const gl = c.getContext("webgl2") || c.getContext("webgl");
			if (!gl) return null;
			const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
			const px = new Uint8Array(w * h * 4);
			gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
			const seen = new Set();
			let nonblank = 0, total = 0;
			// sample a grid; full-frame Set building is slow at this size
			for (let y = 0; y < h; y += 3) {
				for (let x = 0; x < w; x += 3) {
					const i = (y * w + x) * 4;
					const r = px[i], g = px[i + 1], b = px[i + 2];
					total++;
					// background is the dark viewer color + faint grid lines
					// (all channels low and near-equal)
					const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
					if (mx > 40 && mx - mn > 12) nonblank++;
					if (seen.size < 4000) seen.add((r >> 3) << 10 | (g >> 3) << 5 | (b >> 3));
				}
			}
			return { nonblank: nonblank / total, colors: seen.size, w, h };
		});

		const err = errors.find((e) => /Texture Error|Error:|RangeError/i.test(e)) || null;
		const row = {
			id,
			nonblank: stats ? +stats.nonblank.toFixed(4) : null,
			colors: stats ? stats.colors : null,
			err: err ? String(err).slice(0, 100) : null,
		};
		rows.push(row);
		fs.appendFileSync(OUT, JSON.stringify(row) + "\n");
		const ok = row.nonblank > 0.005 && row.colors > 20;
		console.log(
			`${ok ? "ok  " : "BLANK"} ${id.padEnd(40)} nonblank=${String(row.nonblank).padStart(7)} colors=${String(row.colors).padStart(5)} ${err ? "ERR" : ""}`
		);
	}

	const blank = rows.filter((r) => !(r.nonblank > 0.005 && r.colors > 20));
	console.log("\n=== SUMMARY ===");
	console.log("total :", rows.length);
	console.log("drawn :", rows.length - blank.length);
	console.log("blank :", blank.length);
	if (blank.length) console.log("blank models:\n  " + blank.map((r) => r.id).join("\n  "));
	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
