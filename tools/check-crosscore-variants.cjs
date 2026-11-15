#!/usr/bin/env node
/**
 * Regresi varian CrossCore: rig Spine dan rig interaksi harus melebur jadi
 * SATU kartu dengan dropdown "Spine / Interaksi".
 *
 * Regresi yang dicegah: attachCrosscoreFamilies() dulu mencocokkan nama folder
 * secara persis, padahal dua pohon aset beda kapital dan pohon interaksi
 * berakhiran `_spine` (10010_skin_Alps03 vs 10010_skin_alps03_spine). Hasilnya
 * cuma 18 dari 899 model yang ber-family. Kuncinya sekarang dinormalisasi.
 *
 * Usage: node tools/check-crosscore-variants.cjs
 */
const assert = require("assert");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ok = (m) => console.log("ok   " + m);

(async () => {
	const raw = await fetch(`${BASE}/api/models?lean=1`, { cache: "no-store" });
	assert.ok(raw.ok, `/api/models -> HTTP ${raw.status}`);
	const d = await raw.json();
	const all = d.models || (Array.isArray(d) ? d : []);
	const cc = all.filter((m) => String(m.id).startsWith("crosscore/") ||
		String(m.id).startsWith("crosscore-interaction/"));
	assert.ok(cc.length >= 800, `model crosscore terlalu sedikit: ${cc.length}`);

	const fam = cc.filter((m) => (m.family || {}).members?.length);
	const roots = cc.filter((m) => !m.family || m.family.root === m.id);
	const families = new Map();
	for (const m of fam) families.set(m.family.root, m.family);

	assert.ok(fam.length >= 600, `model ber-family: ${fam.length}`);
	assert.ok(families.size >= 300, `jumlah family: ${families.size}`);
	assert.ok(roots.length < cc.length - 300, `kartu root: ${roots.length}/${cc.length}`);
	ok(`${cc.length} model -> ${roots.length} kartu root, ${families.size} family, ${fam.length} model ber-family`);

	let withBoth = 0;
	for (const [root, f] of families) {
		const ids = f.members.map((x) => x.id);
		const spine = ids.filter((id) => id.startsWith("crosscore/"));
		const inter = ids.filter((id) => id.startsWith("crosscore-interaction/"));
		assert.ok(spine.length >= 1 && inter.length >= 1,
			`family ${root} tidak punya pasangan Spine/Interaksi: ${JSON.stringify(ids)}`);
		assert.ok(spine.includes(root), `root ${root} bukan rig Spine`);
		for (const x of f.members) {
			assert.ok(/^(Spine|Interaksi)( \d+)?$/.test(x.label),
				`label varian aneh: ${x.label}`);
		}
		withBoth += 1;
	}
	ok(`${withBoth} family punya Spine + Interaksi, root Spine, label valid`);

	const byId = new Map(all.map((m) => [m.id, m]));
	const a = byId.get("crosscore/10010_skin_Alps03");
	const b = byId.get("crosscore-interaction/10010_skin_alps03_spine");
	assert.ok(a?.family && b?.family, "pasangan Alps03 tidak ber-family");
	assert.strictEqual(a.family.root, b.family.root);
	assert.deepStrictEqual(a.family.members.map((x) => x.label), ["Spine", "Interaksi"]);
	ok("pasangan beda kapital + akhiran _spine: 10010_skin_Alps03 nyambung");

	// Kasus 3 anggota: normalisasi 03 vs 3 menyatukan dua rig Spine sekaligus.
	const three = [...families.values()].find((f) => f.members.length === 3);
	assert.ok(three, "tidak ada family 3 anggota (normalisasi angka tidak jalan?)");
	assert.ok(three.members.some((x) => /^Spine 2$/.test(x.label)));
	ok("normalisasi 03 vs 3: family 3 anggota dengan label Spine 1 / Spine 2");

	// Interaksi yang memang tidak punya pasangan harus tetap berdiri sendiri.
	const orphan = cc.filter((m) => String(m.id).startsWith("crosscore-interaction/") && !m.family);
	assert.ok(orphan.length > 0 && orphan.length < 30, `interaksi yatim: ${orphan.length}`);
	ok(`${orphan.length} interaksi tanpa pasangan dibiarkan standalone`);

	// --- UI --------------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	const errs = [];
	page.on("pageerror", (e) => errs.push(e.message));
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	// Pustaka game besar & di-render bertahap: tunggu daftar game, masuk, lalu
	// saring lewat #search supaya kartu yang dicari benar-benar ada di DOM.
	await page.waitForSelector("#game-list .game", { state: "visible", timeout: 90000 });
	await page.waitForSelector('#game-list .game[data-key="crosscore"]',
		{ state: "visible", timeout: 90000 });
	await page.locator('#game-list .game[data-key="crosscore"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible", timeout: 90000 });
	const cardId = "crosscore/10010_skin_Alps03";
	await page.fill("#search", cardId);
	await page.locator(`#model-list [data-id="${cardId}"]`).first()
		.waitFor({ state: "visible", timeout: 30000 });
	await page.locator(`#model-list [data-id="${cardId}"] .variant-chip`).click();
	await page.waitForFunction(
		() => document.querySelectorAll("#variant-tabs .variant-tab").length === 2,
		{ timeout: 30000 });
	const target = "crosscore-interaction/10010_skin_alps03_spine";
	await page.locator(`#variant-tabs .variant-tab[data-id="${target}"]`).click();
	await page.waitForFunction((id) => window.spineStage?.model?.id === id, target,
		{ timeout: 60000 });
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	ok("UI: chip 2 varian, klik tab Interaksi mengganti model, 0 JS error");
	await browser.close();
	console.log("\nCrossCore varian ok");
})().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
