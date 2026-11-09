#!/usr/bin/env python3
"""Ubah pak komunitas "动态HCG.rar" jadi layout assets/<game>/<model>/.

Pak dari Live2DHub (lihat README.md di folder ini) berisi dua lapis arsip dan
campuran skeleton: sebagian `.skel` biner, sisanya Spine JSON yang tersimpan
dengan ekstensi `.prefab`. Skrip ini:

  1. mengekstrak `.rar` (password sama) lalu `.zip` (password-nya harus dikirim
     sebagai byte GBK — lihat catatan di bawah);
  2. menyalin tiap folder jadi satu model (skeleton + atlas + png), membuang
     `desktop.ini` dan berkas konfigurasi ViewerEX;
  3. menyelamatkan nama file yang rusak dari alat ekstrak penulis
     ("e008_03.atlas #44" -> "e008_03.atlas") supaya nama skeleton == atlas;
  4. menamai ulang folder jadi ASCII dan menulis peta nama tampilan CJK.

Pemakaian:
    python3 tools/lustyodyssey/prepare-pack.py --src /path/ke/动态HCG.rar \
        --assets /root/spine-viewer/assets --game lustyodyssey \
        --names /root/spine-viewer/data/lustyodyssey-names.json

CATATAN PENTING (kenapa password dikirim sebagai byte, bukan str):
7z di Linux membandingkan password apa adanya sebagai byte argv. Arsip ini
dibuat di Windows dengan password Tionghoa, jadi byte-nya GBK, bukan UTF-8 —
`7z t -pbilibili@耀依永恒` gagal sementara versi `.encode("gbk")` berhasil.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

RAR_PW = "bilibili@耀依永恒"
ZIP_PW = "bilibili@耀依永恒".encode("gbk")


def run7z(args, pw=None):
    cmd = [b"7z"] + args
    if pw is not None:
        cmd.insert(1, b"-p" + pw)
    r = subprocess.run(cmd)
    return r.returncode


def extract(src, workdir):
    """Ekstrak rar -> zip -> isi, semuanya ke workdir. Return folder hasil."""
    os.makedirs(workdir, exist_ok=True)
    rar = os.path.join(workdir, os.path.basename(src))
    if os.path.abspath(src) != os.path.abspath(rar):
        shutil.copy2(src, rar)
    # Selalu pakai path absolut: 7z dijalankan dengan cwd pemanggil, bukan workdir.
    if run7z([b"x", b"-y", b"-o" + workdir.encode(),
              os.path.abspath(rar).encode()],
             RAR_PW.encode("utf-8")) != 0:
        sys.exit("gagal ekstrak rar")
    zips = [f for f in os.listdir(workdir) if f.lower().endswith(".zip")]
    if not zips:
        return workdir
    inner = os.path.join(workdir, "inner")
    if run7z([b"x", b"-y", b"-o" + inner.encode(),
              os.path.abspath(os.path.join(workdir, zips[0])).encode()],
             ZIP_PW) != 0:
        sys.exit("gagal ekstrak zip (password GBK salah?)")
    return inner


def clean_name(name):
    """Buang suffix ' #<angka>' yang ditambahkan alat ekstrak penulis."""
    return re.sub(r" #\d+(?=(\.[A-Za-z0-9]+)?$)", "", name)


def find_root(base):
    """Turun sampai ketemu folder yang benar-benar berisi model."""
    while True:
        subs = [d for d in sorted(os.listdir(base))
                if os.path.isdir(os.path.join(base, d))]
        if not subs:
            sys.exit(f"tidak ada subfolder di {base}")
        files = os.listdir(os.path.join(base, subs[0]))
        if any(f.endswith((".atlas", ".skel", ".prefab")) for f in files):
            return base
        if len(subs) == 1:
            base = os.path.join(base, subs[0])
        else:
            # beberapa subfolder = folder pembungkus (mis. "其他(...)"); turun
            # satu tingkat dan perlakukan tiap isinya sebagai model.
            return base


def iter_model_dirs(root):
    """Hasilkan (folder, nama folder sumber) untuk tiap model."""
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d)
        if not os.path.isdir(p):
            continue
        files = os.listdir(p)
        if any(f.endswith((".atlas", ".skel", ".prefab")) for f in files):
            yield p, d
        elif any(os.path.isdir(os.path.join(p, x)) for x in files):
            for sub in sorted(os.listdir(p)):
                sp = os.path.join(p, sub)
                if not os.path.isdir(sp):
                    continue
                sf = os.listdir(sp)
                if any(f.endswith((".atlas", ".skel", ".prefab")) for f in sf):
                    yield sp, f"其他 · {sub}"


def prepare(root, dest, names_out):
    os.makedirs(dest, exist_ok=True)
    names, used, ok = {}, set(), 0
    problems = []
    for src_dir, label in iter_model_dirs(root):
        files = {clean_name(f): f for f in os.listdir(src_dir)}
        atlases = sorted(f for f in files if f.endswith(".atlas"))
        if not atlases:
            problems.append((label, "tanpa .atlas"))
            continue
        base = atlases[0][: -len(".atlas")]

        # skeleton: <base>.skel -> <base>.json (dari .prefab) -> apa saja
        skel = None
        out_skel = None
        if base + ".skel" in files:
            skel, out_skel = files[base + ".skel"], base + ".skel"
        elif base + ".prefab" in files:
            skel, out_skel = files[base + ".prefab"], base + ".json"
        elif base + ".json" in files:
            skel, out_skel = files[base + ".json"], base + ".json"
        else:
            for f in sorted(files):
                if f.endswith((".skel", ".prefab", ".json")):
                    skel = files[f]
                    out_skel = base + (".skel" if f.endswith(".skel") else ".json")
                    problems.append((label, f"skeleton beda nama: {f}"))
                    break
        if not skel:
            problems.append((label, "tanpa skeleton"))
            continue

        ascii_name = re.sub(r"[^A-Za-z0-9_.\-]", "_", base)
        cand, n = ascii_name, 2
        while cand in used:
            cand, n = f"{ascii_name}_{n}", n + 1
        used.add(cand)

        dd = os.path.join(dest, cand)
        os.makedirs(dd, exist_ok=True)
        shutil.copy2(os.path.join(src_dir, skel), os.path.join(dd, out_skel))
        for a in atlases:
            shutil.copy2(os.path.join(src_dir, files[a]), os.path.join(dd, a))
        for p in (f for f in files if f.lower().endswith(".png")):
            shutil.copy2(os.path.join(src_dir, files[p]), os.path.join(dd, p))

        names[cand] = {"name": label}
        ok += 1

    if names_out:
        os.makedirs(os.path.dirname(names_out), exist_ok=True)
        with open(names_out, "w", encoding="utf-8") as f:
            json.dump(names, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"model disiapkan: {ok} ({len(names)} nama)")
    for label, why in problems:
        print(f"   catatan - {label}: {why}")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, help="arsip .rar dari pak komunitas")
    ap.add_argument("--assets", required=True, help="folder assets/ spine-viewer")
    ap.add_argument("--game", default="lustyodyssey", help="nama folder game (ASCII)")
    ap.add_argument("--names", help="tulis peta nama tampilan ke berkas ini")
    ap.add_argument("--workdir", default=None, help="direktori kerja (default: tmp di samping --src)")
    args = ap.parse_args()

    workdir = args.workdir or os.path.join(os.path.dirname(os.path.abspath(args.src)), "lusty-work")
    root = find_root(extract(args.src, workdir))
    prepare(root, os.path.join(args.assets, args.game), args.names)


if __name__ == "__main__":
    main()
