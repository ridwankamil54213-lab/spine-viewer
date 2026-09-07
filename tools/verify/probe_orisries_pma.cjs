// Decide OrisRies PMA default: render one pma:true model and one model with
// no pma: line, with PMA forced ON and OFF, and compare the edges.
//
// Straight-alpha data rendered as PMA (and vice versa) shows up as dark or
// bright fringes around every sprite, so the correct setting is the one whose
// pixels sit closer to the reference (the atlas's own declared mode).
const { chromium } = require("playwright-core");
const fs = require("fs");

const CASES = [
	{ id: "orisries/1408", pma: true, note: "atlas declares pma:true" },
	{ id: "orisries/0000", pma: null, note: "no pma: line" },
];

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 120000 });
	await page.waitForTimeout(3000);

	await page.evaluate(() => {
		const all = [...document.querySelectorAll("span.game-name")];
		const el = all.find((n) => (n.textContent || "").trim() === "OrisRies");
		(el.closest("[role=button],button,li,div") || el).click();
	});
	await page.waitForTimeout(4000);

	for (const c of CASES) {
		for (const pma of [true, false]) {
			// Force the PMA toggle the viewer exposes before selecting.
			await page.evaluate((on) => {
				const sel = [...document.querySelectorAll("input[type=checkbox], select")];
				for (const el of sel) {
					const lbl = (el.closest("label")?.textContent || el.id || "").toLowerCase();
					if (/pma|premult/.test(lbl) && el.type === "checkbox") { el.checked = on; el.dispatchEvent(new Event("change", { bubbles: true })); }
				}
			}, pma);
			await page.evaluate((id) => {
				const b = [...document.querySelectorAll("button.model")].find((x) => x.dataset.id === id);
				if (b) b.click();
			}, c.id);
			await page.waitForTimeout(3500);
			const name = `/root/oris_pma_${c.id.split("/")[1]}_${pma ? "on" : "off"}.png`;
			await page.screenshot({ path: name });
			console.log(`${c.id} pma=${pma} (${c.note}) -> ${name}`);
		}
	}
	await browser.close();
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
