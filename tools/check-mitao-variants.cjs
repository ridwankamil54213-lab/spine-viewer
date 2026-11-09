#!/usr/bin/env node
/* Regresi Mitao Utopia: varian front + thumbnail HeroSelectDisplay.

   - front_<id> = kartu root; back/hfront/common/skill/hspecial_<id> jadi varian.
   - prefix lain (monster, loading, ...) tetap kartu berdiri sendiri.
   - thumbnail dari DynamicSingleTextures/HeroSelectDisplay dipakai bersama
     oleh semua model dengan suffix id yang sama.
   - UI: chip "N varian" -> popup 6 baris -> klik baris ganti model.

   Run: node tools/check-mitao-variants.cjs   (server on :3000)
*/
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.BASE_URL || "http://127.0.0.1:3000";
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

(async () => {
	const all = await fetch(`${BASE}/api/models`).then((r) => r.json());
	const ms = (all.models || []).filter((m) => m.game === "mitao-utopia");
	ok("Mitao: 214 model terindeks", ms.length === 214, String(ms.length));
	const roots = ms.filter((m) => !m.family || m.family.root === m.id);
	const variants = ms.filter((m) => m.family && m.family.root !== m.id);
	ok("Mitao: 136 kartu root", roots.length === 136, String(roots.length));
	ok("Mitao: 78 varian tersembunyi", variants.length === 78, String(variants.length));
	ok("Mitao: model equip_* sudah dihapus",
		ms.every((m) => !String(m.id).split("/").pop().startsWith("equip_")),
		String(ms.filter((m) => String(m.id).includes("/equip_")).length));

	// --- nama karakter dari tabel lokalisasi bundle -----------------------
	const named = ms.filter((m) => m.character?.name);
	ok("Mitao: 143 model punya nama karakter", named.length === 143,
		String(named.length));
	const namedFront = ms.find((m) => m.id === "mitao-utopia/front_10001");
	ok("front_10001 = 綾乃 真理子 (JP) + varian CN/TW",
		namedFront?.character?.name === "綾乃 真理子" &&
		namedFront?.character?.nameCN === "绫乃 真理子" &&
		namedFront?.character?.source === "HEROINFO_Name_10001" &&
		String(namedFront?.name || "").includes("(front_10001)"),
		JSON.stringify(namedFront?.character));
	ok("varian back_10001 mewarisi nama karakter yang sama",
		ms.find((m) => m.id === "mitao-utopia/back_10001")?.character?.name ===
		"綾乃 真理子");
	ok("monster_20001 juga punya nama dari bundle",
		!!ms.find((m) => m.id === "mitao-utopia/monster_20001")?.character?.name,
		String(ms.find((m) => m.id === "mitao-utopia/monster_20001")?.character?.name));

	const f = ms.find((m) => m.id === "mitao-utopia/front_10001");
	const labels = (f?.family?.members || []).map((x) => x.label);
	ok("front_10001: Utama + Back + H Front + Common + Skill + H Special",
		JSON.stringify(labels) === JSON.stringify(
			["Utama", "Back", "H Front", "Common", "Skill", "H Special"]),
		JSON.stringify(labels));
	ok("root family = front_10001", f?.family?.root === "mitao-utopia/front_10001",
		String(f?.family?.root));
	const hidden = ["back", "hfront", "common", "skill", "hspecial"]
		.map((p) => `${p}_10001`)
		.every((s) => {
			const m = ms.find((x) => x.id === `mitao-utopia/${s}`);
			return m && m.family?.root === "mitao-utopia/front_10001";
		});
	ok("back/hfront/common/skill/hspecial bukan kartu root", hidden);
	const hs = ms.find((m) => m.id === "mitao-utopia/hspecial_10001");
	ok("hspecial jadi varian front_10001 dengan label H Special",
		!!hs && hs.family?.root === "mitao-utopia/front_10001" &&
		hs.family?.label === "H Special", JSON.stringify(hs?.family?.label));

	// --- thumbnail --------------------------------------------------------
	const th = await fetch(`${BASE}/api/thumbnails`).then((r) => r.json());
	const thumbs = th.thumbs || {};
	const keys = Object.keys(thumbs).filter((k) => k.startsWith("mitao-utopia/"));
	ok("thumbnail Mitao >= 110 kunci", keys.length >= 110, String(keys.length));
	ok("tidak ada thumbnail equip yang tersisa",
		keys.every((k) => !k.includes("/equip_")));
	ok("semua varian front_10001 punya thumbnail",
		["front", "back", "hfront", "common", "skill", "hspecial"].every(
			(p) => !!thumbs[`mitao-utopia/${p}_10001`]));
	const filesOk = keys.every((k) => {
		const rel = thumbs[k];
		return typeof rel === "string" &&
			fs.existsSync(path.join(ROOT, "public", "thumbs", rel));
	});
	ok("semua berkas thumbnail ada di disk", filesOk);
	const sample = path.join(ROOT, "public", "thumbs",
		"mitao-utopia", "HeroSelectDisplay_10001.webp");
	const magic = fs.existsSync(sample) ? fs.readFileSync(sample).subarray(0, 16) : Buffer.alloc(0);
	ok("thumbnail berformat WebP", magic.subarray(0, 4).toString() === "RIFF" &&
		magic.subarray(8, 12).toString() === "WEBP", magic.toString("hex").slice(0, 32));

	// --- UI ---------------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(90000);
	const missing = [];
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|png|atlas|json|skel)(\?|$)/.test(r.url()))
			missing.push(`${r.status()} ${r.url()}`);
	});
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible", timeout: 90000 });
	await page.locator('#game-list .game[data-key="mitao-utopia"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible" });
	const ID = "mitao-utopia/front_10001";
	await page.fill("#search", ID);
	const card = page.locator(`#model-list [data-id="${ID}"]`).first();
	await card.waitFor({ state: "visible", timeout: 30000 });
	ok("kartu front_10001 tampil", (await card.count()) === 1);
	// Layout bisa daftar (.model-thumb) atau galeri (.gcard-img) — selector netral.
	const cardImg = await page.waitForFunction((id) => {
		const c = document.querySelector(`#model-list [data-id="${id}"]`);
		const img = c && c.querySelector("img.model-thumb, img.gcard-img");
		return img && img.complete && img.naturalWidth > 0
			? { complete: true, w: img.naturalWidth } : false;
	}, ID, { timeout: 30000 }).then((h) => h.jsonValue())
		.catch(() => ({ complete: false, w: 0 }));
	ok("thumbnail ter-render di kartu", cardImg.complete && cardImg.w > 0,
		JSON.stringify(cardImg));
	const chip = card.locator(".variant-chip");
	ok("chip 'N varian' muncul", (await chip.count()) === 1);
	await chip.click();
	await page.waitForTimeout(450);
	const pop = await page.evaluate(() => {
		const items = [...document.querySelectorAll("#variant-list .variant-item")];
		return {
			open: !document.querySelector("#variant-popup")?.hidden,
			items: items.length,
			ids: items.map((x) => x.dataset.id),
			thumbs: items.filter((x) => {
				const img = x.querySelector(".variant-item-thumb img");
				return img && img.complete && img.naturalWidth > 0;
			}).length,
		};
	});
	ok("popup varian terbuka dengan 6 baris", pop.open && pop.items === 6,
		JSON.stringify({ open: pop.open, items: pop.items }));
	ok("baris popup = front/back/hfront/common/skill/hspecial",
		JSON.stringify(pop.ids.slice().sort()) === JSON.stringify([
			"mitao-utopia/front_10001", "mitao-utopia/back_10001",
			"mitao-utopia/hfront_10001", "mitao-utopia/common_10001",
			"mitao-utopia/skill_10001", "mitao-utopia/hspecial_10001"].sort()),
		JSON.stringify(pop.ids));
	ok("semua baris popup punya thumbnail termuat", pop.thumbs === 6,
		String(pop.thumbs));

	const target = "mitao-utopia/back_10001";
	await page.locator(`#variant-list .variant-item[data-id="${target}"]`).click();
	await page.waitForFunction((id) => window.spineStage?.model?.id === id, target,
		{ timeout: 90000 });
	const after = await page.evaluate(() => ({
		id: window.spineStage?.model?.id,
		closed: document.querySelector("#variant-popup")?.hidden,
		selected: document.querySelector("#variant-select")?.selectedOptions?.[0]?.dataset?.id,
	}));
	ok("klik varian Back mengganti model", after.id === target, after.id);
	ok("popup tertutup & select tersinkron",
		after.closed === true && after.selected === target, JSON.stringify(after));
	ok("tidak ada aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));

	await browser.close();
	console.log(`\n${failed.length ? "GAGAL: " + failed.join(" | ") : "Mitao varian + thumbnail ok"}`);
	process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
