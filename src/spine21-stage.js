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
			page.width = 0;
			page.height = 0;
		},
		unload() {},
	};
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

	// Ukuran asli baru diketahui setelah gambar selesai dimuat.
	for (const page of atlas.pages) {
		if (page.rendererObject) {
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
		const skeletonData = parser.readSkeletonData(JSON.parse(skelText));
		if (!skeletonData?.bones?.length) {
			throw new Error("Data skeleton tidak berisi tulang.");
		}

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
			// Hanya RegionAttachment yang didukung renderer ini — mesh dan
			// skinned mesh butuh jalur berbeda yang belum diimplementasi.
			if (!att || !(att instanceof sp.RegionAttachment)) continue;

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
