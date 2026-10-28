#!/usr/bin/env python3
"""Normalisasi atlas hasil ekstraksi Otogi Frontier.

Atlas Otogi ditulis di Windows: setiap baris diakhiri CRLF, dan berkasnya
DIAWALI satu baris kosong (CRLF). Parser atlas Spine memperlakukan baris
kosong pertama itu sebagai nama halaman, sehingga halaman pertama terbaca
sebagai string kosong dan pemuatan gagal dengan:

    name cannot be null
    Offset is outside the bounds of the DataView

Gejalanya membingungkan karena .skel-nya sendiri sehat (versi 3.6.52,
byte biner utuh) — yang rusak hanya atlasnya.

Perbaikan: buang BOM, ubah CRLF -> LF, dan buang baris kosong di awal.
Dijalankan otomatis oleh update-otogi.py setelah ekstraksi.
"""

import os
import sys


def normalize(path: str) -> bool:
    with open(path, "rb") as fh:
        raw = fh.read()

    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    fixed = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    # buang semua baris kosong di awal berkas
    while fixed.startswith(b"\n"):
        fixed = fixed[1:]

    if fixed == raw:
        return False
    with open(path, "wb") as fh:
        fh.write(fixed)
    return True


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    n = total = 0
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".atlas"):
                continue
            total += 1
            if normalize(os.path.join(dirpath, name)):
                n += 1
    print(f"atlas dinormalisasi: {n} dari {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
