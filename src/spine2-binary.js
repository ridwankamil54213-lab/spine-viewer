/**
 * Pembaca skeleton biner Spine 2.x (.skel).
 *
 * WHY THIS EXISTS
 *   pixi-spine tidak punya runtime 2.x, dan runtime 3.8 tidak bisa membaca
 *   berkas 2.x — format binernya beda sejak header. Model 2.1.27 (Epic Seven,
 *   Project QT, Echocalypse) selama ini ditampilkan lewat iframe ke penampil
 *   GWT vendored, yang berarti timeline/skin/export/FPS punya kita mati semua
 *   untuk model-model itu: penampilnya punya loop dan kontrol sendiri.
 *   Dengan parser ini kita bisa mengubah .skel 2.x menjadi JSON yang bisa
 *   dimasukkan ke runtime 3.8, sehingga model-model itu jadi model biasa.
 *
 * ASAL
 *   Diadaptasi dari lib/spine2-skeleton-binary.js milik
 *   4163/pixijs-live2d-spine-viewer (MIT). Tata letak biner dan urutan
 *   pembacaannya dipertahankan persis — perubahan hanya pada:
 *     - dibungkus jadi kelas ESM supaya bisa di-bundle esbuild (aslinya
 *       fungsi global untuk tag <script>);
 *     - pembacaan float lewat DataView, bukan bit-shift manual.
 *       Aslinya menghitung (b0<<24)|(b1<<16)|(b2<<8)|b3 lalu mengurai
 *       IEEE-754 dengan tangan. Di JS, b0<<24 menghasilkan int32 bertanda,
 *       dan hasilnya benar murni karena & dan >> bersifat 32-bit — jadi
 *       percakapan ini rawan, bukan salah. DataView melakukan hal yang sama
 *       tanpa jebakan itu.
 *     - readString(): aslinya memanggil readInt(this, true), yang bebas-bebas
 *       saja benar karena `this` truthy dipakai sebagai optimizePositive.
 *       Dibetulkan jadi readInt(true) supaya maksudnya jelas.
 *     - timeline IK diberi nama. Aslinya `ik[this.json.ik[ikIndex]]` —
 *       json.ik berisi OBJEK constraint, jadi kuncinya jadi "[object Object]".
 *       Timeline-nya sendiri tidak membawa nama, dan format 3.8 perlu nama.
 *
 * HASIL
 *   Objek JSON dalam format Spine 2.x (bukan 3.8). Untuk dirender, hasilnya
 *   harus lewat spine2-to-modern.js dulu.
 *
 * CATATAN
 *   Ini parser 2.x, bukan 3.x/4.x. Jangan dipakai untuk berkas yang sudah
 *   terdeteksi sebagai 3.8+ — pakai runtime yang sesuai.
 */

const BLEND_MODE = ["normal", "additive", "multiply", "screen"];
const ATTACHMENT_TYPE = ["region", "boundingbox", "mesh", "skinnedmesh"];

/**
 * Batas wajar untuk hitungan yang dibaca dari berkas (bone, slot, frame).
 * Dipakai readInt() — lihat catatan di sana.
 */
const MAX_COUNT = 16_000_000;

export class SkeletonBinary2 {
	/**
	 * @param {Uint8Array|ArrayBuffer} data isi berkas .skel
	 * @param {number} scale pengali untuk x/y/length (1 = apa adanya)
	 */
	constructor(data, scale = 1) {
		this.bytes = data instanceof Uint8Array
			? data
			: new Uint8Array(data);
		this.view = new DataView(
			this.bytes.buffer,
			this.bytes.byteOffset,
			this.bytes.byteLength,
		);
		this.pos = 0;
		this.scale = scale;
		this.json = {};
	}

	// ---------------------------------------------------------- primitif --

	readByte() {
		if (this.pos >= this.bytes.length) return 0;
		return this.bytes[this.pos++];
	}

	readBoolean() {
		return this.readByte() !== 0;
	}

	readShort() {
		// Maksimal 255<<8 = 65280, jadi tidak pernah negatif.
		return (this.readByte() << 8) | this.readByte();
	}

	/** int32 big-endian, apa adanya. */
	readIntRaw() {
		const v = this.view.getInt32(this.pos, false);
		this.pos += 4;
		return v;
	}

	/**
	 * int32 varint. optimizePositive=true memakai zigzag decoding.
	 *
	 * Hitungan yang dibaca dipakai untuk mengalokasikan array, jadi bacaan
	 * yang melenceng bisa menghasilkan angka miliaran — itu yang membuat
	 * parser menghabiskan memori sampai OOM alih-alih gagal. Batas wajar
	 * (16 juta elemen) mengubah kegagalan itu menjadi error yang jelas.
	 */
	readInt(optimizePositive) {
		if (optimizePositive === undefined) return this.readIntRaw();

		let b = this.readByte();
		let result = b & 0x7f;
		if ((b & 0x80) !== 0) {
			b = this.readByte();
			result |= (b & 0x7f) << 7;
			if ((b & 0x80) !== 0) {
				b = this.readByte();
				result |= (b & 0x7f) << 14;
				if ((b & 0x80) !== 0) {
					b = this.readByte();
					result |= (b & 0x7f) << 21;
					if ((b & 0x80) !== 0) {
						b = this.readByte();
						result |= (b & 0x7f) << 28;
					}
				}
			}
		}
		const value = optimizePositive ? result : ((result >> 1) ^ -(result & 1));
		if (value > MAX_COUNT) {
			throw new Error(
				`[spine2] hitungan ${value} di luar batas wajar (pos ${this.pos}) ` +
				`— bacaan melenceng, bukan berkas 2.x yang valid`);
		}
		return value;
	}

	/** float32 big-endian. */
	readFloat() {
		if (this.pos + 4 > this.bytes.length) {
			throw new Error(
				`[spine2] baca float di luar batas (pos ${this.pos}/${this.bytes.length})`);
		}
		const v = this.view.getFloat32(this.pos, false);
		this.pos += 4;
		return v;
	}

	readFloatArray() {
		const n = this.readInt(true);
		const array = new Array(n);
		if (this.scale === 1) {
			for (let i = 0; i < n; i++) array[i] = this.readFloat();
		} else {
			for (let i = 0; i < n; i++) array[i] = this.readFloat() * this.scale;
		}
		return array;
	}

	readShortArray() {
		const n = this.readInt(true);
		const array = new Array(n);
		for (let i = 0; i < n; i++) array[i] = this.readShort();
		return array;
	}

	readIntArray() {
		const n = this.readInt(true);
		const array = new Array(n);
		for (let i = 0; i < n; i++) array[i] = this.readInt(true);
		return array;
	}

	readHex() {
		const hex = this.readByte().toString(16);
		return hex.length === 2 ? hex : "0" + hex;
	}

	readColor() {
		return this.readHex() + this.readHex() + this.readHex() + this.readHex();
	}

	/** Jalur lambat UTF-8: dipanggil hanya bila ada byte >127. */
	readUtf8Slow(charCount, charIndex, b) {
		for (;;) {
			switch (b >> 4) {
				case 0: case 1: case 2: case 3:
				case 4: case 5: case 6: case 7:
					this.chars += String.fromCharCode(b);
					break;
				case 12: case 13:
					this.chars += String.fromCharCode(
						((b & 0x1f) << 6) | (this.readByte() & 0x3f));
					break;
				case 14:
					this.chars += String.fromCharCode(
						((b & 0x0f) << 12)
						| ((this.readByte() & 0x3f) << 6)
						| (this.readByte() & 0x3f));
					break;
				case 15: {
					// 4 byte (di luar jangkauan BMP). Aslinya tidak menangani
					// ini — karakternya hilang. Ditambahkan supaya nama yang
					// mengandung emoji tidak jadi rusak, bukan karena umum
					// dipakai aset 2.x.
					const cp = ((b & 0x07) << 18)
						| ((this.readByte() & 0x3f) << 12)
						| ((this.readByte() & 0x3f) << 6)
						| (this.readByte() & 0x3f);
					const v = cp - 0x10000;
					this.chars += String.fromCharCode(
						0xd800 + (v >> 10), 0xdc00 + (v & 0x3ff));
					break;
				}
			}
			if (++charIndex >= charCount) break;
			b = this.readByte() & 0xff;
		}
	}

	readString() {
		const charCount = this.readInt(true);
		if (charCount === 0) return null;
		if (charCount === 1) return "";

		// Karakter terakhir adalah penanda akhir string, bukan isi.
		let n = charCount - 1;
		// Panjang mustahil: string ASCII tidak mungkin lebih panjang dari
		// sisa berkas. Tanpa batas ini, panjang yang salah membuat loop di
		// bawah membaca melewati akhir dan menghasilkan sampah panjang.
		if (n > this.bytes.length - this.pos) {
			throw new Error(
				`[spine2] panjang string ${charCount} melebihi sisa berkas ` +
				`(${this.bytes.length - this.pos} byte) pada pos ${this.pos}`);
		}
		this.chars = "";
		let b = 0;
		let charIndex = 0;
		while (charIndex < n) {
			b = this.readByte();
			if (b > 127) break;
			this.chars += String.fromCharCode(b);
			charIndex++;
		}
		if (charIndex < n) this.readUtf8Slow(n, charIndex, b);
		return this.chars;
	}

	// ------------------------------------------------------------ skeleton --

	/** Baca seluruh berkas. Mengembalikan objek JSON format Spine 2.x. */
	readSkeletonData() {
		this.initJson();
		return this.json;
	}

	initJson() {
		this.json.skeleton = {};
		const skeleton = this.json.skeleton;
		skeleton.hash = this.readString();
		if (skeleton.hash && skeleton.hash.length === 0) skeleton.hash = null;
		skeleton.spine = this.readString();
		if (skeleton.spine && skeleton.spine.length === 0) skeleton.spine = null;
		skeleton.width = this.readFloat();
		skeleton.height = this.readFloat();
		const nonessential = this.readBoolean();
		if (nonessential) {
			skeleton.images = this.readString();
			if (skeleton.images && skeleton.images.length === 0) skeleton.images = null;
		}

		// Bone.
		this.json.bones = new Array(this.readInt(true));
		const bones = this.json.bones;
		for (let i = 0; i < bones.length; i++) {
			const boneData = { name: this.readString(), parent: null };
			const parentIndex = this.readInt(true) - 1;
			if (parentIndex !== -1) boneData.parent = bones[parentIndex].name;
			boneData.x = this.readFloat() * this.scale;
			boneData.y = this.readFloat() * this.scale;
			boneData.scaleX = this.readFloat();
			boneData.scaleY = this.readFloat();
			boneData.rotation = this.readFloat();
			boneData.length = this.readFloat() * this.scale;
			boneData.flipX = this.readBoolean();
			boneData.flipY = this.readBoolean();
			boneData.inheritScale = this.readBoolean();
			boneData.inheritRotation = this.readBoolean();
			if (nonessential) boneData.color = this.readColor();
			bones[i] = boneData;
		}

		// Constraint IK.
		//
		// TIDAK ADA field kapasitas di sini. Formatnya murni:
		//   jumlah, lalu sebanyak itu record {nama, bones, target, mix, bend}.
		//
		// Aslinya (`lib/spine2-skeleton-binary.js` milik
		// 4163/pixijs-live2d-spine-viewer) membacaangka kedua sebagai
		// KAPASITAS array lalu mengulang sebanyak JUMLAH:
		//     this.json.ik = new Array(this.readInt(true));
		//     for (i = 0; i < ikIndex; i++)
		// Angka "kedua" itu sebenarnya PANJANG NAMA constraint pertama, jadi
		// seluruh pembacaan bergeser: nama constraint jadi string raksasa
		// ("leg_L_IK1-2\u0001\u001b<?..."), dan indeks bone di record-record
		// berikutnya menunjuk ke luar jangkauan.
		//
		// Yang membuatnya tidak ketahuan pada model aslinya: Springfield
		// (satu-satunya model yang dipakai repo itu) tidak punya constraint
		// IK sama sekali, jadi cabang ini tidak pernah dijalankan.
		// PetBG3003_S02 dan 1001_Event_CG11 punya — dan keduanya gagal.
		//
		// catatan: 1001_Event_CG11 = 11 constraint, semuanya
		// leg_{L,R}_IK{1,2}-{1,2}; PetBG3003_S02 = 7.
		const ikIndex = this.readInt(true);
		if (ikIndex > 0) {
			this.json.ik = [];
			const ik = this.json.ik;
			for (let i = 0; i < ikIndex; i++) {
				const c = { name: this.readString() };
				c.bones = new Array(this.readInt(true));
				for (let j = 0; j < c.bones.length; j++) {
					const boneIdx = this.readInt(true);
					// Sebuah constraint bisa menunjuk bone yang tidak ada bila
					// bacaan mulai melenceng. Melempar di sini (daripada
					// merusak JSON diam-diam) membuat kegagalan kelihatan di
					// tempat asalnya.
					const bone = this.json.bones[boneIdx];
					if (!bone) {
						throw new Error(
							`[spine2] constraint IK "${c.name}" menunjuk bone #${boneIdx} ` +
							`yang tidak ada (ada ${this.json.bones.length})`);
					}
					c.bones[j] = bone.name;
				}
				const targetIdx = this.readInt(true);
				const target = this.json.bones[targetIdx];
				if (!target) {
					throw new Error(
						`[spine2] constraint IK "${c.name}" menunjuk target #${targetIdx} ` +
						`yang tidak ada (ada ${this.json.bones.length})`);
				}
				c.target = target.name;
				c.mix = this.readFloat();
				c.bendPositive = this.readBoolean();
				ik[i] = c;
			}
		}

		// Slot.
		this.json.slots = new Array(this.readInt(true));
		const slots = this.json.slots;
		for (let i = 0; i < slots.length; i++) {
			const slotData = { name: this.readString() };
			slotData.bone = this.json.bones[this.readInt(true)].name;
			slotData.color = this.readColor();
			slotData.attachment = this.readString();
			slotData.blend = BLEND_MODE[this.readInt(true)];
			slots[i] = slotData;
		}

		// Skin default.
		this.json.skins = {};
		this.json.skinsName = [];
		const skins = this.json.skins;
		const defaultSkin = this.readSkin("default", nonessential);
		if (defaultSkin !== null) {
			skins.default = defaultSkin;
			this.json.skinsName.push("default");
		}

		// Skin lain.
		const skinCount = this.readInt(true);
		for (let i = 0; i < skinCount; i++) {
			const skinName = this.readString();
			const skin = this.readSkin(skinName, nonessential);
			skins[skinName] = skin;
			// Aslinya mendorong string literal "skinName" — salah ketik yang
			// bikin skinsName berisi nama yang sama berulang kali. Konverter
			// kita tidak memakai skinsName, jadi tidak merusak apa pun, tapi
			// diperbaiki supaya tidak menyesatkan siapa pun yang membacanya.
			this.json.skinsName.push(skinName);
		}

		// Event.
		this.json.events = {};
		this.json.eventsName = [];
		const events = this.json.events;
		const eventCount = this.readInt(true);
		for (let i = 0; i < eventCount; i++) {
			const eventName = this.readString();
			const event = {};
			event.int = this.readInt(false);
			event.float = this.readFloat();
			event.string = this.readString();
			events[eventName] = event;
			this.json.eventsName[i] = eventName;
		}

		// Animasi.
		this.json.animations = {};
		const animations = this.json.animations;
		const animCount = this.readInt(true);
		for (let i = 0; i < animCount; i++) {
			const animationName = this.readString();
			animations[animationName] = this.readAnimation(animationName);
		}
	}

	readSkin(skinName, nonessential) {
		const slotCount = this.readInt(true);
		if (slotCount === 0) return null;
		const skin = {};
		// Urutan lampiran per slot, sesuai kemunculannya di berkas.
		// Diperlukan bagian FFD: ia menyebut lampiran berdasar URUTAN, bukan
		// nama (lihat catatan di readAnimation). Disimpan berdasar indeks
		// slot supaya FFD bisa menemukannya lagi.
		const order = (this.attachOrder = this.attachOrder || {});
		for (let i = 0; i < slotCount; i++) {
			const slotIndex = this.readInt(true);
			const slot = {};
			const attachCount = this.readInt(true);
			const list = [];
			for (let j = 0; j < attachCount; j++) {
				const name = this.readString();
				const att = this.readAttachment(name, nonessential);
				slot[name] = att;
				list.push(att);
			}
			order[slotIndex] = list;
			skin[this.json.slots[slotIndex].name] = slot;
		}
		return skin;
	}

	readAttachment(attachmentName, nonessential) {
		let name = this.readString();
		if (name === null) name = attachmentName;

		switch (ATTACHMENT_TYPE[this.readByte()]) {
			case "region": {
				let path = this.readString();
				if (path === null) path = name;
				const region = {
					type: "region", name, path,
					x: this.readFloat() * this.scale,
					y: this.readFloat() * this.scale,
					scaleX: this.readFloat(),
					scaleY: this.readFloat(),
					rotation: this.readFloat(),
					width: this.readFloat() * this.scale,
					height: this.readFloat() * this.scale,
					color: this.readColor(),
				};
				return region;
			}
			case "boundingbox": {
				const box = {
					type: "boundingbox", name,
					vertices: this.readFloatArray(),
				};
				return box;
			}
			case "mesh": {
				let path = this.readString();
				if (path === null) path = name;
				const mesh = {
					type: "mesh", name, path,
					uvs: this.readFloatArray(),
					triangles: this.readShortArray(),
					vertices: this.readFloatArray(),
					color: this.readColor(),
					hull: this.readInt(true),
				};
				if (nonessential) {
					mesh.edges = this.readIntArray();
					mesh.width = this.readFloat();
					mesh.height = this.readFloat();
				}
				return mesh;
			}
			case "skinnedmesh": {
				let path = this.readString();
				if (path === null) path = name;
				const mesh = {
					type: "skinnedmesh", name, path,
					uvs: this.readFloatArray(),
					triangles: this.readShortArray(),
					color: this.readColor(),
				};

				// Format berbobot: untuk tiap vertex, [boneCount, lalu
				// boneCount x (boneIndex, x, y, weight)]. Inilah juga format
				// yang dipakai 3.8 untuk mesh berbobot, jadi konverter
				// tinggal menyalin — yang penting runtime tahu ini berbobot,
				// dan 3.8 menyimpulkannya dari vertices.length != uvs.length.
				const vertexCount = this.readInt(true);
				const vertices = [];
				let i = 0;
				while (i < vertexCount) {
					const boneCount = Math.floor(this.readFloat());
					vertices.push(boneCount);
					i++;
					for (let b = 0; b < boneCount; b++) {
						vertices.push(Math.floor(this.readFloat()));
						vertices.push(this.readFloat());
						vertices.push(this.readFloat());
						vertices.push(this.readFloat());
					}
					i += boneCount * 4;
				}
				mesh.vertices = vertices;
				mesh.hull = this.readInt(true);
				if (nonessential) {
					mesh.edges = this.readIntArray();
					mesh.width = this.readFloat();
					mesh.height = this.readFloat();
				}
				return mesh;
			}
		}
		return null;
	}

	// ------------------------------------------------------------ animasi --

	readCurve(frameIndex, timeline) {
		switch (this.readByte()) {
			case 1: // CURVE_STEPPED
				timeline[frameIndex].curve = "stepped";
				break;
			case 2: { // CURVE_BEZIER
				const cx1 = this.readFloat();
				const cy1 = this.readFloat();
				const cx2 = this.readFloat();
				const cy2 = this.readFloat();
				timeline[frameIndex].curve = [cx1, cy1, cx2, cy2];
				break;
			}
		}
	}

	readAnimation(name) {
		const animation = {};
		const scale = this.scale;
		let duration = 0;

		// Timeline slot.
		const slots = {};
		const slotTimelineCount = this.readInt(true);
		for (let i = 0; i < slotTimelineCount; i++) {
			const slotIndex = this.readInt(true);
			const slotMap = {};
			const timeCount = this.readInt(true);
			for (let ii = 0; ii < timeCount; ii++) {
				const timelineType = this.readByte();
				const frameCount = this.readInt(true);
				switch (timelineType) {
					case 4: { // TIMELINE_COLOR
						const timeline = new Array(frameCount);
						for (let f = 0; f < frameCount; f++) {
							timeline[f] = { time: this.readFloat(), color: this.readColor() };
							if (f < frameCount - 1) this.readCurve(f, timeline);
						}
						slotMap.color = timeline;
						duration = Math.max(duration, timeline[frameCount - 1].time);
						break;
					}
					case 3: { // TIMELINE_ATTACHMENT
						const timeline = new Array(frameCount);
						for (let f = 0; f < frameCount; f++) {
							timeline[f] = { time: this.readFloat(), name: this.readString() };
						}
						slotMap.attachment = timeline;
						duration = Math.max(duration, timeline[frameCount - 1].time);
						break;
					}
				}
			}
			slots[this.json.slots[slotIndex].name] = slotMap;
		}
		animation.slots = slots;

		// Timeline bone.
		const bones = {};
		const boneTimelineCount = this.readInt(true);
		for (let i = 0; i < boneTimelineCount; i++) {
			const boneIndex = this.readInt(true);
			const boneMap = {};
			const timeCount = this.readInt(true);
			for (let ii = 0; ii < timeCount; ii++) {
				const timelineType = this.readByte();
				const frameCount = this.readInt(true);
				switch (timelineType) {
					case 1: { // TIMELINE_ROTATE
						const timeline = new Array(frameCount);
						for (let f = 0; f < frameCount; f++) {
							timeline[f] = { time: this.readFloat(), angle: this.readFloat() };
							if (f < frameCount - 1) this.readCurve(f, timeline);
						}
						boneMap.rotate = timeline;
						duration = Math.max(duration, timeline[frameCount - 1].time);
						break;
					}
					case 0: // TIMELINE_SCALE
					case 2: { // TIMELINE_TRANSLATE
						const timeline = new Array(frameCount);
						// translate ikut skala, scale tidak (skala sudah
						// relatif terhadap bone).
						const timelineScale = timelineType === 2 ? scale : 1;
						for (let f = 0; f < frameCount; f++) {
							timeline[f] = {
								time: this.readFloat(),
								x: this.readFloat() * timelineScale,
								y: this.readFloat() * timelineScale,
							};
							if (f < frameCount - 1) this.readCurve(f, timeline);
						}
						if (timelineType === 0) boneMap.scale = timeline;
						else boneMap.translate = timeline;
						duration = Math.max(duration, timeline[frameCount - 1].time);
						break;
					}
					case 5: // TIMELINE_FLIPX
					case 6: { // TIMELINE_FLIPY
						const timeline = new Array(frameCount);
						for (let f = 0; f < frameCount; f++) {
							const t = { time: this.readFloat() };
							const flip = this.readBoolean();
							if (timelineType === 5) t.x = flip;
							else t.y = flip;
							timeline[f] = t;
						}
						if (timelineType === 5) boneMap.flipX = timeline;
						else boneMap.flipY = timeline;
						duration = Math.max(duration, timeline[frameCount - 1].time);
						break;
					}
				}
			}
			bones[this.json.bones[boneIndex].name] = boneMap;
		}
		animation.bones = bones;

		// Timeline IK.
		const ik = {};
		const ikTimelineCount = this.readInt(true);
		for (let i = 0; i < ikTimelineCount; i++) {
			const ikIndex = this.readInt(true);
			const frameCount = this.readInt(true);
			const timeline = new Array(frameCount);
			for (let f = 0; f < frameCount; f++) {
				timeline[f] = {
					time: this.readFloat(),
					mix: this.readFloat(),
					bendPositive: this.readBoolean(),
				};
				if (f < frameCount - 1) this.readCurve(f, timeline);
			}
			// Nama constraint disimpan di timeline, karena format 3.8
			// mengharapkan tiap timeline IK menyebut constraint-nya sendiri.
			// Aslinya menjadikan OBJEK constraint sebagai kunci, yang
			// menghasilkan "[object Object]".
			timeline.name = this.json.ik[ikIndex].name;
			ik[timeline.name] = timeline;
		}
		animation.ik = ik;

		// Timeline FFD (free-form deformation).
		const ffd = {};
		const skinCount = this.readInt(true);
		for (let i = 0; i < skinCount; i++) {
			const skinIndex = this.readInt(true);
			const slotMap = {};
			const slotCount = this.readInt(true);
			for (let ii = 0; ii < slotCount; ii++) {
				const slotIndex = this.readInt(true);
				const meshMap = {};
				const meshCount = this.readInt(true);
				for (let iii = 0; iii < meshCount; iii++) {
					const meshName = this.readString();
					const frameCount = this.readInt(true);

					// Nama lampiran TIDAK bisa dipakai untuk mencari
					// lampirannya: di 2.x nama lampiran sering berbeda dari
					// kunci yang dipakai skin. Yang dipakai adalah URUTAN:
					// FFD menulis lampiran sesuai urutan kemunculannya di
					// skin, jadi indeks ke-N di sini = lampiran ke-N di slot
					// itu. Terbukti pada 1001_Event_CG11: mencari berdasar
					// nama menghasilkan found=false untuk SEMUA 17 slot,
					// sedangkan urutannya cocok persis (Chest(L), Chest(R),
					// Foot(L), LegCalf(L), LegCalf(R), LegThigh(L),
					// LegThigh(R), MoniterA, MoniterB, MoniterC, Mouth,
					// Nipple(L), ..., Semen, water, water_drop,
					// water_ground) — dan offset string yang dihasilkan
					// persis sama dengan posisi string di berkas mentah.
					const order = (this.attachOrder || {})[slotIndex] || [];
					const attachment = order[iii] || null;
					if (!attachment) {
						// Tidak fatal: lewati timeline-nya tapi TETAP baca
						// bytes-nya, atau sisa berkas jadi bergeser.
						console.warn("[spine2] lampiran FFD tidak ketemu: " + meshName);
					}

					const timeline = new Array(frameCount);
					for (let f = 0; f < frameCount; f++) {
						const time = this.readFloat();
						let vertexCount;
						if (attachment && attachment.type === "mesh") {
							vertexCount = attachment.vertices.length;
						} else {
							// Perkiraan asli untuk skinnedmesh.
							vertexCount = attachment ? attachment.uvs.length * 3 * 3 : 0;
						}

						const vertices = new Array(vertexCount).fill(0);

						// Aslinya memakai 0.1 dengan komentar "I have no idea
						// why we need this". Ini karena vertex FFD 2.x
						// disimpan sebagai SELISIH terhadap pose setup,
						// sedangkan array yang dipakai di sini sudah diisi
						// nilai pose setup — jadi nilai dasar memang harus
						// ditambahkan. Dibiarkan apa adanya: mengubahnya
						// berarti mengubah hasil render yang sudah diverifikasi
						// pemilik aslinya lewat tangkapan layar Playwright.
						const bugFixMultiplicator = 0.1;

						let end = this.readInt(true);
						if (end === 0) {
							if (attachment && attachment.type === "mesh") {
								for (let v = 0; v < vertexCount; v++) {
									vertices[v] += attachment.vertices[v] * bugFixMultiplicator;
								}
							}
						} else {
							const start = this.readInt(true);
							end += start;
							for (let v = start; v < end; v++) {
								vertices[v] = this.readFloat() * scale;
							}
							if (attachment && attachment.type === "mesh") {
								const meshVertices = attachment.vertices;
								for (let v = 0; v < vertices.length; v++) {
									vertices[v] += meshVertices[v] * bugFixMultiplicator;
								}
							}
						}
						timeline[f] = { time, vertices };
						if (f < frameCount - 1) this.readCurve(f, timeline);
					}
					meshMap[meshName] = timeline;
					duration = Math.max(duration, timeline[frameCount - 1].time);
				}
				slotMap[this.json.slots[slotIndex].name] = meshMap;
			}
			ffd[this.json.skinsName[skinIndex]] = slotMap;
		}
		animation.ffd = ffd;

		// Timeline urutan gambar.
		const drawOrderCount = this.readInt(true);
		if (drawOrderCount > 0) {
			const drawOrders = new Array(drawOrderCount);
			for (let i = 0; i < drawOrderCount; i++) {
				const offsets = new Array();
				const offsetCount = this.readInt(true);
				for (let ii = 0; ii < offsetCount; ii++) {
					const slotIndex = this.readInt(true);
					const dooffset = this.readInt(true);
					offsets.push({
						slot: this.json.slots[slotIndex].name,
						offset: dooffset,
					});
				}
				drawOrders[i] = { offsets, time: this.readFloat() };
			}
			duration = Math.max(duration, drawOrders[drawOrderCount - 1].time);
			animation.drawOrder = drawOrders;
		}

		// Format event 2.x, persis seperti yang diverifikasi pada
		// 1001_Event_CG11 (event "PlaySound" membawa "1001_LG_fast.mp3"):
		//   time=f32 | nameIndex=varint | int=zigzag varint | float=f32
		//   | hasString=bool | string=hanya bila bool itu true
		// Jika bool-nya false, string TIDAK ditulis — nilainya diambil
		// dari definisi event. Ini beda dari 3.8, yang selalu menulis int,
		// float, dan string.
		const eventCount = this.readInt(true);
		if (eventCount > 0) {
			const events = new Array(eventCount);
			for (let i = 0; i < eventCount; i++) {
				const time = this.readFloat();
				const eventName = this.json.eventsName[this.readInt(true)];
				const eventData = this.json.events[eventName] || {};
				const e = {
					name: eventName,
					int: this.readInt(false),
					float: this.readFloat(),
					string: this.readBoolean() ? this.readString() : eventData.string,
					time,
				};
				events[i] = e;
			}
			duration = Math.max(duration, events[eventCount - 1].time);
			animation.events = events;
		}

		return animation;
	}
}

/** Singkatnya: parse ArrayBuffer/Uint8Array .skel 2.x menjadi JSON 2.x. */
export function parseSpine2Skel(data, scale = 1) {
	return new SkeletonBinary2(data, scale).readSkeletonData();
}
