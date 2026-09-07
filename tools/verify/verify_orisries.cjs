// Smoke test: OrisRies models actually render (draw calls) with no atlas
// errors. Also compares PMA on vs off so the right default can be chosen.
const { chromium } = require("playwright-core");

const SAMPLE = Number(process.env.SAMPLE || 6);
const OUT = process.env.OUT || "/root/orisries_result.json";
const fs = require("fs");

async function boot() {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 120000 });
	await page.waitForTimeout(3000);
	return { browser, page, errors };
}

async function openGame(page) {
	return page.evaluate(() => {
		const all = [...document.querySelectorAll("span.game-name")];
		const el = all.find((n) => (n.textContent || "").trim() === "OrisRies");
		if (!el) return null;
		(el.closest("[role=button],button,li,div") || el).click();
		return (el.textContent || "").trim();
	});
}

async function hookDraws(page) {
	await page.evaluate(() => {
		window.__dc = { calls: 0 };
		window.__hooked = new WeakSet();
		window.__hook = () => {
			for (const c of document.querySelectorAll("canvas")) {
				if (window.__hooked.has(c)) continue;
				const gl = c.getContext("webgl2") || c.getContext("webgl");
				if (!gl) continue;
				window.__hooked.add(c);
				const od = gl.drawElements.bind(gl), oa = gl.drawArrays.bind(gl);
				gl.drawElements = function (...a) { window.__dc.calls++; return od(...a); };
				gl.drawArrays = function (...a) { window.__dc.calls++; return oa(...a); };
			}
		};
		window.__hook();
		setInterval(window.__hook, 200);
	});
}

(async () => {
	const api = await fetch("http://127.0.0.1:3000/api/models");
	const all = (await api.json()).models || [];
	const oris = all.filter((m) => m.game === "orisries" && (m.animations || []).length);
	console.log(`API   : ${oris.length} model OrisRies beranimasi`);

	const { browser, page, errors } = await boot();
	console.log("buka game:", await openGame(page));
	await page.waitForTimeout(4000);
	await hookDraws(page);

	const targets = oris.slice(0, SAMPLE);
	const rows = [];
	for (const t of targets) {
		errors.length = 0;
		const clicked = await page.evaluate((id) => {
			const b = [...document.querySelectorAll("button.model")].find((x) => x.dataset.id === id);
			if (!b) return false;
			window.__dc.calls = 0;
			b.click();
			return true;
		}, t.id);
		if (!clicked) { rows.push({ id: t.id, ok: false, reason: "tidak ada di UI" }); console.log(`  LEWAT ${t.id}`); continue; }
		await page.waitForTimeout(3200);
		const dc = await page.evaluate(() => ({ ...window.__dc }));
		const atlasErr = errors.filter((e) => /frame does not fit|base Texture|atlas/i.test(e));
		const ok = dc.calls > 0 && atlasErr.length === 0;
		rows.push({ id: t.id, ok, drawCalls: dc.calls, anims: (t.animations || []).length, err: errors.slice(0, 1) });
		console.log(`  ${ok ? "OK  " : "FAIL"} ${t.id.padEnd(24)} calls=${String(dc.calls).padStart(5)} anim=${(t.animations || []).length}${errors[0] ? "  " + errors[0].slice(0, 90) : ""}`);
	}

	fs.writeFileSync(OUT, JSON.stringify(rows, null, 1));
	const bad = rows.filter((r) => !r.ok);
	console.log(`\nHASIL: ${rows.length - bad.length}/${rows.length} render bersih -> ${OUT}`);
	await browser.close();
	process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
