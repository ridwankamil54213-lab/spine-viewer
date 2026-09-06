// Capture the actual failure: click the model and report EVERY console
// message + page error, plus whether the loading overlay ever clears.
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
	page.on("pageerror", (e) => logs.push("[PAGEERROR] " + e.message + "\n" + (e.stack || "").split("\n").slice(0, 6).join("\n")));

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });

	const label = { stellaraffinity: "Stellar Affinity", tenkafuma: "TenkaFuma", demo: "Demo" }[game] || game;
	for (const it of await page.$$("button, .game, aside button")) {
		if (((await it.textContent()) || "").includes(label)) { await it.click(); break; }
	}
	await page.waitForTimeout(2500);
	const s = await page.$("input[type=search], input[type=text], .search input");
	if (s) { await s.fill(name || ""); await page.waitForTimeout(2500); }

	const btn = await page.$(`button.model[data-id="${modelId}"]`);
	if (!btn) { console.log("model card not found"); await browser.close(); process.exit(1); }
	await btn.click();
	await page.waitForTimeout(45000);

	const st = await page.evaluate(() => ({
		emptyHidden: document.querySelector(".empty")?.hidden,
		loadingHidden: document.querySelector(".loading")?.hidden,
		errorText: document.querySelector(".error, .toast, #error")?.textContent?.trim()?.slice(0, 300) || null,
		body: (document.body.innerText || "").slice(0, 500),
	}));

	console.log("=== " + modelId + " ===");
	console.log("empty overlay hidden  :", st.emptyHidden);
	console.log("loading overlay hidden:", st.loadingHidden);
	console.log("error text            :", st.errorText);
	console.log("");
	console.log("--- console (" + logs.length + ") ---");
	logs.slice(0, 25).forEach((l) => console.log("  " + l.slice(0, 400)));
	console.log("");
	console.log("--- page text ---");
	console.log(st.body);

	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
