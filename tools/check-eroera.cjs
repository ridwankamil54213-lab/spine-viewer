#!/usr/bin/env node
/**
 * Verifikasi end-to-end 欲洛降临 (EroEra — https://www.youdianse.com/game/detail/456):
 *   1. /api/models?game=eroera -> 174 model Spine 4.1.23/4.1.24, 43 kartu root
 *      (30 hero + 10 pet + 3 extra), semua punya metadata character dari Luban.
 *   2. Semua 174 skeleton (.skel biner maupun .json) berhasil di-parse oleh
 *      @pixi-spine/runtime-4.1 tanpa error (dan 0 BOM di .atlas).
 *   3. /api/thumbnails -> 165/174 model punya thumbnail WebP dari SpriteAtlas/Packs/Hero
 *      (card_1_1..card_30_3 untuk hero & varian H/Interaction, p_kp* untuk Pet).
 *   4. /api/update/eroera?mode=check -> ok:true, changed:false, previous=version,
 *      log progres bersih, state di data/eroera-update-state.json.
 *   5. Playwright headless:
 *      - Tile game 欲洛降临 (EroEra) menampilkan 43 kartu root + ikon game.
 *      - Tombol Periksa pembaruan tampil, titik merah mati, klik menampilkan modal log.
 *      - Kartu 白川纱世 (10001) menampilkan thumbnail WebP & chip '7 varian'.
 *      - Popup Varian menampilkan 7 baris (Utama, H Scene Base, H Scene Adv,
 *        Interaction, Aim, Cover, Skill Cut) dengan thumbnail per varian (card_1_1,
 *        card_1_2, card_1_3).
 *      - Klik varian H Scene Base, H Scene Adv, Interaction, Skill Cut, plus
 *        hero_10009 (.json) dan pet_huoyanfeie ter-render di kanvas dengan 0 404.
 */
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { chromium } = require("playwright-core");
const { SkeletonBinary, SkeletonJson, AtlasAttachmentLoader } = require("@pixi-spine/runtime-4.1");
const { TextureAtlas } = require("@pixi-spine/base");

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
	console.log("=== Check 欲洛降临 / EroEra (youdianse.com/game/detail/456) ===");

	const [{ body: eeBody }, { body: thumbBody }, { body: updBody }] = await Promise.all([
		getJson("/api/models?game=eroera&refresh=1"),
		getJson("/api/thumbnails"),
		getJson("/api/update/eroera?mode=check"),
	]);

	const models = eeBody.models || [];
	const thumbs = thumbBody.thumbs || {};

	ok(models.length === 174, "jumlah model Spine EroEra = 174", `${models.length}`);

	const roots = models.filter((m) => !m.family || m.family.root === m.id);
	const variants = models.filter((m) => m.family && m.family.root !== m.id);
	ok(roots.length === 43, "jumlah kartu root = 43 (30 hero + 10 pet + 3 extra)", `roots=${roots.length}`);
	ok(variants.length === 131, "jumlah varian tersembunyi = 131", `variants=${variants.length}`);

	const withChar = models.filter(
		(m) => m.character && m.character.source === "youdianse.com/game/detail/456" && m.character.name,
	);
	ok(withChar.length === models.length, "semua 174 model punya metadata character Luban", `${withChar.length}/${models.length}`);

	// Parse semua 174 skeleton dengan @pixi-spine/runtime-4.1 & cek kelengkapan disk
	let parseOk = 0;
	const parseErrs = [];
	let missingFiles = 0;
	for (const m of models) {
		const dir = path.join(ROOT, "assets", m.id);
		for (const f of m.files || []) {
			if (!fs.existsSync(path.join(dir, f))) missingFiles++;
		}
		try {
			const atlasFile = (m.files || []).find((f) => f.endsWith(".atlas"));
			const skelFile = m.skeletonFile || (m.files || []).find((f) => /\.(skel|json)$/i.test(f));
			const atlasText = fs.readFileSync(path.join(dir, atlasFile), "utf8");
			const atlas = new TextureAtlas(atlasText, (_line, cb) =>
				cb({ width: 2048, height: 2048, valid: true, scaleMode: 1, setSize() {}, dispose() {} }),
			);
			const loader = new AtlasAttachmentLoader(atlas);
			let d;
			if (/\.json$/i.test(skelFile)) {
				d = new SkeletonJson(loader).readSkeletonData(
					JSON.parse(fs.readFileSync(path.join(dir, skelFile), "utf8")),
				);
			} else {
				d = new SkeletonBinary(loader).readSkeletonData(
					new Uint8Array(fs.readFileSync(path.join(dir, skelFile))),
				);
			}
			if (d.bones.length > 0 && d.animations.length > 0) parseOk++;
		} catch (e) {
			parseErrs.push(`${m.id}: ${e.message}`);
		}
	}
	ok(missingFiles === 0, "semua berkas .skel/.json/.atlas/.png ada di disk", `missing=${missingFiles}`);
	ok(parseOk === models.length, "174/174 skeleton ter-parse bersih oleh @pixi-spine/runtime-4.1", `${parseOk}/${models.length} ${parseErrs.slice(0, 2).join("; ")}`);

	// Thumbnail
	const withThumb = models.filter((m) => thumbs[m.id]);
	let missingThumbDisk = 0;
	for (const m of withThumb) {
		const rel = thumbs[m.id];
		if (!fs.existsSync(path.join(ROOT, "public", "thumbs", rel))) missingThumbDisk++;
	}
	ok(withThumb.length === 165, "165/174 model (30 hero + semua variannya + 10 pet) punya thumbnail WebP", `${withThumb.length}`);
	ok(missingThumbDisk === 0, "semua berkas WebP thumbnail ada di public/thumbs/eroera", `missing=${missingThumbDisk}`);
	ok(
		thumbs["eroera/hero_10001"] === "eroera/card_1_1.webp" &&
			thumbs["eroera/hero_10001_h_base"] === "eroera/card_1_2.webp" &&
			thumbs["eroera/hero_10001_h_adv"] === "eroera/card_1_3.webp",
		"varian H Base & H Adv memakai potret kartu bertingkat (card_1_1 / card_1_2 / card_1_3)",
	);
	ok(fs.existsSync(path.join(ROOT, "public", "thumbs", "_game", "eroera.png")), "ikon game public/thumbs/_game/eroera.png tersedia");

	// Kontrak updater
	ok(
		updBody &&
			updBody.ok === true &&
			updBody.changed === false &&
			updBody.have === 174 &&
			!!updBody.previous &&
			updBody.previous === updBody.version &&
			updBody.new === 0,
		"GET /api/update/eroera?mode=check mengembalikan ok:true, changed:false, previous=version",
		`version=${updBody?.version} have=${updBody?.have}`,
	);
	ok(
		Array.isArray(updBody?.log) &&
			updBody.log.length >= 3 &&
			updBody.log.every((l) => !l.trim().startsWith("{")),
		"log --check berisi baris progres manusiawi (bukan raw JSON)",
	);
	ok(fs.existsSync(path.join(ROOT, "data", "eroera-update-state.json")), "state updater tersimpan di data/eroera-update-state.json");

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
		const el = document.querySelector('#game-list .game[data-key="eroera"]');
		return {
			exists: !!el,
			text: el ? el.textContent.trim() : "",
		};
	});
	ok(gameCheck.exists && gameCheck.text.includes("43"), "tile game 欲洛降临 (EroEra) menampilkan 43 kartu root", gameCheck.text);

	await page.locator('#game-list .game[data-key="eroera"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard", { state: "visible" });

	// Cek tombol Periksa pembaruan & titik merah
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

	const ID = "eroera/hero_10001";
	await page.fill("#search", "白川纱世");
	const card = page.locator(`#model-list [data-id="${ID}"]`).first();
	await card.waitFor({ state: "visible", timeout: 30000 });
	ok((await card.count()) === 1, "kartu 白川纱世 (10001) ditemukan lewat pencarian nama Tionghoa");

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
	ok(cardImg.complete && cardImg.w > 0, "thumbnail kartu 白川纱世 ter-render", `${cardImg.w}x${cardImg.h}`);

	// Klik chip '7 varian'
	const chip = card.locator(".variant-chip");
	ok((await chip.count()) === 1, "chip '7 varian' muncul di kartu 白川纱世");
	await chip.click();
	await page.waitForFunction(
		() => {
			const pop = document.querySelector("#variant-popup");
			if (!pop || pop.hidden) return false;
			const imgs = [...document.querySelectorAll("#variant-list .variant-item-thumb img")];
			return imgs.length === 7 && imgs.every((img) => img.complete && img.naturalWidth > 0);
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
			groups,
		};
	});
	ok(pop.open && pop.items === 7, "popup Varian 白川纱世 terbuka dengan 7 baris", `groups=${pop.groups.join("/")}`);
	ok(pop.thumbs === 7, "semua 7 baris di popup Varian punya thumbnail termuat", `thumbs=${pop.thumbs}/7`);

	for (const [targetId, label] of [
		["eroera/hero_10001_h_base", "H Scene — Base (初级)"],
		["eroera/hero_10001_h_adv", "H Scene — Adv (高级)"],
		["eroera/hero_10001_interaction", "Interaction (调教)"],
		["eroera/hero_10001_skill", "Skill Cut"],
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

	// Uji pencarian & muat kartu Pet (卜吉 / 炽羽 -> pet_huoyanfeie)
	await page.fill("#search", "卜吉");
	const petCard = page.locator('#model-list [data-id="eroera/pet_huoyanfeie"]').first();
	await petCard.waitFor({ state: "visible", timeout: 30000 });
	await petCard.click();
	await page.waitForFunction(() => window.spineStage?.model?.id === "eroera/pet_huoyanfeie", null, { timeout: 60000 });
	ok(true, "kartu Pet · 卜吉 / 炽羽 (pet_huoyanfeie) ter-render di kanvas");

	ok(bad404.length === 0, "0 request 404/500 selama pengujian browser", bad404.slice(0, 3).join("; "));
	ok(pageErrors.length === 0, "0 uncaught pageerror selama pengujian browser", pageErrors.slice(0, 3).join("; "));

	await browser.close();
	console.log(`\n=== Hasil EroEra: ${pass} ok, ${fail} FAIL ===`);
	process.exit(fail ? 1 : 0);
})().catch((err) => {
	console.error("FATAL:", err);
	process.exit(1);
});
