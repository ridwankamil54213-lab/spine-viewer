#!/usr/bin/env python3
"""Potong screenshot canvas CrossCore jadi thumbnail WebP yang rapat.

Dipanggil tools/crosscore/render-thumbs.cjs:
    python3 tools/crosscore/normalize-thumbs.py public/thumbs/crosscore-render

Baca _raw/*.png, tulis <stem>.webp di direktori yang sama, lalu hapus PNG
mentahnya. Idempoten: PNG yang sudah punya WebP dilewati (kecuali --force).

Latar viewer gelap, jadi subjek diisolasi dengan ambang kecerahan. Koordinat
batas memakai persentil 2%/98% (bukan min/max) supaya satu piksel terang di
pojok — indikator zoom, grid, tooltip — tidak membuat crop melar ke seluruh
kanvas. Hasilnya potret ~200x256 yang tetap terbaca di kartu perpustakaan.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

SAMPLE_W, SAMPLE_H = 160, 120
THRESHOLD = 80
EDGE_PAD_PCT = 0.02
PAD_PX = 20
MAX_SIDE = 256
WEBP_QUALITY = 82


def percentile(values: list[int], p: float) -> int:
    values = sorted(values)
    return values[int((len(values) - 1) * p)]


def content_box(im: Image.Image) -> tuple[int, int, int, int] | None:
    sample = im.convert("RGB").resize((SAMPLE_W, SAMPLE_H))
    lum = [max(px) for px in sample.get_flattened_data()]
    pts = [(k % SAMPLE_W, k // SAMPLE_W) for k, v in enumerate(lum) if v > THRESHOLD]
    if len(pts) < 20:
        return None
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    sx, sy = im.width / SAMPLE_W, im.height / SAMPLE_H
    x0 = max(0, int(percentile(xs, EDGE_PAD_PCT) * sx - PAD_PX))
    y0 = max(0, int(percentile(ys, EDGE_PAD_PCT) * sy - PAD_PX))
    x1 = min(im.width, int(percentile(xs, 1 - EDGE_PAD_PCT) * sx + PAD_PX))
    y1 = min(im.height, int(percentile(ys, 1 - EDGE_PAD_PCT) * sy + PAD_PX))
    if x1 - x0 < 40 or y1 - y0 < 40:
        return None
    return x0, y0, x1, y1


def main() -> int:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "public/thumbs/crosscore-render")
    raw = dest / "_raw"
    force = "--force" in sys.argv
    dest.mkdir(parents=True, exist_ok=True)
    made = skipped = fallback = 0
    for src in sorted(raw.glob("*.png")):
        out = dest / (src.stem + ".webp")
        if out.exists() and not force:
            src.unlink()
            skipped += 1
            continue
        try:
            im = Image.open(src).convert("RGB")
            box = content_box(im)
            if box:
                im = im.crop(box)
            else:
                fallback += 1
            im.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            im.save(out, "WEBP", quality=WEBP_QUALITY, method=5)
            made += 1
        finally:
            if src.exists():
                src.unlink()
    print(json.dumps({"normalized": made, "skipped": skipped,
                      "fallback_full_frame": fallback}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
