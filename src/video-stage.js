/**
 * Video stage — plays Lost Sword cutscene movies (.mp4/.m4v).
 *
 * Those models are plain video files, not skeletons, so they get their own
 * renderer: an overlay <video> that covers the PIXI canvas (which is hidden via
 * the `is-video` class on the wrap). Kept deliberately tiny and framework-free
 * — a native <video> already has play/scrub/volume controls, so the viewer's
 * Spine timeline and skin dropdowns are simply disabled for this format.
 */

let host = null;
let vid = null;

/** Is the video stage the thing currently on screen? */
export function videoStageActive() {
	return !!vid;
}

/** The live <video> element, or null. */
export function videoElement() {
	return vid;
}

/** Tear the overlay down (called before loading any other model). */
export function disposeVideo() {
	if (vid) {
		try {
			vid.pause();
		} catch {
			/* ignore */
		}
		// Clearing src stops the download; leaving it would keep the network
		// busy and the decoder alive after the user moved on.
		vid.removeAttribute("src");
		try {
			vid.load();
		} catch {
			/* ignore */
		}
		vid.remove();
		vid = null;
	}
	if (host) {
		host.classList.remove("is-video");
		host = null;
	}
}

/**
 * Mount `url` as a video on the stage. Any previous video is replaced.
 * Returns the <video> element so the caller can wire HUD/error handlers.
 */
export function loadVideo({ wrap, url }) {
	disposeVideo();
	host = wrap;
	host.classList.add("is-video");

	vid = document.createElement("video");
	vid.className = "video-stage";
	vid.src = url;
	// Kontrol bawaan browser DIMATIKAN: viewer sudah punya tombol play/pause
	// sendiri dan scrub bar di panel bawah. Kontrol bawaan menutupi bagian
	// bawah kanvas (terutama untuk klip 4K) dan gayanya tidak bisa disamakan
	// dengan UI aplikasi. Klik pada video tetap ditangani lewat stage.
	vid.controls = false;
	vid.autoplay = true;
	vid.loop = true;
	vid.playsInline = true;
	vid.preload = "auto";
	// Tanpa `controls`, klik di video tidak melakukan apa pun — beberapa
	// pengguna menjangkanya untuk pause. Petakan ke play/pause.
	vid.addEventListener("click", () => {
		if (vid.paused) vid.play().catch(() => {});
		else vid.pause();
	});
	host.appendChild(vid);
	return vid;
}
