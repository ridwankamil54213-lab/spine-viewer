// Regresi lintas-game untuk perbaikan deteksi overflow atlas.
//
// Perbaikan overflowsPage() bersifat global — ia menentukan halaman mana yang
// di-rescue untuk SEMUA game. Mengubahnya bisa menyelamatkan halaman yang
// tadinya gagal, tapi juga bisa membiarkan halaman rusak lewat. Uji ini
// mengambil sampel model dari tiap game dan memastikan tidak ada yang
// memunculkan error "frame does not fit inside the base Texture".
const { chromium } = require("playwright-core");
const fs = require("fs");

const PER_GAME = Number(process.env.PER_GAME || 3);
const OUT = process.env.OUT || "/root/atlas_regress.json";

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

	// Kumpulkan nama game yang tampak di sidebar.
	const games = await page.evaluate(() =>
		[...document.querySelectorAll("span.game-name")].map((e) => (e.textContent || "").trim()).filter(Boolean)
	);
	console.log("game ditemukan:", games.length, "->", games.join(", "));

	const rows = [];
	for (const g of games) {
		// Buka game-nya lewat JS: tombol di sidebar bisa saja di luar viewport
		// (perlu scroll) sehingga Playwright menolak mengkliknya.
		const opened = await page.evaluate((name) => {
			const el = [...document.querySelectorAll("span.game-name")]
				.find((e) => (e.textContent || "").trim() === name);
			if (!el) return false;
			(el.closest("[role=button],button,li,div") || el).click();
			return true;
		}, g);
		if (!opened) { console.log(`\n[${g}] tidak ditemukan`); continue; }
		await page.waitForTimeout(2500);

		const ids = await page.evaluate(() =>
			[...document.querySelectorAll("button.model")].map((b) => b.dataset.id).filter(Boolean)
		);
		if (!ids.length) { console.log(`\n[${g}] tidak ada model`); continue; }
		// Sampel merata: awal, tengah, akhir daftar.
		const picks = [];
		for (let i = 0; i < PER_GAME && i < ids.length; i++) {
			picks.push(ids[Math.floor((i * ids.length) / PER_GAME)]);
		}

		let gOk = 0;
		for (const id of picks) {
			// Satu model yang gagal tidak boleh menghentikan seluruh regresi.
			try {
			errors.length = 0;
			await page.evaluate((i) => {
				window.__dc.calls = 0; window.__dc.verts = 0;
				const b = [...document.querySelectorAll("button.model")].find((x) => x.dataset.id === i);
				if (b) b.click();
			}, id);
			await page.waitForTimeout(3200);
			const dc = await page.evaluate(() => ({ ...window.__dc }));
			const atlasErr = errors.filter((e) => /frame does not fit|base Texture/i.test(e));
			const ok = atlasErr.length === 0;
			if (ok) gOk++;
			rows.push({ game: g, id, ok, drawCalls: dc.calls, atlasErr: atlasErr[0] ? atlasErr[0].slice(0, 120) : null });
			console.log(`  ${ok ? "ok  " : "FAIL"} ${id.slice(0, 58).padEnd(58)} calls=${String(dc.calls).padStart(5)}` +
				(atlasErr.length ? "  " + atlasErr[0].slice(0, 70) : ""));
			} catch (err) {
				rows.push({ game: g, id, ok: false, error: String(err.message || err).slice(0, 120) });
				console.log(`  ERR  ${id.slice(0, 58)}  ${String(err.message || err).slice(0, 60)}`);
			}
		}
		console.log(`[${g}] ${gOk}/${picks.length} bersih  (total model ${ids.length})`);
	}

	fs.writeFileSync(OUT, JSON.stringify(rows, null, 1));
	const bad = rows.filter((r) => !r.ok);
	console.log(`\nHASIL AKHIR: ${rows.length - bad.length}/${rows.length} bersih`);
	if (bad.length) {
		console.log("\nYang bermasalah:");
		for (const b of bad.slice(0, 15)) console.log(`  ${b.id}\n     ${b.atlasErr}`);
	}
	await browser.close();
	process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
