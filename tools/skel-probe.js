#!/usr/bin/env node
/**
 * Minimal Spine binary (.skel) reader — pulls out version, size, skins and
 * animation names without parsing the whole skeleton.
 *
 * Mirrors pixi-spine's BinaryInput (varint + zigzag + string table) so the
 * offsets match the real loader instead of a guess.
 */
"use strict";
const fs = require("fs");

class Reader {
	constructor(buf) {
		this.buf = buf;
		this.i = 0;
		this.strings = [];
	}
	byte() {
		return this.buf.readInt8(this.i++);
	}
	ubyte() {
		return this.buf.readUInt8(this.i++);
	}
	int32() {
		const v = this.buf.readInt32LE(this.i);
		this.i += 4;
		return v;
	}
	float() {
		const v = this.buf.readFloatLE(this.i);
		this.i += 4;
		return v;
	}
	/** varint, zigzag-decoded when optimizePositive is false */
	int(optimizePositive) {
		let b = this.byte();
		let result = b & 127;
		if ((b & 128) !== 0) {
			b = this.byte();
			result |= (b & 127) << 7;
			if ((b & 128) !== 0) {
				b = this.byte();
				result |= (b & 127) << 14;
				if ((b & 128) !== 0) {
					b = this.byte();
					result |= (b & 127) << 21;
					if ((b & 128) !== 0) {
						b = this.byte();
						result |= (b & 127) << 28;
					}
				}
			}
		}
		return optimizePositive ? result : (result >>> 1) ^ -(result & 1);
	}
	/** reads a string and registers it in the string table */
	readString() {
		let byteCount = this.int(true);
		if (byteCount === 0) return null;
		if (byteCount === 1) return "";
		byteCount--;
		let chars = "";
		for (let i = 0; i < byteCount; ) {
			const b = this.ubyte();
			switch (b >> 4) {
				case 0:
				case 1:
				case 2:
				case 3:
				case 4:
				case 5:
				case 6:
				case 7:
					chars += String.fromCharCode(b);
					i += 1;
					break;
				case 12:
				case 13:
					chars += String.fromCharCode(((b & 0x1f) << 6) | (this.ubyte() & 0x3f));
					i += 2;
					break;
				case 14:
					chars += String.fromCharCode(
						((b & 0x0f) << 12) | ((this.ubyte() & 0x3f) << 6) | (this.ubyte() & 0x3f)
					);
					i += 3;
					break;
				default:
					i += 1;
					break;
			}
		}
		this.strings.push(chars);
		return chars;
	}
	stringArray() {
		const n = this.int(true);
		const out = [];
		for (let i = 0; i < n; i++) out.push(this.readString());
		return out;
	}
}

function probe(file) {
	const buf = fs.readFileSync(file);
	const r = new Reader(buf);
	r.int32(); // hash low
	r.int32(); // hash high
	const version = r.readString();
	r.float(); // x
	r.float(); // y
	const width = r.float();
	const height = r.float();
	r.stringArray(); // bones
	r.stringArray(); // slots
	r.stringArray(); // ik constraints
	r.stringArray(); // transform constraints
	r.stringArray(); // path constraints
	const skins = r.stringArray();
	r.stringArray(); // events
	const animations = r.stringArray();
	return {
		spine: version,
		width,
		height,
		skins: skins.filter((s) => s != null),
		animations: animations.filter((a) => a != null),
	};
}

module.exports = { probe, Reader };

if (require.main === module) {
	for (const f of process.argv.slice(2)) {
		try {
			const r = probe(f);
			console.log(`\n${f}`);
			console.log(`  spine  : ${r.spine}`);
			console.log(`  size   : ${r.width} x ${r.height}`);
			console.log(`  skins  : ${r.skins.length} -> ${r.skins.slice(0, 5).join(", ")}`);
			console.log(`  anims  : ${r.animations.length} -> ${r.animations.slice(0, 10).join(", ")}`);
		} catch (e) {
			console.log(`\n${f}\n  ERROR: ${e.message}`);
		}
	}
}
