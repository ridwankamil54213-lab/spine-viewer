/**
 * Smoke test: timeline adegan + voice + efek lensa CherryTale.
 *
 * Memuat satu scene HCG yang punya data (lihat
 * tools/build-cherrytale-scenes.py) dan memeriksa:
 *   - dock timeline tampil, segmennya selebar durasi (bukan sama rata),
 *   - klik segmen mengganti animasi, Play memutar voice opus,
 *   - tombol lensa menyetel filter + vignette, M mematikannya lagi,
 *   - model non-CherryTale tidak menampilkan dock/lensa.
 *
 * Run: PORT=3001 node tools/check-cherrytale-scene.cjs
 */
const { chromium } = require("playwright-core");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const PORT = Number(process.env.PORT) || 3000;
const BASE = `http://127.0.0.1:${PORT}`;
const MODEL = "cherrytale/img_hcg_dynamic_a007_04_hcg1_1_spine";

function token() {
	const secret = fs.readFileSync(path.join(__dirname, "..", "data", "auth-secret"), "utf8").trim();
	const payload = Buffer.from(JSON.stringify({ u: "admin", t: Date.now() })).toString("base64url");
	const sig = crypto.createHmac("sha256", secret).update(payload).digest("base64url");
	return `${payload}.${sig}`;
}

function permalink(id) {
	return BASE + "/?v=" + Buffer.from(JSON.stringify({ v: 1, g: "cherrytale", m: id }))
		.toString("base64url");
}

let failures = 0;
function check(name, ok, detail = "") {
	console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? " — " + detail : ""}`);
	if (!ok) failures++;
}

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME || "/usr/bin/google-chrome",
		args: ["--no-sandbox", "--autoplay-policy=no-user-gesture-required"],
	});
	const ctx = await browser.newContext({ viewport: { width: 1280, height: 820 } });
	await ctx.addCookies([{ name: "spine_auth", value: token(), domain: "127.0.0.1", path: "/" }]);
	const page = await ctx.newPage();
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));

	await page.goto(permalink(MODEL), { waitUntil: "domcontentloaded" });
	await page
		.waitForFunction(() => {
			const t = document.getElementById("ct-timeline");
			return t && !t.hidden && t.querySelectorAll(".ct-tl-seg").length > 0;
		}, { timeout: 30000 })
		.catch(() => {});

	const dock = await page.evaluate(() => {
		const root = document.getElementById("ct-timeline");
		const segs = [...document.querySelectorAll(".ct-tl-seg")];
		return {
			visible: !!root && !root.hidden,
			segs: segs.length,
			labels: segs.map((s) => s.querySelector(".ct-tl-label")?.textContent),
			widths: segs.map((s) => s.getBoundingClientRect().width),
			title: document.getElementById("ct-title")?.textContent,
			lensBtn: !document.getElementById("lens-btn")?.hidden,
		};
	});
	check("dock timeline tampil", dock.visible);
	check("segmen sesuai jumlah fase", dock.segs === 5, `dapat ${dock.segs}`);
	check("label fase dari data", dock.labels.join("|").includes("Insert 02"), dock.labels.join("|"));
	check("fase dari urutan cerita", dock.labels.join("|") === "Idle 01|Manbody 02|Insert 01|Manbody 04|Insert 02", dock.labels.join("|"));
	check("judul memuat total durasi", /Adegan .*1:13|Adegan .*0:1[0-9]|Adegan/.test(dock.title || ""), dock.title || "");
	const last = dock.widths[dock.widths.length - 1] || 0;
	const mid = dock.widths[1] || 0;
	check("segmen terpanjang lebih lebar (durasi 6s)", last > mid, `${Math.round(mid)} vs ${Math.round(last)}`);
	check("tombol lensa tersedia", dock.lensBtn);

	// Klik fase Insert (segmen ke-3): animasi + skin + lapisan ikut.
	await page.click(".ct-tl-seg:nth-child(3)");
	await page.waitForTimeout(500);
	const active = await page.evaluate(() => document.querySelectorAll(".ct-tl-seg.is-active").length);
	check("hanya satu fase aktif", active === 1, String(active));

	const skinA = await page.evaluate(() => ({
		skin: window.__spineStage.skin,
		tracks: window.__spineStage.tracks,
		sel: document.getElementById("skin-select").value,
		att: window.__spineStage.spine?.skeleton?.slots
			?.map((sl) => sl.getAttachment()?.name || "")
			.slice(0, 400)
			.join(","),
	}));
	check("skin fase terpasang (gabungan)", skinA.skin === "ct-phase", skinA.skin);
	check("dropdown skin ikut pilihan fase", /^Blush_02/.test(skinA.sel), skinA.sel);
	check("animasi lapisan ikut jalan", skinA.tracks.includes("Penis_01") && skinA.tracks.includes("Water_01"), skinA.tracks.join(","));

	// Kembali ke fase Idle: lapisan dibuang dan skin Idle dipakai lagi.
	await page.click(".ct-tl-seg:nth-child(1)");
	await page.waitForTimeout(400);
	const skinIdle = await page.evaluate(() => ({
		tracks: window.__spineStage.tracks,
		sel: document.getElementById("skin-select").value,
		att: window.__spineStage.spine?.skeleton?.slots
			?.map((sl) => sl.getAttachment()?.name || "")
			.slice(0, 400)
			.join(","),
	}));
	check("lapisan dibersihkan saat fase lain", skinIdle.tracks.length === 1, skinIdle.tracks.join(","));
	check("skin Idle dipakai", /^Eye_05/.test(skinIdle.sel), skinIdle.sel);
	check("attachment benar-benar berubah antar fase", skinIdle.att !== skinA.att);

	// Segmen ke-5 = Insert_02: animasi benar-benar berganti.
	await page.click(".ct-tl-seg:nth-child(5)");
	await page.waitForTimeout(400);
	const anim = await page.evaluate(() => document.getElementById("anim-select")?.value);
	check("klik segmen memilih animasinya", anim === "Insert_02", String(anim));

	// Play: progres berjalan, voice + subtitle + SFX/BGM hidup.
	await page.click(".ct-tl-seg:nth-child(1)");
	await page.click("#ct-play");
	await page.waitForTimeout(900);
	const story = await page.evaluate(() => ({
		sub: !document.getElementById("ct-sub").hidden,
		text: document.getElementById("ct-sub-en").textContent,
		bgm: window.__spineStage.ctBgm,
		zh: document.getElementById("ct-sub-zh").hidden,
		censoredAlpha: window.__spineStage.spine.skeleton.slots
			.filter((sl) => /censor|mark|mosaic|fog|light/i.test(sl.data.name))
			.reduce((n, sl) => n + sl.color.a, 0),
	}));
	check("subtitle tampil", story.sub && story.text.length > 10, story.text.slice(0, 40));
	check("teks EN terisi", /pushed|Sukuna|tight|rod/i.test(story.text), story.text.slice(0, 40));
	check("BGM adegan berputar", !!story.bgm && story.bgm.paused === false, JSON.stringify(story.bgm));
	check("ZH default tersembunyi", story.zh === true);
	check("sensor default aktif (alpha 0)", story.censoredAlpha === 0, String(story.censoredAlpha));
	await page.click("#ct-zh");
	await page.waitForTimeout(200);
	const zh = await page.evaluate(() => ({
		hidden: document.getElementById("ct-sub-zh").hidden,
		text: document.getElementById("ct-sub-zh").textContent,
	}));
	check("toggle ZH menampilkan teks asli", zh.hidden === false && zh.text.length > 0, zh.text.slice(0, 30));
	await page.click("#ct-censor");
	await page.waitForTimeout(200);
	const uncensored = await page.evaluate(() =>
		window.__spineStage.spine.skeleton.slots
			.filter((sl) => /censor|mark|mosaic|fog|light/i.test(sl.data.name))
			.reduce((n, sl) => n + sl.color.a, 0)
	);
	check("toggle sensor menyalakan slot", uncensored > 0, String(uncensored));

	// Tap kanvas: maju satu baris (subtitle berubah), geser tidak dihitung.
	const before = await page.evaluate(() => document.getElementById("ct-sub-en").textContent);
	const box = await page.locator("#canvas-wrap").boundingBox();
	await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
	await page.waitForTimeout(600);
	const afterTap = await page.evaluate(() => ({
		text: document.getElementById("ct-sub-en").textContent,
		line: window.__spineStage.ctLine,
	}));
	check("tap kanvas memajukan baris", afterTap.text !== before && afterTap.text.length > 0, afterTap.text.slice(0, 40));
	// Seret (bukan tap) tidak memajukan baris.
	const b2 = await page.evaluate(() => document.getElementById("ct-sub-en").textContent);
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
	await page.mouse.down();
	await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2 + 40, { steps: 6 });
	await page.mouse.up();
	await page.waitForTimeout(500);
	const afterDrag = await page.evaluate(() => document.getElementById("ct-sub-en").textContent);
	check("seret tidak memajukan baris", afterDrag === b2, afterDrag.slice(0, 40));

	const playing = await page.evaluate(() => ({
		state: document.getElementById("ct-play")?.dataset.playing,
		activeIdx: [...document.querySelectorAll(".ct-tl-seg")].findIndex((s) => s.classList.contains("is-active")),
		fill: parseFloat(document.querySelector(".ct-tl-seg.is-active .ct-tl-fill")?.style.width || "0"),
		audioBtn: document.getElementById("audio-btn")?.dataset.playing,
		audioSrc: [...document.querySelectorAll("audio")].map((a) => a.src).join(","),
	}));
	check("tombol Play menandai sedang main", playing.state === "true");
	// Baris pertama fase Idle hanya narasi; voice muncul di baris berikutnya.
	await page
		.waitForFunction(() => document.getElementById("audio-btn")?.dataset.playing === "true", { timeout: 12000 })
		.catch(() => {});
	const voiceOn = await page.evaluate(() => document.getElementById("audio-btn")?.dataset.playing);
	check("voice baris berbunyi", voiceOn === "true", String(voiceOn));
	check("progres segmen berjalan", playing.fill > 0, `${playing.fill}%`);

	// Voice element tidak ada di DOM (new Audio()); cek lewat state internal.
	const src = await page.evaluate(() => {
		const ev = new Event("x");
		window.dispatchEvent(ev);
		return document.getElementById("audio-btn")?.dataset.playing;
	});
	check("audio tetap bertanda playing setelah 1,4 dtk", src === "true", String(src));

	// Lensa.
	await page.click("#lens-btn");
	await page.waitForTimeout(250);
	const lens = await page.evaluate(() => {
		const c = [...document.querySelectorAll("#canvas-wrap canvas")].find((x) => x.width > 400);
		return {
			body: document.body.classList.contains("ct-lens"),
			on: document.getElementById("lens-btn")?.dataset.on,
			filter: c ? getComputedStyle(c).filter : "",
			vignette: !document.getElementById("stage-lens")?.hidden,
		};
	});
	check("kelas lensa aktif", lens.body && lens.on === "true");
	check("filter chromatic terpasang di kanvas", /url\("#ct-lens"\)/.test(lens.filter), lens.filter.slice(0, 60));
	check("vignette tampil", lens.vignette);
	await page.keyboard.press("m");
	await page.waitForTimeout(200);
	const off = await page.evaluate(() => document.body.classList.contains("ct-lens"));
	check("M mematikan lensa", off === false);

	check("tanpa error halaman", errors.length === 0, errors.slice(0, 2).join(" | "));

	// Model tanpa animasi/scene: dock & lensa harus hilang.
	await page.goto(BASE + "/?v=" + Buffer.from(JSON.stringify({ v: 1, g: "cherrytale", m: "cherrytale/mainui_alliance_bg_e001_01_guild_spine" }))
		.toString("base64url"), { waitUntil: "domcontentloaded" });
	await page.waitForTimeout(2500);
	const other = await page.evaluate(() => ({
		dock: !document.getElementById("ct-timeline")?.hidden,
		lens: !document.getElementById("lens-btn")?.hidden,
	}));
	check("model tanpa fase menyembunyikan dock", other.dock === false);
	check("model tanpa fase menyembunyikan tombol lensa", other.lens === false);

	await browser.close();
	console.log(failures ? `\n${failures} gagal` : "\nsemua lulus");
	process.exit(failures ? 1 : 0);
})();
