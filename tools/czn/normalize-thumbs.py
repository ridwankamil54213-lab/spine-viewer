#!/usr/bin/env python3
"""Samakan thumbnail kartu wiki ke ukuran native 260x460.

capture-thumbs.cjs meraster elemen DOM live; lebar CSS kartu pecahan membuat
hasilnya 260/261 x 460/463 px. Satu resize kecil bikin semuanya tepat
260x460 (ukuran asli portrait_character_crop_half_*.webp).

Sengaja TANPA Pillow: server systemd menjalankan /usr/bin/python3 yang punya
`cryptography` tapi tidak punya PIL dan tidak punya pip. ffmpeg sudah ada di
/usr/bin (dipakai server untuk export) dan membaca/menulis PNG dengan baik.
Ukuran dibaca langsung dari header IHDR PNG, jadi tidak butuh library gambar.

Usage: python3 tools/czn/normalize-thumbs.py
"""
from __future__ import annotations

import os
import struct
import subprocess
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "public" / "thumbs" / "chaoszero"
SIZE = (260, 460)


def png_size(p: Path) -> tuple[int, int] | None:
    with p.open("rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def resize(p: Path) -> None:
    fd, tmp = tempfile.mkstemp(suffix=".png", dir=str(p.parent))
    os.close(fd)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(p),
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
    fixed = 0
    for p in files:
        if png_size(p) != SIZE:
            resize(p)
            fixed += 1
    print(f"thumbnail: {len(files)} file, {fixed} dinormalisasi ke {SIZE[0]}x{SIZE[1]}")


if __name__ == "__main__":
    main()
