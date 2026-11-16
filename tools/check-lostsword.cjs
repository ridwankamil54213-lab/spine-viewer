#!/usr/bin/env node
/**
 * Verifikasi end-to-end Lost Sword (sumber: https://lost-sword-l2d-viewer.pages.dev/):
 *   1. /api/models?game=lostsword -> model Spine (standing/chibi/pet),
 *      kartu root, 0 duplikat kapitalisasi, semua punya metadata character.
 *   2. /api/models?game=lostsword-video -> video, semuanya terhubung ke
 *      family karakter di lostsword dan disembunyikan dari daftar game utama.
 *   3. /api/thumbnails -> semua item (Spine + video) punya thumbnail WebP
 *      valid di disk (char_*, small_*, pet_*).
 *   4. /api/update/lostsword?mode=check -> ok:true, changed:false.
 *
 * Angka ekspektasi DIHITUNG dari assets/lostsword/_names.json (yang ditulis
 * refresh.py dari katalog live), bukan hardcode: jumlah entri situs bisa
 * berubah tiap rilis tanpa membuat regresi ini palsu merah.
 *
 *   5. Playwright headless:
 *      - Pilih Lost Sword -> kartu root + thumbnail ter-render, dan tile
 *        Lost Sword — Video disembunyikan.
 *      - Buka popup Varian Agravaine -> 5 baris (Utama, Daily — Silent Shadow,
 *        Battle Mode, Pet Agravaine, Skill Cutscene) + grup Model/Aksi/Varian +
 *        semua baris punya thumbnail termuat + badge Video.
 *      - Klik varian Daily, Battle Mode, Pet, dan Skill Cutscene (MP4) +
 *        model baru Galahad_Memorial tanpa 404 maupun pageerror.
 */
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.SPINE_VIEWER_URL || "http://127.0.0.1:3000";

let pass = 0;
let fail = 0;
function ok(cond, msg, extra = "") {
	if (cond) {
		pass++;
		console.log(`  ok   ${msg}${extra ? " — " + extra : ""}`);
	} else {
		fail++;
		console.error(`  FAIL ${msg}${extra ? " — " + extra : ""}`);
	}
}

function getJson(urlPath) {
	return new Promise((resolve, reject) => {
		http.get(BASE + urlPath, (res) => {
			let raw = "";
			res.on("data", (d) => (raw += d));
			res.on("end", () => {
				try {
					resolve({ status: res.statusCode, body: JSON.parse(raw) });
				} catch (e) {
					reject(new Error(`${urlPath}: JSON invalid (${e.message})`));
				}
			});
		}).on("error", reject);
	});
}

(async () => {
console.log("=== Check Lost Sword (lost-sword-l2d-viewer.pages.dev) ===");

// Sumber kebenaran tunggal: metadata yang ditulis refresh.py dari katalog
// live. Kunci `models` mencakup id Spine DAN id video.
const namesFile = JSON.parse(fs.readFileSync(
	path.join(ROOT, "assets", "lostsword", "_names.json"), "utf8"));
const metaIds = Object.keys(namesFile.models || {});
const expectedSpine = metaIds.filter((k) => k.startsWith("lostsword/")).length;
const expectedVideos = metaIds.filter((k) => k.startsWith("lostsword-video/")).length;
const expectedFamilies = (namesFile.families || []).length;
console.log(`  ekspektasi dari _names.json: ${expectedSpine} Spine, `
	+ `${expectedVideos} video, ${expectedFamilies} family, `
	+ `${namesFile.entries} entri (sig ${namesFile.sig})`);

const [{ body: lsBody }, { body: vidBody }, { body: thumbBody }, { body: updBody }] =
		await Promise.all([
			getJson("/api/models?game=lostsword&refresh=1"),
			getJson("/api/models?game=lostsword-video"),
			getJson("/api/thumbnails"),
			getJson("/api/update/lostsword?mode=check"),
		]);

	const models = lsBody.models || [];
	const videos = vidBody.models || [];
	const thumbs = thumbBody.thumbs || {};

	ok(models.length === expectedSpine, "jumlah model Spine sesuai _names.json",
		`${models.length}/${expectedSpine}`);
	ok(videos.length === expectedVideos, "jumlah video sesuai _names.json",
		`${videos.length}/${expectedVideos}`);

	const roots = models.filter((m) => !m.family || m.family.root === m.id);
	const inFam = models.filter((m) => m.family && m.family.members.length >= 2);
	ok(roots.length === expectedFamilies, "jumlah kartu root = family di _names.json",
		`roots=${roots.length}/${expectedFamilies}`);
	ok(inFam.length >= expectedSpine - 20,
		"mayoritas model Spine tergabung di family karakter",
		`inFam=${inFam.length}/${models.length}`);

	const withChar = models.filter(
		(m) => m.character && m.character.source === "lost-sword-l2d-viewer.pages.dev" && m.character.name,
	);
	ok(withChar.length === models.length, "semua model Spine punya metadata character dari situs", `${withChar.length}/${models.length}`);

	// Tripwire penggantian penuh: folder sisa ekstraksi XAPK lama tidak boleh
	// kembali (dulu 732 model "hantu" dari unit/ + lobbyunit/ ikut terindeks).
	const legacyModel = ["unit", "lobbyunit"].filter((d) =>
		fs.existsSync(path.join(ROOT, "assets", "lostsword", d)));
	const legacyVideo = ["High", "Low"].filter((d) =>
		fs.existsSync(path.join(ROOT, "assets", "lostsword-video", d)));
	ok(legacyModel.length === 0 && legacyVideo.length === 0,
		"tidak ada sisa pohon XAPK lama (unit/lobbyunit/High/Low)",
		`model=${legacyModel.join(",") || "-"} video=${legacyVideo.join(",") || "-"}`);
	const kinds = new Set(models.map((m) => m.id.split("/")[1]));
	ok([...kinds].every((k) => ["standing", "chibi", "pet"].includes(k)),
		"semua model berasal dari standing/chibi/pet sesuai katalog situs",
		[...kinds].join(","));

	// Pastikan tidak ada duplikat kapitalisasi folder di disk
	const lowerFolders = new Set();
	let caseDup = 0;
	for (const kind of ["standing", "chibi", "pet"]) {
		const kd = path.join(ROOT, "assets", "lostsword", kind);
		if (!fs.existsSync(kd)) continue;
		for (const d of fs.readdirSync(kd)) {
			const k = `${kind}/${d.toLowerCase()}`;
			if (lowerFolders.has(k)) caseDup++;
			lowerFolders.add(k);
		}
	}
	ok(caseDup === 0, "0 folder duplikat kapitalisasi di assets/lostsword", `caseDup=${caseDup}`);

	// Semua video terhubung ke family karakter di lostsword & hiddenGame=true
	const vidsLinked = videos.filter((v) => v.family && v.family.root.startsWith("lostsword/"));
	const vidsHidden = videos.filter((v) => v.hiddenGame === true);
	ok(vidsLinked.length === videos.length, "semua video terhubung ke family karakter Lost Sword", `${vidsLinked.length}/${videos.length}`);
	ok(vidsHidden.length === videos.length, "lostsword-video memakai hiddenGame: true", `${vidsHidden.length}/${videos.length}`);

	// Cek kelengkapan berkas di disk untuk seluruh model Spine & video
	let missingFiles = 0;
	for (const m of models) {
		const dir = path.join(ROOT, "assets", m.id.split("#")[0]);
		for (const f of m.files || []) {
			if (!fs.existsSync(path.join(dir, f))) missingFiles++;
		}
	}
	for (const v of videos) {
		const p = path.join(ROOT, "assets", decodeURIComponent(v.videoFile || "").replace(/^\//, ""));
		if (!fs.existsSync(p)) missingFiles++;
	}
	ok(missingFiles === 0, "semua berkas .skel/.json/.atlas/.png/.mp4 ada di disk", `missing=${missingFiles}`);

	// Thumbnail untuk seluruh model Spine + video
	const spineThumbs = models.filter((m) => thumbs[m.id]);
	const videoThumbs = videos.filter((v) => thumbs[v.id]);
	let missingThumbDisk = 0;
	for (const item of [...models, ...videos]) {
		const rel = thumbs[item.id];
		if (!rel || !fs.existsSync(path.join(ROOT, "public", "thumbs", rel))) {
			missingThumbDisk++;
		}
	}
	ok(spineThumbs.length === models.length, "100% model Spine punya thumbnail", `${spineThumbs.length}/${models.length}`);
	ok(videoThumbs.length === videos.length, "100% video punya thumbnail", `${videoThumbs.length}/${videos.length}`);
	ok(missingThumbDisk === 0, "semua berkas WebP thumbnail ada di public/thumbs/lostsword", `missing=${missingThumbDisk}`);

	// Cek kontrak updater --check & --apply
	ok(
		updBody &&
			updBody.ok === true &&
			updBody.changed === false &&
			updBody.have === expectedSpine &&
			!!updBody.previous &&
			updBody.previous === updBody.version &&
			updBody.new === 0,
		"GET /api/update/lostsword?mode=check mengembalikan ok:true, changed:false, previous=version",
		`version=${updBody?.version} previous=${updBody?.previous} have=${updBody?.have} videos=${updBody?.videos}`,
	);
	ok(
		Array.isArray(updBody?.log) &&
			updBody.log.length >= 4 &&
			updBody.log.some((l) => l.includes("lost-sword-l2d-viewer.pages.dev")) &&
			updBody.log.every((l) => !l.trim().startsWith("{")),
		"log --check berisi baris progres manusiawi (bukan raw JSON)",
		`${updBody?.log?.length || 0} baris`,
	);
	ok(
		fs.existsSync(path.join(ROOT, "data", "lostsword-update-state.json")),
		"state updater tersimpan di data/lostsword-update-state.json",
	);

	// Verifikasi nyata di browser Playwright
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(90000);
	const bad404 = [];
	const pageErrors = [];
	page.on("response", (res) => {
		if (res.status() >= 400 && !res.url().includes("favicon")) {
			bad404.push(`${res.status()} ${res.url()}`);
		}
	});
	page.on("pageerror", (err) => pageErrors.push(err.message));

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible", timeout: 90000 });

	const gameCheck = await page.evaluate(() => {
		const ls = document.querySelector('#game-list .game[data-key="lostsword"]');
		const lsVid = document.querySelector('#game-list .game[data-key="lostsword-video"]');
		return {
			hasLs: !!ls,
			lsText: ls ? ls.textContent.trim() : "",
			hasLsVid: !!lsVid,
		};
	});
	ok(gameCheck.hasLs && gameCheck.lsText.includes(String(expectedFamilies)),
		`tile game Lost Sword menampilkan ${expectedFamilies} kartu root`, gameCheck.lsText);
	ok(!gameCheck.hasLsVid, "tile Lost Sword — Video disembunyikan dari daftar game utama");

	await page.locator('#game-list .game[data-key="lostsword"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard", { state: "visible" });

	// Verifikasi tombol pembaru di UI untuk Lost Sword (tidak ada titik merah palsu & log bersih)
	await page.waitForTimeout(600);
	const updUi = await page.evaluate(() => {
		const btn = document.getElementById("update-check");
		const dot = document.getElementById("update-dot");
		return {
			btnVisible: !!btn && !btn.hidden,
			dotHidden: !!dot && dot.hidden === true,
		};
	});
	ok(updUi.btnVisible && updUi.dotHidden, "tombol Periksa pembaruan tampil & titik merah mati saat sudah terbaru");

	await page.locator("#update-check").click();
	await page.waitForFunction(
		() => {
			const modal = document.getElementById("update-log-modal");
			const view = document.getElementById("update-log-view");
			return modal && !modal.hidden && view && view.textContent.includes("lost-sword-l2d-viewer.pages.dev");
		},
		null,
		{ timeout: 15000 },
	);
	const logText = await page.evaluate(() => {
		const txt = document.getElementById("update-log-view")?.textContent || "";
		document.getElementById("update-log-close")?.click();
		return txt;
	});
	ok(
		logText.includes("Sudah terbaru") && !logText.trim().startsWith("{"),
		"klik Periksa pembaruan menampilkan log pemeriksaan situs referensi di modal",
	);

	const ID = "lostsword/standing/Agravaine";
	await page.fill("#search", "Agravaine");
	const card = page.locator(`#model-list [data-id="${ID}"]`).first();
	await card.waitFor({ state: "visible", timeout: 30000 });
	ok((await card.count()) === 1, "kartu Agravaine tampil di daftar/galeri");

	const cardImg = await page.waitForFunction(
		(id) => {
			const c = document.querySelector(`#model-list [data-id="${id}"]`);
			const img = c && c.querySelector("img.model-thumb, img.gcard-img");
			return img && img.complete && img.naturalWidth > 0
				? { complete: true, w: img.naturalWidth, h: img.naturalHeight }
				: false;
		},
		ID,
		{ timeout: 30000 },
	).then((h) => h.jsonValue()).catch(() => ({ complete: false, w: 0, h: 0 }));
	ok(cardImg.complete && cardImg.w > 0, "thumbnail kartu Agravaine ter-render (WebP 256x340)", `${cardImg.w}x${cardImg.h}`);

	// Buka popup varian dari chip kartu Agravaine
	const chip = card.locator(".variant-chip");
	ok((await chip.count()) === 1, "chip '5 varian' muncul di kartu Agravaine");
	await chip.click();
	await page.waitForFunction(
		() => {
			const pop = document.querySelector("#variant-popup");
			if (!pop || pop.hidden) return false;
			const imgs = [...document.querySelectorAll("#variant-list .variant-item-thumb img")];
			return imgs.length === 5 && imgs.every((img) => img.complete && img.naturalWidth > 0);
		},
		null,
		{ timeout: 30000 },
	);

	const pop = await page.evaluate(() => {
		const items = [...document.querySelectorAll("#variant-list .variant-item")];
		const groups = [...document.querySelectorAll("#variant-list .variant-group-head")].map((g) => g.textContent.trim());
		return {
			open: !document.querySelector("#variant-popup")?.hidden,
			items: items.length,
			ids: items.map((x) => x.dataset.id),
			thumbs: items.filter((x) => {
				const img = x.querySelector(".variant-item-thumb img");
				return img && img.complete && img.naturalWidth > 0;
			}).length,
			hasVideoBadge: items.some((x) => x.dataset.id.startsWith("lostsword-video/") && x.textContent.toLowerCase().includes("video")),
			groups,
		};
	});
	ok(
		pop.open && pop.items === 5,
		"popup Varian Agravaine terbuka dengan 5 baris (Utama, Daily, Battle Mode, Pet, Skill Cutscene)",
		`groups=${pop.groups.join("/")} ids=${pop.ids.length}`,
	);
	ok(pop.thumbs === 5, "semua 5 baris di popup Varian punya thumbnail termuat (char/small/pet)", `thumbs=${pop.thumbs}/5`);
	ok(pop.hasVideoBadge, "baris Skill Cutscene di popup Varian memiliki badge Video");

	// Klik varian Daily — Silent Shadow, Battle Mode, Pet Agravaine, lalu Skill Cutscene
	for (const [targetId, label] of [
		["lostsword/standing/Agravaine_Daily", "Daily — Silent Shadow (Standing)"],
		["lostsword/chibi/Agravaine", "Battle Mode (Chibi)"],
		["lostsword/pet/Pet_Agravaine_01", "Pet Agravaine"],
	]) {
		const pill = page.locator("#variant-btn");
		if (await page.evaluate(() => document.querySelector("#variant-popup")?.hidden)) {
			await pill.click();
			await page.waitForTimeout(250);
		}
		await page.locator(`#variant-list .variant-item[data-id="${targetId}"]`).click();
		await page.waitForFunction((id) => window.spineStage?.model?.id === id, targetId, { timeout: 60000 });
		const cur = await page.evaluate(() => window.spineStage?.model?.id);
		ok(cur === targetId, `klik varian ${label} memuat model dengan mulus`, cur);
	}

	// Klik varian video Skill Cutscene
	await page.locator("#variant-btn").click();
	await page.waitForTimeout(250);
	const vidTarget = "lostsword-video/skill-videos/Pc_Agravaine_01";
	await page.locator(`#variant-list .variant-item[data-id="${vidTarget}"]`).click();
	await page.waitForFunction(
		(id) => {
			const v = document.querySelector("video.video-stage");
			return window.spineStage?.model?.id === id && !!v && v.getAttribute("src")?.includes("Pc_Agravaine_01.mp4");
		},
		vidTarget,
		{ timeout: 30000 },
	);
	const vidState = await page.evaluate(() => {
		const v = document.querySelector("video.video-stage");
		return { id: window.spineStage?.model?.id, src: v?.getAttribute("src") || "" };
	});
	ok(vidState.id === vidTarget && vidState.src.includes("Pc_Agravaine_01.mp4"), "klik varian Skill Cutscene memasang video.video-stage MP4", vidState.src);

	// Uji pencarian judul kostum ("First Love") -> menemukan kartu Galahad & memuat varian Memorial baru
	await page.fill("#search", "First Love");
	const galCard = page.locator('#model-list [data-id="lostsword/standing/Galahad"]').first();
	await galCard.waitFor({ state: "visible", timeout: 30000 });
	ok((await galCard.count()) === 1, "pencarian sub-judul kostum 'First Love' menemukan kartu Galahad");
	await galCard.locator(".variant-chip").click();
	await page.waitForTimeout(350);
	const memTarget = "lostsword/standing/Galahad_Memorial";
	await page.locator(`#variant-list .variant-item[data-id="${memTarget}"]`).click();
	await page.waitForFunction((id) => window.spineStage?.model?.id === id, memTarget, { timeout: 60000 });
	ok(true, "model baru Galahad_Memorial (First Love) ter-render di kanvas");

	ok(bad404.length === 0, "0 request 404/500 selama pengujian browser", bad404.slice(0, 3).join("; "));
	ok(pageErrors.length === 0, "0 uncaught pageerror selama pengujian browser", pageErrors.slice(0, 3).join("; "));

	await browser.close();
	console.log(`\n=== Hasil Lost Sword: ${pass} ok, ${fail} FAIL ===`);
	process.exit(fail ? 1 : 0);
})().catch((err) => {
	console.error("FATAL:", err);
	process.exit(1);
});
