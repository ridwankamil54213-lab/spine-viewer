/**
 * Spine version detection + runtime dispatch.
 *
 * Spine Stage originally hard-coded the 4.1 runtime, so any model exported by
 * an older Spine editor (3.7/3.8/4.0) failed with "Spine 4.1 loader cant load
 * version ...". The runtimes all expose the same API surface, so we sniff the
 * version from the file itself and hand the data to the matching parser.
 *
 * Detection, in order of reliability:
 *   .json  -> read the "skeleton.spine" field. Cheap and exact.
 *   .skel  -> the binary header is a length-prefixed version string:
 *               [ varint length ][ version ascii ][ ... ]
 *             Azur Lane bundles prepend a custom prefix (their files carry a
 *             hash + a 1-byte length), so we scan for the "major.minor.patch"
 *             pattern near the start rather than assuming offset 0.
 */

export const SPINE_RUNTIMES = ["3.7", "3.8", "4.0", "4.1"];

/** Major.minor (and optional patch) pulled out of a candidate version string. */
export function parseVersion(str) {
	if (typeof str !== "string") return null;
	const m = str.match(/(\d+)\.(\d+)(?:\.(\d+))?/);
	if (!m) return null;
	return { major: +m[1], minor: +m[2], patch: m[3] ? +m[3] : 0, raw: m[0] };
}

/**
 * Spine versions this viewer can handle, across BOTH renderers:
 *   2.x  -> vendored legacy viewer (pixi-spine has no 2.x runtime)
 *   3.x+ -> pixi-spine runtimes
 * Kept in sync with the CommonJS twin in spine-version.cjs.
 */
const MIN_MAJOR = 2;
const MAX_MAJOR = 4;

/** True when we have a renderer for this version. */
function supported(v) {
	return !!v && v.major >= MIN_MAJOR && v.major <= MAX_MAJOR;
}

/**
 * Pick the runtime that can read this version.
 * Each Spine runtime reads its own major.minor and, importantly, refuses
 * anything newer than itself — so pick the SMALLEST runtime >= the file,
 * except 3.7 which has no binary loader and maps onto 3.8.
 */
export function pickRuntime(version) {
	if (!version) return "4.1"; // unknown -> current default
	const { major, minor } = version;

	// 2.x has no pixi-spine runtime at all — those models are rendered
	// by the vendored legacy viewer.
	if (major < 3) return "legacy-2.1.27";
	if (major === 3 && minor <= 7) return "3.8"; // 3.7 has no SkeletonBinary
	if (major === 3 && minor === 8) return "3.8";
	if (major === 4 && minor === 0) return "4.0";
	if (major === 4) return "4.1";
	if (major < 3) return "3.8";
	return "4.1";
}

/** Version straight out of a Spine .json skeleton. */
export function detectFromJson(json) {
	try {
		const v = json?.skeleton?.spine;
		return v ? parseVersion(v) : null;
	} catch {
		return null;
	}
}

/**
 * Version out of a Spine .skel binary.
 *
 * The canonical layout is [varint len][version ascii]. Some games (Azur Lane)
 * prepend their own header, so we fall back to a bounded regex scan for a
 * "x.y.z" ascii run in the first few hundred bytes.
 */
export function detectFromBinary(bytes) {
	if (!bytes || bytes.length < 4) return null;

	const MAX_SCAN = 512;
	const limit = Math.min(bytes.length, MAX_SCAN);

	// Fast path: a plain ASCII version string with no length prefix.
	// Azur Lane's .skel files put "3.8.99" at offset 29 with no prefix byte,
	// so a length-prefixed-only scan finds nothing and we fall through to
	// trying every runtime (which logs a console error per attempt).
	let run = "";
	for (let i = 0; i < limit; i++) {
		const c = bytes[i];
		if ((c >= 48 && c <= 57) || c === 46) {
			run += String.fromCharCode(c);
		} else {
			if (run.length >= 4 && /^\d+\.\d+(\.\d+)?$/.test(run)) {
				const v = parseVersion(run);
				if (supported(v)) return v;
			}
			run = "";
		}
	}
	if (run.length >= 4 && /^\d+\.\d+(\.\d+)?$/.test(run)) {
		const v = parseVersion(run);
		if (supported(v)) return v;
	}

	// Canonical layout: [varint len][version ascii].
	for (let off = 0; off < limit - 2; off++) {
		const len = bytes[off];
		// a version string is short; anything longer is not a length prefix
		if (len < 4 || len > 16) continue;
		if (off + 1 + len > bytes.length) break;
		let s = "";
		let ok = true;
		for (let i = 1; i <= len; i++) {
			const c = bytes[off + i];
			// version strings are digits and dots only
			if (!((c >= 48 && c <= 57) || c === 46)) { ok = false; break; }
			s += String.fromCharCode(c);
		}
		if (!ok) continue;
		const v = parseVersion(s);
		// only accept a known Spine major, and require at least major.minor
		if (supported(v) && /^\d+\.\d+(\.\d+)?$/.test(s)) return v;
	}

	// Fallback: loose scan. Deliberately strict — a random "4.3.8" buried in a
	// hash prefix is NOT a version, and guessing wrong makes the loader reject
	// a perfectly good file (observed: 3.8.99 misread as 4.3.8).
	let buf = "";
	for (let i = 0; i < limit; i++) {
		const c = bytes[i];
		buf += c >= 32 && c < 127 ? String.fromCharCode(c) : "\n";
	}
	const all = buf.match(/\d+\.\d+(?:\.\d+)?/g) || [];
	// only trust major.minor.patch where major is a real Spine major
	for (const cand of all) {
		const v = parseVersion(cand);
		if (supported(v) && /\.\d/.test(cand)) return v;
	}
	return null;
}

/** Convenience: detect from either kind of payload. */
export function detectSpineVersion({ isBinary, raw }) {
	if (!isBinary) return detectFromJson(raw);
	return detectFromBinary(raw);
}
