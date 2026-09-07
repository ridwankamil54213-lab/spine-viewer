// Verifikasi model Epic Seven benar-benar ter-render.
//
// Model dibuka lewat kolom pencarian (#search), bukan klik tombol sidebar:
// daftar 1273 model tidak pernah di-render seluruhnya, sehingga
// button.model[data-id] sering tidak ketemu walau model ada di API.
const { chromium } = require("playwright-core");
const fs = require("fs");

const SAMPLE = Number(process.env.SAMPLE || 6);
const OUT = process.env.OUT || "/root/epic7_result.json";

(async () => {
	const api = await fetch("http://127.0.0.1:3000/api/models");
	const all = (await api.json()).models || [];
	const e7 = all.filter((m) => m.game === "epic7" && (m.animations || []).length);
	console.log(`API   : ${e7.length} model Epic Seven beranimasi`);

	// Ambil contoh dari tiap versi Spine yang terdeteksi.
	const byVer = {};
	for (const m of e7) {
		const v = m.spine || "(tidak terbaca)";
		if (!byVer[v]) byVer[v] = [];
		if (byVer[v].length < SAMPLE) byVer[v].push(m);
	}
	console.log("versi :", Object.entries(byVer).map(([k, v]) => `${k}=${v.length}`).join(" "));

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

	await page.evaluate(() => {
		const el = [...document.querySelectorAll("span.game-name")].find(
			(n) => (n.textContent || "").trim() === "Epic Seven"
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
	for (const [ver, list] of Object.entries(byVer)) {
		for (const t of list) {
			errors.length = 0;
			const name = t.id.split("/").pop();
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
				rows.push({ id: t.id, ver, ok: false, reason: "tidak ada hasil pencarian" });
				console.log(`  LEWAT ${t.id}`);
				continue;
			}
			await page.waitForTimeout(3200);
			const dc = await page.evaluate(() => ({ ...window.__dc }));
			const atlasErr = errors.filter((e) => /frame does not fit|base Texture|atlas|\.sct/i.test(e));

			// Spine 2.x is drawn by the vendored legacy viewer, which lives in
			// an <iframe> with its OWN canvas and its own WebGL context. The
			// top-level draw-call hook cannot see it, so calls==0 there means
			// "not measured", not "not drawn". For those, check that the
			// legacy frame is present and did not report an error instead.
			let ok;
			let note = "";
			if (t.needsLegacyViewer) {
				const legacy = await page.evaluate(() => {
					const f = [...document.querySelectorAll("iframe")].find((x) =>
						(x.src || "").includes("legacy-spine"));
					return f ? { present: true, src: f.src.slice(0, 80) } : { present: false };
				});
				ok = legacy.present && atlasErr.length === 0;
				note = legacy.present ? " (legacy viewer aktif)" : " (iframe legacy tidak ada)";
			} else {
				ok = dc.calls > 0 && atlasErr.length === 0;
			}
			rows.push({ id: t.id, ver, ok, drawCalls: dc.calls, legacy: !!t.needsLegacyViewer,
				anims: (t.animations || []).length, err: errors.slice(0, 1) });
			console.log(`  ${ok ? "OK  " : "FAIL"} [${ver}] ${t.id.padEnd(30)} calls=${String(dc.calls).padStart(5)}${note}${errors[0] ? "  " + errors[0].slice(0, 60) : ""}`);
		}
	}

	fs.writeFileSync(OUT, JSON.stringify(rows, null, 1));
	const bad = rows.filter((r) => !r.ok);
	console.log(`\nHASIL: ${rows.length - bad.length}/${rows.length} render bersih -> ${OUT}`);
	await browser.close();
	process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
