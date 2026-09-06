// Re-check a single model in isolation. The bulk verifier clicks models back to
// back, so a zero on the very FIRST click is usually just the renderer not
// being warm yet — clicking it again (and waiting longer) tells us whether the
// model itself is broken.
const { chromium } = require("playwright-core");

const TARGET = process.argv[2];
const LABEL = process.argv[3] || "DotAbyss";

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });
	await page.waitForTimeout(2500);

	for (const el of await page.$$("span.game-name")) {
		if (((await el.textContent()) || "").trim() === LABEL) { await el.click(); break; }
	}
	await page.waitForTimeout(4000);

	const btn = await page.$(`button.model[data-id="${TARGET}"]`);
	if (!btn) { console.log("no card for", TARGET); await browser.close(); return; }

	// hook draw calls AFTER the page has settled
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

	// click twice with a long settle, so "first click" warm-up can't hide it
	for (const pass of [1, 2]) {
		await btn.click();
		await page.waitForTimeout(5000);
		const dc = await page.evaluate(() => window.__dc);
		const hud = await page.evaluate(() => {
			const t = document.body.innerText || "";
			return {
				spine: (t.match(/Spine\s+([\d.]+)/) || [])[1] || null,
				bones: (t.match(/Bones?\s*:?\s*(\d+)/i) || [])[1] || null,
				slots: (t.match(/Slots?\s*:?\s*(\d+)/i) || [])[1] || null,
			};
		});
		console.log(`pass${pass}: calls=${dc.calls} verts=${dc.verts} spine=${hud.spine} bones=${hud.bones} slots=${hud.slots}`);
	}

	if (errors.length) console.log("errors:\n  " + errors.slice(0, 5).join("\n  "));
	else console.log("errors: none");

	await page.screenshot({ path: "/root/shot_target.png" });
	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
