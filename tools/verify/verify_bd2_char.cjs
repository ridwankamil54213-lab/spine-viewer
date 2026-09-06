// Verifikasi relayout BD2 per karakter: struktur keluarga (varian) muncul
// dan model benar-benar ter-render.
//
// Dua hal yang diuji, karena keduanya bisa gagal sendiri-sendiri:
//  1. API  -> family.members berisi varian (Utama / Skill Cutscene / ...)
//  2. Browser -> model dipilih dan menghasilkan draw call, tanpa error atlas
//
// Symlink jadi perhatian khusus: relayout memakai symlink ke /srv/spine-assets,
// jadi kalau server tidak mau mengikuti symlink, render gagal meski API ok.
const { chromium } = require("playwright-core");
const fs = require("fs");

const OUT = process.env.OUT || "/root/bd2_char_result.json";
const SAMPLE = Number(process.env.SAMPLE || 6);

(async () => {
	// --- 1. API: cek struktur keluarga -------------------------------
	const api = await fetch("http://127.0.0.1:3000/api/models");
	const data = await api.json();
	const all = data.models || [];
	const bd2 = all.filter((m) => String(m.id).startsWith("bd2-char/"));

	const withFam = bd2.filter((m) => m.family);
	const roots = bd2.filter((m) => m.family && m.family.root === m.id);
	const variants = bd2.filter((m) => m.family && m.family.root !== m.id);
	const byLabel = {};
	for (const m of variants) {
		const l = m.family.label;
		byLabel[l] = (byLabel[l] || 0) + 1;
	}
	console.log(`API  : ${bd2.length} model bd2-char`);
	console.log(`       ${withFam.length} tergabung dalam keluarga`);
	console.log(`       ${roots.length} akar (Utama), ${variants.length} varian`);
	console.log("       varian per jenis:", JSON.stringify(byLabel));

	// --- 2. Browser: benar-benar ter-render --------------------------
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

	const opened = await page.evaluate(() => {
		const all = [...document.querySelectorAll("span.game-name")];
		const el = all.find((n) => (n.textContent || "").trim() === "Brown Dust 2")
			|| all.find((n) => (n.textContent || "").trim().indexOf("Brown Dust") >= 0);
		if (!el) return null;
		const t = (el.textContent || "").trim();
		(el.closest("[role=button],button,li,div") || el).click();
		return t;
	});
	console.log(`\nbuka game: ${opened}`);
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

	// Pilih beberapa akar keluarga, termasuk yang punya varian.
	const targets = roots.filter((r) => r.family && r.family.members.length >= 2).slice(0, SAMPLE);
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
		if (!clicked) {
			rows.push({ id: t.id, ok: false, reason: "tidak ada di UI" });
			console.log(`  LEWAT ${t.id}`);
			continue;
		}
		await page.waitForTimeout(3200);
		const dc = await page.evaluate(() => ({ ...window.__dc }));
		const atlasErr = errors.filter((e) => /frame does not fit|base Texture/i.test(e));
		const other = errors.filter((e) => !/frame does not fit|base Texture/i.test(e));
		const ok = dc.calls > 0 && atlasErr.length === 0;
		rows.push({ id: t.id, ok, drawCalls: dc.calls, members: t.family.members.length,
			other: other.slice(0, 1) });
		console.log(`  ${ok ? "OK  " : "FAIL"} ${t.id.padEnd(42)} calls=${String(dc.calls).padStart(5)} varian=${t.family.members.length}`);
	}

	// Coba satu varian (bukan akar) untuk memastikan varian bisa dibuka.
	if (variants.length) {
		const v = variants[0];
		errors.length = 0;
		await page.evaluate((id) => {
			const b = [...document.querySelectorAll("button.model")].find((x) => x.dataset.id === id);
			if (b) { window.__dc.calls = 0; b.click(); }
		}, v.id);
		await page.waitForTimeout(3200);
		const dc = await page.evaluate(() => ({ ...window.__dc }));
		const atlasErr = errors.filter((e) => /frame does not fit|base Texture/i.test(e));
		console.log(`  ${dc.calls > 0 && !atlasErr.length ? "OK  " : "FAIL"} ${v.id} (varian) calls=${dc.calls}`);
		rows.push({ id: v.id, isVariant: true, ok: dc.calls > 0 && atlasErr.length === 0, drawCalls: dc.calls });
	}

	fs.writeFileSync(OUT, JSON.stringify(rows, null, 1));
	const bad = rows.filter((r) => !r.ok);
	console.log(`\nHASIL: ${rows.length - bad.length}/${rows.length} render bersih -> ${OUT}`);
	await browser.close();
	process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
