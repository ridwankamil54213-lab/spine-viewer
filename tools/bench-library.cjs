/**
 * Micro-benchmark for the model library.
 *
 * Measures the parts that actually hurt at tens of thousands of models:
 *   - boot: navigation -> first game card visible
 *   - fetch/parse of /api/models
 *   - entering the largest game (gameBuckets + modelsInScope + DOM page)
 *   - paging within that game (modelsInScope again)
 *   - back to the game grid (gameBuckets again)
 *   - toggling list/gallery layout (full renderLibrary)
 *
 * Run: node tools/bench-library.cjs   (server on :3000)
 * Output is JSON on the last line, so it can be diffed before/after a change.
 */
const fs = require("fs");
const { chromium } = require("playwright-core");

function installedChromium() {
	const roots = ["/root/.cache/ms-playwright", process.env.HOME + "/.cache/ms-playwright"];
	for (const root of roots) {
		try {
			for (const dir of fs.readdirSync(root)) {
				if (!dir.startsWith("chromium")) continue;
				const base = `${root}/${dir}`;
				for (const sub of fs.readdirSync(base)) {
					if (!sub.startsWith("chrome-linux")) continue;
					for (const bin of ["chrome", "headless_shell"]) {
						const full = `${base}/${sub}/${bin}`;
						if (fs.existsSync(full)) return full;
					}
				}
			}
		} catch { /* missing dir */ }
	}
	return null;
}

async function launch() {
	try {
		return await chromium.launch({ args: ["--no-sandbox"] });
	} catch (err) {
		const exe = installedChromium();
		if (!exe) throw err;
		return await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
	}
}

const median = (xs) => {
	const s = [...xs].sort((a, b) => a - b);
	return Math.round(s[Math.floor(s.length / 2)] * 100) / 100;
};

(async () => {
	const browser = await launch();
	const runs = Number(process.env.BENCH_RUNS || 3);
	const samples = { bootMs: [], fetchMs: [], parseMs: [], enterMs: [], pageMs: [], backMs: [], layoutMs: [] };
	let modelCount = 0;
	let gameKey = null;

	for (let i = 0; i < runs; i++) {
		const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
		page.setDefaultTimeout(120000);
		await page.addInitScript(() => {
			window.__bench = { fetchMs: 0, parseMs: 0, modelCount: 0 };
			const orig = window.fetch;
			window.fetch = function (...args) {
				const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
				if (!url.includes("/api/models")) return orig.apply(this, args);
				const t0 = performance.now();
				return orig.apply(this, args).then(async (res) => {
					const t1 = performance.now();
					try {
						const d = await res.clone().json();
						// Only the library index counts. GET /api/models/:id
						// returns { model }, and its tiny body must not
						// overwrite the boot numbers during a run.
						if (Array.isArray(d.models)) {
							window.__bench.fetchMs = t1 - t0;
							window.__bench.parseMs = performance.now() - t1;
							window.__bench.modelCount = d.models.length;
						}
					} catch { /* leave zero */ }
					return res;
				});
			};
		});

		const t0 = Date.now();
		await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
		await page.waitForSelector("#game-list .game", { state: "visible", timeout: 60000 });
		samples.bootMs.push(Date.now() - t0);
		const net = await page.evaluate(() => window.__bench);
		samples.fetchMs.push(net.fetchMs);
		samples.parseMs.push(net.parseMs);
		modelCount = net.modelCount || modelCount;

		// Largest game = the one whose card reports the most models. Fall back
		// to the first card if the label can't be parsed.
		if (!gameKey) {
			gameKey = await page.evaluate(() => {
				const cards = [...document.querySelectorAll("#game-list .game")];
				let best = cards[0], n = -1;
				for (const c of cards) {
					const m = (c.querySelector(".game-meta")?.textContent || "").match(/^([\d.]+)\s*model/);
					const v = m ? Number(m[1].replace(/\./g, "")) : 0;
					if (v > n) { n = v; best = c; }
				}
				return best?.dataset.key || null;
			});
		}

		// One synchronous action, measured until the next animation frame: this
		// captures the whole render (grouping, filtering, sorting, DOM build).
		const measure = (fn, arg) => page.evaluate(async ({ fn, arg }) => {
			const t = performance.now();
			await new Promise((resolve) => {
				// eslint-disable-next-line no-new-func
				Function("arg", fn)(arg);
				requestAnimationFrame(() => resolve());
			});
			return performance.now() - t;
		}, { fn, arg });

		samples.enterMs.push(await measure(
			`document.querySelector('#game-list .game[data-key="' + arg + '"]').click();`, gameKey));
		samples.pageMs.push(await measure(
			`const b=[...document.querySelectorAll('#pager .pager-btn')].find(x=>x.textContent==='›'); if(b&&!b.disabled)b.click();`));
		samples.backMs.push(await measure(`document.getElementById('back-btn').click();`));
		samples.layoutMs.push(await measure(
			`const grid = document.getElementById('view-grid-btn').classList.contains('is-on');
			 document.getElementById(grid ? 'view-list-btn' : 'view-grid-btn').click();`));
		await page.close();
	}

	await browser.close();
	const out = { gameKey, modelCount, runs };
	for (const [k, v] of Object.entries(samples)) out[k] = median(v);
	console.log(`game=${out.gameKey}  models=${out.modelCount}  runs=${out.runs}`);
	for (const k of Object.keys(samples)) console.log(`  ${k.padEnd(10)} ${String(out[k]).padStart(8)} ms`);
	console.log("BENCH_JSON " + JSON.stringify(out));
})().catch((err) => { console.error(err); process.exit(1); });
