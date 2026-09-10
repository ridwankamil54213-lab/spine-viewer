/**
 * Normalisasi skeleton JSON 2.x supaya bisa dimakan runtime 3.8/4.x.
 *
 * Mengapa perlu
 * -------------
 * Runtime 3.8+ dan format 2.x itu tidak sama, tetapi perbedaannya cukup
 * kecil sehingga satu berkas bisa dibaca dua-duanya asalkan dua hal ini
 * dibereskan lebih dulu. Tanpa normalisasi, runtime melempar dan model
 * gagal dimuat sama sekali.
 *
 * 1. Event boleh tanpa nama (2.x) — WAJIB bernama (3.8+)
 *
 *      2.x:  {"time": 0.2333}                <- memakai nilai dari definisi
 *      2.x:  {"time": 0.4, "name": "hit"}    <- menyebut nama
 *
 *    Runtime 3.8+ membaca field `name` tanpa pemeriksaan, lalu menolak:
 *      "eventDataName cannot be null"
 *    Ini satu-satunya penyebab 13 dari 300 model Epic Seven gagal.
 *
 * 2. `skins` berbentuk objek (2.x) vs larik (3.x/4.x)
 *
 *      2.x:  "skins": { "default": { <slot>: { <nama>: {...} } } }
 *      4.x:  "skins": [ { "name": "default", "attachments": {...} } ]
 *
 *    Runtime 4.x mengharapkan larik; yang berbentuk objek membuat
 *    `skins.map(...)` melempar, atau menghasilkan nol skin.
 *
 * Yang TIDAK disentuh
 * -------------------
 * Sisanya sudah cocok: bones, slots, animations (rotate/translate/scale),
 * drawOrder, dan lampiran (region/mesh/skinnedmesh dengan field `path`).
 * Justru karena itulah rute konversi bekerja — parser 4.1 bisa berjalan
 * melewati struktur 2.x tanpa komplain.
 *
 * Dipakai di
 * ----------
 * Panggil normalizeSpine2Json() pada data skeleton sebelum diberikan ke
 * SkeletonJson runtime mana pun, setiap kali versi terdeteksi 2.x.
 */

/**
 * Beri nama pada frame event yang tidak punya nama.
 *
 * @returns jumlah frame yang ditambal
 */
export function fixEventNames(data, { onWarn } = {}) {
	const declared = Object.keys(data.events || {});
	// Urutan prioritas: nama yang paling mungkin dimaksud. Kalau tidak ada
	// satupun event yang dideklarasi, frame-frame itu tidak bisa diselamatkan
	// dan kita buang saja timeline-nya — lebih baik daripada melempar.
	const fallback =
		declared.find((n) => n === "hit") ||
		declared.find((n) => n === "sound") ||
		declared[0];

	let patched = 0;
	for (const name of Object.keys(data.animations || {})) {
		const anim = data.animations[name];
		if (!anim || !Array.isArray(anim.events)) continue;
		for (const frame of anim.events) {
			if (!frame || frame.name) continue;
			if (!fallback) {
				delete anim.events;
				onWarn?.(`animasi "${name}": event tanpa nama dibuang ` +
					`(tidak ada event yang dideklarasi)`);
				break;
			}
			frame.name = fallback;
			patched++;
		}
	}
	// Definisi event kosong juga ditolak runtime.
	if (!declared.length) delete data.events;
	return patched;
}

/**
 * Ubah `skins` bentuk objek (2.x) menjadi larik (3.x/4.x).
 *
 * @returns true bila diubah
 */
export function normalizeSkins(data) {
	const skins = data.skins;
	if (Array.isArray(skins) || !skins || typeof skins !== "object") return false;

	const list = Object.keys(skins).map((name) => ({
		name,
		attachments: skins[name] || {},
	}));
	data.skins = list;
	return true;
}

/**
 * Terapkan semua normalisasi 2.x -> 3.8+.
 * Aman dipanggil pada data non-2.x: ia hanya menyentuh apa yang perlu.
 *
 * @returns ringkasan apa yang diubah (berguna untuk log/debug)
 */
export function normalizeSpine2Json(data, { onWarn } = {}) {
	if (!data || typeof data !== "object") return null;

	const ver = String(data?.skeleton?.spine || "");
	const major = parseInt(ver.split(".")[0], 10);
	const is2x = Number.isFinite(major) && major > 0 && major < 3;

	const result = { version: ver || null, is2x, eventsPatched: 0, skinsConverted: false };

	// Event dan skin dinormalisasi tanpa memandang versi: kedua bentuk
	// "rusak" ini bisa muncul pada berkas hasil konversi yang label
	// versinya sudah tidak bisa dipercaya.
	result.eventsPatched = fixEventNames(data, { onWarn });
	result.skinsConverted = normalizeSkins(data);

	return result;
}

/** Versi major dari string "2.1.27" -> 2. NaN bila tidak terbaca. */
export function spineMajor(data) {
	const ver = String(data?.skeleton?.spine || "");
	return parseInt(ver.split(".")[0], 10);
}
