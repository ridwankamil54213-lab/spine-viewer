// Reliable per-model render check for DotAbyss.
//
// The earlier bulk script hooked drawElements once and clicked straight down
// the list, which misses two things: the viewer recreates its canvas on load
// (so the hook goes stale), and it never looks at the console, so a model that
// throws "frame does not fit inside the base Texture" still scores whatever
// the previous model left behind. This one re-hooks after every click and
// records console errors, which is what actually distinguishes a drawn model
// from a silently-broken one.
const { chromium } = require("playwright-core");
const fs = require("fs");

const LABEL = process.argv[2] || "DotAbyss";
const OUT = "/root/dotabyss_render.jsonl";

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

	// install a self-installing hook: it re-attaches whenever a canvas appears
	await page.evaluate(() => {
		window.__dc = { calls: 0, verts: 0 };
		window.__hooked = new WeakSet();
		window.__hook = () => {
			for (const c of document.querySelectorAll("canvas")) {
				if (window.__hooked.has(c)) continue;
				const gl = c.getContext("webgl2") || c.getContext("webgl");
				if (!gl) continue;
				window.__hooked.add(c);
				const od = gl.drawElements.bind(gl);
				const oa = gl.drawArrays.bind(gl);
				gl.drawElements = function (...a) { window.__dc.calls++; window.__dc.verts += a[1]; return od(...a); };
				gl.drawArrays = function (...a) { window.__dc.calls++; window.__dc.verts += a[2]; return oa(...a); };
			}
		};
		window.__hook();
		setInterval(window.__hook, 200);
	});

	fs.writeFileSync(OUT, "");
	const rows = [];
	for (const id of ids) {
		errors = [];
		await page.evaluate(() => { window.__dc = { calls: 0, verts: 0 }; });
		const btn = await page.$(`button.model[data-id="${id}"]`);
		if (!btn) { rows.push({ id, calls: 0, err: "no card" }); continue; }
		await btn.click();
		await page.waitForTimeout(3000);
		const dc = await page.evaluate(() => window.__dc);
		const hud = await page.evaluate(() => {
			const t = document.body.innerText || "";
			return { spine: (t.match(/Spine\s+([\d.]+)/) || [])[1] || null };
		});
		const err = errors.find((e) => /Texture Error|Error:/i.test(e)) || errors[0] || null;
		const row = { id, calls: dc.calls, verts: dc.verts, spine: hud.spine, err: err ? String(err).slice(0, 120) : null };
		rows.push(row);
		fs.appendFileSync(OUT, JSON.stringify(row) + "\n");
		const flag = dc.calls > 0 ? "ok  " : "ZERO";
		console.log(`${flag} ${id.padEnd(40)} calls=${String(dc.calls).padStart(4)} verts=${String(dc.verts).padStart(8)} ${err ? "ERR:" + String(err).slice(0, 60) : ""}`);
	}

	const zero = rows.filter((r) => !r.calls);
	console.log("\n=== SUMMARY ===");
	console.log("total   :", rows.length);
	console.log("draws>0 :", rows.length - zero.length);
	console.log("zero    :", zero.length);
	if (zero.length) console.log("zero-draw:\n  " + zero.map((r) => r.id).join("\n  "));
	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
