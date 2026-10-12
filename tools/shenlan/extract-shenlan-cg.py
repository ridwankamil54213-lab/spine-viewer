#!/usr/bin/env python3
"""Ekstrak CG / illust 深蓝终末录 (shenlan) dari APK.

Sumber (UnityFS .unity3d di dalam APK):
  assets/art/texture/herobust/ill/   -> cgs_<char>_<n> (CG karakter),
                                        main_avg_<ch>_<n> (CG cerita), bg_puzzle_*
  assets/art/texture/backgroud/      -> cg_avg_<ch>_<n> (CG cerita/H),
                                        activity_avg_*, main_avg_*, battle_*, bg_*
  assets/art/texture/herobust/atlas/ -> thumbnail bust 159x287 (dibuang)

Tiap bundle = Sprite + Texture2D. Keluaran: satu PNG per Texture2D dengan nama
= nama bundle (+ "_<i>" bila ada beberapa). Font/mesh tak ada -> murni gambar.

Pakai:  /srv/venv-spine/bin/python tools/shenlan/extract-shenlan-cg.py
"""
import os
import re
import sys
import zipfile
import collections

import UnityPy

APK = "/opt/games/shenlan.apk"
OUT = "/opt/spine-viewer/assets/shenlan-cg"
UnityPy.config.FALLBACK_UNITY_VERSION = "2021.3.45f1"

# Folder yang diambil sebagai galeri CG.
SRC_PREFIXES = [
    "assets/art/texture/herobust/ill/",
    "assets/art/texture/backgroud/",
]


def main():
    z = zipfile.ZipFile(APK)
    names = z.namelist()
    bundles = []
    for p in SRC_PREFIXES:
        bundles.extend(sorted(n for n in names if n.startswith(p) and n.endswith(".unity3d")))
    bundles = sorted(set(bundles))
    print(f"CG bundle: {len(bundles)}")
    os.makedirs(OUT, exist_ok=True)

    sizes = collections.Counter()
    per_cat = collections.Counter()
    written = 0
    skipped = 0

    def cat_of(stem):
        if stem.startswith("cgs_"):
            return "CG karakter (cgs)"
        if stem.startswith("cg_avg_"):
            return "CG cerita (cg_avg)"
        if stem.startswith("main_avg_"):
            return "Cerita utama (main_avg)"
        if stem.startswith("activity_avg_"):
            return "CG event (activity_avg)"
        if stem.startswith("bg_puzzle"):
            return "Puzzle"
        if stem.startswith("battle"):
            return "Battle bg"
        return "Lainnya"

    for i, b in enumerate(bundles, 1):
        stem = os.path.splitext(os.path.basename(b))[0]
        try:
            env = UnityPy.load(z.read(b))
        except Exception:
            skipped += 1
            continue
        n_tex = 0
        for o in env.objects:
            if o.type.name != "Texture2D":
                continue
            try:
                d = o.read()
                w, h = d.m_Width, d.m_Height
                # buang thumbnail: 159x287 = bust kecil, 314x191 = pratinjau
                # kecil (pasangan low-res dari CG layar penuh di backgroud/).
                # Kalau tidak dibuang, nama stem yang sama menimpa versi
                # full-res 1280x720/1920x1080 milik folder backgroud.
                if (w, h) in ((159, 287), (314, 191)):
                    n_tex += 1
                    continue
                name = stem if n_tex == 0 else f"{stem}_{n_tex}"
                img = d.image
                img.save(os.path.join(OUT, name + ".png"))
                sizes[f"{w}x{h}"] += 1
                per_cat[cat_of(stem)] += 1
                written += 1
                n_tex += 1
            except Exception:
                pass
        if i % 50 == 0:
            print(f"  {i}/{len(bundles)} tulis={written}")

    print(f"SELESAI tulis={written} bundle_dilewati={skipped}")
    print("── per kategori ──")
    for k, v in per_cat.most_common():
        print(f"  {v:5d}  {k}")
    print("── 15 resolusi terbanyak ──")
    for k, v in sizes.most_common(15):
        print(f"  {v:5d}  {k}")


if __name__ == "__main__":
    main()
