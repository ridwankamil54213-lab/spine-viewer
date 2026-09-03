// Batch-render original Project QT .skel files in the native 2.1.27 viewer.
//
// Confirms the finding across several models: the assets are fine, so the
// scrambling is specific to the pixi-spine 3.8 runtime's handling of these
// weighted meshes.
"use strict";
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");
const http = require("http");
const { execFileSync } = require("child_process");

const CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const VIEWER = "/root/kurumispine";
const OUT = "/root/qt-native-shots";
const PY = "/root/venv-ls/bin/python";

const EXTRACT = `
import UnityPy, struct, os, sys
UnityPy.config.FALLBACK_UNITY_VERSION = '2020.3.33f1'
src, out, stem = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
def pta(raw):
    nl = struct.unpack_from('<i', raw, 0)[0]
    off = (4 + nl + 3) & ~3
    dl = struct.unpack_from('<i', raw, off)[0]
    off += 4
    return raw[off:off+dl]
env = UnityPy.load(src)
for o in env.objects:
    if str(o.type) == '49':
        d = o.read()
        if d.m_Name.endswith('.skel'):
            open(os.path.join(out, stem + '.skel'), 'wb').write(pta(o.get_raw_data()))
        if d.m_Name.endswith('.atlas'):
            open(os.path.join(out, stem + '.atlas'), 'wb').write(pta(o.get_raw_data()))
    if str(o.type) == '28':
        d = o.read()
        d.image.save(os.path.join(out, d.m_Name + '.png'))
print('ok')
`;

const MIME = { ".skel": "application/octet-stream", ".atlas": "text/plain", ".png": "image/png", ".html": "text/html", ".js": "application/javascript", ".css": "text/css" };

function staticServer(root) {
	return (req, res) => {
		const url = decodeURIComponent(req.url.split("?")[0]);
		const file = path.join(root, url === "/" ? "index.html" : url);
		if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
			res.writeHead(404).end("nf");
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
	fs.mkdirSync(OUT, { recursive: true });
	const models = (process.argv[2] || "SimGirls_3_Spine_1,SimGirls_10_Spine_1,SimGirls_Spine_1,SimGirls_16_Spine_4").split(",");

	const browser = await chromium.launch({
		executablePath: CHROME,
		args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage"],
	});

	for (const stem of models) {
		const raw = `/root/projectqt-raw/${stem}.unity3d`;
		if (!fs.existsSync(raw)) {
			console.log(`${stem}: no bundle`);
			continue;
		}
		const dir = `/tmp/qtorig-${stem}`;
		fs.rmSync(dir, { recursive: true, force: true });
		fs.mkdirSync(dir, { recursive: true });
		try {
			execFileSync(PY, ["-c", EXTRACT, raw, dir, stem], { stdio: "pipe" });
		} catch (e) {
			console.log(`${stem}: extract failed ${String(e.stderr || e).slice(0, 90)}`);
			continue;
		}
		const files = fs.readdirSync(dir);
		if (!files.some((f) => f.endsWith(".skel"))) {
			console.log(`${stem}: no skel extracted`);
			continue;
		}

		const port = 8200 + models.indexOf(stem) * 2;
		const modelServer = http.createServer(staticServer(dir));
		const viewerServer = http.createServer(staticServer(VIEWER));
		await new Promise((r) => modelServer.listen(port, r));
		await new Promise((r) => viewerServer.listen(port + 1, r));

		const page = await browser.newPage({ viewport: { width: 1000, height: 1100 } });
		const errs = [];
		page.on("pageerror", (e) => errs.push(e.message.slice(0, 100)));
		await page.goto(
			`http://127.0.0.1:${port + 1}/index.html?url=http://127.0.0.1:${port}/${stem}.skel`,
			{ waitUntil: "networkidle", timeout: 90000 }
		);
		await page.waitForTimeout(11000);
		const st = await page.evaluate(() => ({
			anims: window.DALFC?.animation?.animations?.length ?? null,
			skins: window.DALFC?.skin?.skins?.length ?? null,
		}));
		const file = path.join(OUT, stem + ".png");
		await page.screenshot({ path: file });
		console.log(`${stem}: anims=${st.anims} skins=${st.skins} errs=${errs.length} -> ${file}`);
		await page.close();
		modelServer.close();
		viewerServer.close();
	}

	await browser.close();
	console.log("\ndone");
})();
