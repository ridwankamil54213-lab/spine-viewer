/**
 * Uji loader runtime 2.1 terhadap BANYAK model Project QT.
 *
 * Yang diuji di sini adalah bagian yang paling sering gagal dan paling
 * mahal untuk diulang: membaca JSON 2.1.27, atlas, dan tekstur, lalu
 * membangun skeleton beserta animasinya. Kalau tahap ini lolos, model bisa
 * digambar.
 *
 * Kenapa tidak lewat antarmuka: daftar model divirtualisasi (cuma ~60 yang
 * ada di DOM), jadi model acak tidak bisa diklik — padahal modelnya valid.
 * Menguji loader langsung membuat seluruh 1294 model terjangkau.
 *
 * Catatan: ini menguji parsing + konstruksi skeleton, bukan piksel
 * akhir. Piksel diuji terpisah oleh check-spine21.cjs pada model tunggal.
 *
 * Pakai: node tools/check-spine21-load.cjs [jumlahSampel|semua]
 */
const { chromium } = require("playwright-core");

const arg = process.argv[2] || "60";

(async () => {
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));

	const api = await page.request.get("http://127.0.0.1:3000/api/models", { timeout: 300000 });
	const json = await api.json();
	const all = (json.models || []).filter((m) => String(m.id).startsWith("projectqt21/"));
	if (!all.length) {
		console.log("Tidak ada model projectqt21.");
		await browser.close();
		process.exit(1);
	}

	let sample = all;
	if (arg !== "semua") {
		const n = Math.min(Number(arg) || 60, all.length);
		const step = Math.max(1, Math.floor(all.length / n));
		sample = [];
		for (let i = 0; i < all.length && sample.length < n; i += step) sample.push(all[i]);
	}

	console.log(`Menguji loader terhadap ${sample.length} dari ${all.length} model\n`);

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
	await page.waitForTimeout(1500);

	const result = await page.evaluate(async (models) => {
		// Muat runtime 2.1 dengan cara yang sama seperti src/spine21-stage.js.
		await new Promise((resolve, reject) => {
			if (window.spine21) return resolve();
			const s = document.createElement("script");
			s.src = "/vendor/spine21/spine.js";
			s.onload = resolve;
			s.onerror = () => reject(new Error("gagal memuat runtime 2.1"));
			document.head.appendChild(s);
		});
		// spine.js 2.1 defines the global `spine` (not `spine21`). The viewer
		// moves it to window.spine21 afterwards so it can coexist with the
		// other runtimes; here we take it straight from `spine` because
		// nothing else has loaded yet.
		const sp = window.spine21 || window.spine;
		if (!sp || !sp.SkeletonJson) throw new Error("runtime 2.1 tidak tersedia");

		const out = { ok: 0, fail: [], anims: 0, bones: 0, slots: 0 };

		for (const m of models) {
			// Id bisa berbentuk "<dir>#<stem>" untuk folder yang berisi
			// beberapa model (varian B/M/T). "#<stem>" bukan bagian path di
			// disk, jadi harus dibuang sebelum dipakai sebagai URL.
			const rawId = String(m.id).split("/").slice(1).join("/").split("#")[0];
			const dir = rawId.split("/").map(encodeURIComponent).join("/");
			const base = "/assets/projectqt21/" + dir + "/";
			// Server sudah mengetahui pasangan atlas yang benar (lihat
			// GAME_ROOTS/scanModels). Menebaknya dari nama skeleton selalu
			// meleset pada folder yang berisi beberapa model: 2001_1.json
			// berpasangan dengan DragonPose1.atlas, bukan 2001.atlas.
			const jsonFile = encodeURIComponent(String(m.skeletonFile).split("#")[0]);
			const atlasFile = encodeURIComponent(
				String(m.atlasFile || String(m.skeletonFile).replace(/\.json$/i, ".atlas")).split("#")[0]);
			try {
				const [skelText, atlasText] = await Promise.all([
					fetch(base + jsonFile).then((r) => { if (!r.ok) throw new Error("json " + r.status); return r.text(); }),
					fetch(base + atlasFile).then((r) => { if (!r.ok) throw new Error("atlas " + r.status); return r.text(); }),
				]);

				const pending = [];
				const loader = {
					load(page, path) {
						const img = new Image();
						pending.push(new Promise((res, rej) => {
							img.onload = res;
							img.onerror = () => rej(new Error("tekstur " + path));
						}));
						img.src = base + path;
						page.rendererObject = img;
					},
					unload() {},
				};
				const atlas = new sp.Atlas(atlasText, loader);
				await Promise.all(pending);

				const prev = window.spine;
				window.spine = sp;
				try {
					sp.Bone.yDown = false;
					const skelData = new sp.SkeletonJson(new sp.AtlasAttachmentLoader(atlas))
						.readSkeletonData(JSON.parse(skelText));
					if (!skelData?.bones?.length) throw new Error("tanpa tulang");
					out.bones += skelData.bones.length;
					out.slots += (skelData.slots || []).length;
					out.anims += Object.keys(skelData.animations || {}).length;
					out.ok++;
				} finally {
					window.spine = prev;
				}
			} catch (e) {
				out.fail.push([m.id, String(e.message).slice(0, 70)]);
			}
		}
		return out;
	}, sample);

	console.log(`Berhasil dimuat : ${result.ok}/${sample.length}`);
	console.log(`Total tulang    : ${result.bones}`);
	console.log(`Total slot      : ${result.slots}`);
	console.log(`Total animasi   : ${result.anims}`);
	if (result.fail.length) {
		console.log(`\nGagal (${result.fail.length}):`);
		result.fail.slice(0, 15).forEach(([id, w]) => console.log(`  ${id}: ${w}`));
	}
	console.log("\njs errors:", errors.length ? errors.slice(0, 3) : "none");
	await browser.close();
	process.exit(0);
})();
