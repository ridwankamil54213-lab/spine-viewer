#!/usr/bin/env node
/**
 * Regresi potret NKAS + skillcut sebagai varian.
 *
 * Sumber: https://nkas-l2d.pages.dev/characters.json
 * Potret : https://nkas.pages.dev/characters/mi_<kode>_s.png
 *
 * Usage: node tools/check-nikke-nkas.cjs
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const BASE = process.env.SPINE_URL || "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const ok = (m, x = "") => console.log("ok   " + m + (x ? " — " + x : ""));

(async () => {
	const dir = path.join(ROOT, "public", "thumbs", "nikke-nkas");
	const man = JSON.parse(fs.readFileSync(path.join(dir, "_manifest.json"), "utf8"));
	const keys = Object.keys(man);
	assert.ok(keys.length >= 1500, `manifest: ${keys.length}`);
	assert.ok(keys.every((k) => man[k].startsWith("nikke-nkas/")));
	ok(`${keys.length} id model memakai potret NKAS`);

	let broken = 0;
	for (const rel of new Set(Object.values(man))) {
		const f = path.join(ROOT, "public", "thumbs", rel);
		if (!fs.existsSync(f)) { broken++; continue; }
		const h = fs.readFileSync(f).subarray(0, 12);
		if (h.subarray(0, 4).toString() !== "RIFF" ||
			h.subarray(8, 12).toString() !== "WEBP") broken++;
	}
	assert.strictEqual(broken, 0, `rusak: ${broken}`);
	ok(`${new Set(Object.values(man)).size} berkas WebP valid`);

	const thumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs || {};
	const served = Object.entries(thumbs).filter(([, v]) =>
		String(v).startsWith("nikke-nkas/"));
	assert.ok(served.length >= 1500, `api override: ${served.length}`);
	ok(`/api/thumbnails menyajikan ${served.length} override NKAS`);

	const models = (await fetch(`${BASE}/api/models?game=nikke&lean=1`,
		{ cache: "no-store" }).then((r) => r.json())).models || [];
	const skill = models.filter((m) => /skillcut|slillcut/i.test(m.id));
	const solo = skill.filter((m) => !m.family || !m.family.members?.length ||
		m.family.root === m.id);
	assert.ok(skill.length >= 200, `skillcut: ${skill.length}`);
	assert.deepStrictEqual(solo.map((m) => m.id), [], "skillcut masih jadi kartu");
	ok(`${skill.length} skillcut semuanya jadi anggota varian`);

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	const errs = [], bad = [];
	page.on("pageerror", (e) => errs.push(e.message));
	page.on("response", (r) => {
		if (r.status() >= 400 && !r.url().includes("favicon")) bad.push(r.status() + " " + r.url());
	});
	await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
	await page.waitForSelector('#game-list .game[data-key="nikke"]',
		{ state: "visible", timeout: 90000 });
	await page.locator('#game-list .game[data-key="nikke"]').click();
	await page.waitForSelector("#model-list .gcard", { state: "visible", timeout: 90000 });
	await page.waitForTimeout(2400);

	const art = await page.evaluate(() => {
		const g = [...document.querySelectorAll("#model-list .gcard")];
		return {
			n: g.length,
			nkas: g.filter((x) => x.querySelector("img.gcard-img")?.getAttribute("src")
				?.startsWith("/thumbs/nikke-nkas/")).length,
			skill: g.filter((x) => /skillcut|slillcut/i.test(x.dataset.id || "")).length,
			filters: document.querySelector("#nk-filters")?.hidden === false,
			count: document.querySelector("#model-count")?.textContent || "",
		};
	});
	assert.ok(art.n > 0 && art.nkas === art.n, JSON.stringify(art));
	assert.strictEqual(art.skill, 0, "skillcut masih tampil sebagai kartu");
	assert.strictEqual(art.filters, true);
	ok(`halaman 1: ${art.nkas}/${art.n} potret NKAS · 0 kartu skillcut · ${art.count}`);

	const all = Number(await page.locator("#model-count").textContent());
	await page.locator('#nk-filters .ls-row[data-kind="rarity"] .ls-chip[data-value="SSR"]').click();
	await page.waitForTimeout(900);
	const ssr = Number(await page.locator("#model-count").textContent());
	assert.ok(ssr < all, `${all} -> ${ssr}`);
	await page.locator("#nk-reset").click();
	await page.waitForTimeout(900);
	assert.strictEqual(Number(await page.locator("#model-count").textContent()), all);
	ok(`filter tetap jalan: ${all} -> ${ssr} -> ${all}`);

	assert.strictEqual(bad.length, 0, "404: " + bad.slice(0, 2).join(" | "));
	assert.strictEqual(errs.length, 0, "JS error: " + errs.slice(0, 2).join(" | "));
	ok("0 request 404, 0 JS error");
	await browser.close();
	console.log("\nPotret NKAS & varian skillcut ok");
})().catch((e) => { console.error("FAIL " + e.message); process.exit(1); });
