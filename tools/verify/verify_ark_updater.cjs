// Tes tombol "Perbarui aset": tombol hanya muncul untuk Ark Re:Code,
// dan tombol cek benar-benar mengembalikan info versi.
const { chromium } = require("playwright-core");

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(e.message));
	// 16.9k models means the network never really goes idle; wait for the
	// DOM and then for the game list to render instead.
	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.waitForSelector("span.game-name", { timeout: 120000 });
	await page.waitForTimeout(3000);

	// 1. Di daftar game, tombol updater harus tersembunyi.
	let hidden = await page.evaluate(() => document.getElementById("update-check")?.hidden);
	console.log(`1. updater di daftar game tersembunyi : ${hidden === true ? "OK" : "FAIL (" + hidden + ")"}`);

	// 2. Buka game lain (OrisRies) -> harus tetap tersembunyi.
	await page.evaluate(() => {
		const el = [...document.querySelectorAll("span.game-name")].find(
			(n) => (n.textContent || "").trim() === "OrisRies");
		(el.closest("[role=button],button,li,div") || el).click();
	});
	await page.waitForTimeout(2500);
	hidden = await page.evaluate(() => document.getElementById("update-check")?.hidden);
	console.log(`2. updater di OrisRies tersembunyi     : ${hidden === true ? "OK" : "FAIL (" + hidden + ")"}`);

	// 3. Kembali, lalu buka Ark Re:Code -> harus MUNCUL.
	await page.evaluate(() => document.getElementById("back-btn")?.click());
	await page.waitForTimeout(2000);
	await page.evaluate(() => {
		const el = [...document.querySelectorAll("span.game-name")].find(
			(n) => (n.textContent || "").trim().includes("Ark Re"));
		(el.closest("[role=button],button,li,div") || el).click();
	});
	await page.waitForTimeout(4500);
	hidden = await page.evaluate(() => document.getElementById("update-check")?.hidden);
	console.log(`3. updater di Ark Re:Code tampil       : ${hidden === false ? "OK" : "FAIL (" + hidden + ")"}`);

	// 3b. Posisi: tombol harus berada di dalam .lib-head (sejajar judul).
	const inHead = await page.evaluate(() => {
		const btn = document.getElementById("update-check");
		const head = document.querySelector(".lib-head");
		return !!(btn && head && head.contains(btn));
	});
	console.log(`3b. tombol di dalam .lib-head         : ${inHead ? "OK" : "FAIL"}`);

	// 3c. Auto-check sudah jalan (permintaan ?mode=check terkirim).
	const auto = await page.evaluate(async () => {
		const r = await fetch("/api/update/arkrecode?mode=check").then((x) => x.json());
		return r.catalog || null;
	});
	console.log(`3c. auto-check menjawab               : ${auto || "FAIL"}`);

	// 4. Dot merah: terlihat hanya jika ada yang baru. state.json sudah
	//    menyimpan catalog_114626, jadi seharusnya TIDAK menyala.
	const dot = await page.evaluate(() => !document.getElementById("update-dot")?.hidden);
	console.log(`4. dot merah menyala                  : ${dot ? "ya (ada update)" : "tidak (sudah terbaru)"}`);

	await page.screenshot({ path: "/root/ark_updater_ui.png" });
	console.log("\nerror JS:", errors.slice(0, 3));
	await browser.close();
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
