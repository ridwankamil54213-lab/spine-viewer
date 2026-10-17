/**
 * Renderer Spine 2.1 untuk kanvas 2D.
 *
 * Mengapa modul ini ada
 * ---------------------
 * Runtime 3.8/4.x tidak bisa membaca skeleton 2.x, dan tidak ada runtime 2.x
 * di antara dependensi pixi-spine. Akibatnya model 2.1.27 (Project QT,
 * Echocalypse, Epic Seven) terpaksa ditampilkan lewat iframe ke penampil GWT
 * vendored — yang punya loop sendiri, jadi timeline, skin, export PNG, dan
 * FPS meter milik viewer mati semua untuk model-model itu.
 *
 * Dua usaha sebelumnya salah arah, dan keduanya dicoba lebih dulu:
 *
 *   1. Parser biner 2.x buatan sendiri (src/spine2-binary.js)
 *      Hanya ~8% pada Project QT. Format binernya punya banyak variasi yang
 *      tidak terdokumentasi, dan setiap perbaikan membuka perbedaan baru.
 *
 *   2. Konversi .skel -> JSON 2.1.27 (tools/convert-spine2.py)
 *      Parsing 97,8%, tapi RENDER gagal: AnimationState 4.1 memanggil
 *      timeline.getPropertyId() yang tidak ada di timeline 2.x. Mengubah
 *      wadah (biner -> JSON) tidak mengubah isi (format 2.x).
 *
 * Yang benar: sediakan runtime 2.1 yang sesungguhnya. Tidak ada konversi.
 *
 * Mengapa bukan Pixi
 * ------------------
 * spine.js 2.1 ditulis sebelum Pixi ada. Ia tahu Skeleton, AnimationState,
 * Atlas, dan Attachment — tetapi tidak tahu PIXI.Container, texture, atau
 * batching. Jadi ia tidak bisa dimasukkan ke scene graph Pixi yang dipakai
 * viewer untuk model 3.8/4.x.
 *
 * Konsekuensinya: model 2.1 digambar ke kanvas 2D tersendiri yang menempel
 * di atas kanvas Pixi. Ini pilihan yang disengaja, bukan kekurangan —
 * keduanya tetap WebGL di bawahnya (Pixi pakai WebGL, kanvas 2D
 * dipercepat GPU), dan viewport-nya dibagikan supaya pan/zoom terasa sama.
 *
 * Sumber runtime
 * --------------
 * vendor/spine21/ berisi runtime JS resmi EsotericSoftware (tag 2.1.25),
 * disalin apa adanya. Lisensi Spine Runtimes Software License 2.2 — BUKAN
 * MIT. Boleh dipakai untuk keperluan internal dengan menyertakan notice;
 * membuat turunan perlu izin tertulis. Karena itu berkasnya tidak diubah
 * sedikit pun.
 *
 * Catatan kunci dari implementasi referensi
 * -----------------------------------------
 * - `spine.Bone.yDown = false` sebelum membuat Skeleton: biarkan koordinat
 *   y-up bawaan Spine, lalu balik dengan ctx.scale(1, -1) saat menggambar.
 *   Kalau yDown diset true, posisi attachment meleset.
 * - attachment.rendererObject adalah AtlasRegion, dan GAMBARNYA ada di
 *   region.page.rendererObject (diisi sendiri oleh textureLoader di bawah).
 * - region.rotate menandakan tekstur dipaket miring 90 derajat, sehingga
 *   lebar/tinggi SUMBER ditukar dan kanvas diputar -PI/2.
 * - window.spine harus ditukar sementara ke spine21 selama menggambar,
 *   karena bagian dalam runtime mengakses window.spine.
 */

/** Muat runtime 2.1 sekali, Return promise ke objek spine. */
let spine21Promise = null;

export function loadSpine21() {
	if (spine21Promise) return spine21Promise;

	spine21Promise = new Promise((resolve, reject) => {
		// Sudah ada (dipasang tag script di index.html)?
		if (window.spine21) return resolve(window.spine21);

		const script = document.createElement("script");
		script.src = "/vendor/spine21/spine.js";
		script.onload = () => {
			const sp = window.spine;
			if (!sp || !sp.SkeletonJson) {
				return reject(new Error("Runtime Spine 2.1 tidak memuat dengan benar."));
			}
			// Pindahkan ke nama sendiri supaya tidak menimpa window.spine
			// yang mungkin dipakai runtime lain.
			window.spine21 = sp;
			resolve(sp);
		};
		script.onerror = () =>
			reject(new Error("Gagal memuat /vendor/spine21/spine.js"));
		document.head.appendChild(script);
	});
	return spine21Promise;
}

/**
 * Pengisi tekstur atlas: spine.js 2.1 memanggil load(page, path) untuk
 * setiap halaman atlas dan berharap page.rendererObject diisi gambarnya.
 */
function makeTextureLoader(basePath, atlasParent) {
	const pending = [];
	return {
		pending,
		load(page, path) {
			const url = basePath + (atlasParent ? atlasParent + "/" : "") + path;
			const img = new Image();
			const p = new Promise((resolve, reject) => {
				img.onload = resolve;
				img.onerror = () => reject(new Error("Gagal memuat tekstur: " + url));
			});
			img.src = url;
			pending.push(p);
			page.rendererObject = img;
			// JANGAN menimpa page.width/height di sini. Atlas masih sedang
			// di-parse dan parser menghitung region.u = x / page.width dari
			// nilai "size:" yang baru saja dibaca; menolkan di sini membuat
			// SEMUA UV jadi Infinity (tampil null di JSON) dan mesh tak
			// tergambar. Ukuran asli diisi setelah gambar selesai dimuat —
			// hanya bila atlas tak mencantumkan "size:".
		},
		unload() {},
	};
}

/**
 * Perbaiki durasi animasi 2.1 yang NaN — kenapa ini perlu
 * ------------------------------------------------------
 * readAnimation() di vendor/spine21/spine.js menghitung durasi animasi
 * dengan `Math.max(duration, timeline.frames[timeline.frameCount - 1])`
 * (dan varian `frameCount * 3 - 3` untuk timeline tiga-slot). Tetapi
 * timeline Spine 2.1 TIDAK punya properti `frameCount` — yang ada hanya
 * getFrameCount() — jadi indeksnya NaN, hasilnya undefined, dan
 * `Math.max(0, undefined)` = NaN. Terukur: SEMUA 17 animasi abigail (Epic
 * Seven) berdurasi NaN.
 *
 * Bukan cuma angka jelek. Animation.apply menjalankan
 * `if (loop && this.duration != 0) time %= this.duration;`, jadi dengan
 * loop=true: `time %= NaN` = NaN. FfdTimeline.apply menerima time=NaN dan
 * tak satu pun guard-nya cocok (NaN < x dan NaN >= x sama-sama false) →
 * binarySearch1 balik nilai di luar panjang array → frameVertices[...]
 * undefined → TypeError di frame PERTAMA → loop requestAnimationFrame mati
 * → kanvas kosong total tanpa pesan apa pun (terukur: 0 piksel opaque,
 * satu pageerror "Cannot read properties of undefined (reading '0')").
 *
 * Vendor tidak disentuh karena Spine Runtimes License melarang memodifikasi
 * berkasnya. Durasi dihitung ulang dari JSON asli: semua keyframe punya
 * bidang `time`, jadi maksimumnya adalah durasi sebenarnya.
 */
function fixAnimationDurations(skeletonData, skelJson) {
	const walk = (node, max) => {
		if (Array.isArray(node)) {
			for (const x of node) max = walk(x, max);
		} else if (node && typeof node === "object") {
			if (typeof node.time === "number" && node.time > max) max = node.time;
			for (const v of Object.values(node)) {
				if (v && typeof v === "object") max = walk(v, max);
			}
		}
		return max;
	};
	const byName = skelJson && skelJson.animations ? skelJson.animations : {};
	for (const anim of skeletonData.animations || []) {
		if (Number.isFinite(anim.duration) && anim.duration >= 0) continue;
		const fromJson = walk(byName[anim.name], 0);
		anim.duration = Number.isFinite(fromJson) ? fromJson : 0;
	}
}

/**
 * Muat model 2.1 dan kembalikan negara yang bisa digambar berulang kali.
 *
 * @param {object} opts
 * @param {string} opts.basePath  URL direktori model, harus berakhir "/"
 * @param {string} opts.jsonFile  nama berkas skeleton .json
 * @param {string} opts.atlasFile nama berkas .atlas
 * @returns {Promise<object>} { spine, skeleton, skeletonData, animationState, animations }
 */
export async function loadSpine21Model({ basePath, jsonFile, atlasFile }) {
	const sp = await loadSpine21();

	const [skelText, atlasText] = await Promise.all([
		fetch(basePath + jsonFile).then((r) => {
			if (!r.ok) throw new Error("Skeleton tidak bisa diambil: " + jsonFile);
			return r.text();
		}),
		fetch(basePath + atlasFile).then((r) => {
			if (!r.ok) throw new Error("Atlas tidak bisa diambil: " + atlasFile);
			return r.text();
		}),
	]);

	if (!basePath.endsWith("/")) basePath += "/";
	const atlasParent = atlasFile.includes("/")
		? atlasFile.substring(0, atlasFile.lastIndexOf("/"))
		: "";

	const textureLoader = makeTextureLoader(basePath, atlasParent);
	const atlas = new sp.Atlas(atlasText, textureLoader);
	await Promise.all(textureLoader.pending);

	// Ukuran asli HANYA diisi bila atlas tidak mencantumkan "size:" — kalau
	// ditimpa selalu, UV yang dihitung parser (x / page.width) jadi tak cocok
	// dengan tekstur yang digambar.
	for (const page of atlas.pages) {
		if (page.rendererObject && !page.width) {
			page.width = page.rendererObject.naturalWidth || page.width;
			page.height = page.rendererObject.naturalHeight || page.height;
		}
	}

	// Simpan dan pulihkan window.spine: runtime mengaksesnya dari dalam.
	const prevSpine = window.spine;
	window.spine = sp;
	try {
		// yUp bawaan Spine; pembalikan dilakukan saat menggambar.
		sp.Bone.yDown = false;

		const atlasLoader = new sp.AtlasAttachmentLoader(atlas);
		const parser = new sp.SkeletonJson(atlasLoader);
		const skelJson = JSON.parse(skelText);
		const skeletonData = parser.readSkeletonData(skelJson);
		if (!skeletonData?.bones?.length) {
			throw new Error("Data skeleton tidak berisi tulang.");
		}
		fixAnimationDurations(skeletonData, skelJson);

		const skeleton = new sp.Skeleton(skeletonData);
		const stateData = new sp.AnimationStateData(skeletonData);
		const animationState = new sp.AnimationState(stateData);

		// Skin: pakai "default" kalau berisi lampiran, jika tidak skin pertama.
		// Beberapa model 2.x mengekspor default kosong.
		const skins = skeletonData.skins || [];
		const defaultSkin = skins.find((s) => s.name === "default");
		const firstSkin = skins[0];
		const useSkin =
			defaultSkin && Object.keys(defaultSkin.attachments || {}).length > 0
				? "default"
				: firstSkin?.name || "default";
		try {
			skeleton.setSkinByName(useSkin);
			skeleton.setSlotsToSetupPose();
		} catch {
			/* skin tidak ada — biarkan pose setup apa adanya */
		}

		const animations = (skeletonData.animations || []).map((a) => a.name);
		if (animations.length && animationState.setAnimationByName) {
			animationState.setAnimationByName(0, animations[0], true);
		}

		return { spine: sp, skeleton, skeletonData, animationState, animations, useSkin };
	} finally {
		window.spine = prevSpine;
	}
}

/**
 * Gambar satu attachment MESH / SKINNED-MESH ke kanvas 2D.
 *
 * Kenapa perlu jalur ini
 * ----------------------
 * Renderer 2.1 asli (vendor/spine21/spine-canvas.js) HANYA menggambar
 * RegionAttachment — ia melewati mesh. Itu cukup untuk Project QT/Epic Seven
 * yang seluruh lampirannya region, tetapi TIDAK untuk model seperti
 * 极乐深渊 (Blissful Abyss): kulit "default"-nya berisi 38 skinnedmesh + 17
 * mesh dan 0 region, jadi tak ada satu pun yang tergambar.
 *
 * Kanvas 2D tak punya jalur mesh bertekstur seperti WebGL, jadi tiap segitiga
 * digambar terpisah: potong (clip) ke segitiga di ruang dunia, lalu pasang
 * transform affine yang memetakan koordinat teksturnya ke titik-titik dunia,
 * baru drawImage seluruh halaman atlas. Ini teknik kanvas 2D standar untuk
 * mesh Spine 2.x.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {object} sp    objek runtime spine (spine21)
 * @param {object} att   MeshAttachment / SkinnedMeshAttachment
 * @param {object} slot  slot pemilik attachment
 */
function drawMeshAttachment(ctx, sp, att, slot) {
	const region = att.rendererObject;
	const page = region?.page;
	const img = page?.rendererObject;
	if (!region || !img || !att.triangles || !att.uvs || !att.triangles.length) return;

	const pw = page.width || img.naturalWidth || img.width || 0;
	const ph = page.height || img.naturalHeight || img.height || 0;
	if (!pw || !ph) return;

	// Titik-titik dunia untuk attachment ini (sudah termasuk bobot tulang
	// untuk skinned mesh, dan FFD bila ada).
	const world = new Float32Array(att.uvs.length);
	att.computeWorldVertices(0, 0, slot, world);

	const tris = att.triangles;
	const uvs = att.uvs;
	for (let t = 0; t + 2 < tris.length; t += 3) {
		const i0 = tris[t] * 2;
		const i1 = tris[t + 1] * 2;
		const i2 = tris[t + 2] * 2;

		const x0 = world[i0], y0 = world[i0 + 1];
		const x1 = world[i1], y1 = world[i1 + 1];
		const x2 = world[i2], y2 = world[i2 + 1];

		// Posisi tekstur (piksel) untuk tiap sudut, dari UV absolut.
		const t0x = uvs[i0] * pw, t0y = uvs[i0 + 1] * ph;
		const t1x = uvs[i1] * pw, t1y = uvs[i1 + 1] * ph;
		const t2x = uvs[i2] * pw, t2y = uvs[i2 + 1] * ph;

		// Affine yang memetakan (tx,ty) -> (x,y):
		//   x = a*tx + c*ty + e ;  y = b*tx + d*ty + f
		const det =
			(t1x - t0x) * (t2y - t0y) - (t2x - t0x) * (t1y - t0y);
		if (Math.abs(det) < 1e-9) continue; // segitiga degenerate

		const a = ((x1 - x0) * (t2y - t0y) - (x2 - x0) * (t1y - t0y)) / det;
		const c = ((x2 - x0) * (t1x - t0x) - (x1 - x0) * (t2x - t0x)) / det;
		const e = x0 - a * t0x - c * t0y;
		const b = ((y1 - y0) * (t2y - t0y) - (y2 - y0) * (t1y - t0y)) / det;
		const d = ((y2 - y0) * (t1x - t0x) - (y1 - y0) * (t2x - t0x)) / det;
		const f = y0 - b * t0x - d * t0y;

		ctx.save();
		ctx.beginPath();
		ctx.moveTo(x0, y0);
		ctx.lineTo(x1, y1);
		ctx.lineTo(x2, y2);
		ctx.closePath();
		ctx.clip();
		ctx.transform(a, b, c, d, e, f);
		ctx.drawImage(img, 0, 0);
		ctx.restore();
	}
}

/**
 * Gambar satu frame ke konteks kanvas 2D.
 *
 * @param {object} st      hasil loadSpine21Model
 * @param {object} opts
 * @param {CanvasRenderingContext2D} opts.ctx
 * @param {number} opts.width   lebar kanvas (px CSS)
 * @param {number} opts.height  tinggi kanvas (px CSS)
 * @param {number} opts.zoom
 * @param {number} opts.panX
 * @param {number} opts.panY
 * @param {string} opts.bgColor warna latar, format "#rrggbb"
 */
export function drawSpine21(st, opts) {
	const { ctx, width, height, zoom = 1, panX = 0, panY = 0, bgColor = "#101014" } = opts;
	const { spine: sp, skeleton, animationState } = st;

	// Bagian dalam runtime mengakses window.spie secara global.
	const prevSpine = window.spine;
	window.spine = sp;
	try {
		ctx.fillStyle = bgColor;
		ctx.fillRect(0, 0, width, height);

		if (!skeleton) return;

		ctx.save();
		ctx.translate(width / 2 + panX, height / 2 + panY);
		ctx.scale(zoom, zoom);
		// Spine memakai y-up; kanvas memakai y-down.
		ctx.scale(1, -1);

		for (const slot of skeleton.drawOrder) {
			if (!slot) continue;
			const att = slot.attachment;
			if (!att) continue;

			// Mesh & skinned-mesh digambar lewat jalur segitiga sendiri.
			if (
				att instanceof sp.MeshAttachment ||
				att instanceof sp.SkinnedMeshAttachment
			) {
				drawMeshAttachment(ctx, sp, att, slot);
				continue;
			}

			if (!(att instanceof sp.RegionAttachment)) continue;

			const region = att.rendererObject;
			const img = region?.page?.rendererObject;
			if (!region || !img) continue;

			const bone = slot.bone;
			const x = bone.worldX + att.x * bone.m00 + att.y * bone.m01;
			const y = bone.worldY + att.x * bone.m10 + att.y * bone.m11;
			const rot = (-(bone.worldRotation + att.rotation) * Math.PI) / 180;

			ctx.save();
			ctx.translate(x, y);
			ctx.rotate(rot);
			ctx.scale(att.scaleX || 1, att.scaleY || 1);

			// Tekstur yang dipaket miring 90 derajat: tukar ukuran sumber.
			const srcW = region.rotate ? region.height : region.width;
			const srcH = region.rotate ? region.width : region.height;
			if (region.rotate) ctx.rotate(-Math.PI / 2);

			ctx.drawImage(
				img,
				region.x, region.y, srcW, srcH,
				-att.width / 2, -att.height / 2, att.width, att.height,
			);
			ctx.restore();
		}
		ctx.restore();
	} finally {
		window.spine = prevSpine;
	}
}

/** Majukan animasi. `delta` dalam detik. */
export function advanceSpine21(st, delta) {
	if (!st?.animationState || !st?.skeleton) return;
	const prevSpine = window.spine;
	window.spine = st.spine;
	try {
		st.animationState.update(delta);
		st.animationState.apply(st.skeleton);
		st.skeleton.updateWorldTransform();
	} finally {
		window.spine = prevSpine;
	}
}

/** Waktu putar saat ini (detik) pada track 0. */
export function spine21TrackTime(st) {
	if (!st?.animationState) return 0;
	const track = st.animationState.getCurrent
		? st.animationState.getCurrent(0)
		: st.animationState.tracks?.[0];
	return track ? track.trackTime || 0 : 0;
}

/** Putar animasi berdasarkan nama. */
export function setSpine21Animation(st, name, loop = true) {
	if (!st?.animationState?.setAnimationByName) return false;
	const prevSpine = window.spine;
	window.spine = st.spine;
	try {
		st.animationState.setAnimationByName(0, name, loop);
		return true;
	} catch {
		return false;
	} finally {
		window.spine = prevSpine;
	}
}
