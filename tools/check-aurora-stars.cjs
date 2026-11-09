/**
 * Regresi: bintang backdrop Aurora berkedip + "bintang jatuh" (meteor).
 *
 * Bintang tidak lagi digambar di aurora.svg (CSS animation tidak bisa menyentuh
 * isi background-image), tapi sebagai .starfield DOM di dalam #stage-backdrop.
 * Tes ini memastikan animasinya BENAR-BENAR berjalan (currentTime maju),
 * lintasan meteor bergerak ke kiri-bawah lalu menghilang saat jeda, ada
 * beberapa meteor aktif bersamaan, scene lain tetap statis, dan
 * prefers-reduced-motion mematikan meteornya.
 *
 * Run: node tools/check-aurora-stars.cjs   (server on :3000)
 */
const fs = require("fs");
const { chromium } = require("playwright-core");

const BASE = "http://127.0.0.1:3000";
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

(async () => {
	// --- 0. SVG sumber tidak boleh punya bintang statis lagi ---------------
	const svg = fs.readFileSync("public/backgrounds/aurora.svg", "utf8");
	ok("aurora.svg tanpa <circle> bintang statis", !/<circle\b/.test(svg));
	ok("aurora.svg masih punya langit + aurora", /linearGradient id="sky"/.test(svg) && /id="ribbon"/.test(svg));

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const errors = [];
	const badResponses = [];
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	page.setDefaultTimeout(60000);
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => r.status() >= 400 && r.url().includes("/backgrounds/") &&
		badResponses.push(`${r.status()} ${r.url()}`));

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible" });
	await page.locator("#game-list .game").first().click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	await page.locator("#model-list li > button:not(.model-fav), #model-list .gcard").first().click();
	await page.waitForFunction(() => !!window.spineStage?.spine?.skeleton, null, { timeout: 60000 });

	// --- 1. nyalakan scene Aurora ------------------------------------------
	if (await page.locator("#backdrop-btn").evaluate((n) => n.dataset.on !== "true")) {
		await page.locator("#backdrop-btn").click();
	}
	await page.locator("#backdrop-select").selectOption("aurora");
	await page.waitForTimeout(300);

	const layer = await page.locator("#stage-backdrop .starfield").evaluate((n) => ({
		scene: n.parentElement.dataset.scene,
		display: getComputedStyle(n).display,
		stars: n.querySelectorAll(".star").length,
		meteors: n.querySelectorAll(".meteor").length,
		pointerEvents: getComputedStyle(n).pointerEvents,
	}));
	ok("scene aktif = aurora", layer.scene === "aurora", layer.scene);
	ok("starfield tampil", layer.display !== "none", layer.display);
	ok("18 bintang kedip", layer.stars === 18, String(layer.stars));
	ok("bintang jatuh banyak (>= 16)", layer.meteors >= 16, String(layer.meteors));
	ok("starfield tidak menangkap klik", layer.pointerEvents === "none", layer.pointerEvents);

	const names = await page.evaluate(() => ({
		star: getComputedStyle(document.querySelector(".starfield .star")).animationName,
		meteor: getComputedStyle(document.querySelector(".starfield .meteor")).animationName,
		starDur: getComputedStyle(document.querySelector(".starfield .star")).animationDuration,
		meteorDur: getComputedStyle(document.querySelector(".starfield .meteor")).animationDuration,
	}));
	ok("bintang pakai animasi star-twinkle", names.star === "star-twinkle", names.star);
	ok("meteor pakai animasi meteor-fall", names.meteor === "meteor-fall", names.meteor);
	ok("durasi meteor > durasi kedip",
		parseFloat(names.meteorDur) > parseFloat(names.starDur),
		`${names.starDur} vs ${names.meteorDur}`);

	// --- 2. animasi benar-benar berjalan (currentTime maju) ----------------
	const t0 = await page.evaluate(() => {
		const s = document.querySelector(".starfield .star").getAnimations()[0];
		const m = document.querySelector(".starfield .meteor").getAnimations()[0];
		return { s: s && s.currentTime, m: m && m.currentTime,
			sState: s && s.playState, mState: m && m.playState };
	});
	await page.waitForTimeout(350);
	const t1 = await page.evaluate(() => {
		const s = document.querySelector(".starfield .star").getAnimations()[0];
		const m = document.querySelector(".starfield .meteor").getAnimations()[0];
		return { s: s && s.currentTime, m: m && m.currentTime };
	});
	ok("animasi bintang running", t0.sState === "running", String(t0.sState));
	ok("animasi meteor running", t0.mState === "running", String(t0.mState));
	ok("waktu animasi bintang maju", t1.s > t0.s, `${t0.s} -> ${t1.s}`);
	ok("waktu animasi meteor maju", t1.m > t0.m, `${t0.m} -> ${t1.m}`);

	// --- 3. lintasan meteor: ke kiri-bawah, lalu mati saat jeda ------------
	const path = await page.evaluate(async () => {
		const node = document.querySelector(".starfield .meteor");
		const anim = node.getAnimations()[0];
		const dur = anim.effect.getTiming().duration;
		const frame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
		const read = async (frac) => {
			anim.currentTime = dur * frac;
			await frame();
			const cs = getComputedStyle(node);
			const dm = new DOMMatrix(cs.transform);
			return { x: dm.m41, y: dm.m42, opacity: parseFloat(cs.opacity) };
		};
		anim.pause();
		const start = await read(0.03);
		const end = await read(0.13);
		const paused = await read(0.55);
		anim.play();
		return { start, end, paused, dur };
	});
	ok("meteor bergerak ke kiri", path.end.x < path.start.x - 50,
		`x ${path.start.x.toFixed(1)} -> ${path.end.x.toFixed(1)}`);
	ok("meteor bergerak ke bawah", path.end.y > path.start.y + 20,
		`y ${path.start.y.toFixed(1)} -> ${path.end.y.toFixed(1)}`);
	ok("meteor terang saat melintas", path.start.opacity > 0.5 && path.end.opacity > 0.5,
		`${path.start.opacity} / ${path.end.opacity}`);
	ok("meteor menghilang di jeda antar kemunculan", path.paused.opacity < 0.05,
		String(path.paused.opacity));

	// --- 3b. kepadatan: fase jeda tersebar, beberapa meteor aktif barengan --
	// Fase dihitung deterministik dari delay negatif + durasi (t=0 saat load),
	// jadi tidak bergantung pada timing eksekusi tes.
	const density = await page.evaluate(() => {
		const ms = [...document.querySelectorAll(".starfield .meteor")];
		const phases = ms.map((n) => {
			const d = parseFloat(n.style.getPropertyValue("--d")) || 0;
			const dur = parseFloat(getComputedStyle(n).animationDuration) || 1;
			return ((-d) % dur) / dur;
		});
		return {
			total: ms.length,
			active: phases.filter((p) => p >= 0 && p < 0.2).length,
			distinct: new Set(ms.map((n) => n.style.getPropertyValue("--d"))).size,
			angles: new Set(ms.map((n) => n.style.getPropertyValue("--angle"))).size,
		};
	});
	ok("jeda meteor tersebar (tidak serempak)", density.distinct >= 16,
		String(density.distinct));
	ok("lintasan meteor bervariasi", density.angles >= 8, String(density.angles));
	ok("beberapa meteor aktif bersamaan", density.active >= 3,
		`${density.active}/${density.total} di fase lintasan`);

	// --- 4. scene lain tidak ikut berbintang --------------------------------
	await page.locator("#backdrop-select").selectOption("night");
	await page.waitForTimeout(200);
	const night = await page.locator("#stage-backdrop .starfield").evaluate((n) => ({
		display: getComputedStyle(n).display,
		img: getComputedStyle(n.parentElement).backgroundImage,
		anims: n.querySelector(".meteor").getAnimations().length,
	}));
	ok("starfield mati di scene Malam", night.display === "none", night.display);
	ok("night.svg tetap terpasang", /night\.svg/.test(night.img), night.img);
	ok("tidak ada animasi jalan di scene Malam", night.anims === 0, String(night.anims));
	await page.locator("#backdrop-select").selectOption("aurora");
	await page.waitForTimeout(200);
	ok("starfield hidup lagi saat balik ke Aurora",
		await page.locator("#stage-backdrop .starfield").evaluate((n) => getComputedStyle(n).display !== "none"));

	// --- 5. prefers-reduced-motion -----------------------------------------
	const rmPage = await browser.newPage({ viewport: { width: 1200, height: 800 }, reducedMotion: "reduce" });
	await rmPage.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await rmPage.waitForSelector("#backdrop-btn", { state: "attached" });
	if (await rmPage.locator("#backdrop-btn").evaluate((n) => n.dataset.on !== "true")) {
		await rmPage.locator("#backdrop-btn").click();
	}
	await rmPage.locator("#backdrop-select").selectOption("aurora");
	const rm = await rmPage.evaluate(() => ({
		star: getComputedStyle(document.querySelector(".starfield .star")).animationName,
		meteor: getComputedStyle(document.querySelector(".starfield .meteor")).display,
	}));
	ok("reduced-motion mematikan meteor", rm.meteor === "none", rm.meteor);
	ok("reduced-motion mematikan kedip", rm.star === "none", rm.star);
	await rmPage.close();

	ok("tidak ada 404 aset backdrop", badResponses.length === 0, badResponses.join(" | "));
	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	if (errors.length) failed.push("js errors");

	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nAurora shooting stars ok");
})().catch((e) => { console.error(e); process.exit(1); });
