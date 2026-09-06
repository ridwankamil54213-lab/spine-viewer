// Buktikan fix atlas: model yang halamannya "squashed" (declared size beda
// proporsi dengan PNG-nya) sekarang harus RENDER, bukan throw
// "frame does not fit inside the base Texture dimensions".
//
// Cara ukur: hook drawElements/drawArrays (self-installing, karena viewer
// bikin ulang canvas tiap ganti model) + catat console error. Model yang
// cuma nol drawing call atau memicu error atlas = gagal.
const { chromium } = require("playwright-core");
const fs = require("fs");

const TARGETS = (process.argv[2] || "AIBoss2018101_1,UnitDragonBase,UnitArmorKnightBase,Chara2001101,Unit100301000G,spineboy")
	.split(",").map((s) => s.trim()).filter(Boolean);
const OUT = process.env.OUT || "/root/atlas_fix_result.json";

// Detik per model — cukup buat atlas selesai dimuat + beberapa frame animasi.
const SETTLE_MS = 3500;

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });
	await page.waitForTimeout(2500);

	// Buka game DotAbyss dulu (target utama ada di situ).
	for (const el of await page.$$("span.game-name")) {
		if (((await el.textContent()) || "").trim() === "DotAbyss") { await el.click(); break; }
	}
	await page.waitForTimeout(4000);

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

	const results = [];
	for (const needle of TARGETS) {
		errors.length = 0;
		// Cari tombol model yang id-nya mengandung needle (case-insensitive).
		const clicked = await page.evaluate((n) => {
			const btns = [...document.querySelectorAll("button.model")];
			const b = btns.find((x) => (x.dataset.id || "").toLowerCase().includes(n.toLowerCase()))
				|| btns.find((x) => ((x.textContent) || "").toLowerCase().includes(n.toLowerCase()));
			if (!b) return null;
			const id = b.dataset.id;
			b.click();
			return id;
		}, needle);

		if (!clicked) {
			results.push({ needle, found: false, ok: false, reason: "model tidak ditemukan di UI" });
			continue;
		}

		await page.waitForTimeout(SETTLE_MS);
		const dc = await page.evaluate(() => ({ ...window.__dc }));
		const atlasErr = errors.filter((e) => /frame does not fit|base Texture/i.test(e));
		const otherErr = errors.filter((e) => !/frame does not fit|base Texture/i.test(e));
		const ok = dc.calls > 0 && atlasErr.length === 0;
		results.push({
			needle, id: clicked, found: true, ok,
			drawCalls: dc.calls, verts: dc.verts,
			atlasErrors: atlasErr.slice(0, 2),
			otherErrors: otherErr.slice(0, 2),
		});
		console.log(`${ok ? "OK  " : "FAIL"} ${needle.padEnd(22)} calls=${String(dc.calls).padStart(5)} verts=${String(dc.verts).padStart(7)}` +
			(atlasErr.length ? `  ATLAS_ERR: ${atlasErr[0].slice(0, 90)}` : ""));
	}

	fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
	const pass = results.filter((r) => r.ok).length;
	console.log(`\nHASIL: ${pass}/${results.length} model render bersih  ->  ${OUT}`);
	await browser.close();
	process.exit(pass === results.length ? 0 : 1);
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
