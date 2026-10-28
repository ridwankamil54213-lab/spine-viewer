"use strict";

/**
 * Spine version detection — SINGLE SOURCE for both sides.
 *
 * The server (src/server.js, CommonJS `require`) and the viewer
 * (src/viewer.js, ESM `import` bundled by esbuild) both use this file. It
 * used to exist twice — spine-version.js and spine-version.cjs — with a
 * comment in each claiming to be "kept in sync" with the other. Nothing
 * enforced that, and the copies had already begun to drift; a fix landing in
 * one would silently miss the other. esbuild happily consumes CommonJS, so
 * one file does the job.
 *
 * Why we sniff the header at all: the runtime's own `data.version` is NOT
 * trustworthy for files it can't parse. Reading a 3.8.99 skeleton with the
 * 4.1 runtime returns a garbage string pulled from the wrong offset, which
 * surfaced in the UI as a version like "jCsuDWsJ3kO2LTEQ+VY...".
 */

/** Major.minor (and optional patch) pulled out of a candidate version string. */
function parseVersion(str) {
	if (typeof str !== "string") return null;
	const m = str.match(/(\d+)\.(\d+)(?:[.](\d+))?/);
	if (!m) return null;
	return { major: +m[1], minor: +m[2], patch: m[3] ? +m[3] : 0, raw: m[0] };
}

/**
 * Spine versions this viewer can handle, across BOTH renderers:
 *   2.x  -> vendored legacy viewer (pixi-spine has no 2.x runtime)
 *   3.x+ -> pixi-spine runtimes
 * The original range was 3..4 only, which made Spine 2.1.27 files detect as
 * "unknown" and get reported as broken models instead of routed to the
 * legacy viewer.
 */
const MIN_MAJOR = 2;
const MAX_MAJOR = 4;

/** True when we have a renderer for this version (2.x legacy, 3.x and 4.x pixi-spine). */
function supported(v) {
	return !!v && v.major >= MIN_MAJOR && v.major <= MAX_MAJOR;
}

/**
 * Pick the runtime that can read this version.
 *
 * Each Spine runtime reads its own major.minor and refuses anything newer
 * than itself, so pick the SMALLEST runtime that is >= the file's version,
 * except 3.x<=7 which has no binary loader and maps onto 3.8.
 *
 * Callers must keep their runtime table in step with the keys returned here.
 * That linkage has already broken once: this function returned "4.3" while
 * server.js's RUNTIMES table stopped at "4.2", so every 4.3 file fell through
 * to an older runtime and landed in the cache with no metadata at all.
 */
function pickRuntime(version) {
	if (!version) return "4.1"; // unknown -> current default
	const { major, minor } = version;

	// 2.x has no pixi-spine runtime at all — those models are rendered by the
	// vendored legacy viewer, so the caller must check for this value.
	if (major < 3) return "legacy-2.1.27";
	if (major === 3 && minor <= 7) return "3.8"; // 3.7 has no SkeletonBinary
	if (major === 3 && minor === 8) return "3.8";
	if (major === 4 && minor === 0) return "4.0";
	// 4.3 needs the genuine 4.3 runtime: the 4.2 core predates the 4.3 binary
	// layout (it never gets past readString on the header). 4.2 needs its own
	// too: 4.1 predates it.
	if (major === 4 && minor >= 3) return "4.3";
	if (major === 4 && minor === 2) return "4.2";
	if (major === 4) return "4.1";
	return "4.1";
}

/** Version straight out of a Spine .json skeleton. */
function detectFromJson(json) {
	try {
		const v = json && json.skeleton && json.skeleton.spine;
		return v ? parseVersion(v) : null;
	} catch {
		return null;
	}
}

/**
 * Version out of a Spine .skel binary.
 *
 * The canonical layout is [varint len][version ascii]. Some games (Azur Lane)
 * prepend their own header, so we fall back to a bounded regex scan for an
 * "x.y.z" ascii run in the first few hundred bytes.
 */
function detectFromBinary(bytes) {
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
		// a version string is short ("4.3.39" is 6 bytes); anything longer is
		// not a length prefix, and 0 would match every zero byte in the file.
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
	for (const cand of all) {
		const v = parseVersion(cand);
		// only trust major.minor.patch where major is a real Spine major
		if (supported(v) && /\.\d/.test(cand)) return v;
	}
	return null;
}

/**
 * Detect from either kind of payload.
 *
 * `raw` for JSON may be a RAW STRING/BUFFER (that is how the viewer calls it:
 * the skeleton file's bytes verbatim) or an already-parsed object. An older
 * version always treated it as an object, so `json?.skeleton?.spine` was
 * always undefined and the result always null — every JSON skeleton lost its
 * version and was rendered with the default 4.1 runtime. 3.8 models from
 * e7codex broke because of that.
 */
function detectSpineVersion({ isBinary, raw }) {
	if (isBinary) return detectFromBinary(raw);
	if (raw && typeof raw === "object" && !(raw instanceof Uint8Array)) {
		return detectFromJson(raw);
	}
	// String / ArrayBuffer / Uint8Array: parse first, then read the version.
	// A parse failure is not fatal — return null so the caller uses the
	// default runtime.
	try {
		const text =
			typeof raw === "string"
				? raw
				: new TextDecoder().decode(raw instanceof Uint8Array ? raw : new Uint8Array(raw));
		return detectFromJson(JSON.parse(text));
	} catch {
		return null;
	}
}

// Both callers import the same names; module.exports serves `require`, and
// the named re-exports below let esbuild resolve `import { ... }` from it.
module.exports = {
	parseVersion,
	pickRuntime,
	supported,
	detectFromJson,
	detectFromBinary,
	detectSpineVersion,
};
