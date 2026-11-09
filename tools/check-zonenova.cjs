#!/usr/bin/env node
/**
 * Regresi Zone Nova (禁域战姬) — tools/zonenova/update.py.
 *
 * Rantai: config 1.06 -> CDN CloudFront -> katalog XOR(i%63) -> 188 .ab
 * (fake header "UtS\0 5.0.") -> UnityPy 2022.3.62f2 -> Spine 4.1.24.
 * Nama Inggris dari master-data.bytes (AES-256-CBC + MasterMemory/LZ4),
 * thumbnail ilustrasi dari GachaWiki (bukan halaman atlas).
 *
 * Sengaja TIDAK menjalankan --apply penuh (unduh ~400 MB dari CDN).
 * Run: node tools/check-zonenova.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.BASE_URL || "http://127.0.0.1:3000";
const ASSETS = path.join(ROOT, "assets", "zonenova");
const THUMBS = path.join(ROOT, "public", "thumbs", "zonenova");
const NAMES = path.join(ROOT, "data", "zonenova-names.json");
const FAMILY = path.join(ROOT, "data", "zonenova-family.json");
const UPDATER = path.join(ROOT, "tools", "zonenova", "update.py");
const REFRESH = path.join(ROOT, "tools", "zonenova", "refresh.py");

const failed = [];
const ok = (label, cond, extra = "") => {
    if (!cond) failed.push(label);
    console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};
// Baris HALAMAN atlas selalu diikuti properti `size:`.
const atlasPages = (p) => {
    const lines = fs.readFileSync(p, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/);
    const out = [];
    for (let i = 0; i < lines.length; i++) {
        const s = lines[i].trim().replace(/^\uFEFF/, "").trim();
        if (!s || /^\s/.test(lines[i]) || !/\.(png|webp|jpe?g)$/i.test(s) ||
            s.includes("/") || s.includes("\\")) continue;
        const nxt = lines.slice(i + 1, i + 4).map((l) => l.trim()).find(Boolean) || "";
        if (/^size:/i.test(nxt)) out.push(s);
    }
    return [...new Set(out)];
};

(async () => {
    // --- kontrak sumber ----------------------------------------------------
    const src = fs.readFileSync(UPDATER, "utf8");
    ok("config appVersion=1.06 (satu-satunya yang ngasih AssetBundlePath)",
        /appVersion=1\.06/.test(src) && /AssetBundlePath/.test(src));
    ok("katalog: MD5(Android+path) + XOR(i % 63)",
        /XOR_MOD\s*=\s*63/.test(src) && /ab_name/.test(src) && /i % XOR_MOD/.test(src));
    ok("master-data: AES via openssl + MasterMemory/LZ4",
        /aes-256-cbc/.test(src) && /translation_ds/.test(src) && /lz4\.block/.test(src));
    ok("fake-header UtS dibuang sebelum UnityPy",
        /find\(b"UnityFS"/.test(src) && /FALLBACK_UNITY_VERSION/.test(src) &&
        /2022\.3\.62f2/.test(src));
    ok("refresh.py membangun ulang dari cache",
        fs.existsSync(REFRESH) && /--apply", "--offline/.test(fs.readFileSync(REFRESH, "utf8")));

    // --- endpoint updater --------------------------------------------------
    const chk = await fetch(`${BASE}/api/update/zonenova?mode=check`).then((r) => r.json());
    const chk2 = await fetch(`${BASE}/api/update/zonenova?mode=check`).then((r) => r.json());
    ok("--check via HTTP ok:true", chk.ok === true && !chk.error, String(chk.error || ""));
    ok("dua --check identik", chk.version === chk2.version &&
        chk.changed === chk2.changed && chk.new === chk2.new &&
        chk.expected === chk2.expected);
    ok("kontrak check lengkap", /^[0-9a-f]{12}$/.test(chk.version || "") &&
        chk.catalogBundles > 900 && chk.expected >= 150 && chk.have === chk.expected &&
        chk.changed === (chk.version !== chk.previous),
        JSON.stringify({ v: chk.version, cat: chk.catalogVersion,
            bundles: chk.catalogBundles, expected: chk.expected, have: chk.have }));

    // --- integritas model --------------------------------------------------
    const models = (await fetch(`${BASE}/api/models`).then((r) => r.json())).models || [];
    const zn = models.filter((m) => m.game === "zonenova");
    const dirs = fs.readdirSync(ASSETS).filter((d) => fs.statSync(path.join(ASSETS, d)).isDirectory());
    ok(">= 150 model Zone Nova", zn.length >= 150 && zn.length === dirs.length,
        `${zn.length} model / ${dirs.length} folder`);
    ok("tidak ada id dobel", new Set(zn.map((m) => m.id)).size === zn.length);
    ok("semua folder bernama ASCII (id = folder)",
        dirs.every((d) => /^[A-Za-z0-9_.\-]+$/.test(d)),
        dirs.filter((d) => !/^[A-Za-z0-9_.\-]+$/.test(d)).slice(0, 3).join(" | ") || `${dirs.length} folder`);
    ok("runtime Spine 4.1 & straight-alpha",
        zn.every((m) => String(m.spine || "").startsWith("4.1") && m.pmaDefault === false),
        JSON.stringify({ spine: zn[0]?.spine, pma: zn[0]?.pmaDefault }));

    let broken = [];
    for (const m of zn) {
        const leaf = String(m.id).split("/").pop().split("#")[0];
        const dir = path.join(ASSETS, leaf);
        const sk = path.join(dir, m.skeletonFile);
        const at = path.join(dir, m.atlasFile);
        if (!fs.existsSync(sk) || !fs.existsSync(at)) { broken.push(`${m.id}: skel/atlas`); continue; }
        for (const p of atlasPages(at)) {
            if (!fs.existsSync(path.join(dir, p))) broken.push(`${m.id}: ${p}`);
        }
    }
    ok("semua aset model resolve (0 404)", broken.length === 0,
        broken.slice(0, 4).join(" | ") || `${zn.length} model`);

    // --- nama & family ------------------------------------------------------
    const names = JSON.parse(fs.readFileSync(NAMES, "utf8"));
    const CJK = /[\u4e00-\u9fff]/;
    const cjk = Object.entries(names).filter(([, v]) => CJK.test(String(v.name || "")));
    ok("nama tampilan 0 aksara Tionghoa", cjk.length === 0,
        cjk.slice(0, 2).map(([k, v]) => `${k}=${v.name}`).join(" | ") || `${Object.keys(names).length} nama`);
    ok("nama lengkap (karakter + varian) & kunci ASCII",
        Object.keys(names).length >= 150 &&
        Object.entries(names).every(([k, v]) => /^[A-Za-z0-9_.\-]+$/.test(k) &&
            !!v.name && !!v.character && v.name !== k),
        String(Object.keys(names).length));
    const fam = JSON.parse(fs.readFileSync(FAMILY, "utf8")).families || [];
    const ids = new Set(zn.map((m) => m.id));
    ok("family CG/portrait terbentuk (>= 30)", fam.length >= 30, String(fam.length));
    ok("semua anggota family = id model valid",
        fam.every((f) => ids.has(f.root) && (f.members || []).every((x) => ids.has(x.id))));

    // --- thumbnail ilustrasi -----------------------------------------------
    const man = JSON.parse(fs.readFileSync(path.join(THUMBS, "_manifest.json"), "utf8"));
    ok("manifest >= 40 thumbnail ilustrasi", Object.keys(man).length >= 40,
        String(Object.keys(man).length));
    ok("semua kunci manifest = id model valid", Object.keys(man).every((k) => ids.has(k)));
    ok("semua berkas WebP ada & bukan atlas",
        Object.values(man).every((f) => f.endsWith(".webp") && fs.existsSync(path.join(THUMBS, f))));
    const apiThumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs || {};
    ok("/api/thumbnails memuat kunci zonenova",
        Object.keys(apiThumbs).filter((k) => k.startsWith("zonenova/")).length >= 40,
        String(Object.keys(apiThumbs).filter((k) => k.startsWith("zonenova/")).length));

    // --- browser -----------------------------------------------------------
    const browser = await chromium.launch({ args: ["--no-sandbox"] });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(90000);
    const errors = [], missing = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
    page.on("response", (r) => {
        if (r.status() >= 400 && /\.(png|webp|atlas|json|skel)(\?|$)/.test(r.url()))
            missing.push(`${r.status()} ${r.url()}`);
    });
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await page.waitForSelector('#game-list .game[data-key="zonenova"]', { state: "visible" });
    await page.locator('#game-list .game[data-key="zonenova"]').click();
    await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
        { state: "visible" });
    const btn = await page.evaluate(() => {
        const b = document.getElementById("update-check");
        return b ? { hidden: b.hidden } : null;
    });
    ok("tombol Manual Update tampil untuk Zone Nova", btn && btn.hidden === false,
        JSON.stringify(btn));
    // Cari model yang punya thumbnail supaya kartunya benar-benar termuat.
    const withThumb = Object.keys(man)[0];
    const card = await page.evaluate(() => {
        const img = document.querySelector(
            "#model-list li > button:not(.model-fav) img, #model-list .gcard img");
        return img ? { src: img.getAttribute("src"), w: img.naturalWidth, complete: img.complete } : null;
    });
    ok("thumbnail ilustrasi ter-render di kartu",
        card && card.complete && card.w > 0,
        JSON.stringify({ card, contoh: withThumb }));

    const roots = zn.filter((m) => !m.family || m.family.root === m.id).map((m) => m.id);
    const picks = roots.slice(0, 3);
    for (const wanted of picks) {
        await page.fill("#search", wanted);
        await page.locator(`#model-list [data-id="${wanted}"]`).first()
            .waitFor({ state: "visible", timeout: 30000 });
        await page.locator(`#model-list [data-id="${wanted}"]`).first().click({ timeout: 60000 });
        await page.waitForFunction(
            (id) => window.spineStage?.model?.id === id && !!window.spineStage?.spine?.skeleton,
            wanted, { timeout: 90000 });
        const st = await page.evaluate(() => ({
            id: window.spineStage.model?.id,
            anims: document.querySelectorAll("#anim-select option").length,
        }));
        ok(`render ${wanted}`, st.id === wanted && st.anims > 0, JSON.stringify(st));
    }
    ok("tidak ada aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));
    ok("tidak ada JS error", errors.length === 0, errors.slice(0, 2).join(" | "));
    await browser.close();

    console.log(`\n${failed.length ? "GAGAL: " + failed.join(" | ") : "Zone Nova ok"}`);
    process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
