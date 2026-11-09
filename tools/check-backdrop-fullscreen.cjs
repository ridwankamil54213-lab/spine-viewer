/**
 * Regresi: gambar latar (backdrop) on/off + bug layar blank hitam di fullscreen.
 *
 * Bug lama: `.layout.is-gallery.sidebar-hidden` (3 kelas) imbang spesifisitasnya
 * dengan `:root:fullscreen .layout` dan muncul belakangan, sehingga grid tetap
 * dua kolom `0 1fr`. Sidebar di-display:none saat fullscreen -> `.stage` jatuh
 * ke kolom pertama yang lebarnya 0 -> seluruh layar hitam. Tes ini memaksa mode
 * galeri, masuk fullscreen, lalu mengukur lebar stage DAN kecerahan screenshot.
 *
 * Run: node tools/check-backdrop-fullscreen.cjs   (server on :3000)
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");
const { chromium } = require("playwright-core");

const BASE = "http://127.0.0.1:3000";
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

/** Rata-rata kecerahan + persentase piksel tidak-hitam dari screenshot. */
function brightness(png) {
	const raw = path.join(os.tmpdir(), `spine-bright-${process.pid}-${Date.now()}.raw`);
	try {
		execFileSync("ffmpeg", ["-loglevel", "error", "-y", "-i", png,
			"-vf", "scale=64:40", "-f", "rawvideo", "-pix_fmt", "rgb24", raw]);
		const b = fs.readFileSync(raw);
		let sum = 0, nonblack = 0;
		const n = Math.floor(b.length / 3);
		for (let i = 0; i < b.length; i += 3) {
			const v = (b[i] + b[i + 1] + b[i + 2]) / 3;
			sum += v;
			if (v > 28) nonblack++;
		}
		return { mean: sum / n, nonblack: nonblack / n };
	} finally {
		try { fs.unlinkSync(raw); } catch { /* already gone */ }
	}
}

const shot = async (page, name) => {
	const p = path.join(os.tmpdir(), `spine-${name}-${process.pid}.png`);
	await page.screenshot({ path: p });
	const b = brightness(p);
	fs.unlinkSync(p);
	return b;
};

(async () => {
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	page.setDefaultTimeout(60000);
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible" });
	await page.locator("#game-list .game").first().click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	// Paksa mode galeri: di sinilah aturan CSS yang bermasalah aktif.
	if (await page.locator("#view-grid-btn").count()) await page.locator("#view-grid-btn").click();
	await page.locator("#model-list li > button:not(.model-fav), #model-list .gcard").first().click();
	await page.waitForFunction(() => !!window.spineStage?.spine?.skeleton, null, { timeout: 60000 });
	await page.waitForTimeout(900);

	// --- 1. fullscreen tidak boleh blank hitam ----------------------------
	const before = await shot(page, "fs-before");
	await page.locator("#fullscreen-btn").click();
	await page.waitForTimeout(1400);
	const fsState = await page.evaluate(() => ({
		fs: !!document.fullscreenElement,
		stageW: Math.round(document.querySelector(".stage").getBoundingClientRect().width),
		wrapW: Math.round(document.querySelector("#canvas-wrap").getBoundingClientRect().width),
		cols: getComputedStyle(document.querySelector(".layout")).gridTemplateColumns,
		model: window.spineStage?.model?.id || null,
	}));
	const after = await shot(page, "fs-after");
	ok("fullscreen aktif", fsState.fs, JSON.stringify(fsState));
	ok("stage tidak collapse (lebar > 500px)", fsState.stageW > 500, `${fsState.stageW}px`);
	ok("canvas-wrap tidak collapse", fsState.wrapW > 500, `${fsState.wrapW}px`);
	ok("grid fullscreen cuma 1 kolom", !/ /.test(fsState.cols.trim()), fsState.cols);
	ok("layar tidak blank hitam", after.nonblack > 0.12,
		`non-hitam ${(after.nonblack * 100).toFixed(1)}% (sebelum ${(before.nonblack * 100).toFixed(1)}%), mean ${after.mean.toFixed(1)}`);
	ok("model masih termuat di fullscreen", !!fsState.model, String(fsState.model));

	// --- 2. tombol on/off gambar latar -------------------------------------
	await page.locator("#fs-exit, .fs-exit").first().click().catch(() => {});
	await page.waitForTimeout(500);
	const bd = "#stage-backdrop";
	ok("backdrop mati secara default", await page.locator(bd).evaluate((n) => n.hidden));
	await page.locator("#backdrop-btn").click();
	await page.waitForTimeout(250);
	const on = await page.locator(bd).evaluate((n) => ({
		hidden: n.hidden,
		scene: n.dataset.scene,
		img: getComputedStyle(n).backgroundImage,
		btnOn: document.querySelector("#backdrop-btn").dataset.on,
	}));
	ok("tombol menyalakan backdrop", !on.hidden && on.btnOn === "true", JSON.stringify(on));
	ok("gambar latar benar-benar terpasang", /backgrounds\/.+\.svg/.test(on.img), on.img);

	await page.locator("#backdrop-select").selectOption("night");
	await page.waitForTimeout(200);
	const night = await page.locator(bd).evaluate((n) => ({
		scene: n.dataset.scene, img: getComputedStyle(n).backgroundImage,
	}));
	ok("pilih scene Malam", night.scene === "night" && /night\.svg/.test(night.img),
		JSON.stringify(night));

	const lit = await shot(page, "backdrop-on");
	ok("backdrop menambah kecerahan panggung", lit.nonblack > 0.10,
		`non-hitam ${(lit.nonblack * 100).toFixed(1)}%`);

	// Shortcut Shift+L mematikan (L tanpa shift tetap mengganti warna latar).
	await page.keyboard.press("Shift+L");
	await page.waitForTimeout(200);
	ok("Shift+L mematikan backdrop", await page.locator(bd).evaluate((n) => n.hidden));
	await page.keyboard.press("Shift+L");
	// schedulePermalinkWrite punya debounce 400 ms.
	await page.waitForTimeout(750);
	ok("Shift+L menyalakan lagi", !(await page.locator(bd).evaluate((n) => n.hidden)));

	// --- 3. persist + permalink -------------------------------------------
	const raw = await page.evaluate(() => new URLSearchParams(location.search).get("v"));
	ok("permalink memuat kunci backdrop", !!raw &&
		JSON.parse(Buffer.from(raw.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString()).bk === "night",
		String(raw).slice(0, 30));

	await page.reload({ waitUntil: "domcontentloaded" });
	await page.waitForTimeout(1200);
	const restored = await page.locator(bd).evaluate((n) => ({
		hidden: n.hidden, scene: n.dataset.scene,
		btnOn: document.querySelector("#backdrop-btn").dataset.on,
	}));
	ok("preferensi tersimpan saat reload", !restored.hidden &&
		restored.scene === "night" && restored.btnOn === "true", JSON.stringify(restored));

	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	if (errors.length) failed.push("js errors");
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nbackdrop + fullscreen ok");
})().catch((e) => { console.error(e); process.exit(1); });
