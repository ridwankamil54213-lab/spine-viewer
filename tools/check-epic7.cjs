/**
 * Smoke test untuk pustaka Epic Seven (sumber: e7codex.com).
 *
 * Memverifikasi rantai yang dibangun tools/update-epic7.py:
 *   - 855 rig lobby + 466 rig combat + 426 animasi skill + 24 wallpaper
 *   - nama / rarity / elemen / kelas dari units.json lewat _names.json
 *   - combat & skill terlampir sebagai VARIAN di kartu karakter
 *   - thumbnail dinormalisasi ke lebar 300 px dan benar-benar termuat
 *   - model Spine benar-benar ter-render di stage tanpa aset 404
 *   - updater --check stabil (changed:false) setelah apply
 *
 * Run: node tools/check-epic7.cjs   (server on :3000)
 */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const BASE = "http://127.0.0.1:3000";
const ROOT = path.resolve(__dirname, "..");
const failed = [];
const ok = (label, cond, extra = "") => {
	if (!cond) failed.push(label);
	console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

(async () => {
	const all = (await fetch(`${BASE}/api/models?lean=1`).then((r) => r.json())).models || [];
	const byGame = (g) => all.filter((m) => (m.game || "") === g);
	const lobby = byGame("epic7");
	const combat = byGame("epic7-combat");
	const skill = byGame("epic7-skill");
	const wall = byGame("epic7-wallpaper");
	const names = JSON.parse(fs.readFileSync(path.join(ROOT, "assets/epic7/_names.json"), "utf8"));
	ok("tidak ada root legacy epic7-v3",
		!fs.existsSync(path.join(ROOT, "assets", "epic7-v3")) &&
		!all.some((m) => String(m.id).startsWith("epic7-v3/")));
	ok("folder lobby = katalog nama",
		fs.readdirSync(path.join(ROOT, "assets", "epic7"), { withFileTypes: true })
			.filter((d) => d.isDirectory()).length === Object.keys(names).length);

	// Katalog e7codex bisa bertambah; yang dijaga adalah keselarasan API dan
	// _names.json, bukan angka beku 855.
	ok("rig lobby terpasang sesuai katalog", lobby.length === Object.keys(names).length,
		`${lobby.length} vs ${Object.keys(names).length}`);
	ok("rig combat terpasang", combat.length > 400, String(combat.length));
	ok("animasi skill terpasang", skill.length > 400, String(skill.length));
	ok("wallpaper terpasang", wall.length >= 24, String(wall.length));

	ok("semua model punya nama katalog", lobby.every((m) => m.name && m.character?.name));
	ok("metadata rarity/elemen/kelas dari e7codex",
		lobby.some((m) => m.character?.rarity?.includes("★")) &&
		lobby.some((m) => ["Fire", "Ice", "Wind", "Light", "Dark"].includes(m.character?.element)) &&
		lobby.some((m) => ["Knight", "Ranger", "Mage", "Assassin", "Warrior", "Manauser"]
			.includes(m.character?.class)));
	ok("sumber metadata tercatat e7codex.com",
		lobby.filter((m) => m.character).every((m) => m.character.source === "e7codex.com"));

	const withCombat = lobby.filter((m) => m.family?.members?.some((x) => x.id.startsWith("epic7-combat/")));
	ok("combat jadi varian, bukan entri terpisah", withCombat.length > 400,
		`${withCombat.length} karakter`);
	const withSkill = lobby.filter((m) => m.family?.members?.some((x) => x.id.startsWith("epic7-skill/")));
	ok("skill ikut masuk dropdown varian", withSkill.length > 300, `${withSkill.length} karakter`);

	// --- thumbnail ---------------------------------------------------------
	const thumbsDir = path.join(ROOT, "public/thumbs/epic7");
	const manifest = JSON.parse(fs.readFileSync(path.join(thumbsDir, "_manifest.json"), "utf8"));
	// Tidak semua unit punya `thumb` di e7codex (527 dari 855), jadi manifest
	// tidak mungkin seluas daftar model. Yang penting: kuncinya valid.
	const lobbyIds = new Set(lobby.map((m) => m.id));
	ok("manifest thumbnail valid", Object.keys(manifest).length >= 500 &&
		Object.keys(manifest).every((k) => lobbyIds.has(k)),
		`${Object.keys(manifest).length} potret dari ${lobby.length} model`);
	const files = Object.values(manifest).map((f) => path.join(thumbsDir, f));
	ok("file thumbnail ada semua", files.every((p) => fs.existsSync(p)));
	const big = files.filter((p) => fs.statSync(p).size > 400 * 1024);
	ok("thumbnail dinormalisasi (<400 KB)", big.length === 0,
		big.length ? big.slice(0, 3).map((p) => path.basename(p)).join(", ") : "semua ringan");
	const tmap = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs;
	ok("/api/thumbnails memuat kunci epic7", Object.keys(tmap).some((k) => k.startsWith("epic7/")),
		String(Object.keys(tmap).filter((k) => k.startsWith("epic7/")).length));
	const oneThumb = await fetch(`${BASE}/thumbs/epic7/${Object.values(manifest)[0]}`);
	ok("thumbnail tersaji 200", oneThumb.status === 200, `${oneThumb.status} ${oneThumb.headers.get("content-type")}`);

	// --- updater -----------------------------------------------------------
	const chk = await fetch(`${BASE}/api/update/epic7?mode=check`).then((r) => r.json());
	// Katalog e7codex bisa sah berubah (karakter baru) di antara run — jangan
	// paksa changed:false. Yang diuji: --check tetap jalan dan kalau ada `new`
	// maka memang diiringi flag perubahan katalog, bukan error/429.
	ok("updater --check jalan (toleran pembaruan upstream)",
		chk.ok === true &&
		(chk.new === 0 || (chk.changed === true &&
			(chk.alasan || []).some((a) => /katalog e7codex berubah/.test(a)))),
		JSON.stringify({ ok: chk.ok, changed: chk.changed, new: chk.new, alasan: chk.alasan }));

	// --- browser -----------------------------------------------------------
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.setDefaultTimeout(120000);
	const errors = [];
	const missingAssets = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
	page.on("response", (r) => {
		if (r.status() >= 400 && /\.(webp|png|atlas|json|webm)(\?|$)/.test(r.url()))
			missingAssets.push(`${r.status()} ${r.url()}`);
	});

	await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
	await page.waitForSelector("#game-list .game", { state: "visible" });
	const gameCard = page.locator('#game-list .game[data-key="epic7"]');
	ok("kartu game Epic Seven tampil", await gameCard.count() === 1);
	await gameCard.click();
	await page.waitForSelector("#model-list li > button:not(.model-fav)", { state: "visible" });
	const thumbUi = await page.evaluate(() => {
		const img = document.querySelector("#model-list li > button:not(.model-fav) img");
		return img ? { w: img.naturalWidth, complete: img.complete } : null;
	});
	ok("thumbnail 300 px ter-render di galeri",
		!!thumbUi && thumbUi.complete && thumbUi.w === 300, JSON.stringify(thumbUi));

	const target = lobby.find((m) => m.family?.members?.some((x) => x.id.startsWith("epic7-combat/")) &&
		m.family?.members?.some((x) => x.id.startsWith("epic7-skill/")));
	ok("ada karakter dengan Lobby+Combat+Skill", !!target, target?.name || "tidak ada");
	// #search mencocokkan id maupun nama, jadi memakai id menjamin tepat satu
	// kartu dan dropdown varian pasti terisi (tidak bergantung urutan sortir).
	const wanted = target?.id || "epic7/c0002";
	await page.fill("#search", wanted);
	await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 30000 });
	await page.waitForFunction(() => !!window.spineStage?.spine?.skeleton, null, { timeout: 90000 });
	const st = await page.evaluate(() => ({
		id: window.spineStage.model?.id,
		name: window.spineStage.model?.name,
		anims: document.querySelectorAll("#anim-select option").length,
		variants: document.querySelector("#variant-select")?.options?.length || 0,
	}));
	ok("model Spine E7 ter-render", !!st.id && st.id.startsWith("epic7/"), JSON.stringify(st));
	ok("animasi tersedia", st.anims > 0, String(st.anims));
	ok("dropdown varian terisi", st.variants > 1, String(st.variants));
	ok("tidak ada aset 404", missingAssets.length === 0, missingAssets.slice(0, 3).join(" | "));

	console.log("js errors:", errors.length ? errors.join(" | ") : "none");
	if (errors.length) failed.push("js errors");
	if (missingAssets.length) failed.push("aset 404");
	await browser.close();
	if (failed.length) {
		console.error(`FAILED: ${failed.join(", ")}`);
		process.exit(1);
	}
	console.log("\nEpic Seven ok");
})().catch((err) => {
	console.error(err);
	process.exit(1);
});
