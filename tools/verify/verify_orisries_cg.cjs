// Verifikasi model CG OrisRies (hasil unduhan CDN) benar-benar ter-render.
//
// Pakai kolom pencarian (#search) untuk membuka model, BUKAN klik tombol di
// sidebar: daftar model panjang dan tombolnya tidak pernah di-render semua,
// jadi `button.model[data-id=...]` sering tidak ketemu ("LEWAT") meski model
// ada di API.
const { chromium } = require("playwright-core");
const fs = require("fs");

const SAMPLE = Number(process.env.SAMPLE || 6);
const OUT = process.env.OUT || "/root/orisries_cg_result.json";

(async () => {
	const api = await fetch("http://127.0.0.1:3000/api/models");
	const all = (await api.json()).models || [];
	const cg = all.filter(
		(m) => m.game === "orisries" && /(^|\/)cg|interactivecg/i.test(m.id) && (m.animations || []).length
	);
	console.log(`API   : ${cg.length} model CG beranimasi`);

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

	// Pilih game OrisRies dulu supaya pencarian terbatas pada game itu.
	await page.evaluate(() => {
		const el = [...document.querySelectorAll("span.game-name")].find(
			(n) => (n.textContent || "").trim() === "OrisRies"
		);
		(el.closest("[role=button],button,li,div") || el).click();
	});
	await page.waitForTimeout(4000);

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

	const rows = [];
	for (const t of cg.slice(0, SAMPLE)) {
		errors.length = 0;
		const name = t.id.split("/").pop();
		// Ketik nama model di kolom pencarian, lalu klik hasil pertama.
		await page.fill("#search", "");
		await page.fill("#search", name);
		await page.waitForTimeout(1200);
		const clicked = await page.evaluate(() => {
			const b = [...document.querySelectorAll("button.model")].find((x) => x.offsetParent !== null);
			if (!b) return false;
			window.__dc.calls = 0;
			b.click();
			return true;
		});
		if (!clicked) {
			rows.push({ id: t.id, ok: false, reason: "tidak ada hasil pencarian" });
			console.log(`  LEWAT ${t.id}`);
			continue;
		}
		await page.waitForTimeout(3200);
		const dc = await page.evaluate(() => ({ ...window.__dc }));
		const atlasErr = errors.filter((e) => /frame does not fit|base Texture|atlas/i.test(e));
		const shown = await page.evaluate(() => {
			const el = document.querySelector(".model-name, #model-name, [data-model-name]");
			return el ? (el.textContent || "").trim() : null;
		});
		const ok = dc.calls > 0 && atlasErr.length === 0;
		rows.push({ id: t.id, ok, drawCalls: dc.calls, anims: (t.animations || []).length, shown, err: errors.slice(0, 1) });
		console.log(`  ${ok ? "OK  " : "FAIL"} ${t.id.padEnd(24)} calls=${String(dc.calls).padStart(5)} anim=${(t.animations || []).length}${errors[0] ? "  " + errors[0].slice(0, 70) : ""}`);
	}

	fs.writeFileSync(OUT, JSON.stringify(rows, null, 1));
	const bad = rows.filter((r) => !r.ok);
	console.log(`\nHASIL: ${rows.length - bad.length}/${rows.length} render bersih -> ${OUT}`);
	await browser.close();
	process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
