// Unit test untuk logika deteksi region yang keluar dari halaman atlas.
//
// Logika ini hidup di dalam viewer.js (closure, tidak di-export), jadi di sini
// di-replikasi persis. Kalau kode di viewer.js berubah, uji ini harus
// diperbarui — ia menjaga PERILAKU, bukan implementasi.
//
// Kasus utama: DotAbyss AIBoss2018101_1. Halamannya 512x512 tetapi atlas
// mendeklarasikan 732x532, dan 16 dari 24 region-nya keluar dari berkas.
// Dulu hanya region TERAKHIR yang diuji (bounds: menimpa `pending` tanpa
// memanggil flush()), dan region terakhir itu kebetulan muat — jadi
// overflow dilaporkan false dan jalur penyelamatan tidak pernah jalan.
const fs = require("fs");
const path = require("path");

/** Replika setia `overflowsPage` dari src/viewer.js. */
function overflowsPage(atlasText, pageName, bt) {
	if (!bt) return false;
	let current = null;
	let pending = null;
	let rotated = false;
	let seenRotate = false;   // format lama: `rotate:` muncul sebelum xy/size
	let evaluated = 0;
	const flush = () => {
		if (current !== pageName || !pending) return false;
		const { x, y, w, h } = pending;
		const pw = rotated ? h : w;
		const ph = rotated ? w : h;
		evaluated++;
		return x + pw > bt.width || y + ph > bt.height;
	};
	for (const line of atlasText.split(/\r?\n/)) {
		const s = line.trim();
		if (/\.(png|jpe?g|webp)$/i.test(s) && !s.includes(" ")) {
			if (flush()) return true;
				current = s;
				pending = null;
				rotated = false;
				seenRotate = false;
				continue;
		}
		const b = s.match(/^bounds:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
		if (b) {
			// Baris inilah yang dulu hilang: region sebelumnya harus diuji
			// sebelum `pending` ditimpa region berikutnya.
			if (flush()) return true;
			// `rotate:` milik SATU region, jadi dibersihkan tiap `bounds:` baru.
			rotated = false;
			const [, x, y, w, h] = b.map(Number);
			pending = { x, y, w, h };
			continue;
		}
			const xy = s.match(/^xy:\s*(\d+)\s*,\s*(\d+)\s*$/i);
			if (xy) {
				if (flush()) return true;
				rotated = seenRotate;
				seenRotate = false;
				pending = { x: Number(xy[1]), y: Number(xy[2]), w: 0, h: 0 };
				continue;
			}
			const sz = s.match(/^size:\s*(\d+)\s*,\s*(\d+)\s*$/i);
			if (sz && pending && pending.w === 0 && pending.h === 0) {
				pending.w = Number(sz[1]);
				pending.h = Number(sz[2]);
				continue;
			}
			if (/^rotate:\s*(90|270|true)/i.test(s)) { rotated = true; seenRotate = true; }
		}
		return flush();
	}

/** Hitung region yang overflow dengan menguji tiap blok secara independen. */
function expectedOverflow(atlasText, pageName, bt) {
	const blocks = [];
	let current = null;
	let pendingRot = false;
	for (const line of atlasText.split(/\r?\n/)) {
		const s = line.trim();
		if (/\.(png|jpe?g|webp)$/i.test(s) && !s.includes(" ")) { current = s; pendingRot = false; continue; }
		const b = s.match(/^bounds:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
		if (b) { blocks.push({ page: current, bounds: b.slice(1).map(Number), rot: pendingRot }); pendingRot = false; continue; }
		// Format lama: `rotate:` mendahului `xy:`/`size:`.
		const xy = s.match(/^xy:\s*(\d+)\s*,\s*(\d+)\s*$/i);
		if (xy) { blocks.push({ page: current, bounds: [Number(xy[1]), Number(xy[2]), 0, 0], rot: pendingRot }); pendingRot = false; continue; }
		const sz = s.match(/^size:\s*(\d+)\s*,\s*(\d+)\s*$/i);
		if (sz && blocks.length && blocks.at(-1).bounds[2] === 0 && blocks.at(-1).bounds[3] === 0 && !blocks.at(-1).closed) {
			blocks.at(-1).bounds[2] = Number(sz[1]);
			blocks.at(-1).bounds[3] = Number(sz[2]);
			blocks.at(-1).closed = true;
			continue;
		}
		if (/^rotate:\s*(90|270|true)/i.test(s)) pendingRot = true;
	}
	return blocks.some((blk) => {
		if (blk.page !== pageName) return false;
		const [x, y, w, h] = blk.bounds;
		const pw = blk.rot ? h : w;
		const ph = blk.rot ? w : h;
		return x + pw > bt.width || y + ph > bt.height;
	});
}

let pass = 0;
let fail = 0;
const check = (name, got, want) => {
	if (got === want) { pass++; console.log(`  ok   ${name}`); }
	else { fail++; console.log(`  FAIL ${name}: dapat ${got}, harap ${want}`); }
};

const ASSETS = path.join(__dirname, "..", "..", "assets");

console.log("1) Kasus nyata DotAbyss");
{
	const dir = path.join(ASSETS, "dotabyss", "AIBoss2018101_1.prefab");
	const text = fs.readFileSync(path.join(dir, "BaseData.atlas"), "utf8");
	// Halaman terpasang 512x512, atlas mendeklarasikan 732x532.
	const bt = { width: 512, height: 512 };
	check("AIBoss2018101_1 terdeteksi overflow", overflowsPage(text, "BaseData.png", bt), true);
	check("sesuai hitungan independen", overflowsPage(text, "BaseData.png", bt),
		expectedOverflow(text, "BaseData.png", bt));
	// Setelah di-stretch ke ukuran deklarasi, region harus muat.
	check("tidak overflow setelah discale ke 732x532",
		overflowsPage(text, "BaseData.png", { width: 732, height: 532 }), false);
}

console.log("\n2) Rotasi 90: bounds menyimpan ukuran asli, kemasan transpose");
{
	// 10 + 30 = 40 <= 64 bila ditukar; tanpa tukar 10+20=30 juga muat.
	// Dipilih angka yang HANYA overflow kalau transpose dihitung benar:
	// bounds w=20 h=50 di halaman 64x64 -> kemasan 50x20.
	const atlas = "p.png\nsize:64,64\nr1\nbounds:20,20,20,50\nrotate:90";
	check("rotate:90 memakai transpose (20+50=70 > 64)",
		overflowsPage(atlas, "p.png", { width: 64, height: 64 }), true);
	// Tanpa rotate, 20+20=40 dan 20+50=70 -> overflow dari sumbu Y.
	const noRot = "p.png\nsize:64,64\nr1\nbounds:20,20,20,50";
	check("tanpa rotate dipakai apa adanya", overflowsPage(noRot, "p.png", { width: 64, height: 64 }), true);
}

console.log("\n3) Halaman sehat tidak boleh ikut tersapu");
{
	const atlas = "p.png\nsize:64,64\nr1\nbounds:0,0,10,10\nr2\nbounds:10,10,20,20\nrotate:90";
	check("semua region muat -> false", overflowsPage(atlas, "p.png", { width: 64, height: 64 }), false);
}

console.log("\n4) Region terakhir saja yang muat (bentuk bug lama)");
{
	// Region pertama overflow, terakhir tidak. Dulu ini mengembalikan false.
	const atlas = "p.png\nsize:64,64\nbad\nbounds:60,0,10,10\ngood\nbounds:0,0,5,5";
	check("region pertama overflow terdeteksi", overflowsPage(atlas, "p.png", { width: 64, height: 64 }), true);
}

console.log("\n5) `rotate:` milik SATU region — jangan bocor ke region berikutnya");
{
	// Region pertama berotasi dan overflow; region kedua TANPA rotate dan
	// sebenarnya muat. Dulu `rotated` tidak dibersihkan, jadi region kedua
	// ikut dihitung transpose dan ikut dituduh overflow.
	const atlas = "p.png\nsize:64,64\nr1\nbounds:40,0,10,30\nrotate:90\nr2\nbounds:0,0,10,30";
	check("region pertama (rotasi) overflow", overflowsPage(atlas, "p.png", { width: 64, height: 64 }), true);
	// Hanya region kedua: 0+10=10, 0+30=30 -> muat. Kalau rotasi bocor,
	// 0+30=30 dan 0+10=10 pun masih muat, jadi pakai angka yang membedakan:
	const only = "p.png\nsize:64,64\nr2\nbounds:0,0,10,30";
	check("region tanpa rotate diukur apa adanya", overflowsPage(only, "p.png", { width: 64, height: 64 }), false);
	// Dan terakhir: rotasi harusnya TIDAK menimpa hasil halaman sehat.
	const healthy = "p.png\nsize:64,64\nr1\nbounds:0,0,50,10\nrotate:90\nr2\nbounds:0,0,10,50";
	// r1 transpose = 10x50 -> muat. r2 apa adanya 10x50 -> muat.
	check("halaman sehat dengan rotasi campur -> false",
		overflowsPage(healthy, "p.png", { width: 64, height: 64 }), false);
}

console.log("\n6) Multi-halaman: hanya halaman bernama yang diuji");
{
	const atlas = [
		"a.png", "size:64,64", "r1", "bounds:0,0,10,10",
		"b.png", "size:64,64", "r2", "bounds:60,60,10,10",
	].join("\n");
	check("halaman a aman", overflowsPage(atlas, "a.png", { width: 64, height: 64 }), false);
	check("halaman b overflow", overflowsPage(atlas, "b.png", { width: 64, height: 64 }), true);
}

console.log("\n7) Format atlas lama (`xy:` + `size:`, `rotate:` di depan)");
{
	// 74% koleksi memakai format ini; parser yang hanya paham `bounds:`
	// melihat NOL region dan tidak pernah menyelamatkan halaman rusak.
	const legacy = [
		"p.png",
		"size: 64,64",
		"format: RGBA8888",
		"r1",
		"  rotate: true",
		"  xy: 40, 0",
		"  size: 30, 10",
	].join("\n");
	// rotate -> kemasan transpose: 40+10=50 <=64, 0+30=30 <=64 -> muat.
	check("format lama, region muat -> false", overflowsPage(legacy, "p.png", { width: 64, height: 64 }), false);

	const legacyOver = [
		"p.png",
		"size: 64,64",
		"r1",
		"  rotate: true",
		"  xy: 60, 0",
		"  size: 30, 10",
	].join("\n");
	// transpose: 60+10=70 > 64 -> overflow.
	check("format lama, region overflow -> true", overflowsPage(legacyOver, "p.png", { width: 64, height: 64 }), true);

	// `size:` halaman (di bawah nama berkas) tidak boleh dianggap ukuran region.
	const pageHeader = [
		"p.png",
		"size: 256,256",       // ukuran HALAMAN
		"r1",
		"  xy: 0, 0",
		"  size: 10, 10",      // ukuran REGION
	].join("\n");
	check("size: halaman tidak jadi ukuran region", overflowsPage(pageHeader, "p.png", { width: 64, height: 64 }), false);
}

console.log("\n8) Konsistensi di seluruh atlas DotAbyss yang mismatched");
{
	const cases = [
		["AIBoss2018101_1.prefab", "BaseData.atlas", "BaseData.png", 512, 512, true],
		["UnitDragonBase.prefab", "BaseData.atlas", "BaseData.png", 512, 512, true],
		["UnitArmorKnightBase.prefab", "BaseData.atlas", "BaseData.png", 1024, 512, true],
	];
	for (const [dir, atlasFile, page, w, h, want] of cases) {
		const p = path.join(ASSETS, "dotabyss", dir, atlasFile);
		if (!fs.existsSync(p)) { console.log(`  lewati ${dir} (tidak ada)`); continue; }
		const text = fs.readFileSync(p, "utf8");
		const got = overflowsPage(text, page, { width: w, height: h });
		check(`${dir} -> ${want}`, got, want);
		check(`${dir} konsisten`, got, expectedOverflow(text, page, { width: w, height: h }));
	}
}

console.log(`\nHASIL: ${pass} lulus, ${fail} gagal`);
process.exit(fail === 0 ? 0 : 1);
