/**
 * Smoke test: updater Ark Re:Code (regresi "20 model baru -> 18 '?' tanpa atlas").
 *
 * Latar: catalog_116031 membawa 20 bundle hero baru. 18 di antaranya (H169,
 * H191..H210, H611) ternyata BUKAN Spine — isinya cuma prefab/ikon/partikel,
 * 0 TextAsset. Dua bug lama bikin hasilnya menyesatkan:
 *   1. state["processed"] ditulis SEBELUM ekstraksi, jadi model yang gagal
 *      dicatat "selesai" selamanya;
 *   2. processed cuma menyimpan id polos, jadi kalau game kemudian menambah
 *      skeleton ke H191, updater tetap melewatkannya.
 *
 * Yang dibuktikan di sini:
 *   - processed_v2 menyimpan signature bundle (hash URL), bukan id polos;
 *   - state disimpan SETELAH ekstraksi, dan hanya untuk yang terverifikasi;
 *   - stem_installed mengenali M001 -> M_001_1 tanpa false-positive A001/A0018;
 *   - --check idempoten: 250 terpasang / 18 bukan Spine / 0 baru;
 *   - dashboard menampilkan have <= expected (dulu 609/268);
 *   - model M_001_1 benar-benar render, 0 aset 404, 0 JS error.
 *
 * Run: node tools/check-arkrecode.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = "http://127.0.0.1:3000";
const ASSETS = path.join(ROOT, "assets", "arkrecode");
const STATE = "/srv/spine-assets/arkrecode/state.json";
const UPDATER = path.join(ROOT, "tools", "update-arkrecode.py");
const PY = fs.existsSync("/srv/venv-spine/bin/python")
    ? "/srv/venv-spine/bin/python" : "python3";

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

(async () => {
    // --- 1. Kontrak sumber -------------------------------------------------
    const src = fs.readFileSync(UPDATER, "utf8");
    ok("signature bundle pakai hashlib",
        /import hashlib/.test(src) && /def model_signature/.test(src));
    ok("processed_v2 menggantikan processed polos",
        /processed_v2/.test(src) && /state\.pop\("processed"/.test(src));
    ok("state disimpan SETELAH loop ekstraksi",
        src.indexOf("save_state(state)") > src.indexOf("bukan Spine (0 TextAsset)"));
    ok("log tidak lagi memakai '?' / 'tanpa atlas'",
        !/doc\.get\('name'\) if doc else '\?'/.test(src) &&
        !/'tanpa atlas'/.test(src) && /bukan Spine \(0 TextAsset\)/.test(src));
    ok("model gagal TIDAK ditandai processed",
        /verified_non_spine/.test(src) && /extract_errors\.append/.test(src));
    ok("alias underscore M001 -> M_001_1",
        /alias = f"\{m\.group\(1\)\}_\{m\.group\(2\)\}_"/.test(src));
    ok("check & apply melaporkan nonSpine",
        /"nonSpine": non_spine/.test(src) && /"nonSpine": len\(non_spine\)/.test(src));
    ok("router ganda + katalog tertinggi tetap dipakai",
        /game-arkre-labs\.ecchi\.xxx/.test(src) &&
        /game-arkre-nu\.ecchi\.xxx/.test(src) && /nomor tertinggi/.test(src));

    // --- 2. Unit Python: alias + signature ---------------------------------
    const unit = `
import importlib.util
s = importlib.util.spec_from_file_location('u', 'tools/update-arkrecode.py')
u = importlib.util.module_from_spec(s); s.loader.exec_module(u)
print(u.stem_installed('M001', {'M_001_1','M_001_2'}))
print(u.stem_installed('A001', {'A0018'}))
print(u.stem_installed('H189', {'H189_S'}))
m = {'H191': ['a','b']}
f = {'a':'/game/hero/h191_AAA.bundle','b':'/game/hero/h191/img_BBB.bundle'}
f2 = dict(f); f2['a'] = '/game/hero/h191_CCC.bundle'
print(u.model_signature(m, f, 'H191') != u.model_signature(m, f2, 'H191'))
`;
    const u = execFileSync(PY, ["-c", unit], { cwd: ROOT, encoding: "utf8" })
        .trim().split("\n").map((x) => x.trim());
    ok("stem_installed(M001) cocok M_001_1", u[0] === "True", u.join("|"));
    ok("tidak false-positive A001 vs A0018", u[1] === "False");
    ok("stem_installed(H189) cocok H189_S", u[2] === "True");
    ok("signature berubah saat hash bundle berubah", u[3] === "True");

    // --- 3. --check lewat HTTP ---------------------------------------------
    const get = (u2) => fetch(BASE + u2).then((r) => r.json());
    const chk = await get("/api/update/arkrecode?mode=check");
    const chk2 = await get("/api/update/arkrecode?mode=check");
    ok("--check via HTTP ok", chk.ok === true && !chk.error, String(chk.error || ""));
    ok("dua --check identik (idempoten)",
        chk.catalog === chk2.catalog && chk.changed === chk2.changed &&
        chk.new === chk2.new && chk.installed === chk2.installed &&
        chk.nonSpine === chk2.nonSpine);
    ok("katalog terbaru dipilih", /^catalog_\d+$/.test(chk.catalog || ""), chk.catalog);
    ok("268 model, 250 terpasang, 18 bukan Spine, 0 baru",
        chk.total >= 260 && chk.installed >= 240 && chk.nonSpine >= 18 &&
        chk.new === 0 && chk.changed === false,
        JSON.stringify({ total: chk.total, installed: chk.installed,
            nonSpine: chk.nonSpine, new: chk.new, changed: chk.changed }));
    ok("installed <= total (regresi 609/268)", chk.installed <= chk.total);
    ok("samples kosong saat tidak ada yang baru",
        Array.isArray(chk.samples) && chk.samples.length === 0);

    // --- 4. State -----------------------------------------------------------
    const state = JSON.parse(fs.readFileSync(STATE, "utf8"));
    ok("state memakai processed_v2", state.processed_v2 &&
        typeof state.processed_v2 === "object" && !("processed" in state));
    const sigs = Object.entries(state.processed_v2 || {});
    ok("18 model bukan Spine tercatat", sigs.length >= 18, String(sigs.length));
    ok("semua value signature 12 hex",
        sigs.every(([, v]) => /^[0-9a-f]{12}$/.test(v || "")));
    const keys = new Set(sigs.map(([k]) => k.toUpperCase()));
    ok("H169 / H191 / H611 tercatat",
        keys.has("H169") && keys.has("H191") && keys.has("H611"));
    ok("M001 / M020 TIDAK tercatat (punya folder)",
        !keys.has("M001") && !keys.has("M020"));
    ok("state.catalog cocok dengan --check", state.catalog === chk.catalog);

    // --- 5. Aset di disk ----------------------------------------------------
    ok("tidak ada folder bernama '?'",
        !fs.existsSync(path.join(ASSETS, "?")));
    const all = await get("/api/models?game=arkrecode");
    const models = all.models || [];
    ok("pustaka Ark Re:Code >= 600 model", models.length >= 600, String(models.length));
    ok("tidak ada id model berisi '?'",
        models.every((m) => !String(m.id).includes("?")));
    const ids = new Set(models.map((m) => m.id));
    ok("M_001_1 & M_020_1 terdaftar",
        ids.has("arkrecode/M_001_1") && ids.has("arkrecode/M_020_1"));

    const broken = [];
    for (const m of models.slice(0, 60)) {
        const folder = path.join(ASSETS, String(m.id).split("/").pop().split("#")[0]);
        for (const f of [m.skeletonFile, m.atlasFile]) {
            if (f && !fs.existsSync(path.join(folder, f))) broken.push(`${m.id}: ${f}`);
        }
    }
    ok("aset 60 model pertama resolve (0 404)", broken.length === 0,
        broken.slice(0, 3).join(" | ") || "60 model");

    // --- 6. Dashboard -------------------------------------------------------
    const health = await get("/api/updaters/health");
    const row = (health.games || []).find((g) => g.game === "arkrecode");
    ok("baris dashboard arkrecode sehat",
        row && row.ok === true && row.changed === false && row.new === 0,
        JSON.stringify(row && { ok: row.ok, changed: row.changed, new: row.new }));
    ok("dashboard have/expected masuk akal",
        row && Number(row.have) <= Number(row.expected),
        row && `${row.have}/${row.expected}`);

    // --- 7. Render di browser ----------------------------------------------
    const browser = await launch();
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [], missing = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("response", (r) => { if (r.status() === 404) missing.push(r.url()); });

    const wanted = "arkrecode/M_001_1";
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await page.waitForSelector('#game-list .game[data-key="arkrecode"]', { state: "visible" });
    ok("tile Ark Re:Code tampil", true);
    await page.locator('#game-list .game[data-key="arkrecode"]').click();
    await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
        { state: "visible" });
    await page.fill("#search", wanted);
    await page.locator(`#model-list [data-id="${wanted}"]`).first()
        .waitFor({ state: "visible", timeout: 30000 });
    await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 60000 });
    await page.waitForFunction(
        (id) => window.spineStage?.model?.id === id && !!window.spineStage?.spine,
        wanted, { timeout: 90000 });
    const st = await page.evaluate(() => ({
        id: window.spineStage.model?.id,
        anims: document.querySelectorAll("#anim-select option").length,
    }));
    ok(`render ${wanted}`, st.id === wanted && st.anims > 0, JSON.stringify(st));
    ok("tidak ada aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));
    ok("tidak ada JS error", errors.length === 0, errors.slice(0, 2).join(" | "));

    await browser.close();
    console.log(`\n=== Hasil Ark Re:Code: ${failed.length ? failed.length + " FAIL" : "semua ok"} ===`);
    if (failed.length) console.log(failed.map((x) => "  - " + x).join("\n"));
    process.exit(failed.length ? 1 : 0);
})().catch((err) => {
    console.error("FATAL", err);
    process.exit(1);
});
