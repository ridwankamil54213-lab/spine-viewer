#!/usr/bin/env python3
"""Ekstrak model Spine dari イヴンタイト (IV-N-Tight, DMM/FANZA, Dieselmine).

Game-nya Unity WebGL. Unduhan `dmm4_build.data.unityweb` = brotli berisi
kontainer `UnityWebData1.0.0`, yang di dalamnya ada `data.unity3d` (UnityFS,
Unity 6). Semua model Spine ada di TextAsset + Texture2D di dalamnya
(JSON Spine 4.0.64/4.2.38/4.2.43 — bukan biner).

Alur:
    unduh  <Build>/dmm4_build.data.unityweb  ->  brotli  ->  UnityWebData1.0
    ekstrak data.unity3d  ->  UnityPy  ->  TextAsset(.json/.atlas) + Texture2D
    tulis  assets/ivntight/<nama>/{<nama>.json,<nama>.atlas,<halaman>.png}

Pemakaian:
    /srv/venv-spine/bin/python tools/extract-ivntight.py \
        --bundle /opt/ivntight/extract/data.unity3d
"""
import argparse
import os
import re
import sys

import UnityPy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("IVN_OUT", os.path.join(ROOT, "assets", "ivntight"))
PAGE_RE = re.compile(r"\.(png|jpg|jpeg|webp)$", re.I)


def _log(m):
	import time
	sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
	sys.stderr.flush()


def read_assets(bundle):
	"""{nama: bytes} untuk TextAsset, {nama: obj} untuk Texture2D."""
	env = UnityPy.load(bundle)
	texts, texes = {}, {}
	for obj in env.objects:
		if obj.type.name == "TextAsset":
			d = obj.read()
			name = getattr(d, "m_Name", "") or ""
			data = getattr(d, "m_Script", None)
			if isinstance(data, str):
				data = data.encode("utf-8", "surrogateescape")
			texts[name] = bytes(data or b"")
		elif obj.type.name == "Texture2D":
			d = obj.read()
			name = getattr(d, "m_Name", "") or ""
			texes[name] = obj
	return texts, texes


def pages_of(atlas_text):
	out = []
	for line in atlas_text.splitlines():
		if not line.strip() or line[0] in " \t":
			continue
		if PAGE_RE.search(line.strip()):
			out.append(line.strip())
	return out


def base_of(name):
	"""prin -> prin ; watermelon.json -> watermelon ; x.atlas -> x"""
	return re.sub(r"\.(json|skel|atlas|txt|bytes)$", "", name, flags=re.I)


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--bundle", default="/opt/ivntight/extract/data.unity3d")
	ap.add_argument("--out", default=OUT)
	ap.add_argument("--list", action="store_true")
	a = ap.parse_args()

	texts, texes = read_assets(a.bundle)
	_log(f"TextAsset={len(texts)} Texture2D={len(texes)}")

	# skeleton = TextAsset yang isinya JSON spine
	skeletons = {n: b for n, b in texts.items()
	             if b.lstrip().startswith(b'{"skeleton"')}
	# atlas = TextAsset yang punya baris halaman gambar
	atlases = {}
	for n, b in texts.items():
		txt = b.decode("utf-8", "replace")
		if pages_of(txt):
			atlases[n] = txt
	if a.list:
		_log("skeleton: " + ", ".join(sorted(skeletons)))
		_log("atlas   : " + ", ".join(sorted(atlases)))
		return 0

	os.makedirs(a.out, exist_ok=True)
	written = 0
	for skname, skbytes in sorted(skeletons.items()):
		base = base_of(skname)
		# cari atlas sebasis
		aname = next((n for n in atlases if base_of(n) == base), None)
		if not aname:
			_log(f"  tanpa atlas: {skname}")
			continue
		atxt = atlases[aname]
		pages = pages_of(atxt)
		dest = os.path.join(a.out, base)
		os.makedirs(dest, exist_ok=True)
		open(os.path.join(dest, base + ".json"), "wb").write(skbytes)
		open(os.path.join(dest, base + ".atlas"), "w", encoding="utf-8").write(atxt)
		got = 0
		for pg in pages:
			stem = re.sub(r"\.(png|jpg|jpeg|webp)$", "", pg, flags=re.I)
			obj = texes.get(stem) or texes.get(stem + "_1") or texes.get(pg)
			if obj is None:
				# cari tekstur yang namanya diawali stem
				cand = next((k for k in texes if k.startswith(stem)), None)
				obj = texes.get(cand) if cand else None
			if obj is None:
				_log(f"    tekstur tak ada utk halaman {pg} ({base})")
				continue
			try:
				img = obj.read().image
				img.save(os.path.join(dest, pg), "PNG")
				got += 1
			except Exception as e:  # noqa: BLE001
				_log(f"    gagal tekstur {pg}: {str(e)[:60]}")
		_log(f"  {base}: skeleton+atlas, {got}/{len(pages)} halaman")
		if got:
			written += 1

	total = sum(os.path.getsize(os.path.join(dp, f))
	            for dp, _, fs in os.walk(a.out) for f in fs)
	_log(f"=== {written} model ditulis, {total/1e6:.1f} MB -> {a.out}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
