/**
 * Construction of the model-library payloads.
 *
 * The full `/api/models` response is tens of MB (34 MB at 46k models before
 * the game cleanup): JSON.stringify and JSON.parse both scale with
 * character count, so shipping every field to every visitor is the single
 * most expensive thing the app does at boot. Most of those fields are only
 * read once a model is actually opened on the stage (skeleton/atlas filenames,
 * animation name lists, skin lists, byte sizes, …).
 *
 * So there are two shapes:
 *   - lean  (`?lean=1`): everything the library needs to draw cards, group
 *     games, search, switch variants and show badges.
 *   - full  (default): unchanged, kept for compatibility and for callers that
 *     really want every field.
 * and `GET /api/models/:id` hands back one full record when a model is opened.
 *
 * Both bodies, their ETags and their gzip bytes are cached per scan signature;
 * a rescan invalidates everything at once. Extracted out of server.js so the
 * route handlers stay about HTTP, not about stringify/compress bookkeeping.
 */
const crypto = require("crypto");
const zlib = require("zlib");
const { promisify } = require("util");

const gzipAsync = promisify(zlib.gzip);

/**
 * Fields read only on the load path. Kept as a DENY list on purpose: a field
 * added to scanModels() later still shows up in the lean index by default,
 * instead of silently disappearing from the library.
 *
 * `animations` is replaced by `animCount` — the list card only shows a count,
 * while the Live2D motion picker needs the real names (available in detail).
 */
const DETAIL_FIELDS = new Set([
	"files", "skeletonFile", "atlasFile", "atlasPages", "textureFiles",
	"animations", "skins", "bones", "slots", "size", "motionFiles", "expressions",
	"spine", "runtime", "spineRuntime", "needsLegacyViewer", "needsProbe",
	"pmaDefault", "bytes", "group", "subgroup",
	// CherryTale: timeline fase + voice hanya dipakai setelah model dibuka.
	"ctScene", "audio",
	// Ark Re:Code: state kamera LoveTalk, juga hanya untuk detail.
	"loveTalk",
]);

/** Compact copy of one model for the library index. */
function leanModel(model) {
	const out = {};
	for (const key of Object.keys(model)) {
		if (!DETAIL_FIELDS.has(key)) out[key] = model[key];
	}
	out.animCount = (model.animations || []).length;
	return out;
}

let store = { signature: "", entries: new Map() };

/**
 * Cached {body, etag, gzPromise} for one shape of the current model list.
 * Both shapes can coexist; a new scan signature drops both.
 */
function payloadFor(models, signature, lean) {
	const sig = `${signature}:${models.length}`;
	if (store.signature !== sig) store = { signature: sig, entries: new Map() };
	const key = lean ? "lean" : "full";
	let payload = store.entries.get(key);
	if (payload) return payload;
	const body = JSON.stringify({ models: lean ? models.map(leanModel) : models });
	payload = {
		body,
		etag: `W/"${body.length.toString(36)}-${crypto.createHash("sha1").update(body).digest("base64url").slice(0, 27)}"`,
		gzPromise: null,
	};
	store.entries.set(key, payload);
	return payload;
}

/** Shared promise so concurrent requests never gzip the same body twice. */
function gzipFor(payload) {
	if (!payload.gzPromise) payload.gzPromise = gzipAsync(payload.body, { level: 6 });
	return payload.gzPromise;
}

let indexStore = { signature: "", map: null };

/** id -> full model, rebuilt only when the scan signature changes. */
function modelIndex(models, signature) {
	const sig = `${signature}:${models.length}`;
	if (indexStore.signature !== sig || !indexStore.map) {
		indexStore = { signature: sig, map: new Map(models.map((m) => [m.id, m])) };
	}
	return indexStore.map;
}

module.exports = { leanModel, payloadFor, gzipFor, modelIndex };
