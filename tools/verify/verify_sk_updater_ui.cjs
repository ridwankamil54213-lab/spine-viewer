// Verifikasi tombol pembaruan + badge NEW untuk Shoujou Kaisen.
const { chromium } = require("playwright-core");

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.waitForSelector("span.game-name", { timeout: 120000 });
	await page.waitForTimeout(3000);

	const open = async (label) => {
		await page.evaluate((l) => {
			const el = [...document.querySelectorAll("span.game-name")].find(
				(n) => (n.textContent || "").trim() === l);
			(el.closest("[role=button],button,li,div") || el).click();
		}, label);
		await page.waitForTimeout(4500);
	};
	const btnHidden = () => page.evaluate(() => document.getElementById("update-check")?.hidden);

	console.log(`1. tersembunyi di daftar game      : ${(await btnHidden()) === true ? "OK" : "FAIL"}`);

	await open("Epic Seven");
	console.log(`2. tersembunyi di Epic Seven      : ${(await btnHidden()) === true ? "OK" : "FAIL"}`);

	await page.evaluate(() => document.getElementById("back-btn")?.click());
	await page.waitForTimeout(2000);

	await open("Shoujou Kaisen");
	const hidden = await btnHidden();
	console.log(`3. tampil di Shoujou Kaisen       : ${hidden === false ? "OK" : "FAIL (" + hidden + ")"}`);

	// Auto-check: endpoint versi merespons.
	const ver = await page.evaluate(async () => {
		const r = await fetch("/api/update/shoujoukaisen?mode=check").then((x) => x.json());
		return r.version || null;
	});
	console.log(`4. auto-check menjawab            : ${ver || "FAIL"}`);

	// Dot merah: manifest masih melapor 14 model baru -> seharusnya MENYALA.
	const dot = await page.evaluate(() => !document.getElementById("update-dot")?.hidden);
	console.log(`5. dot merah menyala              : ${dot ? "ya" : "tidak"}`);

	// Badge NEW: simpan ID baru, cari modelnya, lalu periksa badge.
	await page.evaluate(() => {
		sessionStorage.setItem("spine-stage:new-models", JSON.stringify({
			"shoujoukaisen/benduozhongsheng01": Date.now(),
		}));
	});
	// Muat ulang agar renderModels() membaca markah dari sessionStorage.
	await page.reload({ waitUntil: "domcontentloaded", timeout: 120000 });
	await page.waitForSelector("span.game-name", { timeout: 120000 });
	await page.waitForTimeout(3000);
	await page.evaluate(() => {
		const el = [...document.querySelectorAll("span.game-name")].find(
			(n) => (n.textContent || "").trim() === "Shoujou Kaisen");
		(el.closest("[role=button],button,li,div") || el).click();
	});
	await page.waitForTimeout(4000);
	await page.fill("#search", "benduozhongsheng01");
	await page.waitForTimeout(2500);
	const badge = await page.evaluate(() => {
		const el = document.querySelector(".badge-new");
		return el ? el.textContent.trim() : null;
	});
	console.log(`6. badge NEW muncul               : ${badge === "NEW" ? "OK" : "FAIL (" + badge + ")"}`);

	await page.screenshot({ path: "/root/sk_ui.png" });
	console.log("\nerror JS:", errors.slice(0, 3));
	await browser.close();
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
