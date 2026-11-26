/**
 * Smoke test: timeline adegan Ark Re:Code (Hxxx_S) + voice opus.
 *
 * Memuat satu model H-scene yang punya data (data/arkrecode-scenes.json) dan
 * memeriksa: dock timeline tampil dengan segmen per fase, voice 200 (bukan
 * 302/404), dan model arkrecode non-H tidak menampilkan dock.
 *
 * Run: node tools/check-arkrecode-scene.cjs
 */
const { chromium } = require("playwright-core");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const PORT = Number(process.env.PORT) || 3000;
const BASE = `http://127.0.0.1:${PORT}`;
const ROOT = path.join(__dirname, "..");

function token() {
	const secret = fs.readFileSync(path.join(ROOT, "data", "auth-secret"), "utf8").trim();
	const payload = Buffer.from(JSON.stringify({ u: "admin", t: Date.now() })).toString("base64url");
	const sig = crypto.createHmac("sha256", secret).update(payload).digest("base64url");
	return `${payload}.${sig}`;
}

const permalink = (g, m) =>
	BASE + "/?v=" + Buffer.from(JSON.stringify({ v: 1, g, m })).toString("base64url");

let failures = 0;
const check = (name, ok, detail = "") => {
	console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? " — " + detail : ""}`);
	if (!ok) failures++;
};

(async () => {
	const scenes = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "arkrecode-scenes.json"), "utf8"));
	const [model, scene] = Object.entries(scenes)[0];
	const plain = JSON.parse(
		fs.readFileSync(path.join(ROOT, "cache", "models-arkrecode.json"), "utf8")
	).models.find((m) => !m.ctScene && !/^arkrecode\/H\d{3}_S$/.test(m.id));

	const browser = await chromium.launch({
		executablePath: process.env.CHROME || "/usr/bin/google-chrome",
		args: ["--no-sandbox", "--autoplay-policy=no-user-gesture-required"],
	});
	const ctx = await browser.newContext({ viewport: { width: 1280, height: 820 } });
	await ctx.addCookies([{ name: "spine_auth", value: token(), domain: "127.0.0.1", path: "/" }]);
	const page = await ctx.newPage();
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));

	// 1. Model H: dock muncul, segmen = jumlah fase.
	await page.goto(permalink("arkrecode", model), { waitUntil: "domcontentloaded" });
	await page
		.waitForFunction(() => {
			const t = document.getElementById("ct-timeline");
			return t && !t.hidden && t.querySelectorAll(".ct-tl-seg").length > 0;
		}, { timeout: 30000 })
		.catch(() => {});
	const segs = await page.evaluate(
		() => document.querySelectorAll("#ct-timeline .ct-tl-seg").length
	);
	const phases = scene.phases.filter((p) => p && p.anim).length;
	check("dock timeline tampil", segs > 0, `${segs} segmen`);
	check("segmen = fase", segs === phases, `${segs} vs ${phases}`);

	// 2. Voice benar-benar ada di server (bukan 302 login / 404).
	const url = scene.phases.find((p) => p.lines?.[0]?.voice)?.lines[0].voice;
	const res = await ctx.request.get(BASE + url);
	check("voice 200", res.status() === 200, `${res.status()} ${url}`);
	check("voice bukan kosong", (await res.body()).length > 1000);

	// 3. Model arkrecode biasa: dock tersembunyi.
	await page.goto(permalink("arkrecode", plain.id), { waitUntil: "domcontentloaded" });
	await page.waitForTimeout(4000);
	const hidden = await page.evaluate(() => {
		const t = document.getElementById("ct-timeline");
		return !t || t.hidden;
	});
	check("model non-H tanpa dock", hidden, plain.id);
	check("tanpa JS error", errors.length === 0, errors.join(" | "));

	await browser.close();
	console.log(failures ? `\n${failures} gagal` : "\nsemua lolos");
	process.exit(failures ? 1 : 0);
})();