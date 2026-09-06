// Render check that drives the real UI: pick the game in the sidebar, search
// for the model, click it, then measure the composited canvas.
// (The viewer has no hash routing — models load on click.)
const { chromium } = require("playwright-core");
const fs = require("fs");

(async () => {
	const modelId = process.argv[2] || "stellaraffinity/c00001_01";
	const outPng = process.argv[3] || null;
	const [game, name] = modelId.split("/");

	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

	const errors = [];
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
	page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });

	// 1. Filter to the game (click the sidebar entry whose label matches)
	const gameLabel = {
		stellaraffinity: "Stellar Affinity",
		demo: "Demo",
		tenkafuma: "TenkaFuma",
	}[game] || game;

	let clickedGame = false;
	const items = await page.$$(".game, .game-item, aside button, .sidebar button");
	for (const it of items) {
		const t = (await it.textContent()) || "";
		if (t.includes(gameLabel)) { await it.click(); clickedGame = true; break; }
	}
	console.log("game filter clicked:", clickedGame, "(" + gameLabel + ")");
	await page.waitForTimeout(2500);

	// 2. Search for the exact model id
	const search = await page.$("input[type=search], input[type=text], .search input");
	if (search) {
		await search.fill(name || "");
		await page.waitForTimeout(2500);
		console.log("search filled   :", name);
	} else {
		console.log("search input    : NOT FOUND");
	}

	// 3. Click the model card
	const btn = await page.$(`button.model[data-id="${modelId}"]`);
	if (!btn) {
		const any = await page.$$("button.model");
		console.log("model button    : NOT FOUND (visible cards: " + any.length + ")");
		if (any.length) {
			const ids = [];
			for (const b of any.slice(0, 5)) ids.push(await b.getAttribute("data-id"));
			console.log("  first ids:", ids.join(", "));
		}
		await browser.close();
		process.exit(1);
	}
	await btn.click();
	console.log("model clicked   :", modelId);
	await page.waitForTimeout(14000);

	const canvas = await page.$("canvas");
	const shot = await canvas.screenshot();
	if (outPng) fs.writeFileSync(outPng, shot);

	const stats = await page.evaluate(async (b64) => {
		const img = new Image();
		await new Promise((r) => { img.onload = r; img.src = "data:image/png;base64," + b64; });
		const cv = document.createElement("canvas");
		cv.width = img.width; cv.height = img.height;
		const ctx = cv.getContext("2d");
		ctx.drawImage(img, 0, 0);
		const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
		const seen = new Map();
		let opaque = 0;
		for (let i = 0; i < d.length; i += 4) {
			if (d[i + 3] > 8) opaque++;
			const k = (d[i] >> 4) + "," + (d[i + 1] >> 4) + "," + (d[i + 2] >> 4);
			seen.set(k, (seen.get(k) || 0) + 1);
		}
		return { w: img.width, h: img.height, total: d.length / 4, opaque, distinct: seen.size };
	}, shot.toString("base64"));

	const pct = ((stats.opaque / stats.total) * 100).toFixed(2);
	console.log("");
	console.log("=== " + modelId + " ===");
	console.log("canvas   :", stats.w + "x" + stats.h);
	console.log("drawn px :", stats.opaque, "/", stats.total, "(" + pct + "%)");
	console.log("colors   :", stats.distinct);
	console.log("errors   :", errors.length);
	errors.slice(0, 8).forEach((e) => console.log("  !", e.slice(0, 220)));
	if (outPng) console.log("saved    :", outPng);

	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
