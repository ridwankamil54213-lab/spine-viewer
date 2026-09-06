#!/usr/bin/env python3
"""Validasi: apakah filter grep '.skel' melewatkan bundle berisi Spine?

Kekhawatiran: bundle UnityFS terkompresi, jadi string bernama
"dongzuo_juese_aertaiya.skel" bisa saja tidak muncul sebagai teks utuh
dan grep melewatkan bundle yang sebenarnya berisi skeleton.

Cara menguji: buka SEMUA bundle dengan UnityPy (sumber kebenaran),
bandingkan dengan daftar hasil grep.

Ini membaca tiap header bundle — jauh lebih cepat daripada mengekspor
texture, tapi tetap perlu waktu untuk ratusan file.
"""
import io
import os
import struct
import sys

import UnityPy

ROOT = "/srv/spine-assets/hazereverb-raw"
GREP_LIST = "/srv/spine-assets/hazereverb-bundles.txt"


def parse_text_asset(b):
    try:
        n = struct.unpack("<i", b[0:4])[0]
        if not (0 < n < 512):
            return None
        name = b[4:4 + n].decode("utf-8", "replace")
        pos = 4 + n
        pos += (4 - (pos % 4)) % 4
        size = struct.unpack("<i", b[pos:pos + 4])[0]
        if not (0 <= size <= len(b) - pos - 4):
            return name
        return name
    except Exception:
        return None


def main():
    limit = int(os.environ.get("LIMIT", "0"))
    bundles = []
    for dirpath, _d, files in os.walk(ROOT):
        if "__data" in files:
            bundles.append(os.path.join(dirpath, "__data"))
    bundles.sort()
    if limit:
        bundles = bundles[:limit]

    # daftar hasil grep, dinormalisasi ke path relatif
    grep = set()
    if os.path.exists(GREP_LIST):
        for line in open(GREP_LIST):
            line = line.strip().replace("/__data", "")
            if line:
                grep.add(os.path.basename(line))
                # simpan juga "folder/file" untuk pencocokan longgar
                parts = line.split("/")
                if len(parts) >= 2:
                    grep.add(parts[-2])

    print("bundle di host:", len(bundles))
    print("daftar grep   :", len(grep))
    print()

    with_spine = []
    without = []
    for i, p in enumerate(bundles, 1):
        try:
            env = UnityPy.load(io.BytesIO(open(p, "rb").read()))
        except Exception:
            continue
        if not env.objects:
            continue
        names = []
        for obj in env.objects:
            if getattr(obj.type, "value", obj.type) == 49:
                nm = parse_text_asset(obj.get_raw_data())
                if nm:
                    names.append(nm)
        skels = [n for n in names if n.lower().endswith((".skel", ".json"))]
        rel = os.path.relpath(p, ROOT)
        folder = os.path.basename(os.path.dirname(p))
        if skels:
            with_spine.append((rel, skels))
        else:
            without.append(rel)
        if i % 50 == 0:
            print(f"  ...{i}/{len(bundles)} (spine={len(with_spine)})", flush=True)

    print()
    print("=== HASIL ===")
    print("bundle berisi skeleton :", len(with_spine))
    print("bundle tanpa skeleton  :", len(without))

    # apakah ada yang TIDAK ada di daftar grep?
    missed = [(r, s) for r, s in with_spine
              if os.path.basename(os.path.dirname(r)) not in grep]
    print("\nbundle berisi skeleton tapi TIDAK ada di daftar grep:", len(missed))
    for r, s in missed[:10]:
        print("   ", r, "->", s[:3])


if __name__ == "__main__":
    sys.exit(main())
