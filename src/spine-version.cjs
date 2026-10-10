"use strict";

/**
 * Spine version detection (CommonJS twin of src/spine-version.js).
 *
 * The runtime's own `data.version` is NOT trustworthy for files it can't
 * parse: reading a 3.8.99 skeleton with the 4.1 runtime returns a garbage
 * string pulled from the wrong offset, which surfaced in the UI as a version
 * like "jCsuDWsJ3kO2LTEQ+VY...". So the server sniffs the version from the
 * raw bytes using the same logic the browser uses.
 */

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

/** True when we have a renderer for this version (2.x legacy, 3.x/4.x pixi-spine). */
function supported(v) {
	return !!v && v.major >= MIN_MAJOR && v.major <= MAX_MAJOR;
}

/** Pick the runtime that can read this version. */
function pickRuntime(version) {
	if (!version) return "4.1";
	const { major, minor } = version;
	// 2.x has no pixi-spine runtime at all — those models are rendered by the
	// vendored legacy viewer, so the caller must check for this value.
	if (major < 3) return "legacy-2.1.27";
	if (major === 3 && minor <= 7) return "3.8"; // 3.7 has no SkeletonBinary
	if (major === 3 && minor === 8) return "3.8";
	if (major === 4 && minor === 0) return "4.0";
	// 4.3 needs the genuine 4.3 runtime (the 4.2 core predates the 4.3 binary
	// layout). 4.2 needs its own too: 4.1 predates it.
	if (major === 4 && minor >= 3) return "4.3";
	if (major === 4 && minor === 2) return "4.2";
	if (major === 4) return "4.1";
	if (major < 3) return "3.8";
	return "4.1";
}

function detectFromJson(json) {
	try {
		const v = json && json.skeleton && json.skeleton.spine;
		return v ? parseVersion(v) : null;
	} catch {
		return null;
	}
}

/**
 * Version from a Spine .skel binary.
 *
 * Canonical layout is [len][version ascii], but Azur Lane prepends its own
 * header, so we scan for a length-prefixed digits/dots run and accept only a
 * known Spine major. A loose regex alone produced false positives like "4.3.8"
 * read out of the hash prefix.
 */
function detectFromBinary(bytes) {
	if (!bytes || bytes.length < 4) return null;

	const MAX_SCAN = 512;
	const limit = Math.min(bytes.length, MAX_SCAN);

	// Fast path: plain ASCII version string with no length prefix.
	// Azur Lane puts "3.8.99" at offset 29 with no prefix byte, so a
	// length-prefixed-only scan finds nothing there.
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

	// Canonical layout: [len][version ascii].
	for (let off = 0; off < limit - 2; off++) {
		const len = bytes[off];
		if (len < 4 || len > 16) continue;
		if (off + 1 + len > bytes.length) break;
		let s = "";
		let ok = true;
		for (let i = 1; i <= len; i++) {
			const c = bytes[off + i];
			if (!((c >= 48 && c <= 57) || c === 46)) { ok = false; break; }
			s += String.fromCharCode(c);
		}
		if (!ok) continue;
		const v = parseVersion(s);
		if (supported(v) && /^\d+\.\d+(\.\d+)?$/.test(s)) return v;
	}

	let buf = "";
	for (let i = 0; i < limit; i++) {
		const c = bytes[i];
		buf += c >= 32 && c < 127 ? String.fromCharCode(c) : "\n";
	}
	const all = buf.match(/\d+\.\d+(?:\.\d+)?/g) || [];
	for (const cand of all) {
		const v = parseVersion(cand);
		if (supported(v) && /\.\d/.test(cand)) return v;
	}
	return null;
}

module.exports = { parseVersion, pickRuntime, detectFromJson, detectFromBinary };
