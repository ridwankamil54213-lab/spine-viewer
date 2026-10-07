#!/usr/bin/env python3
"""Rakit model Spine 极乐深渊 (Blissful Abyss, com.vmos.virtual?) untuk viewer.

Game ini Cocos2d-lua. Aset Spine di `assets/res/animation/**` disimpan sebagai:

    <base>.jn        -> spine skeleton JSON, TERENKRIPSI (subtract cipher)
    <base>.atb       -> atlas text, TERENKRIPSI
    <base>.pvr.ccz   -> tekstur, CCZ (header "CCZ!" + zlib) berisi PVR3 RGBA8888

Sebagian lagi sudah polos: <base>.atlas / <base>.png / <base>.skel.

Cipher (kunci publik dari forum, XXTEA-game cocos): plaintext[i] = cipher[i] -
key[i % len(key)], key = b"YUNMIAO2014RES".

Alur:
    untuk tiap .jn:  skeleton = dekripsi(.jn)
                     atlas    = dekripsi(.atb)  (atau baca .atlas polos)
                     tekstur  = .pvr.ccz -> CCZ -> PVR3 -> PNG
    -> assets/blissful/<base>/<base>.json + <base>.atlas + <base>.png

Halaman di atlas yang menunjuk ".pvr.ccz" ditulis ulang jadi ".png" supaya
viewer menemukannya.

Pemakaian:
    /srv/venv-spine/bin/python tools/extract-blissful.py --apk /opt/blissful/BlissfulAbyss.apk
"""
import argparse
import collections
import io
import os
import re
import struct
import sys
import zipfile
import zlib

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("BLISS_OUT", os.path.join(ROOT, "assets", "blissful"))
KEY = b"YUNMIAO2014RES"
PAGE_RE = re.compile(r"\.(pvr\.ccz|png|jpg|jpeg|webp)$", re.I)


def _log(msg):
	sys.stderr.write("[%s] %s\n" % (__import__("time").strftime("%H:%M:%S"), msg))
	sys.stderr.flush()


def decrypt(data: bytes) -> bytes:
	n = len(KEY)
	return bytes((b - KEY[i % n]) & 0xFF for i, b in enumerate(data))


def ccz_to_pvr(data: bytes) -> bytes:
	"""CCZ ("CCZ!" + 12 byte header) -> PVR mentah."""
	if data[:4] != b"CCZ!":
		raise ValueError("bukan CCZ")
	return zlib.decompress(data[16:])


def pvr_to_png(data: bytes) -> bytes:
	"""PVR3 (tak terkompresi, RGBA8888) -> PNG bytes."""
	if data[:4] != b"PVR\x03":
		raise ValueError("bukan PVR3")
	h = data[:52]
	pf = data[8:16]
	if pf[:4] != b"rgba":
		raise ValueError("pixel format tak didukung: %r" % pf)
	height, width = struct.unpack("<II", h[24:32])
	off = 52
	n = width * height * 4
	raw = data[off:off + n]
	return _png_from_rgba(raw, width, height)


def _png_from_rgba(raw: bytes, w: int, h: int) -> bytes:
	import zlib as _z

	def chunk(typ, payload):
		return (struct.pack(">I", len(payload)) + typ + payload
			+ struct.pack(">I", _z.crc32(typ + payload) & 0xFFFFFFFF))

	# tiap baris diberi filter byte 0
	stride = w * 4
	body = bytearray()
	for y in range(h):
		body.append(0)
		body += raw[y * stride:(y + 1) * stride]
	ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
	return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
		+ chunk(b"IDAT", _z.compress(bytes(body), 6)) + chunk(b"IEND", b""))


def read_entry(zf, name):
	try:
		return zf.read(name)
	except KeyError:
		return None


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--apk", default="/opt/blissful/BlissfulAbyss.apk")
	ap.add_argument("--out", default=OUT)
	ap.add_argument("--limit", type=int, default=0)
	a = ap.parse_args()

	zf = zipfile.ZipFile(a.apk)
	names = set(zf.namelist())
	# kandidat model = tiap .jn (skeleton JSON) di animation
	jn = sorted(n for n in names if n.endswith(".jn") and "/animation/" in n)
	if a.limit:
		jn = jn[:a.limit]
	_log(f"{len(jn)} model (.jn) ditemukan")

	os.makedirs(a.out, exist_ok=True)
	stats = collections.Counter()
	problems = []

	for path in jn:
		base = path[:-3]  # buang ".jn"
		name = os.path.basename(base)
		raw_skel = read_entry(zf, path)
		if raw_skel is None:
			problems.append(name + " (jn hilang)")
			continue
		skeleton = decrypt(raw_skel)

		atlas = None
		for ext in (".atb", ".atlas"):
			raw = read_entry(zf, base + ext)
			if raw is None:
				continue
			atlas = decrypt(raw) if ext == ".atb" else raw
			break
		# Sebagian skeleton memakai atlas bersufiks ("<base>0.atb") atau
		# dipakai-bersama banyak atlas ("<base>_*.atb") — ambil yang pertama.
		if atlas is None:
			cands = sorted(n for n in names
			               if n.startswith(base) and n.endswith((".atb", ".atlas"))
			               and "/animation/" in n)
			if cands:
				raw = read_entry(zf, cands[0])
				if raw is not None:
					atlas = decrypt(raw) if cands[0].endswith(".atb") else raw
		if atlas is None:
			problems.append(name + " (atlas)")
			continue

		# halaman atlas -> PNG
		if isinstance(atlas, bytes):
			atlas_text = atlas.decode("utf-8", "replace")
		else:
			atlas_text = atlas
		pages = [ln.strip() for ln in atlas_text.splitlines()
		         if ln.strip() and ln[0] not in " \t" and PAGE_RE.search(ln.strip())]

		dest = os.path.join(a.out, name)
		os.makedirs(dest, exist_ok=True)
		open(os.path.join(dest, name + ".json"), "wb").write(skeleton)

		got = 0
		new_lines = []
		page_map = {}
		for pg in pages:
			png_name = PAGE_RE.sub(".png", pg)
			page_map[pg] = png_name
			# cari sumber tekstur
			src_ccz = read_entry(zf, base + ".pvr.ccz") if pg.lower().endswith(".pvr.ccz") else None
			if src_ccz is None:
				# atlas menunjuk <pg>; coba di folder yang sama
				src_ccz = read_entry(zf, os.path.join(os.path.dirname(path), pg))
			try:
				if src_ccz is not None:
					png = pvr_to_png(ccz_to_pvr(src_ccz))
				else:
					raw = read_entry(zf, os.path.join(os.path.dirname(path), pg))
					if raw is None:
						raw = read_entry(zf, os.path.join(os.path.dirname(path), png_name))
					if raw is None:
						continue
					# sudah PNG?
					png = raw if raw[:8] == b"\x89PNG\r\n\x1a\n" else None
				if png:
					open(os.path.join(dest, png_name), "wb").write(png)
					got += 1
			except Exception as e:
				problems.append(f"{name}/{pg}: {str(e)[:50]}")

		# tulis atlas dgn nama halaman .png
		for pg, png in page_map.items():
			atlas_text = atlas_text.replace(pg, png)
		open(os.path.join(dest, name + ".atlas"), "w", encoding="utf-8").write(atlas_text)

		stats[".json"] += 1
		stats[".atlas"] += 1
		if got == 0:
			problems.append(name + " (png)")
		stats["png"] += got

	_log("=== hasil ===")
	for k, v in stats.most_common():
		_log("   %6d  %s" % (v, k))
	_log("bermasalah: %d %s" % (len(problems), problems[:8]))
	total = sum(os.path.getsize(os.path.join(dp, f))
	            for dp, _, fs in os.walk(a.out) for f in fs)
	_log("total: %.2f GB -> %s" % (total / 1024 ** 3, a.out))


if __name__ == "__main__":
	sys.exit(main())
