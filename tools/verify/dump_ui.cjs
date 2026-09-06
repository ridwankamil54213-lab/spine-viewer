// Dump the game-list UI so we can see how games are rendered/selected.
const { chromium } = require("playwright-core");

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });
	await page.waitForTimeout(3000);

	const info = await page.evaluate(() => {
		const out = { games: [], inputs: [], cards: 0 };
		// any element whose text looks like a game label
		for (const el of document.querySelectorAll("*")) {
			const t = (el.textContent || "").trim();
			if (el.children.length === 0 && t && t.length < 30) {
				if (/dotabyss|stellar|tenka|haze/i.test(t)) {
					out.games.push({ tag: el.tagName, cls: el.className, text: t });
				}
			}
		}
		for (const i of document.querySelectorAll("input")) {
			out.inputs.push({ type: i.type, cls: i.className, ph: i.placeholder, visible: !!i.offsetParent });
		}
		out.cards = document.querySelectorAll("button.model").length;
		return out;
	});
	console.log(JSON.stringify(info, null, 1).slice(0, 2500));
	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
