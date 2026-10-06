#!/usr/bin/env python3
"""Rakit model Spine 异种啪乐町 / Kink (com.DrGame.Kink) untuk viewer.

Sumber: dump komunitas (RAR `com.DrGame.Kink_20251121.rar`, password 1234) yang
SUDAH berisi hasil ekstraksi AssetStudio, jadi tak perlu UnityPy:

    <src>/com.DrGame.Kink_*/Extract/out-*/Assets/Project/Addressable/**/Spine/**
        <stem>.skel + <stem>.atlas + <stem>.png

Tiap skeleton berdampingan dengan atlas + halaman PNG-nya (205/205 cocok), jadi
tugasnya cuma menyalin tiap triplet ke tata letak yang dibaca viewer:

    assets/kink/<stem>/<stem>.skel
    assets/kink/<stem>/<stem>.atlas
    assets/kink/<stem>/<stem>.png   (+ halaman lain bila atlas multi-halaman)

Catatan: nama file bisa berakhiran ganda ("BaseBear.skel.skel"); hanya SATU
sufiks ".skel" yang dibuang supaya atlas "<stem>.atlas" tetap ketemu.

Pemakaian:
    KINK_SRC=/opt/kink/out /srv/venv-spine/bin/python tools/extract-kink.py
"""
import argparse
import collections
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get("KINK_SRC", "/opt/kink/out")
OUT = os.environ.get("KINK_OUT", os.path.join(ROOT, "assets", "kink"))

PAGE_RE = re.compile(r"\.(png|jpg|jpeg|webp)$", re.I)


def pages_of(atlas_path: str):
	"""Nama halaman (baris tak-indent yang berakhiran gambar) dari atlas."""
	out = []
	try:
		text = open(atlas_path, encoding="utf-8", errors="replace").read()
	except Exception:
		return out
	for line in text.splitlines():
		if not line.strip() or line[0] in " \t":
			continue
		low = line.strip().lower()
		if low.endswith((".png", ".jpg", ".jpeg", ".webp")):
			out.append(line.strip())
	return out


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--src", default=SRC)
	ap.add_argument("--out", default=OUT)
	a = ap.parse_args()

	skels = []
	for dp, _, fs in os.walk(a.src):
		for f in fs:
			if f.lower().endswith(".skel"):
				skels.append(os.path.join(dp, f))
	skels.sort()
	print("skeleton ditemukan:", len(skels), flush=True)

	os.makedirs(a.out, exist_ok=True)
	stats = collections.Counter()
	missing = []

	for skel in skels:
		base = os.path.basename(skel)
		stem = base[: -len(".skel")]  # buang SATU sufiks saja
		atlas = os.path.join(os.path.dirname(skel), stem + ".atlas")
		if not os.path.exists(atlas):
			missing.append(stem + " (atlas)")
			continue
		# kumpulkan halaman: halaman yang dirujuk atlas ATAU apa pun yang
		# bernama <stem>.png (kasus atlas tanpa header halaman).
		want = pages_of(atlas) or [stem + ".png"]
		pages = []
		for pg in want:
			p = os.path.join(os.path.dirname(skel), pg)
			if os.path.exists(p):
				pages.append((pg, p))
		if not pages:
			missing.append(stem + " (png)")
			continue

		dest = os.path.join(a.out, stem)
		os.makedirs(dest, exist_ok=True)
		shutil.copyfile(skel, os.path.join(dest, stem + ".skel"))
		shutil.copyfile(atlas, os.path.join(dest, stem + ".atlas"))
		stats[".skel"] += 1
		stats[".atlas"] += 1
		for pg, p in pages:
			shutil.copyfile(p, os.path.join(dest, pg))
			stats["png"] += 1

	print("\n=== hasil ===")
	for k, v in stats.most_common():
		print("   %6d  %s" % (v, k))
	print("model ditulis:", stats[".skel"])
	print("kurang lengkap:", len(missing), missing[:10])
	total = sum(
		os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(a.out) for f in fs
	)
	print("total ukuran: %.2f GB -> %s" % (total / 1024 ** 3, a.out))


if __name__ == "__main__":
	sys.exit(main())
