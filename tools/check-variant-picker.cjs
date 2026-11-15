/**
 * Smoke test untuk variant picker bersama.
 *
 * Memverifikasi:
 *   - <=3 varian: tab segmented inline (satu klik, tanpa popup)
 *   - >3 varian: popup di tepi stage dengan header grup per jenis,
 *     thumbnail per baris, badge format/animasi, dan preview hover
 *   - chip "N varian" di kartu galeri; klik chip langsung buka picker
 *   - <select id="variant-select"> tetap state holder (dataset.id)
 *   - keyboard: 1-9 lompat varian, [ / ] siklus
 *   - CrossCore: 2 pohon aset melebur (899 model -> 583 kartu root)
 *
 * Run: node tools/check-variant-picker.cjs   (server on :3000)
 */
const { chromium } = require("playwright-core");

const BASE = "http://127.0.0.1:3000";
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

(async () => {
	const all = (await fetch(`${BASE}/api/models?lean=1`).then((r) => r.json())).models || [];
	const cc = all.filter((m) => m.game === "crosscore");
	const roots = cc.filter((m) => !m.family || m.family.root === m.id);
	const paired = cc.filter((m) => (m.family || {}).members?.length);
	ok("CrossCore: 2 pohon melebur jadi kartu root", roots.length < cc.length &&
		cc.length - roots.length >= 300,
		`${roots.length} dari ${cc.length}`);
	ok("CrossCore: >=600 model ber-family", paired.length >= 600, String(paired.length));
	const fam = (all.find((m) => m.id === "crosscore/10010_skin_Alps03") || {}).family;
	ok("label family Spine / Interaksi",
		JSON.stringify(fam?.members?.map((x) => x.label)) === JSON.stringify(["Spine", "Interaksi"]),
		JSON.stringify(fam?.members?.map((x) => x.label)));

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(90000);
	const errors = [];
	const missingAssets = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|png|atlas|json|webm|skel)(\?|$)/.test(r.url()))
			missingAssets.push(`${r.status()} ${r.url()}`);
	});

	const cases = [
		{ game: "bd2", id: "bd2-char/Anastasia/Fire_Graffiti", n: 2, label: "BD2", tabs: true },
		{ game: "epic7", id: "epic7/c1070", n: 5, label: "E7", tabs: false },
		{ game: "chaoszero", id: "chaoszero/model/1010", n: 7, label: "CZN", tabs: false, viaChip: true },
		{ game: "crosscore", id: "crosscore/10010_skin_Alps03", n: 2, label: "CrossCore", tabs: true },
	];

	for (const c of cases) {
		await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
		// Tunggu pustaka game benar-benar ter-render dulu (bisa kena 429 / boot
		// lambat), baru cari kartu game spesifiknya.
		await page.waitForSelector("#game-list .game", { state: "visible", timeout: 90000 });
		await page.waitForSelector(`#game-list .game[data-key="${c.game}"]`, { state: "visible", timeout: 90000 });
		await page.locator(`#game-list .game[data-key="${c.game}"]`).click();
		await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
			{ state: "visible" });
		await page.fill("#search", c.id);
		// #search punya debounce 140 ms; tunggu kartu hasil filter benar-benar
		// ke-render sebelum memeriksa chip-nya (kalau tidak, race di game besar).
		await page.locator(`#model-list [data-id="${c.id}"]`).first()
			.waitFor({ state: "visible", timeout: 20000 });
		const chipCount = await page.locator(`#model-list [data-id="${c.id}"] .variant-chip`).count();
		ok(`${c.label}: chip "N varian" di kartu`, chipCount === 1, String(chipCount));

		if (c.viaChip) {
			await page.locator(`#model-list [data-id="${c.id}"] .variant-chip`).click();
		} else {
			await page.locator(`#model-list [data-id="${c.id}"]`).first().click({ timeout: 40000 });
		}
		await page.waitForFunction(() => !!window.spineStage?.model?.id, null, { timeout: 90000 });

		const shown = await page.evaluate(() => ({
			tabsHidden: document.querySelector("#variant-tabs")?.hidden,
			tabCount: document.querySelectorAll("#variant-tabs .variant-tab").length,
			btnHidden: document.querySelector("#variant-btn")?.hidden,
			inlineHidden: document.querySelector("#variant-wrap")?.hidden,
			count: Number(document.querySelector("#variant-count")?.textContent || 0),
			selectCount: document.querySelector("#variant-select")?.options?.length || 0,
			selectIds: [...(document.querySelector("#variant-select")?.options || [])]
				.map((o) => o.dataset.id).filter(Boolean).length,
			selectedId: document.querySelector("#variant-select")?.selectedOptions?.[0]?.dataset?.id,
			currentId: window.spineStage.model?.id,
			popupOpen: !document.querySelector("#variant-popup")?.hidden,
		}));
		ok(`${c.label}: dropdown inline disembunyikan`, shown.inlineHidden === true);
		ok(`${c.label}: ${c.n} varian`, shown.count === c.n && shown.selectCount === c.n,
			`popup ${shown.count} / select ${shown.selectCount}`);
		ok(`${c.label}: <select> tetap state holder`,
			shown.selectIds === c.n && shown.selectedId === shown.currentId,
			JSON.stringify({ ids: shown.selectIds, selected: shown.selectedId, current: shown.currentId }));

		if (c.tabs) {
			ok(`${c.label}: tab segmented tampil`, shown.tabsHidden === false &&
				shown.tabCount === c.n && shown.btnHidden === true,
				JSON.stringify({ tabs: shown.tabCount, btnHidden: shown.btnHidden }));
			const target = await page.evaluate((activeId) => {
				const t = [...document.querySelectorAll("#variant-tabs .variant-tab")]
					.find((x) => x.dataset.id !== activeId);
				return t?.dataset.id || "";
			}, shown.currentId);
			if (target) {
				await page.locator(`#variant-tabs .variant-tab[data-id="${target}"]`).click();
				await page.waitForFunction((id) => window.spineStage?.model?.id === id, target,
					{ timeout: 90000 });
				const after = await page.evaluate(() => ({
					id: window.spineStage.model?.id,
					selected: document.querySelector("#variant-select")?.selectedOptions?.[0]?.dataset?.id,
					active: [...document.querySelectorAll("#variant-tabs .variant-tab.is-active")]
						.map((x) => x.dataset.id),
				}));
				ok(`${c.label}: klik tab mengganti model`, after.id === target, after.id);
				ok(`${c.label}: tab aktif & select tersinkron`,
					after.selected === target && after.active.length === 1 && after.active[0] === target,
					JSON.stringify(after));
			} else {
				ok(`${c.label}: ada tab lain untuk dicoba`, false);
			}

			// Keyboard: "]" maju (wrap-around), "1" lompat ke varian pertama.
			const ids = await page.evaluate(() =>
				window.spineStage?.model?.family?.members?.map((m) => m.id) || []);
			const cur = await page.evaluate(() => window.spineStage.model?.id);
			if (ids.length > 1) {
				await page.keyboard.press("]");
				await page.waitForFunction((id) => window.spineStage?.model?.id === id,
					ids[(ids.indexOf(cur) + 1) % ids.length], { timeout: 90000 });
				ok(`${c.label}: keyboard "]" pindah varian`, true);
				await page.keyboard.press("1");
				await page.waitForFunction((id) => window.spineStage?.model?.id === id,
					ids[0], { timeout: 90000 });
				ok(`${c.label}: keyboard "1" ke varian pertama`, true);
			}
			continue;
		}

		// ---- mode popup (>3 varian) ----
		ok(`${c.label}: tombol Varian tampil, tab disembunyikan`,
			shown.btnHidden === false && shown.tabsHidden === true,
			JSON.stringify({ btnHidden: shown.btnHidden, tabsHidden: shown.tabsHidden }));
		if (c.viaChip) {
			ok("CZN: klik chip langsung buka popup", shown.popupOpen === true);
		} else {
			await page.click("#variant-btn");
			await page.waitForTimeout(450);
		}
		const pop = await page.evaluate(() => {
			const items = [...document.querySelectorAll("#variant-list .variant-item")];
			return {
				open: !document.querySelector("#variant-popup")?.hidden,
				items: items.length,
				title: document.querySelector("#variant-popup-title")?.textContent,
				active: items.filter((x) => x.classList.contains("is-active")).length,
				thumbs: items.filter((x) => {
					const img = x.querySelector(".variant-item-thumb img");
					return img && img.complete && img.naturalWidth > 0;
				}).length,
				thumbBoxes: items.filter((x) => x.querySelector(".variant-item-thumb")).length,
				badges: items.filter((x) => x.querySelector(".variant-item-badge")).length,
				groups: [...document.querySelectorAll(".variant-group-head")].map((x) => x.textContent),
			};
		});
		ok(`${c.label}: popup terbuka`, pop.open && pop.items === c.n, `${pop.items} baris`);
		ok(`${c.label}: judul & baris aktif`, !!pop.title && pop.title !== "—" && pop.active === 1,
			`${pop.title} / aktif ${pop.active}`);
		ok(`${c.label}: semua baris punya kotak thumbnail`, pop.thumbBoxes === c.n,
			String(pop.thumbBoxes));
		ok(`${c.label}: minimal satu thumbnail termuat`, pop.thumbs > 0, `${pop.thumbs}/${pop.items}`);
		ok(`${c.label}: header grup per jenis`, pop.groups.length >= 2, JSON.stringify(pop.groups));
		if (c.label === "E7") {
			ok("E7: badge jumlah animasi muncul", pop.badges > 0, `${pop.badges} badge`);
		}

		// Hover preview: panel gambar besar muncul untuk baris yang punya potret.
		const hoverable = await page.evaluate(() => {
			const items = [...document.querySelectorAll("#variant-list .variant-item")];
			return items.findIndex((x) => x.querySelector(".variant-item-thumb img"));
		});
		if (hoverable >= 0) {
			await page.locator("#variant-list .variant-item").nth(hoverable).hover();
			await page.waitForTimeout(200);
			const prev = await page.evaluate(() => {
				const p = document.querySelector("#variant-preview");
				const img = p?.querySelector("img");
				return { open: !p?.hidden, loaded: !!img && img.complete && img.naturalWidth > 0 };
			});
			ok(`${c.label}: preview hover muncul`, prev.open && prev.loaded, JSON.stringify(prev));
		}

		const target = await page.evaluate((activeId) => {
			const items = [...document.querySelectorAll("#variant-list .variant-item")];
			const other = items.find((x) => x.dataset.id !== activeId);
			return other?.dataset.id || "";
		}, shown.currentId);
		if (target) {
			await page.locator(`#variant-list .variant-item[data-id="${target}"]`).click();
			await page.waitForFunction((id) => window.spineStage?.model?.id === id, target,
				{ timeout: 90000 });
			const after = await page.evaluate(() => ({
				id: window.spineStage.model?.id,
				closed: document.querySelector("#variant-popup")?.hidden,
				selected: document.querySelector("#variant-select")?.selectedOptions?.[0]?.dataset?.id,
			}));
			ok(`${c.label}: klik varian mengganti model`, after.id === target, after.id);
			ok(`${c.label}: popup tertutup & select tersinkron`,
				after.closed === true && after.selected === target, JSON.stringify(after));
		} else {
			ok(`${c.label}: ada varian lain untuk dicoba`, false);
		}
	}

	ok("tidak ada aset 404", missingAssets.length === 0, missingAssets.slice(0, 3).join(" | "));
	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	if (errors.length) failed.push("js errors");
	if (missingAssets.length) failed.push("aset 404");
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nvariant picker ok");
})().catch((err) => {
	console.error(err);
	process.exit(1);
});
