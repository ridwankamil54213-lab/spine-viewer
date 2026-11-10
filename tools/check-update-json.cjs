/**
 * Smoke test: "Unexpected end of JSON input" pada tombol updater.
 *
 * Laporan: klik Perbarui aset di Cat Shinobi -> toast
 *   "Gagal memeriksa pembaruan: Failed to execute 'json' on 'Response':
 *    Unexpected end of JSON input"
 *
 * Dua penyebab nyata:
 *   1. Express memberi ETag pada res.json(). Browser yang revalidasi
 *      (If-None-Match) menerima 304 dengan BODY KOSONG -> r.json() meledak.
 *   2. --check Cat Shinobi mengekstrak APK 648 MB + mem-parse semua bundle
 *      UnityPy setiap kali (~17-20 dtk), sehingga proxy/tunnel bisa memutus
 *      request sebelum JSON terkirim.
 *
 * Perbaikan yang diuji:
 *   - endpoint /api/update* & /api/updaters* membuang header conditional,
 *     mengirim no-store, dan menggabungkan --check yang berjalan barengan;
 *   - frontend memakai fetchUpdateJSON() (baca teks dulu, pesan jelas);
 *   - tools/update-catshinobi.py menyimpan hasil scan per ukuran APK,
 *     tetapi tetap memprobe versi terbaru (Range ~3 MB) tiap --check.
 *
 * Run: node tools/check-update-json.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = "http://127.0.0.1:3000";
const SERVER = path.join(ROOT, "src", "server.js");
const VIEWER = path.join(ROOT, "src", "viewer.js");
const PY = path.join(ROOT, "tools", "update-catshinobi.py");
const SCAN_CACHE = "/srv/spine-assets/catshinobi-update/scan-cache.json";

const failed = [];
const ok = (label, cond, extra = "") => {
    if (!cond) failed.push(label);
    console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};

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
        } catch { /* tidak ada */ }
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

async function getRaw(url, headers = {}) {
    const r = await fetch(BASE + url, { headers, cache: "no-store" });
    const text = await r.text();
    let json = null;
    try { json = JSON.parse(text); } catch { /* sengaja */ }
    return { status: r.status, text, json, headers: r.headers };
}

(async () => {
    // --- 1. Kontrak sumber -------------------------------------------------
    const srv = fs.readFileSync(SERVER, "utf8");
    const view = fs.readFileSync(VIEWER, "utf8");
    const py = fs.readFileSync(PY, "utf8");

    ok("server membuang If-None-Match / If-Modified-Since",
        srv.includes('delete req.headers["if-none-match"]') &&
        srv.includes('delete req.headers["if-modified-since"]'));
    ok("server mengirim Cache-Control: no-store",
        /no-store, no-cache, must-revalidate/.test(srv));
    ok("--check barengan digabung (checkInFlight)",
        srv.includes("const checkInFlight = new Map()") &&
        srv.includes("checkInFlight.set(game, job)"));
    ok("frontend punya fetchUpdateJSON + no-store",
        /async function fetchUpdateJSON/.test(view) &&
        /cache: "no-store"/.test(view));
    ok("fetchUpdateJSON menolak body kosong dengan pesan jelas",
        /Server tidak mengirim JSON/.test(view) && /body kosong/.test(view));
    const stale = view.split("\n").filter((l) =>
        /updaterBase|\/api\/update\/|\/api\/updaters\//.test(l) && /\.json\(\)/.test(l));
    ok("tidak ada r.json() tersisa di jalur updater", stale.length === 0,
        stale.slice(0, 2).join(" | "));
    ok("semua jalur updater memakai fetchUpdateJSON",
        (view.match(/fetchUpdateJSON\(/g) || []).length >= 10,
        String((view.match(/fetchUpdateJSON\(/g) || []).length));

    ok("Python punya cache hasil scan",
        /SCAN_CACHE\s*=/.test(py) && /def load_scan_cache/.test(py) &&
        /def save_scan_cache/.test(py) && /def apk_key/.test(py));
    ok("check() tetap memprobe versi terbaru",
        /download_latest_apk\(force=False\)/.test(py));
    ok("check() melaporkan scanCache",
        /"scanCache": "hit" if cached else "miss"/.test(py));

    // --- 2. HTTP: tidak boleh ada 304 --------------------------------------
    const star = await getRaw("/api/update/arkrecode?mode=check",
        { "If-None-Match": "*" });
    ok("If-None-Match: * -> 200 (bukan 304)", star.status === 200, String(star.status));
    ok("body If-None-Match: * berisi JSON valid", !!star.json && !!star.text.length,
        `${star.text.length} byte`);
    ok("header no-store terkirim",
        /no-store/.test(star.headers.get("cache-control") || ""),
        star.headers.get("cache-control"));

    const first = await getRaw("/api/update/arkrecode?mode=check");
    const etag = first.headers.get("etag");
    const cond = await getRaw("/api/update/arkrecode?mode=check",
        { "If-None-Match": etag || "*" });
    ok("ETag lama tidak memicu 304", cond.status === 200 && cond.text.length > 0,
        `${cond.status}, ${cond.text.length} byte`);
    const ims = await getRaw("/api/update/arkrecode?mode=check",
        { "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT" });
    ok("If-Modified-Since tidak memicu 304", ims.status === 200 && !!ims.json);

    const health = await getRaw("/api/updaters/health", { "If-None-Match": "*" });
    ok("/api/updaters/health tidak 304",
        health.status === 200 && health.json?.games?.length >= 25,
        `${health.status}, ${health.json?.games?.length} baris`);
    const status = await getRaw("/api/update/catshinobi/status", { "If-None-Match": "*" });
    ok("/api/update/:game/status tidak 304", status.status === 200 && !!status.json,
        String(status.status));

    // --- 3. Cat Shinobi: cepat & konsisten ----------------------------------
    const warm = await getRaw("/api/update/catshinobi?mode=check");
    ok("--check Cat Shinobi JSON valid", warm.json?.ok === true && !warm.json?.error,
        String(warm.json?.error || warm.json?.version));
    const t0 = Date.now();
    const hit = await getRaw("/api/update/catshinobi?mode=check");
    const elapsed = Date.now() - t0;
    ok("check kedua memakai cache scan", hit.json?.scanCache === "hit",
        String(hit.json?.scanCache));
    ok("check kedua < 8 detik (dulu ~17-20)", elapsed < 8000, `${elapsed} ms`);
    ok("hasil cache tetap benar",
        hit.json?.total === warm.json?.total && hit.json?.new === warm.json?.new &&
        hit.json?.version === warm.json?.version,
        `${hit.json?.total} model / ${hit.json?.new} baru`);

    const cache = JSON.parse(fs.readFileSync(SCAN_CACHE, "utf8"));
    ok("kunci cache = versi APK", cache.key === hit.json?.version,
        `${cache.key} vs ${hit.json?.version}`);
    ok("cache berisi daftar skeleton", Array.isArray(cache.skels) && cache.skels.length >= 500,
        `${cache.skels.length} skeleton`);

    const [p1, p2] = await Promise.all([
        getRaw("/api/update/catshinobi?mode=check"),
        getRaw("/api/update/catshinobi?mode=check"),
    ]);
    ok("dua check bersamaan sama-sama JSON valid",
        p1.status === 200 && p2.status === 200 && !!p1.json?.ok && !!p2.json?.ok);
    ok("dua check bersamaan berbagi log yang sama",
        JSON.stringify(p1.json?.log) === JSON.stringify(p2.json?.log),
        `${(p1.json?.log || []).length} baris`);

    // --- 4. Browser: body kosong tidak lagi jadi error samar ----------------
    const browser = await launch();
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("dialog", (d) => d.dismiss());

    let checkResponses = [];
    page.on("response", async (r) => {
        if (r.url().includes("/api/update/catshinobi?mode=check")) {
            try { checkResponses.push({ status: r.status(), len: (await r.text()).length }); }
            catch { checkResponses.push({ status: r.status(), len: -1 }); }
        }
    });

    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await page.waitForSelector('#game-list .game[data-key="catshinobi"]', { state: "visible" });
    await page.locator('#game-list .game[data-key="catshinobi"]').click();
    await page.waitForSelector("#update-check", { state: "visible", timeout: 30000 });
    ok("tombol updater Cat Shinobi tampil", true);

    // Klik nyata: harus 200 dengan body berisi.
    await page.waitForTimeout(2500);
    await page.locator("#update-check").click();
    await page.waitForFunction(
        () => document.getElementById("update-check")?.classList.contains("is-checking") === false,
        null, { timeout: 60000 });
    const real = checkResponses.filter((x) => x.len > 0);
    ok("klik nyata menerima JSON (bukan body kosong)", real.length >= 1,
        JSON.stringify(checkResponses));

    // Pemeriksaan yang berhasil membuka panel log; tutup dulu supaya tombol
    // header bisa diklik lagi untuk simulasi body kosong.
    await page.keyboard.press("Escape");
    await page.waitForFunction(
        () => document.getElementById("update-log-modal")?.hidden === true,
        null, { timeout: 10000 });

    // Simulasikan proxy yang memutus body: frontend harus kasih pesan jelas.
    await page.evaluate(() => {
        window.__toasts = [];
        const t = document.getElementById("toast");
        if (t) {
            new MutationObserver(() => window.__toasts.push(t.textContent))
                .observe(t, { childList: true, characterData: true, subtree: true });
        }
    });
    const intercepts = [];
    await page.route(
        (u) => u.pathname === "/api/update/catshinobi" && u.searchParams.get("mode") === "check",
        (route) => {
            intercepts.push(1);
            route.fulfill({ status: 200, contentType: "application/json", body: "" });
        });
    await page.locator("#update-check").click();
    await page.waitForTimeout(1200);
    const toasts = await page.evaluate(() => window.__toasts || []);
    const joined = toasts.join(" | ");
    ok("body kosong terintersep", intercepts.length >= 1, String(intercepts.length));
    ok("toast menjelaskan body kosong, bukan 'Unexpected end of JSON input'",
        /Server tidak mengirim JSON/.test(joined) && !/Unexpected end of JSON input/.test(joined),
        joined.slice(0, 180));
    await page.unroute((u) => u.pathname === "/api/update/catshinobi" && u.searchParams.get("mode") === "check");
    ok("tidak ada JS error", errors.length === 0, errors.slice(0, 2).join(" | "));

    await browser.close();
    console.log(`\n=== Hasil Update JSON: ${failed.length ? failed.length + " FAIL" : "semua ok"} ===`);
    if (failed.length) console.log(failed.map((x) => "  - " + x).join("\n"));
    process.exit(failed.length ? 1 : 0);
})().catch((err) => {
    console.error("FATAL", err);
    process.exit(1);
});
