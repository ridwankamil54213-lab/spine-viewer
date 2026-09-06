#!/usr/bin/env python3
"""Uji: apakah Haze Reverb menyimpan alpha terpisah seperti TenkaFuma?

TenkaFuma menyimpan warna dan alpha di Texture2D TERPISAH (<page> dan
<page>_alpha). Mengambil warnanya saja menghasilkan blok sampah merah/
hitam/putih di atas model. Sebelum menulis extractor, pastikan apakah
game ini punya pola yang sama.

Cara: buka satu bundle berisi Spine, daftar semua Texture2D, lalu periksa
apakah kanal alpha texture warna rata 255 (tanda alpha-nya terpisah).
"""
import io
import os
import struct
import sys

import UnityPy


def parse_text_asset(b):
    try:
        n = struct.unpack("<i", b[0:4])[0]
        if not (0 < n < 512):
            return None, None
        name = b[4:4 + n].decode("utf-8", "replace")
        pos = 4 + n
        pos += (4 - (pos % 4)) % 4
        size = struct.unpack("<i", b[pos:pos + 4])[0]
        if not (0 <= size <= len(b) - pos - 4):
            return name, None
        return name, b[pos + 4:pos + 4 + size]
    except Exception:
        return None, None


def main():
    root = "/srv/spine-assets/hazereverb-samples"
    for d in sorted(os.listdir(root)):
        fp = os.path.join(root, d, "__data")
        if not os.path.exists(fp):
            continue
        env = UnityPy.load(io.BytesIO(open(fp, "rb").read()))
        if not env.objects:
            continue

        names = []
        for obj in env.objects:
            if getattr(obj.type, "value", obj.type) == 49:
                nm, data = parse_text_asset(obj.get_raw_data())
                if nm:
                    names.append((nm, len(data or b"")))
        skels = [n for n, _ in names if n.lower().endswith((".skel", ".atlas"))]
        if not skels:
            continue

        print(f"\n=== {d} ===")
        print("  skeleton/atlas:", skels)

        # Daftar texture + statistik kanal alpha
        for obj in env.objects:
            if getattr(obj.type, "value", obj.type) != 28:
                continue
            try:
                dd = obj.read()
                nm = str(getattr(dd, "m_Name", "") or "")
                im = dd.image.convert("RGBA")
                ch = im.split()
                for ci, cname in enumerate("RGBA"):
                    if cname != "A":
                        continue
                    h = ch[ci].histogram()
                    tot = sum(h)
                    zero = h[0] / tot * 100
                    full = h[255] / tot * 100
                    print(f"  TEX {nm:36s} {im.size} alpha: 0={zero:.1f}% 255={full:.1f}%")
            except Exception as e:
                print("  TEX <gagal>", type(e).__name__, e)

        ada_alpha = any(n.lower().endswith("_alpha")
                        for obj in env.objects
                        if getattr(obj.type, "value", obj.type) == 28
                        for n in [str(getattr(obj.read(), "m_Name", "") or "")])
        print("  punya texture '_alpha':", ada_alpha)
        break  # cukup satu bundle berisi Spine


if __name__ == "__main__":
    sys.exit(main())
