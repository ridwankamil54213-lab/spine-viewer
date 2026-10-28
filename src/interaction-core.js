/**
 * Mesin interaksi CrossCore — port dari ArtHub
 * (crosscore-interaction/viewer/core.mjs, 41 baris, tanpa dependensi).
 *
 * Sumber asli tidak diubah logikanya; yang ditambah hanya komentar dan
 * ekspor tambahan supaya bisa dipakai dari viewer ini.
 *
 * Konsepnya sederhana tapi kuat: setiap aksi punya satu atau beberapa
 * "area" berupa kotak yang boleh berotasi, dinyatakan dalam koordinat
 * model:
 *
 *      [cx, cy, w, h, degrees]
 *
 * Titik sentuh diuji dengan memutar balik titik itu ke kerangka kotak,
 * lalu membandingkan setengah lebar/tinggi. Koordinat y model Spine
 * menghadap ke atas, jadi pemanggil harus sudah membalik sumbu y.
 */

/** Uji satu titik terhadap satu area berotasi. */
export function pointInArea(x, y, area) {
	const [cx, cy, w, h, degrees] = area;
	const angle = (degrees * Math.PI) / 180;
	const dx = x - cx;
	const dy = y - cy;
	const localX = dx * Math.cos(angle) + dy * Math.sin(angle);
	const localY = -dx * Math.sin(angle) + dy * Math.cos(angle);
	return w > 0 && h > 0 && Math.abs(localX) <= w / 2 && Math.abs(localY) <= h / 2;
}

/**
 * State machine aksi.
 *
 * `model` = { actions: [...], idle: "nama_animasi" }
 *
 * Tiap aksi: { index, sName, sType, areas, audioId, content, ... }
 * `content` bisa berisi:
 *   activation : { targetIndex: 0|1 }  -> menyalakan/mematikan aksi lain
 *   changeIdle : [namaAnimasi, delayMs] -> ganti idle setelah aksi selesai
 *   clicks     : [progress1, progress2] -> aksi dua tahap (guide)
 *   isHide     : true -> aksi tidak aktif sejak awal
 *
 * Callback `onEvent` menerima objek { kind, ... } dan dipakai UI untuk
 * memutar animasi/audio.
 */
export class InteractionController {
	constructor(model, onEvent = () => {}, isBodyBusy = () => false) {
		this.model = model;
		this.onEvent = onEvent;
		this.isBodyBusy = isBodyBusy;
		this.reset();
	}

	reset() {
		this.active = new Map(
			(this.model.actions || []).map((a) => [a.index, a.sName !== "in" && !a.content?.isHide])
		);
		this.idle = this.model.idle;
		this.cooldownUntil = 0;
		this.pendingIdle = null;
		this.guide = null;
		this.events = [];
	}

	emit(event) {
		this.events.push(event);
		this.onEvent(event);
		return event;
	}

	/** Aksi mana yang kena di titik (x, y)? Aksi terakhir menang. */
	hit(x, y) {
		return (
			[...(this.model.actions || [])]
				.reverse()
				.find(
					(a) =>
						this.active.get(a.index) &&
						(a.areas || []).some((area) => pointInArea(x, y, area))
				) || null
		);
	}

	tick(now) {
		if (this.pendingIdle && now >= this.pendingIdle.at) {
			this.idle = this.pendingIdle.name;
			this.pendingIdle = null;
			this.emit({ kind: "idle", name: this.idle });
		}
	}

	trigger(index, now) {
		this.tick(now);
		const a = (this.model.actions || []).find((x) => x.index === index);
		if (!a || !this.active.get(index)) {
			return this.emit({ kind: "ignored", reason: "inactive", index });
		}
		if (now < this.cooldownUntil) {
			return this.emit({ kind: "ignored", reason: "cooldown", index });
		}
		this.cooldownUntil = now + 0.5; // detik

		const track = a.sType < 6 ? 1 : (a.content?.trackIndex ?? a.index);
		if (track === 1 && this.isBodyBusy()) {
			return this.emit({ kind: "ignored", reason: "busy", index });
		}

		if (a.content?.clicks) {
			if (this.guide?.moving) {
				return this.emit({ kind: "ignored", reason: "guide-moving", index });
			}
			const phase = this.guide ? 2 : 1;
			this.guide = { index, phase, moving: true, progress: a.content.clicks[phase - 1] };
			return this.emit({
				kind: "guide",
				index,
				track,
				name: a.sName,
				phase,
				progress: this.guide.progress,
				audioIds: [],
			});
		}

		if (a.content?.activation) {
			for (const [target, value] of Object.entries(a.content.activation)) {
				this.active.set(Number(target), value === 1);
			}
		}
		if (a.content?.changeIdle) {
			this.pendingIdle = { name: a.content.changeIdle[0], at: now + a.content.changeIdle[1] / 1000 };
		}

		return this.emit({
			kind: "action",
			index,
			track,
			name: a.sName,
			audioIds: a.audioId || [],
		});
	}

	/** Dipanggil UI ketika progres animasi guide mencapai target. */
	guideReached() {
		if (this.guide?.phase === 1) this.guide.moving = false;
		else this.guide = null;
	}
}

/** Track animasi untuk sebuah aksi (sType < 6 selalu track 1 = badan). */
export function trackFor(a) {
	return a.sType < 6 ? 1 : (a.content?.trackIndex ?? a.index);
}
