// Inspect what the atlas page-parser actually extracts for this model.
const { chromium } = require("playwright-core");

(async () => {
	const modelId = process.argv[2] || "stellaraffinity/c00001_01";
	const [game, name] = modelId.split("/");

	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	page.on("pageerror", (e) => console.log("[PAGEERROR]", e.message));

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });

	// Fetch the atlas directly and run the SAME page-name regex the viewer uses.
	const info = await page.evaluate(async (id) => {
		const url = "/assets/" + id.split("/").map(encodeURIComponent).join("/") + "/" + encodeURIComponent(id.split("/")[1] + ".atlas");
		const r = await fetch(url);
		const text = await r.text();
		const pageNames = [];
		for (const line of text.split(/\r?\n/)) {
			const s = line.trim();
			if (/\.(png|jpe?g|webp)$/i.test(s) && !s.includes(" ")) pageNames.push(s);
		}
		return { url, status: r.status, len: text.length, pageNames, head: text.split("\n").slice(0, 14) };
	}, modelId);

	console.log("url       :", info.url, "status", info.status, "len", info.len);
	console.log("pageNames :", JSON.stringify(info.pageNames));
	console.log("");
	console.log("--- atlas head ---");
	info.head.forEach((l) => console.log("  " + JSON.stringify(l)));

	// Also confirm the PNGs are actually served
	if (info.pageNames.length) {
		console.log("");
		console.log("--- png HTTP status ---");
		for (const p of info.pageNames.slice(0, 6)) {
			const u = "/assets/" + modelId.split("/").map(encodeURIComponent).join("/") + "/" + encodeURIComponent(p);
			const st = await page.evaluate(async (x) => {
				const r = await fetch(x, { method: "GET" });
				return r.status;
			}, u);
			console.log("  " + p + " -> " + st);
		}
	}

	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
