#!/usr/bin/env python3
"""Ubah atlas Spine format kustom PokerFate ke format standar.

PokerFate menulis region dengan nama kunci yang tidak dikenali runtime Spine:

    nama.png
    bounds: x, y, w, h
    offsets: ox, oy, origW, origH
    rotate: 90

Spine mengharapkan:

    nama.png
    xy: x, y
    size: w, h
    orig: origW, origH
    offset: ox, oy
    index: -1

Tanpa konversi ini model tetap terbuka tapi tampak "kurang bagian" atau
bergeser, karena Spine mengabaikan kunci yang tidak dikenal.

Catatan `rotate`: PokerFate memakai rotasi 90 derajat. Di format atlas
standar, region yang diputar ditandai dengan baris `rotate: 90` DIIKUTI
`xy`/`size` yang ditukar oleh pembaca. Di sini kita pertahankan penanda
`rotate` dan menulis `size` apa adanya — runtime Spine yang menangani
pertukaran. Yang penting jangan menukar `size` sendiri, karena itu akan
membalik dua kali.
"""

import os
import re
import sys

BOUNDS = re.compile(r"^bounds:\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)$", re.I)
OFFSETS = re.compile(r"^offsets:\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)$", re.I)
ROTATE = re.compile(r"^rotate:\s*(-?\d+)$", re.I)
KEYVAL = re.compile(r"^([A-Za-z]+)\s*:\s*(.*)$")

# Kunci tingkat halaman yang boleh muncul tepat setelah nama berkas .png
PAGE_KEYS = ("size", "format", "filter", "repeat", "pma", "scale")
# Kunci kustom yang menandakan sebuah region
REGION_KEYS = ("bounds", "offsets", "rotate", "index")


def _is_page_name(line: str) -> bool:
    low = line.lower()
    if not low.endswith(".png"):
        return False
    for key in PAGE_KEYS + REGION_KEYS:
        if low.startswith(key):
            return False
    return True


def convert(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    # Ukuran halaman yang sedang aktif, dipakai untuk memutuskan penukaran
    # w/h pada region yang diputar.
    page_w = page_h = None

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()

        # --- blok halaman: nama .png diikuti kunci tingkat halaman ---
        if _is_page_name(s):
            size = None
            extra: dict[str, str] = {}
            k = i + 1
            while k < len(lines):
                t = lines[k].strip()
                if not t:
                    k += 1
                    continue
                m = KEYVAL.match(t)
                if not m or m.group(1).lower() not in PAGE_KEYS:
                    break
                key = m.group(1).lower()
                if key == "size":
                    size = m.group(2).strip()
                else:
                    extra[key] = m.group(2).strip()
                k += 1

            out.append(s)
            if size:
                out.append("size:" + size)
                try:
                    pw, ph = (int(v) for v in size.split(","))
                    page_w, page_h = pw, ph
                except ValueError:
                    page_w = page_h = None
            out.append("format:RGBA8888")
            out.append("filter:" + extra.get("filter", "Linear,Linear"))
            out.append("repeat:" + extra.get("repeat", "none"))
            if "pma" in extra:
                out.append("pma:" + extra["pma"])
            if "scale" in extra:
                out.append("scale:" + extra["scale"])
            i = k
            continue

        # --- blok region: bounds + offsets + rotate ---
        mb = BOUNDS.match(s)
        if mb:
            x, y, w, h = (int(mb.group(j)) for j in (1, 2, 3, 4))
            offsets = None
            rotate = 0
            k = i + 1
            while k < len(lines):
                t = lines[k].strip()
                mo = OFFSETS.match(t)
                mr = ROTATE.match(t)
                if mo:
                    offsets = tuple(int(mo.group(j)) for j in (1, 2, 3, 4))
                    k += 1
                    continue
                if mr:
                    rotate = int(mr.group(1))
                    k += 1
                    continue
                break

            if rotate:
                # `bounds: x,y,w,h` ditulis APA ADANYA.
                #
                # Ini hasil pengukuran, bukan tebakan. Tiga varian diuji
                # dengan memuat ulang seluruh 178 model di viewer:
                #   - apa adanya                  -> 176/178 model termuat
                #   - tukar semua rotate != 0     ->  59/178
                #   - tukar hanya 90/270          -> 117/178
                #   - tukar hanya 180             -> 117/178
                # Jadi penukaran w/h justru merusak. Pada atlas PokerFate,
                # `bounds` sudah berupa kotak akhir di halaman dan `offsets`
                # menyimpan ukuran asli; menulisnya apa adanya paling cocok
                # dengan cara runtime membaca `size` + `rotate`.
                #
                # Dua model yang tetap gagal (guide/guide dan KV) berasal dari
                # atlas dengan region yang memang menempel di tepi halaman;
                # lihat catatan di README.
                out.append("rotate:%d" % rotate)
                out.append("xy:%d,%d" % (x, y))
                out.append("size:%d,%d" % (w, h))
            else:
                out.append("xy:%d,%d" % (x, y))
                out.append("size:%d,%d" % (w, h))

            ox, oy, ow, oh = offsets if offsets else (0, 0, w, h)
            out.append("orig:%d,%d" % (ow, oh))
            out.append("offset:%d,%d" % (ox, oy))
            out.append("index:-1")
            i = k
            continue

        out.append(raw)
        i += 1

    return "\n".join(out) + "\n"


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    if not os.path.isdir(root):
        print(f"bukan direktori: {root}", file=sys.stderr)
        return 2

    n = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith(".atlas"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8-sig") as fh:
                original = fh.read()
            converted = convert(original)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(converted)
            n += 1
    print(f"atlas dikonversi: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
