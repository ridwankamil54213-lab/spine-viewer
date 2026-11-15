#!/usr/bin/env python3
"""Samakan thumbnail kartu wiki ke ukuran native 260x460.

capture-thumbs.cjs meraster elemen DOM live; lebar CSS kartu pecahan membuat
hasilnya 260/261 x 460/463 px. Satu resize kecil bikin semuanya tepat
260x460 (ukuran asli portrait_character_crop_half_*.webp).

Sengaja TANPA Pillow: /usr/bin/python3 punya `cryptography` tapi tidak punya
PIL. ffmpeg membaca/menulis PNG dengan baik dan ukuran dibaca langsung dari
header IHDR PNG, jadi tidak butuh library gambar.

ffmpeg TIDAK selalu ada di PATH systemd (unit service punya PATH minimal).
Karena itu binary-nya dicari lewat $FFMPEG -> PATH -> /usr/local/bin ->
/usr/bin. Kalau benar-benar tidak ada, skrip ini cuma memperingatkan dan
keluar dengan kode 0: normalisasi itu kosmetik, dan capture-thumbs.cjs
memanggil skrip ini lewat execFileSync, jadi kegagalan di sini jangan sampai
menggagalkan seluruh pembaruan thumbnail.

Usage: python3 tools/czn/normalize-thumbs.py
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "public" / "thumbs" / "chaoszero"
SIZE = (260, 460)


def ffmpeg_bin() -> str | None:
    for cand in (os.environ.get("FFMPEG"), shutil.which("ffmpeg"),
                 "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def png_size(p: Path) -> tuple[int, int] | None:
    with p.open("rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def resize(p: Path, ff: str) -> None:
    fd, tmp = tempfile.mkstemp(suffix=".png", dir=str(p.parent))
    os.close(fd)
    try:
        subprocess.run(
            [ff, "-y", "-loglevel", "error", "-i", str(p),
             "-vf", f"scale={SIZE[0]}:{SIZE[1]}", tmp],
            check=True, capture_output=True, timeout=60,
        )
        if png_size(Path(tmp)) != SIZE:
            raise RuntimeError(f"ffmpeg tidak menghasilkan {SIZE}: {p.name}")
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> None:
    files = sorted(OUT.glob("*.png"))
    ff = ffmpeg_bin()
    if not ff:
        print(f"peringatan: ffmpeg tidak ditemukan — {len(files)} thumbnail "
              "dibiarkan apa adanya", file=sys.stderr)
        return
    fixed = 0
    for p in files:
        if png_size(p) != SIZE:
            resize(p, ff)
            fixed += 1
    print(f"thumbnail: {len(files)} file, {fixed} dinormalisasi ke {SIZE[0]}x{SIZE[1]}")


if __name__ == "__main__":
    main()
