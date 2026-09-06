// Per-model render check for DotAbyss that judges the SCREEN, not counters.
//
// Three earlier attempts gave unreliable answers:
//   1. draw-call counting  -> the viewer runs a render loop, so every model
//      scored ~183 whether it drew or threw.
//   2. gl.readPixels       -> the context has preserveDrawingBuffer off, so
//      the buffer is already cleared by the time we read it (all zeros).
// This takes a real Playwright screenshot (compositor output, always valid)
// and decides from two signals measured on the canvas area:
//   nonblank - fraction of pixels that are neither the dark viewer background
//              nor a faint grid line
//   colors   - distinct colors, a proxy for actual character art
const { chromium } = require("playwright-core");
const fs = require("fs");
const zlib = require("zlib");

const LABEL = process.argv[2] || "DotAbyss";
const OUT = "/root/dotabyss_render3.jsonl";

/** Minimal PNG decoder: returns {w, h, px} with px as RGBA. */
function decodePng(buf) {
	let pos = 8; // skip signature
	let w = 0, h = 0, bitDepth = 0, colorType = 0;
	const idat = [];
	while (pos < buf.length) {
		const len = buf.readUInt32BE(pos);
		const type = buf.toString("ascii", pos + 4, pos + 8);
		const data = buf.subarray(pos + 8, pos + 8 + len);
		if (type === "IHDR") {
			w = data.readUInt32BE(0); h = data.readUInt32BE(4);
			bitDepth = data[8]; colorType = data[9];
		} else if (type === "IDAT") {
			idat.push(data);
		} else if (type === "IEND") break;
		pos += 12 + len;
	}
	if (bitDepth !== 8) throw new Error("unsupported bit depth " + bitDepth);
	const channels = { 0: 1, 2: 3, 4: 2, 6: 4 }[colorType];
	if (!channels) throw new Error("unsupported color type " + colorType);
	const raw = zlib.inflateSync(Buffer.concat(idat));
	const stride = w * channels;
	const out = Buffer.alloc(w * h * 4);
	let prev = Buffer.alloc(stride);
	for (let y = 0; y < h; y++) {
		const ft = raw[y * (stride + 1)];
		const line = raw.subarray(y * (stride + 1) + 1, y * (stride + 1) + 1 + stride);
		const cur = Buffer.from(line);
		for (let i = 0; i < stride; i++) {
			const a = i >= channels ? cur[i - channels] : 0;
			const b = prev[i];
			const c = i >= channels ? prev[i - channels] : 0;
			switch (ft) {
				case 1: cur[i] = (cur[i] + a) & 255; break;
				case 2: cur[i] = (cur[i] + b) & 255; break;
				case 3: cur[i] = (cur[i] + ((a + b) >> 1)) & 255; break;
				case 4: {
					const p = a + b - c;
					const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
					cur[i] = (cur[i] + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c)) & 255;
					break;
				}
			}
		}
		for (let x = 0; x < w; x++) {
			const s = x * channels, d = (y * w + x) * 4;
			if (channels >= 3) {
				out[d] = cur[s]; out[d + 1] = cur[s + 1]; out[d + 2] = cur[s + 2];
				out[d + 3] = channels === 4 ? cur[s + 3] : 255;
			} else {
				out[d] = out[d + 1] = out[d + 2] = cur[s];
				out[d + 3] = channels === 2 ? cur[s + 1] : 255;
			}
		}
		prev = cur;
	}
	return { w, h, px: out };
}

function measure(png) {
	const { w, h, px } = png;
	const seen = new Set();
	let nonblank = 0, total = 0;
	for (let y = 0; y < h; y += 2) {
		for (let x = 0; x < w; x += 2) {
			const i = (y * w + x) * 4;
			const r = px[i], g = px[i + 1], b = px[i + 2];
			total++;
			const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
			// viewer background is dark and near-grey; grid lines are faint
			if (mx > 45 && mx - mn > 14) nonblank++;
			if (seen.size < 6000) seen.add(((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3));
		}
	}
	return { nonblank: nonblank / total, colors: seen.size };
}

(async () => {
	const browser = await chromium.launch({
		executablePath: process.env.CHROME_PATH,
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
	});
	const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
	let errors = [];
	page.on("pageerror", (e) => errors.push(e.message));
	page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

	await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 90000 });
	await page.waitForTimeout(2500);

	for (const el of await page.$$("span.game-name")) {
		if (((await el.textContent()) || "").trim() === LABEL) { await el.click(); break; }
	}
	await page.waitForTimeout(4000);

	const ids = await page.evaluate(() =>
		[...document.querySelectorAll("button.model")].map((b) => b.dataset.id).filter(Boolean)
	);
	console.log("models found:", ids.length);

	const canvasSel = "canvas";
	const box = await page.locator(canvasSel).first().boundingBox();
	if (!box) { console.log("no canvas found"); await browser.close(); return; }
	const clip = {
		x: Math.max(0, box.x + 40), y: Math.max(0, box.y + 40),
		width: Math.min(box.width - 80, 1000), height: Math.min(box.height - 80, 800),
	};

	fs.writeFileSync(OUT, "");
	const rows = [];
	for (const id of ids) {
		errors = [];
		const btn = await page.$(`button.model[data-id="${id}"]`);
		if (!btn) { rows.push({ id, nonblank: 0, colors: 0, err: "no card" }); continue; }
		await btn.click();
		await page.waitForTimeout(2600);

		const shot = await page.screenshot({ clip });
		const m = measure(decodePng(shot));
		const err = errors.find((e) => /Texture Error|Error:|RangeError/i.test(e)) || null;
		const row = {
			id,
			nonblank: +m.nonblank.toFixed(4),
			colors: m.colors,
			err: err ? String(err).slice(0, 90) : null,
		};
		rows.push(row);
		fs.appendFileSync(OUT, JSON.stringify(row) + "\n");
		const ok = m.nonblank > 0.004 && m.colors > 15;
		console.log(
			`${ok ? "ok   " : "BLANK"} ${id.padEnd(40)} nonblank=${String(row.nonblank).padStart(7)} colors=${String(m.colors).padStart(5)} ${err ? "ERR" : ""}`
		);
	}

	const blank = rows.filter((r) => !(r.nonblank > 0.004 && r.colors > 15));
	console.log("\n=== SUMMARY ===");
	console.log("total :", rows.length);
	console.log("drawn :", rows.length - blank.length);
	console.log("blank :", blank.length);
	if (blank.length) console.log("blank models:\n  " + blank.map((r) => r.id).join("\n  "));
	await browser.close();
})().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
