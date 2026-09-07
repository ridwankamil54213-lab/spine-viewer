// Verifikasi model baru Shoujou Kaisen benar-benar ter-render.
const { chromium } = require("playwright-core");

const IDS = (process.env.IDS || "benduozhongsheng01,feizuoxiaomengdufu01,liuxiuyinlihua01,q_chenyuluanshishui01,caozhen02").split(",");

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.waitForSelector("span.game-name", { timeout: 120000 });
	await page.waitForTimeout(3000);

	await page.evaluate(() => {
		const el = [...document.querySelectorAll("span.game-name")].find(
			(n) => (n.textContent || "").trim() === "Shoujou Kaisen");
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

	let ok = 0;
	for (const id of IDS) {
		errors.length = 0;
		await page.fill("#search", "");
		await page.fill("#search", id);
		await page.waitForTimeout(1200);
		const clicked = await page.evaluate(() => {
			const b = [...document.querySelectorAll("button.model")].find((x) => x.offsetParent !== null);
			if (!b) return false;
			window.__dc.calls = 0;
			b.click();
			return true;
		});
		if (!clicked) { console.log(`  LEWAT ${id}`); continue; }
		await page.waitForTimeout(3200);
		const dc = await page.evaluate(() => ({ ...window.__dc }));
		const atlasErr = errors.filter((e) => /frame does not fit|base Texture|Region not found|atlas/i.test(e));
		const good = dc.calls > 0 && atlasErr.length === 0;
		if (good) ok++;
		console.log(`  ${good ? "OK  " : "FAIL"} ${id.padEnd(26)} calls=${String(dc.calls).padStart(5)}${errors[0] ? "  " + errors[0].slice(0, 60) : ""}`);
	}

	console.log(`\nHASIL: ${ok}/${IDS.length} render bersih`);
	await browser.close();
	process.exit(ok === IDS.length ? 0 : 1);
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
