#!/usr/bin/env node
/**
 * Regresi Stella Sora — tools/stellasora/update.py.
 *
 * Dua root dari satu updater:
 *   stellasora      36 model Spine 4.2.43 (events/<ref>/spine/*)
 *   stellasora-l2d  293 varian Live2D Cubism 4 (chars/*, .moc3 + tekstur
 *                   + motions/ + physics3), diratakan utk scanner server.
 * Sumber: R2 publik morphthemoth + data JSON GitHub + sinyal CDN resmi Yostar.
 *
 * Sengaja TIDAK menjalankan --apply penuh (ribuan berkas dari R2).
 * Run: node tools/check-stellasora.cjs   (server on :3000)
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.BASE_URL || "http://127.0.0.1:3000";
const SPINE = path.join(ROOT, "assets", "stellasora");
const L2D = path.join(ROOT, "assets", "stellasora-l2d");
const THUMBS = path.join(ROOT, "public", "thumbs", "stellasora");
const UPDATER = path.join(ROOT, "tools", "stellasora", "update.py");
const REFRESH = path.join(ROOT, "tools", "stellasora", "refresh.py");

const failed = [];
const ok = (label, cond, extra = "") => {
    if (!cond) failed.push(label);
    console.log(`${cond ? "ok  " : "FAIL"} ${label}${extra ? "  -> " + extra : ""}`);
};
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
    ok("sumber R2 + 4 data JSON komunitas",
        /pub-fc0f3c90b1b34cacb1ce80b771ca4b08\.r2\.dev/.test(src) &&
        /models\.json/.test(src) && /events\.json/.test(src) && /avg\.json/.test(src));
    ok("sinyal kesegaran: CDN resmi Yostar + StellaSoraData",
        /nova-static\.stellasora\.global/.test(src) && /StellaSoraData/.test(src) &&
        /cdnSha/.test(src) && /dataCommit/.test(src));
    ok("Live2D diratakan: moc3 & tekstur di root, motions/ di subfolder",
        /FileReferences/.test(src) && /motions\//.test(src) && /\.moc3/.test(src));
    ok("prefetch paralel + refresh offline",
        /def prefetch/.test(src) && /ThreadPoolExecutor/.test(src) &&
        fs.existsSync(REFRESH) && /--offline/.test(fs.readFileSync(REFRESH, "utf8")));

    // --- endpoint updater --------------------------------------------------
    const chk = await fetch(`${BASE}/api/update/stellasora?mode=check`).then((r) => r.json());
    const chk2 = await fetch(`${BASE}/api/update/stellasora?mode=check`).then((r) => r.json());
    ok("--check via HTTP ok:true", chk.ok === true && !chk.error, String(chk.error || ""));
    ok("dua --check identik", chk.version === chk2.version &&
        chk.changed === chk2.changed && chk.new === chk2.new &&
        chk.expected === chk2.expected && chk.cdnSha === chk2.cdnSha);
    ok("kontrak check: 36 Spine + 252 Live2D + sinyal live",
        /^[0-9a-f]{12}$/.test(chk.version || "") && chk.expected >= 280 &&
        chk.spineModels >= 30 && chk.l2dModels >= 250 &&
        /^[0-9a-f]{12}$/.test(chk.cdnSha || "") && !!chk.dataCommit &&
        chk.have === chk.expected && chk.changed === (chk.version !== chk.previous),
        JSON.stringify({ v: chk.version, expected: chk.expected, spine: chk.spineModels,
            l2d: chk.l2dModels, cdn: chk.cdnSha }));

    // --- model --------------------------------------------------------------
    const models = (await fetch(`${BASE}/api/models`).then((r) => r.json())).models || [];
    const sp = models.filter((m) => m.game === "stellasora");
    const l2 = models.filter((m) => m.game === "stellasora-l2d");
    ok(">= 30 model Spine Stella Sora", sp.length >= 30, String(sp.length));
    ok(">= 250 varian Live2D Stella Sora", l2.length >= 250, String(l2.length));
    ok("tidak ada id dobel", new Set([...sp, ...l2].map((m) => m.id)).size === sp.length + l2.length);
    ok("Spine 4.2 & Live2D terdeteksi benar",
        sp.every((m) => String(m.spine || "").startsWith("4.2")) &&
        l2.every((m) => m.format === "live2d" && /\.moc3$/i.test(m.skeletonFile || "")),
        JSON.stringify({ spine: sp[0]?.spine, l2d: l2[0]?.format }));
    ok("semua folder bernama ASCII",
        [SPINE, L2D].every((root) => fs.readdirSync(root)
            .filter((d) => fs.statSync(path.join(root, d)).isDirectory())
            .every((d) => /^[A-Za-z0-9_.\-]+$/.test(d))));

    let broken = [];
    for (const m of sp) {
        const d = path.join(SPINE, m.id.split("/").pop().split("#")[0]);
        if (!fs.existsSync(path.join(d, m.skeletonFile)) ||
            !fs.existsSync(path.join(d, m.atlasFile))) { broken.push(m.id + ": skel/atlas"); continue; }
        for (const p of atlasPages(path.join(d, m.atlasFile)))
            if (!fs.existsSync(path.join(d, p))) broken.push(m.id + ": " + p);
    }
    ok("aset Spine resolve (0 404)", broken.length === 0,
        broken.slice(0, 4).join(" | ") || `${sp.length} model`);

    let l2broken = [];
    let withMotions = 0;
    for (const m of l2) {
        const d = path.join(L2D, m.id.split("/").pop().split("#")[0]);
        const tex = m.textureFiles || [];
        if (!fs.existsSync(path.join(d, m.skeletonFile)) || !tex.length) {
            l2broken.push(m.id + ": moc3/tekstur"); continue;
        }
        for (const t of tex)
            if (!fs.existsSync(path.join(d, t))) l2broken.push(m.id + ": " + t);
        const mo = m.motionFiles || [];
        if (mo.length) {
            withMotions++;
            for (const f of mo)
                if (!fs.existsSync(path.join(d, "motions", f))) l2broken.push(m.id + ": " + f);
        }
    }
    ok("aset Live2D resolve (0 404)", l2broken.length === 0,
        l2broken.slice(0, 4).join(" | ") || `${l2.length} model`);
    ok("Live2D punya animasi motion3", withMotions >= l2.length * 0.8,
        `${withMotions}/${l2.length}`);

    // --- nama, family, thumbnail -------------------------------------------
    const CJK = /[\u4e00-\u9fff]/;
    for (const game of ["stellasora", "stellasora-l2d"]) {
        const p = path.join(ROOT, "data", game + "-names.json");
        const n = JSON.parse(fs.readFileSync(p, "utf8"));
        const cjk = Object.entries(n).filter(([, v]) => CJK.test(String(v.name || "")));
        ok(`nama ${game}: lengkap & 0 aksara Tionghoa`,
            Object.keys(n).length >= (game === "stellasora" ? 30 : 250) &&
            cjk.length === 0 && Object.values(n).every((v) => !!v.name && !!v.character),
            `${Object.keys(n).length} nama`);
        const f = JSON.parse(fs.readFileSync(
            path.join(ROOT, "data", game + "-family.json"), "utf8")).families || [];
        ok(`family ${game} valid`, f.length >= (game === "stellasora" ? 2 : 5) &&
            f.every((x) => (x.members || []).length >= 2), String(f.length));
    }
    const man = JSON.parse(fs.readFileSync(path.join(THUMBS, "_manifest.json"), "utf8"));
    const ids = new Set([...sp, ...l2].map((m) => m.id));
    ok("manifest >= 100 thumbnail ilustrasi", Object.keys(man).length >= 100,
        String(Object.keys(man).length));
    ok("thumbnail: kunci valid & WebP ada",
        Object.keys(man).every((k) => ids.has(k)) &&
        Object.values(man).every((f) => f.endsWith(".webp") &&
            fs.existsSync(path.join(THUMBS, f))));
    const apiThumbs = (await fetch(`${BASE}/api/thumbnails`).then((r) => r.json())).thumbs || {};
    ok("/api/thumbnails memuat Stella Sora",
        Object.keys(apiThumbs).filter((k) => k.startsWith("stellasora")).length >= 100,
        String(Object.keys(apiThumbs).filter((k) => k.startsWith("stellasora")).length));

    // --- browser -----------------------------------------------------------
    const browser = await chromium.launch({ args: ["--no-sandbox"] });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(90000);
    const errors = [], missing = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
    page.on("response", (r) => {
        if (r.status() >= 400 && /\.(png|webp|atlas|json|skel|moc3)(\?|$)/.test(r.url()))
            missing.push(`${r.status()} ${r.url()}`);
    });
    for (const key of ["stellasora", "stellasora-l2d"]) {
        // Reload tiap tile: memilih satu game menyembunyikan tile lainnya.
        await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
        await page.waitForSelector(`#game-list .game[data-key="${key}"]`, { state: "visible" });
        await page.locator(`#game-list .game[data-key="${key}"]`).click();
        await page.waitForSelector("#model-list li > button:not(.model-fav), #model-list .gcard",
            { state: "visible" });
        const btn = await page.evaluate(() => {
            const b = document.getElementById("update-check");
            return b ? { hidden: b.hidden } : null;
        });
        ok(`tile + tombol updater ${key}`, btn && btn.hidden === false, JSON.stringify(btn));
    }
    // Render satu model per format, dengan tile game yang sesuai.
    const picks = [sp[0]?.id, l2[0]?.id].filter(Boolean);
    for (const wanted of picks) {
        const game = wanted.split("/")[0];
        await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
        await page.waitForSelector(`#game-list .game[data-key="${game}"]`, { state: "visible" });
        await page.locator(`#game-list .game[data-key="${game}"]`).click();
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
    }
    ok("tidak ada aset 404", missing.length === 0, missing.slice(0, 3).join(" | "));
    ok("tidak ada JS error", errors.length === 0, errors.slice(0, 2).join(" | "));
    await browser.close();

    console.log(`\n${failed.length ? "GAGAL: " + failed.join(" | ") : "Stella Sora ok"}`);
    process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
