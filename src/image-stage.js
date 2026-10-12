/**
 * Image stage — shows plain CG / illust stills (no skeleton, no atlas).
 *
 * 深蓝终末录 ships its 2D CG art as flat PNGs (extracted by
 * tools/shenlan/extract-shenlan-cg.py); other games may add a "<game>-cg"
 * folder the same way. Those have nothing for pixi-spine to draw, so they get
 * their own tiny renderer: an overlay <img> that covers the PIXI canvas (hidden
 * via the `is-image` class on the wrap). Kept framework-free — the viewer's
 * Spine timeline and skin dropdowns are simply disabled for this format.
 */

let host = null;
let img = null;

/** Is the image stage the thing currently on screen? */
export function imageStageActive() {
	return !!img;
}

/** The live <img> element, or null. */
export function imageElement() {
	return img;
}

/** Tear the overlay down (called before loading any other model). */
export function disposeImage() {
	if (img) {
		img.removeAttribute("src");
		img.remove();
		img = null;
	}
	if (host) {
		host.classList.remove("is-image");
		host = null;
	}
}

/**
 * Mount `url` as a still on the stage. Any previous image is replaced.
 * Resolves once the bitmap has decoded (so the HUD can show its real size).
 * Returns the <img> element so the caller can wire error handlers.
 */
export function loadImage({ wrap, url }) {
	disposeImage();
	host = wrap;
	host.classList.add("is-image");

	img = document.createElement("img");
	img.className = "image-stage";
	img.decoding = "async";
	img.alt = "";
	return new Promise((resolve, reject) => {
		img.addEventListener("load", () => resolve(img), { once: true });
		img.addEventListener("error", () => reject(new Error("Gagal memuat gambar: " + url)), { once: true });
		img.src = url;
		host.appendChild(img);
	});
}
