// Verifikasi render Dragon Travelers: buka viewer, pilih game, load tiap
// model, lalu screenshot dan hitung piksel non-latar untuk buktikan bahwa
// model benar-benar tergambar (bukan cuma "tidak ada error").
const { chromium } = require("playwright-core");
const fs = require("fs");

const MODELS = process.argv.slice(2);

(async () => {
  const browser = await chromium.launch({
    args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push("console: " + m.text().slice(0, 160));
  });

  await page.goto("http://127.0.0.1:3000/", { waitUntil: "load", timeout: 120000 });
  await page.waitForTimeout(4000);

  // Pilih game Dragon Travelers dulu (daftar model baru muncul setelah itu).
  const picked = await page.evaluate(() => {
    const btns = [...document.querySelectorAll("button.game")];
    const b = btns.find((x) => (x.dataset.key || "") === "dragontravelers");
    if (b) { b.click(); return true; }
    return false;
  });
  console.log("game dipilih:", picked);
  await page.waitForTimeout(3000);

  // Item model: <li><button class="model" data-id="game/nama">...</button></li>
  const names = MODELS.length
    ? MODELS
    : await page.evaluate(() =>
        [...document.querySelectorAll("button.model")]
          .map((e) => e.dataset.id)
          .filter(Boolean)
      );
  console.log("model diuji:", names.length);

  const results = [];
  for (const nm of names) {
    await page.evaluate((id) => {
      const b = [...document.querySelectorAll("button.model")].find(
        (e) => e.dataset.id === id
      );
      if (b) b.click();
    }, nm);
    await page.waitForTimeout(5000);

    // Nama bersih buat nama file: "dragontravelers/lihui_shirenmonv"
    const slug = nm.split("/").pop().replace(/[^a-z0-9]/gi, "_");
    const shot = `/root/dt_${slug}.png`;
    await page.locator("#canvas-wrap canvas").first().screenshot({ path: shot });

    // Hitung piksel yang "berisi": beda dari warna latar gelap viewer.
    const cover = await page.evaluate(async () => {
      const cv = document.querySelector("canvas");
      if (!cv) return -1;
      const url = cv.toDataURL("image/png");
      const img = new Image();
      await new Promise((r) => { img.onload = r; img.src = url; });
      const c2 = document.createElement("canvas");
      c2.width = img.width; c2.height = img.height;
      const ctx = c2.getContext("2d");
      ctx.drawImage(img, 0, 0);
      const d = ctx.getImageData(0, 0, c2.width, c2.height).data;
      let non = 0, tot = 0;
      for (let i = 0; i < d.length; i += 4 * 37) {
        tot++;
        // latar gelap ~ #14161c; anggap "berisi" kalau terang atau berwarna
        if (d[i] > 45 || d[i + 1] > 45 || d[i + 2] > 55) non++;
      }
      return tot ? +((non / tot) * 100).toFixed(2) : -1;
    });

    results.push({ model: nm, cover, shot });
    console.log(`  ${nm.padEnd(34)} cover=${cover}%`);
  }

  console.log("\nerrors:", errors.length ? errors.slice(0, 5) : "(none)");
  fs.writeFileSync("/root/dt_verify.json", JSON.stringify(results, null, 1));
  await browser.close();
})();
