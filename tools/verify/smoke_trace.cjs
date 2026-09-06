// Find where the 4.2 load hangs: patch Promise + log milestones from inside
// the page by re-driving load through the app's own click handler.
const { chromium } = require("playwright-core");

(async () => {
	const modelId = process.argv[2] || "stellaraffinity/c00001_01";
	const [game, name] = modelId.split("/");

	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

	const logs = [];
	page.on("console", (m) => logs.push("[" + m.type() + "] " + m.text()));
	page.on("pageerror", (e) => logs.push("[PAGEERROR] " + e.message));

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });

	const label = { stellaraffinity: "Stellar Affinity", tenkafuma: "TenkaFuma" }[game] || game;
	for (const it of await page.$$("button, .game, aside button")) {
		if (((await it.textContent()) || "").includes(label)) { await it.click(); break; }
	}
	await page.waitForTimeout(2000);
	const s = await page.$("input[type=search], input[type=text], .search input");
	if (s) { await s.fill(name || ""); await page.waitForTimeout(2000); }

	// Instrument: watch for unhandled rejections + long tasks
	await page.evaluate(() => {
		window.__marks = [];
		window.addEventListener("unhandledrejection", (e) => {
			window.__marks.push("UNHANDLED REJECTION: " + (e.reason?.message || e.reason));
		});
		window.addEventListener("error", (e) => {
			window.__marks.push("WINDOW ERROR: " + e.message);
		});
		// Wrap fetch to see what the loader requests
		const of = window.fetch;
		window.fetch = function (...a) {
			const url = typeof a[0] === "string" ? a[0] : (a[0]?.url || "?");
			window.__marks.push("FETCH -> " + url);
			return of.apply(this, a);
		};
	});

	const btn = await page.$(`button.model[data-id="${modelId}"]`);
	if (!btn) { console.log("card not found"); await browser.close(); process.exit(1); }
	await btn.click();
	await page.waitForTimeout(30000);

	const marks = await page.evaluate(() => window.__marks || []);
	console.log("=== " + modelId + " ===");
	console.log("--- page marks (" + marks.length + ") ---");
	marks.slice(0, 30).forEach((m) => console.log("  " + String(m).slice(0, 200)));
	console.log("");
	console.log("--- console (" + logs.length + ") ---");
	logs.filter((l) => !l.includes("GL Driver")).slice(0, 20).forEach((l) => console.log("  " + l.slice(0, 300)));

	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
