// Load an ORIGINAL Project QT .skel (Spine 2.1.27) in the Kurumifans 2.1.27
// viewer and screenshot it.
//
// This is the decisive test. The conversion to 3.8 was proven byte-faithful,
// yet the models render scrambled in pixi-spine 3.8. If the native 2.1.27
// viewer draws the ORIGINAL file correctly, the assets are fine and the
// problem is purely the 3.8 runtime's handling of these weighted meshes —
// which means the right fix is to view them with a 2.1.27-capable runtime.
//
// The viewer loads via ?url=<skeleton url> and needs CORS, so we serve the
// model files over HTTP from this box instead of using file://.
"use strict";
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");
const http = require("http");

const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const VIEWER = "/root/kurumispine";
const MODEL_DIR = process.argv[2] || "/root/projectqt-models/SimGirls_3_Spine_1";
const OUT = process.argv[3] || "/root/qt-native.png";
const PORT = 8099;

// The viewer expects a .skel/.json plus an atlas named the same, plus the
// atlas's page images. Serve the ORIGINAL (pre-conversion) files.
const ORIG_DIR = process.argv[4] || null;

const MIME = {
	".skel": "application/octet-stream",
	".json": "application/json",
	".atlas": "text/plain",
	".png": "image/png",
	".txt": "text/plain",
	".html": "text/html",
	".js": "application/javascript",
	".css": "text/css",
};

function serveDir(root) {
	return (req, res) => {
		const url = decodeURIComponent(req.url.split("?")[0]);
		let file = path.join(root, url === "/" ? "index.html" : url);
		if (!file.startsWith(root)) {
			res.writeHead(403).end();
			return;
		}
		if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
			res.writeHead(404).end("not found");
			return;
		}
		res.writeHead(200, {
			"Content-Type": MIME[path.extname(file).toLowerCase()] || "application/octet-stream",
			"Access-Control-Allow-Origin": "*",
		});
		fs.createReadStream(file).pipe(res);
	};
}

(async () => {
	// Serve the model dir on :PORT (with CORS) and the viewer on :PORT+1
	const modelServer = http.createServer((req, res) => {
		res.setHeader("Access-Control-Allow-Origin", "*");
		serveDir(MODEL_DIR)(req, res);
	});
	const viewerServer = http.createServer(serveDir(VIEWER));

	await new Promise((r) => modelServer.listen(PORT, r));
	await new Promise((r) => viewerServer.listen(PORT + 1, r));
	console.log(`model  on :${PORT}  (${MODEL_DIR})`);
	console.log(`viewer on :${PORT + 1}`);

	// Find the skeleton file name
	const files = fs.readdirSync(MODEL_DIR);
	const skel = files.find((f) => f.endsWith(".skel")) || files.find((f) => f.endsWith(".json"));
	const atlas = files.find((f) => f.endsWith(".atlas"));
	console.log("skeleton:", skel, "| atlas:", atlas);
	if (!skel || !atlas) {
		console.error("need a .skel and .atlas in the model dir");
		process.exit(1);
	}

	const browser = await chromium.launch({
		executablePath: CHROME,
		args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
	});
	const page = await browser.newPage({ viewport: { width: 1000, height: 1100 } });
	const logs = [];
	page.on("console", (m) => logs.push(`${m.type()}: ${m.text().slice(0, 160)}`));
	page.on("pageerror", (e) => logs.push("pageerror: " + e.message.slice(0, 160)));

	const url = `http://127.0.0.1:${PORT + 1}/index.html?url=http://127.0.0.1:${PORT}/${encodeURIComponent(skel)}`;
	console.log("loading:", url);
	await page.goto(url, { waitUntil: "networkidle", timeout: 90000 });

	// The viewer is GWT-compiled; give it time to boot and fetch the model.
	await page.waitForTimeout(12000);

	const state = await page.evaluate(() => ({
		hasDALFC: typeof window.DALFC !== "undefined",
		bones: window.DALFC?.skeleton?.skeleton?.bones?.length ?? null,
		anims: window.DALFC?.animation?.animations?.length ?? null,
		skins: window.DALFC?.skin?.skins?.length ?? null,
		log: document.getElementById("log")?.textContent?.slice(0, 200) || null,
	}));
	console.log("state:", JSON.stringify(state));

	await page.screenshot({ path: OUT });
	console.log("shot:", OUT);
	if (logs.length) console.log("logs:", logs.slice(0, 8));

	await browser.close();
	modelServer.close();
	viewerServer.close();
})();
