/**
 * Smoke test: kamera LoveTalk (CG Ark Re:Code) + timeline H-scene.
 *
 * A0016 punya dua lapis data:
 *   - 11 animasi Spine biasa (01_Idle_ani1 … 40_End_ani) — sudah tampil;
 *   - 20 state di H015_LoveTalk_03_Controller yang semuanya menggerakkan
 *     TRANSFORM node (pos + skala), bukan karakter. Itu "kamera"-nya.
 *
 * Yang dibuktikan di sini:
 *   - bar kamera muncul dengan satu tombol per state unik,
 *   - klik tombol mengubah zoom/pan dan menyalakan tombolnya,
 *   - model tetap terlihat di panggung (tidak terlempar keluar),
 *   - model CG tanpa data LoveTalk tidak menampilkan bar,
 *   - voice H-scene masih 200, 0 JS error.
 *
 * Run: node tools/check-arkrecode-lovetalk.cjs
 */
const { chromium } = require("playwright-core");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const BASE = `http://127.0.0.1:${process.env.PORT || 3000}`;
const MODEL = "arkrecode/A0016";

function token() {
	const secret = fs.readFileSync(path.join(ROOT, "data", "auth-secret"), "utf8").trim();
	const payload = Buffer.from(JSON.stringify({ u: "admin", t: Date.now() })).toString("base64url");
	const sig = crypto.createHmac("sha256", secret).update(payload).digest("base64url");
	return `${payload}.${sig}`;
}
const permalink = (m) =>
	BASE + "/?v=" + Buffer.from(JSON.stringify({ v: 1, g: "arkrecode", m })).toString("base64url");

let failures = 0;
const check = (name, ok, detail = "") => {
	console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? " — " + detail : ""}`);
	if (!ok) failures++;
};

/** Ukur kotak isi model di layar; dipakai untuk memastikan model tak hilang. */
const probe = (page) =>
	page.evaluate(() => {
		const st = window.__spineStage;
		const cam = st.state;
		const wrap = document.getElementById("canvas-wrap");
		const W = wrap.clientWidth;
		const H = wrap.clientHeight;
		let mnx = 1e9, mny = 1e9, mxx = -1e9, mxy = -1e9;
		for (const sl of st.spine.skeleton.slots) {
			const a = sl.getAttachment();
			if (!a || !a.computeWorldVertices) continue;
			const n = a.worldVerticesLength;
			if (!n) continue;
			const arr = new Float32Array(n);
			a.computeWorldVertices(sl, 0, n, arr, 0, 2);
			for (let i = 0; i < n; i += 2) {
				const sx = W / 2 + cam.panX + arr[i] * cam.zoom;
				const sy = H / 2 + cam.panY + arr[i + 1] * cam.zoom;
				mnx = Math.min(mnx, sx); mxx = Math.max(mxx, sx);
				mny = Math.min(mny, sy); mxy = Math.max(mxy, sy);
			}
		}
		return {
			zoom: +cam.zoom.toFixed(4),
			pan: [Math.round(cam.panX), Math.round(cam.panY)],
			visible: mxx > 0 && mnx < W && mxy > 0 && mny < H,
			W, H,
		};
	});

(async () => {
	const data = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "arkrecode-lovetalk.json"), "utf8"));
	const entry = data[MODEL];
	check("data loveTalk ada", !!entry?.states?.length, `${entry?.states?.length} state`);

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
	await page.waitForFunction(
		() => document.querySelectorAll("#lt-list .lt-btn").length > 0,
		{ timeout: 30000 }
	).catch(() => {});

	const names = await page.evaluate(() =>
		[...document.querySelectorAll("#lt-list .lt-btn")].map((b) => b.textContent)
	);
	check("bar kamera tampil", names.length > 0, names.join("/"));
	check("satu tombol per state unik", names.length === entry.states.length,
		`${names.length} vs ${entry.states.length}`);

	const before = await probe(page);
	await page.click("#lt-list .lt-btn:nth-child(2)");
	await page.waitForTimeout(400);
	const after = await probe(page);
	check("klik mengubah zoom", after.zoom !== before.zoom, `${before.zoom} -> ${after.zoom}`);
	check("klik mengubah pan", after.pan.join() !== before.pan.join(), `${before.pan} -> ${after.pan}`);
	check("model tetap terlihat", after.visible, `bbox terlihat di ${after.W}x${after.H}`);
	const on = await page.evaluate(() =>
		[...document.querySelectorAll("#lt-list .lt-btn")].filter((b) => b.dataset.on === "true").length
	);
	check("tepat satu tombol aktif", on === 1, `${on} aktif`);

	// Model CG tanpa data LoveTalk: bar harus tersembunyi.
	await page.goto(permalink("arkrecode/A0001"), { waitUntil: "domcontentloaded" });
	await page.waitForTimeout(6000);
	const hidden = await page.evaluate(() => document.getElementById("lt-bar").hidden);
	check("model tanpa LoveTalk: bar sembunyi", hidden);

	// Voice H-scene masih terlayani.
	const res = await ctx.request.get(`${BASE}/arkrecode-audio/H001_S/audio/story/Sex_01.opus`);
	check("voice H-scene 200", res.status() === 200, `${res.status()}`);

	check("tanpa JS error", errors.length === 0, errors.join(" | "));

	await browser.close();
	console.log(failures ? `\n${failures} gagal` : "\nsemua lolos");
	process.exit(failures ? 1 : 0);
})();