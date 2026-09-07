// Debug: buka viewer legacy 2.1.27 langsung dengan satu model Epic Seven
// dan catat semua error, untuk melihat kenapa draw call tetap 0.
const { chromium } = require("playwright-core");

const ID = process.env.MODEL || "epic7/abigail";
const BASE = "http://127.0.0.1:3000";

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
	const logs = [];
	page.on("pageerror", (e) => logs.push(["pageerror", e.message]));
	page.on("console", (m) => logs.push([m.type(), m.text()]));
	page.on("requestfailed", (r) => logs.push(["reqfail", `${r.url()} ${r.failure()?.errorText}`]));
	page.on("response", (r) => { if (r.status() >= 400) logs.push(["http", `${r.status()} ${r.url()}`]); });

	// Minta daftar model dulu untuk tahu path asetnya.
	const api = await fetch(`${BASE}/api/models`);
	const all = (await api.json()).models || [];
	const m = all.find((x) => x.id === ID);
	if (!m) { console.log("model tidak ada:", ID); await browser.close(); process.exit(1); }
	const dir = m.id.replace(/^[^/]+\//, "");   // epic7/abigail -> abigail
	const root = m.id.split("/")[0];
	const skelUrl = `${BASE}/assets/${root}/${dir}/${m.skeletonFile}`;
	console.log("model :", m.id, "| spine:", m.spine, "| legacy:", m.needsLegacyViewer);
	console.log("skel  :", skelUrl);

	// Viewer legacy menerima ?url=<skeleton>
	await page.goto(`${BASE}/legacy-spine/index.html?url=${encodeURIComponent(skelUrl)}`,
		{ waitUntil: "networkidle", timeout: 120000 });
	await page.waitForTimeout(9000);

	// Apakah kanvas punya isi?
	const info = await page.evaluate(() => {
		const out = { canvases: [], iframes: [], bodyText: (document.body.innerText || "").slice(0, 300) };
		for (const c of document.querySelectorAll("canvas")) {
			out.canvases.push({ w: c.width, h: c.height });
		}
		for (const f of document.querySelectorAll("iframe")) out.iframes.push(f.src);
		return out;
	});
	console.log("kanvas:", JSON.stringify(info.canvases), "| iframe:", info.iframes.length);
	console.log("teks  :", info.bodyText.replace(/\s+/g, " ").slice(0, 200));

	console.log("\n--- log (20 terakhir) ---");
	for (const [t, s] of logs.slice(-20)) console.log(` [${t}] ${String(s).slice(0, 180)}`);

	await page.screenshot({ path: "/root/e7_legacy_debug.png" });
	await browser.close();
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
