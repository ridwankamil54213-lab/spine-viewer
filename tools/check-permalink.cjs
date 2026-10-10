/**
 * Smoke test: the "Tautan tampilan" permalink feature.
 *
 * What it proves:
 *   1. Opening a model normally writes a ?v= payload that names that model.
 *   2. The link dialog opens and hands back a usable URL.
 *   3. Loading that URL restores the model AND the toggles (bones, zoom).
 *   4. A corrupt payload is ignored without a page error.
 *
 * Run: node tools/check-permalink.cjs   (server on :3000)
 *
 * The browser launch falls back to whatever chromium Playwright has actually
 * installed, so the test still runs when playwright-core's expected revision
 * is not the one on disk.
 */
const fs = require("fs");
const { chromium } = require("playwright-core");

function b64urlDecode(s) {
	const p = String(s).replace(/-/g, "+").replace(/_/g, "/");
	return JSON.parse(Buffer.from(p, "base64").toString("utf8"));
}

function installedChromium() {
	const roots = ["/root/.cache/ms-playwright", process.env.HOME + "/.cache/ms-playwright"];
	for (const root of roots) {
		try {
			for (const dir of fs.readdirSync(root)) {
				if (!dir.startsWith("chromium")) continue;
				const base = `${root}/${dir}`;
				// Playwright ships either chrome-linux (x64) or chrome-linux-arm64;
				// accept both, plus the headless shell.
				for (const sub of fs.readdirSync(base)) {
					if (!sub.startsWith("chrome-linux")) continue;
					for (const bin of ["chrome", "headless_shell"]) {
						const full = `${base}/${sub}/${bin}`;
						if (fs.existsSync(full)) return full;
					}
				}
			}
		} catch {
			/* dir missing — try the next root */
		}
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

(async () => {
	const browser = await launch();
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));

	const results = [];
	const check = (name, ok, detail = "") => results.push({ name, ok, detail });

	// 1. Load a model the normal way and read the auto-written payload.
	await page.goto("http://localhost:3000/", { waitUntil: "domcontentloaded" });
	await page.waitForTimeout(800);
	await page.click("#game-list .game");
	await page.waitForTimeout(900);
	await page.click("#model-list .model");
	await page.waitForTimeout(2500);

	const raw = await page.evaluate(() => new URLSearchParams(location.search).get("v"));
	const modelId = await page.evaluate(() => window.spineStage.model?.id || null);
	let payload = null;
	try {
		payload = b64urlDecode(raw || "");
	} catch {
		/* left null */
	}
	check("auto-writes ?v= after opening a model", !!raw, raw ? "" : "no v param");
	check("payload names the open model", !!payload && payload.m === modelId, `${payload?.m} vs ${modelId}`);

	// 2. The dialog must open and expose a shareable URL.
	await page.click("#link-btn");
	await page.waitForTimeout(200);
	const dlg = await page.evaluate(() => ({
		open: !document.getElementById("link-modal").hidden,
		url: document.getElementById("link-url").value,
	}));
	check("link dialog opens", dlg.open);
	check("dialog URL carries a payload", dlg.url.includes("?v="), dlg.url.slice(0, 60));

	// 3. Mutate the view, then reload the dialog URL: it must come back the same.
	await page.click("#link-close"); // close before touching the stage
	await page.waitForTimeout(200);
	await page.click("#bones-btn"); // bones ON
	await page.click("#grid-btn"); // grid OFF
	await page.waitForTimeout(900); // let the debounced write land
	const stateBefore = await page.evaluate(() => ({
		bones: window.__spineStage.state.showBones,
		grid: window.__spineStage.state.showGrid,
		anim: document.getElementById("anim-select").value,
	}));
	const shareUrl = await page.evaluate(() => location.href);

	await page.goto(shareUrl, { waitUntil: "domcontentloaded" });
	await page.waitForTimeout(3000);
	const stateAfter = await page.evaluate(() => ({
		model: window.spineStage.model?.id || null,
		bones: window.__spineStage.state.showBones,
		grid: window.__spineStage.state.showGrid,
		anim: document.getElementById("anim-select").value,
	}));
	check("reload restores the model", stateAfter.model === modelId, `${stateAfter.model}`);
	check("reload restores bones", stateAfter.bones === stateBefore.bones, `${stateAfter.bones} vs ${stateBefore.bones}`);
	check("reload restores grid", stateAfter.grid === stateBefore.grid, `${stateAfter.grid} vs ${stateBefore.grid}`);
	check("reload restores the animation", stateAfter.anim === stateBefore.anim, `${stateAfter.anim} vs ${stateBefore.anim}`);

	// 4. Garbage payload must not throw.
	await page.goto("http://localhost:3000/?v=!!!not-base64!!!", { waitUntil: "domcontentloaded" });
	await page.waitForTimeout(1500);
	const survived = await page.evaluate(() => !!document.getElementById("model-list"));
	check("corrupt payload ignored without crashing", survived);

	console.log(results.map((r) => `  ${r.ok ? "ok  " : "FAIL"} ${r.name}${r.detail ? "  (" + r.detail + ")" : ""}`).join("\n"));
	console.log("js errors:", errors.length ? errors.slice(0, 5) : "none");

	const bad = results.some((r) => !r.ok) || errors.length;
	await browser.close();
	console.log(bad ? "\nFAIL" : "\npermalink ok");
	process.exit(bad ? 1 : 0);
})();
