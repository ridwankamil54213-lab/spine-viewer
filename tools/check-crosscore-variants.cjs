#!/usr/bin/env node
/**
 * Regresi varian CrossCore: SEMUA scene satu karakter jadi SATU kartu dengan
 * dropdown Varian (root = rig Spine utama, label = outfit · sceneLabel).
 *
 * Sumber crosscore.art punya 486 scene + 227 rig efek / 134 karakter. Tanpa grouping ini
 * pustaka menampilkan belasan kartu bernama sama per karakter; grouping lama
 * "Spine / Interaksi" tidak berlaku lagi karena pohon interaksi sudah
 * diarsipkan bersama aset ArtHub.
 *
 * Usage: node tools/check-crosscore-variants.cjs
 */
const assert = require("assert");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ok = (m) => console.log("ok   " + m);

(async () => {
	const d = await fetch(`${BASE}/api/models?lean=1`, { cache: "no-store" }).then((r) => r.json());
	const all = d.models || (Array.isArray(d) ? d : []);
	const cc = all.filter((m) => m.game === "crosscore");
	const byId = new Map(all.map((m) => [m.id, m]));
	assert.strictEqual(cc.length, 713, `model crosscore: ${cc.length}`);

	const roots = cc.filter((m) => !m.family || m.family.root === m.id);
	const fam = cc.filter((m) => (m.family || {}).members?.length);
	const families = new Map();
	for (const m of fam) families.set(m.family.root, m.family);
	assert.strictEqual(roots.length, 134, `kartu root: ${roots.length}`);
	assert.ok(fam.length >= 700, `model ber-family: ${fam.length}`);
	assert.ok(families.size >= 125, `family: ${families.size}`);
	ok(`${cc.length} scene -> ${roots.length} kartu (1 per karakter), ${families.size} family, ${fam.length} ber-varian`);

	for (const [root, f] of families) {
		const ids = f.members.map((x) => x.id);
		assert.ok(ids.includes(root), `root ${root} tidak ada di members`);
		assert.ok(f.members.length >= 2, `family ${root} cuma 1 anggota`);
		assert.strictEqual(f.members[0].label, "Utama", `label root ${root}: ${f.members[0].label}`);
		for (const x of f.members) {
			assert.ok(x.label && byId.has(x.id),
				`anggota family ${root} tidak valid: ${JSON.stringify(x)}`);
			assert.strictEqual(byId.get(x.id).family.root, root,
				`anggota ${x.id} punya root beda`);
		}
	}
	ok(`${families.size} family konsisten: root ada di members, label Utama, id valid`);

	// Karakter dengan 9 scene: root rig Spine + 8 varian (termasuk ilustrasi).
	const mach = byId.get("crosscore/machairodus_game-3018002_default");
	assert.ok(mach?.family && mach.family.members.length >= 5,
		"family machairodus tidak lengkap");
	const hasStatic = mach.family.members.some((x) => x.id.startsWith("crosscore-cg/"));
	ok(`machairodus: ${mach.family.members.length} varian, ada ilustrasi statis = ${hasStatic}`);

	// Karakter berscene-tunggal memang dibiarkan standalone.
	const standalone = cc.filter((m) => !m.family);
	assert.ok(standalone.length >= 1 && standalone.length <= 10,
		`standalone: ${standalone.length}`);
	ok(`${standalone.length} karakter tanpa saudara dibiarkan standalone`);

	// --- UI: ganti varian lewat #variant-select ---------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	const errs = [];
	page.on("pageerror", (e) => errs.push(e.message));
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	await page.waitForSelector("#game-list .game", { state: "visible", timeout: 90000 });
	await page.locator('#game-list .game[data-key="crosscore"]').click();
	await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
		{ state: "visible", timeout: 90000 });
	const rootId = "crosscore/machairodus_game-3018002_default";
	const target = "crosscore/machairodus_game-3018005_skin05a";
	await page.fill("#search", rootId);
	await page.locator(`#model-list [data-id="${rootId}"]`).first()
		.waitFor({ state: "visible", timeout: 30000 });
	await page.locator(`#model-list [data-id="${rootId}"]`).first().click();
	await page.waitForFunction(() => !!window.spineStage?.model?.id, null, { timeout: 90000 });
	const jumped = await page.evaluate((t) => {
		const sel = document.querySelector("#variant-select");
		const opt = [...(sel?.options || [])].find((o) => o.dataset.id === t);
		if (!opt) return false;
		sel.value = opt.value;
		sel.dispatchEvent(new Event("change", { bubbles: true }));
		return true;
	}, target);
	assert.ok(jumped, "varian target tidak ada di #variant-select");
	await page.waitForFunction((id) => window.spineStage?.model?.id === id, target,
		{ timeout: 90000 });
	await page.waitForTimeout(2500);
	const st = await page.evaluate(() => ({
		id: window.spineStage?.model?.id,
		runtime: window.spineStage?.runtime,
		canvas: !!document.querySelector("canvas"),
	}));
	assert.strictEqual(st.id, target);
	assert.strictEqual(st.runtime, "4.2");
	assert.ok(st.canvas);
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	ok(`UI: ganti varian -> ${target.slice(0, 50)} (runtime ${st.runtime}), 0 JS error`);
	await browser.close();
	console.log("\nCrossCore varian ok");
})().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
