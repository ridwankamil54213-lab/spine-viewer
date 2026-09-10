/**
 * Responsive smoke check for the transport bar + library list.
 *
 * Loads the page at a range of viewport widths and reports, for each:
 *   - transport row heights (a jumped height means the row wrapped)
 *   - horizontal overflow inside each row
 *   - any control clipped outside the transport box
 *   - whether the page itself scrolls sideways
 *
 * Run: node tools/check-toolbar.cjs
 */
const { chromium } = require("playwright-core");

const SIZES = [
	[1600, 900, "desktop wide"],
	[1280, 800, "desktop"],
	[1100, 800, "laptop narrow"],
	[900, 800, "tablet"],
	[760, 900, "phone landscape-ish"],
	[420, 850, "phone"],
	[360, 780, "phone small"],
];

const PROBE = () => {
	const rows = [...document.querySelectorAll(".transport-row")];
	const tb = document.querySelector(".transport").getBoundingClientRect();
	const controls = [...document.querySelectorAll(".transport button, .transport select")].filter(
		(e) => e.offsetParent !== null
	);
	return {
		rowHeights: rows.map((r) => Math.round(r.getBoundingClientRect().height)),
		rowOverflow: rows.map((r) => r.scrollWidth - r.clientWidth),
		transportHeight: Math.round(tb.height),
		pageOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
		clipped: controls
			.filter((e) => {
				const r = e.getBoundingClientRect();
				return r.right > tb.right + 1 || r.left < tb.left - 1;
			})
			.map((e) => e.id || e.className),
		tinyTargets: controls
			.filter((e) => {
				const r = e.getBoundingClientRect();
				return r.width > 0 && (r.width < 24 || r.height < 24);
			})
			.map((e) => `${e.id || e.className}:${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`),
	};
};

(async () => {
	const browser = await chromium.launch({ args: ["--no-sandbox"] });
	let bad = 0;
	for (const [w, h, label] of SIZES) {
		const page = await browser.newPage({ viewport: { width: w, height: h } });
		await page.goto("http://localhost:3000/", { waitUntil: "domcontentloaded" });
		await page.waitForTimeout(500);
		const r = await page.evaluate(PROBE);
		const problems = [];
		if (r.rowOverflow.some((n) => n > 0)) problems.push(`row overflow ${r.rowOverflow}`);
		if (r.clipped.length) problems.push(`clipped: ${r.clipped.join(", ")}`);
		if (r.pageOverflowX > 0) problems.push(`page scrolls sideways ${r.pageOverflowX}px`);
		if (r.tinyTargets.length) problems.push(`tiny: ${r.tinyTargets.join(", ")}`);
		if (problems.length) bad++;
		console.log(
			`${String(w).padStart(4)}x${h}  ${label.padEnd(20)} rows=${JSON.stringify(r.rowHeights)} transport=${r.transportHeight}px  ` +
				(problems.length ? "FAIL -> " + problems.join(" | ") : "ok")
		);
		await page.close();
	}
	await browser.close();
	console.log(bad ? `\n${bad} viewport(s) with problems` : "\nall viewports ok");
	process.exit(bad ? 1 : 0);
})();
