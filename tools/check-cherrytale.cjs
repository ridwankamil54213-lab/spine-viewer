/**
 * Smoke test: a Cherry Tale model actually renders.
 *
 * The extractor can produce files that scan fine but draw as confetti when the
 * atlas points at the wrong texture page, or when the wrong of two same-named
 * TextAssets was kept. This loads real models in the browser and asserts the
 * skeleton parsed and the stage drew something.
 *
 * Run: node tools/check-cherrytale.cjs
 */
const { chromium } = require("playwright-core");
const http = require("http");

const MODELS = [
	"cherrytale/img_cg_dynamic_a001_01_cg_spine",
	"cherrytale/img_cg_dynamic_a002_02_cg_spine",
	"cherrytale/img_cg_dynamic_e004_02_teaching_cg_spine",
	// Empat skeleton biner yang byte pertamanya kebetulan '{' (0x7b). Sebelum
	// inspectSkeletonUncached memakai looksLikeJsonSkeleton(), berkas-berkas
	// ini salah dianggap JSON, JSON.parse melempar, dan model tercatat
	// runtime:null / animations:[] walau renderer bisa memuatnya.
	"cherrytale/img_cg_dynamic_c007_03_cg_spine",
	"cherrytale/img_hcg_dynamic_d001_03_hcg1_1_spine",
	"cherrytale/img_hcg_dynamic_f008_02_hcg1_1_spine",
	"cherrytale/img_hcg_dynamic_story_hcg18_1_spine",
];

function getJSON(path) {
	return new Promise((resolve, reject) => {
		http
			.get({ host: "127.0.0.1", port: 3000, path }, (res) => {
				let b = "";
				res.on("data", (d) => (b += d));
				res.on("end", () => {
					try {
						resolve(JSON.parse(b));
					} catch (e) {
						reject(e);
					}
				});
			})
			.on("error", reject);
	});
}

(async () => {
	// Only test models that actually exist in this checkout.
	const list = await getJSON("/api/models?game=cherrytale");
	const models = Array.isArray(list) ? list : list.models || [];
	const have = new Set(models.map((m) => m.id));
	const targets = MODELS.filter((id) => have.has(id));
	if (!targets.length) {
		console.log("SKIP: belum ada model Cherry Tale yang diekstrak");
		process.exit(0);
	}

	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	let failures = 0;

	for (const id of targets) {
		const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		page.on("console", (m) => {
			if (m.type() === "error") errors.push("console: " + m.text());
		});

		// Viewer hanya memulihkan model dari permalink ?v= (JSON base64url),
		// bukan ?m=. Field "m" = id model, "g" = game aktif.
		const payload = Buffer.from(
			JSON.stringify({ v: 1, g: "cherrytale", m: id }),
			"utf8",
		).toString("base64url");
		await page.goto("http://localhost:3000/?v=" + payload, {
			waitUntil: "domcontentloaded",
		});
		// Tunggu animasi muncul di dropdown (tanda skeleton sudah diparse),
		// bukan sekadar menunggu waktu tetap: bundle CG besar bisa butuh
		// beberapa detik dan tebakan 5 detik membuat hasilnya tidak stabil.
		await page
			.waitForFunction(
				() => {
					const s = document.querySelector("#anim-select");
					return s && s.options.length > 0;
				},
				{ timeout: 25000 },
			)
			.catch(() => {});
		await page.waitForTimeout(1500);

		// Panggung memakai canvas besar; canvas 160x34 di DOM adalah elemen
		// lain (ikon), jadi yang dicari yang lebarnya > 400.
		const info = await page.evaluate(() => {
			const cs = [...document.querySelectorAll("canvas")];
			const c = cs.find((x) => x.width > 400) || cs[0];
			if (!c) return { canvas: false };
			return { canvas: true, w: c.width, h: c.height };
		});

		// readPixels setelah render biasanya balik kosong (buffer sudah di-clear),
		// jadi kehadiran gambar diperiksa dari screenshot: piksel yang bukan
		// warna latar menandakan model benar-benar tergambar.
		const shotPath = `cache/cherrytale/verify-${id.split("/")[1]}.png`;
		let drawnPct = 0;
		let colours = 0;
		try {
			await page.screenshot({ path: shotPath });
			const { execFileSync } = require("child_process");
			const out = execFileSync(
				"/srv/venv-spine/bin/python",
				[
					"-c",
					`from PIL import Image;import collections,sys
im=Image.open(sys.argv[1]).convert("RGB")
c=collections.Counter(im.get_flattened_data() if hasattr(im,"get_flattened_data") else im.getdata())
bg=c.most_common(1)[0][1];tot=im.size[0]*im.size[1]
print(f"{100*(tot-bg)/tot:.1f} {len(c)}")`,
					shotPath,
				],
				{ encoding: "utf8" },
			)
				.trim()
				.split(/\s+/);
			drawnPct = parseFloat(out[0]);
			colours = parseInt(out[1], 10);
		} catch (e) {
			/* screenshot/python tidak tersedia -> lewati cek visual */
		}

		const anims = await page.evaluate(() => {
			const s = document.querySelector("#anim-select");
			return s ? s.options.length : 0;
		});

		const drew = drawnPct > 2 && colours > 200;
		const ok = info.canvas && anims > 0 && drew && errors.length === 0;
		if (!ok) failures++;
		console.log(
			`${ok ? "OK  " : "FAIL"} ${id}  canvas=${info.w}x${info.h} anims=${anims} ` +
				`gambar=${drawnPct}% warna=${colours}` +
				`${errors.length ? " errors=" + errors.slice(0, 2).join(" | ") : ""}`,
		);
		await page.close();
	}

	await browser.close();
	console.log(failures ? `${failures} model gagal` : "semua model lolos");
	process.exit(failures ? 1 : 0);
})();
