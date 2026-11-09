#!/usr/bin/env python3
"""Thumbnail Mitao Utopia dari DynamicSingleTextures/HeroSelectDisplay.

Sumber (hasil tools/mitao/extract-all.py):
  /srv/spine-assets/mitao/extracted/Assets/Res/Textures/
    DynamicSingleTextures/HeroSelectDisplay/HeroSelectDisplay_<id>.png

Ada 35 sprite (karakter utuh, 425x...) dan 35 lembar `__atlas.png`.
Yang dipakai SPRITE, bukan atlas. Satu potret dipakai bersama SEMUA model
dengan suffix id yang sama (front_10001, back_10001, hfront_10001,
common_10001, skill_10001, ...), jadi kartu root maupun baris popup Varian
semuanya punya gambar.

Keluaran: public/thumbs/mitao-utopia/HeroSelectDisplay_<id>.webp (300px,
aspect ratio utuh, alpha dipertahankan) + _manifest.json dengan kunci id
model lengkap. WebP yang sudah ada dilewati (--force untuk regenerate).

Butuh Pillow (ada di /srv/venv-spine/bin/python, dipakai server juga).

Usage:
  /srv/venv-spine/bin/python tools/mitao/refresh-thumbs.py
  /srv/venv-spine/bin/python tools/mitao/refresh-thumbs.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STATE = Path(os.environ.get("MITAO_STATE", "/srv/spine-assets/mitao"))
SRC = STATE / "extracted" / "Assets" / "Res" / "Textures" / \
    "DynamicSingleTextures" / "HeroSelectDisplay"
ASSETS = ROOT / "assets" / "mitao-utopia"
OUT = ROOT / "public" / "thumbs" / "mitao-utopia"
MAP_FILE = OUT / "_manifest.json"
MAX_SIDE = 300

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9
    RESAMPLE = Image.LANCZOS


def num_of(name: str):
    mt = re.search(r"(\d{4,6})$", name)
    return mt.group(1) if mt else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not SRC.is_dir():
        print(json.dumps({
            "ok": False,
            "error": f"folder sumber belum ada: {SRC}. Jalankan extract-all.py dulu.",
        }))
        return 1

    models = sorted(d.name for d in ASSETS.iterdir() if d.is_dir())
    srcs = {}
    for p in sorted(SRC.glob("HeroSelectDisplay_*.png")):
        if "__atlas" in p.name:
            continue
        mt = re.search(r"HeroSelectDisplay_(\d{4,6})\.png$", p.name)
        if mt:
            srcs[mt.group(1)] = p

    OUT.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    mapping = {}
    for num, src in srcs.items():
        dest = OUT / f"HeroSelectDisplay_{num}.webp"
        if dest.exists() and not args.force:
            skipped += 1
        else:
            with Image.open(src) as im:
                thumb = im.convert("RGBA")
                thumb.thumbnail((MAX_SIDE, MAX_SIDE), RESAMPLE)
                thumb.save(dest, "WEBP", quality=82, method=4)
            written += 1
        for model in models:
            if num_of(model) == num:
                mapping[f"mitao-utopia/{model}"] = dest.name

    covered = {k.rsplit("/", 1)[-1] for k in mapping}
    json.dump(mapping, open(MAP_FILE, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({
        "ok": True,
        "source": str(SRC),
        "sumber": len(srcs),
        "model": len(models),
        "thumbnail": len(mapping),
        "tanpa_thumbnail": len(models) - len(covered),
        "written": written,
        "skipped": skipped,
        "manifest": str(MAP_FILE),
    }, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
