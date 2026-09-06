// Verify DotAbyss models actually render: click the game, then a model card.
const { chromium } = require("playwright-core");

(async () => {
	const modelId = process.argv[2] || "dotabyss/Chara2001101.prefab";
	const label = process.argv[3] || "DotAbyss";
	const shot = process.argv[4] || null;

	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });
	await page.waitForTimeout(2500);

	// Game rows are rendered as <span class="game-name">; click the row that
	// contains the one matching our label.
	let clicked = false;
	for (const el of await page.$$("span.game-name")) {
		const t = ((await el.textContent()) || "").trim();
		if (t === label) {
			await el.click().catch(() => {});
			clicked = true;
			break;
		}
	}
	console.log("game clicked:", clicked);
	await page.waitForTimeout(3500);

	// Find the model card. Try the search box if one is visible.
	const search = await page.$("input[type=search]:visible, input[type=text]:visible");
	const short = modelId.split("/")[1].replace(/\.prefab$/, "");
	if (search) {
		try {
			await search.fill(short, { timeout: 5000 });
			await page.waitForTimeout(2500);
		} catch (e) {
			console.log("search fill skipped:", e.message.slice(0, 40));
		}
	}

	const btn = await page.$(`button.model[data-id="${modelId}"]`);
	if (!btn) {
		const ids = await page.evaluate(() =>
			[...document.querySelectorAll("button.model")].slice(0, 5).map((b) => b.dataset.id)
		);
		console.log("card not found. sample ids:", JSON.stringify(ids));
		await browser.close();
		process.exit(1);
	}
	await btn.click();
	await page.waitForTimeout(12000);

	// Count WebGL draw calls for one frame — the real "did it render" test.
	const draws = await page.evaluate(() => new Promise((resolve) => {
		let calls = 0, verts = 0;
		for (const c of document.querySelectorAll("canvas")) {
			const gl = c.getContext("webgl2") || c.getContext("webgl");
			if (!gl) continue;
			const od = gl.drawElements.bind(gl);
			const oa = gl.drawArrays.bind(gl);
			gl.drawElements = function (...a) { calls++; verts += a[1]; return od(...a); };
			gl.drawArrays = function (...a) { calls++; verts += a[2]; return oa(...a); };
		}
		requestAnimationFrame(() => requestAnimationFrame(() => resolve({ calls, verts })));
	}));

	const hud = await page.evaluate(() => {
		const t = document.body.innerText || "";
		const g = (re) => (t.match(re) || [])[1] || null;
		return {
			slots: g(/(\d+)\s+slot/), bones: g(/(\d+)\s+tulang/),
			anims: g(/(\d+)\s+animasi/), runtime: g(/runtime\s+([\d.]+)/), spine: g(/Spine\s+([\d.]+)/),
		};
	});

	console.log("model   :", modelId);
	console.log("HUD     :", JSON.stringify(hud));
	console.log("draws   :", JSON.stringify(draws));
	console.log("errors  :", errors.length, errors.slice(0, 2).join(" | "));

	if (shot) {
		await page.screenshot({ path: shot });
		console.log("shot    :", shot);
	}
	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
