#!/usr/bin/env python3
"""Ekstrak aset Spine Epic Seven dari data.pack lalu konversi .scsp/.sct.

Dua tahap, dua tool berbeda:

  1. CeciliaBot/EpicSevenAssetRipper  -> buka data.pack (terenkripsi XOR)
     dan keluarkan berkas mentah .scsp / .sct / .atlas.
  2. Kutinana/E7SpineAssetConverter   -> .scsp menjadi .json (skeleton
     Spine), .sct menjadi .png (tekstur ASTC/ETC2/RGBA), dan .atlas
     diarahkan dari .sct ke .png.

Kenapa tidak langsung pakai GUI: keduanya berbasis PyQt6 dan data.pack
berukuran ~7 GB, jadi di sini modul intinya dipanggil tanpa antarmuka.

Pemakaian:
    /srv/venv-spine/bin/python tools/extract-epic7.py
    FOLDERS=model,portrait LIMIT=50 ...   # untuk uji coba
"""
import json
import os
import shutil
import subprocess
import sys

RIPPER = "/srv/spine-assets/epic7/ripper"
CONVERTER = "/srv/spine-assets/epic7/tool"
PACK = "/srv/spine-assets/epic7/pack/data.pack"
TREE = "/srv/spine-assets/epic7/pack/tree.json"
RAW = "/srv/spine-assets/epic7/raw"
OUT = "/srv/spine-assets/epic7/spine_out"

PY = "/srv/venv-spine/bin/python"
# Folder yang berisi model; effect/bg bisa ditambahkan tapi jumlahnya puluhan
# ribu dan bukan karakter.
FOLDERS = [f for f in os.environ.get("FOLDERS", "model").split(",") if f]
LIMIT = int(os.environ.get("LIMIT", "0"))  # 0 = semua
NEED = ("scsp", "sct", "atlas")


def load_tree():
    if not os.path.exists(TREE):
        sys.exit(f"tree.json tidak ada — jalankan build_tree dulu: {TREE}")
    return json.load(open(TREE))


def walk(node, out):
    if isinstance(node, dict):
        if node.get("type") == "file":
            out.append(node)
        for key in ("children", "files"):
            val = node.get(key)
            if isinstance(val, list):
                for child in val:
                    walk(child, out)
    elif isinstance(node, list):
        for child in node:
            walk(child, out)


def wanted(files):
    """Kelompokkan per nama dasar yang punya ketiga berkas (scsp+sct+atlas)."""
    groups = {}
    for f in files:
        path = f.get("full_path", "")
        if not any(path.startswith(folder + "/") for folder in FOLDERS):
            continue
        base, ext = os.path.splitext(path)
        ext = ext.lstrip(".").lower()
        if ext not in NEED:
            continue
        groups.setdefault(base, {})[ext] = f
    full = {k: v for k, v in groups.items() if all(e in v for e in NEED)}
    missing = len(groups) - len(full)
    print(f"  kandidat {len(groups)} | lengkap {len(full)} | tidak lengkap {missing}")
    return full


def extract(files):
	"""Keluarkan berkas mentah dari data.pack.

	get_file_from_tree() hanya mengembalikan metadata (dict), bukan isi
	berkas. Isinya dibaca sendiri lewat read_bytes() yang sudah menangani
	dekripsi XOR, sambil menggeser kursor ke offset yang benar.
	"""
	os.makedirs(RAW, exist_ok=True)
	sys.path.insert(0, RIPPER)
	from app.pack import DataPack

	dp = DataPack(PACK)
	dp.set_tree(load_tree())
	written = skipped = failed = 0
	for base, trio in files.items():
		for ext, meta in trio.items():
			dest = os.path.join(RAW, base + "." + ext)
			if os.path.exists(dest) and os.path.getsize(dest) > 0:
				skipped += 1
				continue
			os.makedirs(os.path.dirname(dest), exist_ok=True)
			try:
				info = dp.get_file_from_tree(meta["full_path"])
				if not info or "offset" not in info:
					raise ValueError("entri tidak punya offset")
				fmap = dp.mmap()
				try:
					fmap.seek(int(info["offset"]))
					data = dp.read_bytes(fmap, int(info["offset"]), int(info["size"]))
				finally:
					fmap.close()
				with open(dest, "wb") as fh:
					fh.write(bytes(data))
				written += 1
			except Exception as exc:
				failed += 1
				if failed <= 5:
					print(f"  GAGAL {meta['full_path']}: {exc}")
	dp.destroy()
	print(f"  ekstrak: baru={written} lewati={skipped} gagal={failed}")


def convert():
	"""Jalankan converter E7.

	Hanya scsp2json.py yang menerima direktori; sct2png.py dan fix_atlas.py
	bekerja per berkas meski README menyebutkan mode batch. Karena itu
	konversi .sct/.atlas dilakukan satu per satu dari Python.
	"""
	os.makedirs(OUT, exist_ok=True)
	sys.path.insert(0, CONVERTER)

	# 1. .scsp -> .json (bisa direktori)
	print("  -> scsp2json.py")
	r = subprocess.run([PY, os.path.join(CONVERTER, "scsp2json.py"), RAW, OUT],
	                   capture_output=True, text=True, cwd=CONVERTER)
	if r.returncode != 0:
		print(f"     exit {r.returncode}: {r.stderr[-300:]}")

	# 2. .sct -> .png + .atlas dirapikan (per berkas)
	#
	# Viewer mengharapkan satu folder per model
	# (<OUT>/<nama>/<nama>.{json,atlas,png}); hasil mentah scsp2json justru
	# rata dalam satu direktori, jadi setiap berkas dipindahkan ke folder
	# sesuai namanya.
	ok = fail = 0
	import fix_atlas
	import sct2png
	for root, _dirs, names in os.walk(RAW):
		for n in sorted(names):
			low = n.lower()
			src = os.path.join(root, n)
			stem = os.path.splitext(n)[0]
			dst_dir = os.path.join(OUT, stem)
			os.makedirs(dst_dir, exist_ok=True)
			try:
				if low.endswith(".sct"):
					sct2png.convert_sct_to_png(src, os.path.join(dst_dir, stem + ".png"))
					ok += 1
				elif low.endswith(".atlas"):
					dst = os.path.join(dst_dir, stem + ".atlas")
					shutil.copy2(src, dst)
					# fix_atlas(input, output) — butuh dua argumen.
					fix_atlas.fix_atlas(dst, dst)
					# fix_atlas hanya membuang baris `pma:`, padahal README-nya
					# menjanjikan penggantian referensi .sct -> .png di baris
					# pertama atlas. Tanpa ini atlas tetap menunjuk ke
					# <nama>.sct (yang tidak pernah dibuat) dan model gagal
					# menemukan teksturnya.
					# Baris pertama atlas kadang kosong (diawali \n), jadi
					# jangan berasumsi referensi tekstur selalu di indeks 0.
					with open(dst, "r", encoding="utf-8") as fh:
						lines = fh.readlines()
					for i, line in enumerate(lines[:5]):
						if line.strip().lower().endswith(".sct"):
							lines[i] = os.path.splitext(line.strip())[0] + ".png\n"
							break
					else:
						# Tidak ketemu .sct: pastikan minimal nama PNG benar.
						for i, line in enumerate(lines[:5]):
							s = line.strip()
							if s and "." not in s.rsplit("/", 1)[-1]:
								lines[i] = s + ".png\n"
								break
					with open(dst, "w", encoding="utf-8") as fh:
						fh.writelines(lines)
					ok += 1
			except Exception as exc:
				fail += 1
				if fail <= 5:
					print(f"     GAGAL {n}: {exc}")

	# 3. .json hasil scsp2json dipindahkan ke folder modelnya masing-masing.
	moved = 0
	for root, _dirs, names in os.walk(OUT):
		for n in list(names):
			if not n.lower().endswith(".json"):
				continue
			stem = os.path.splitext(n)[0]
			src = os.path.join(root, n)
			dst_dir = os.path.join(OUT, stem)
			if os.path.abspath(root) == os.path.abspath(dst_dir):
				continue
			os.makedirs(dst_dir, exist_ok=True)
			shutil.move(src, os.path.join(dst_dir, n))
			moved += 1
	print(f"  konversi: ok={ok} gagal={fail} | json dipindah={moved}")


def main():
    tree = load_tree()
    files = []
    walk(tree, files)
    print(f"total berkas di tree : {len(files)}")

    groups = wanted(files)
    keys = sorted(groups)
    if LIMIT:
        keys = keys[:LIMIT]
    print(f"model diproses      : {len(keys)}")

    extract({k: groups[k] for k in keys})
    convert()

    # Ringkasan hasil.
    ok = 0
    if os.path.isdir(OUT):
        for name in os.listdir(OUT):
            d = os.path.join(OUT, name)
            if not os.path.isdir(d):
                continue
            has = {os.path.splitext(f)[1].lstrip(".").lower() for f in os.listdir(d)}
            if {"json", "atlas"} <= has and any(f.endswith(".png") for f in os.listdir(d)):
                ok += 1
    print(f"\nmodel siap pakai    : {ok} -> {OUT}")


if __name__ == "__main__":
    main()
