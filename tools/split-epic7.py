#!/usr/bin/env python3
"""Pisahkan model Epic Seven menurut versi Spine-nya.

E7 menyimpan dua generasi skeleton dalam satu folder `model/`: mayoritas
lama (SCSP v2 -> Spine 2.1.27) dan sebagian baru (SCSP v3 -> Spine 3.8.99).
Keduanya butuh runtime berbeda:

    2.1.27  -> viewer legacy (pixi-spine tidak bisa menggambarnya)
    3.8.99  -> pixi-spine biasa

server.js memilih runtime lewat `spineRuntime` per GAME (berdasar prefix
id), jadi satu folder campuran tidak bisa dilayani dengan benar. Script ini
memindahkan model 3.8.99 ke folder sendiri sehingga tiap folder punya
satu versi dan bisa didaftarkan terpisah.

Pemakaian:
    /srv/venv-spine/bin/python tools/split-epic7.py
"""
import json
import os
import shutil
import sys

SRC = "/srv/spine-assets/epic7/spine_out"
DST = "/srv/spine-assets/epic7/spine_out_v3"


def spine_version(folder: str):
    p = os.path.join(folder, os.path.basename(folder) + ".json")
    if not os.path.exists(p):
        return None
    try:
        with open(p) as fh:
            return json.load(fh).get("skeleton", {}).get("spine")
    except Exception:
        return None


def main() -> int:
    if not os.path.isdir(SRC):
        sys.exit(f"{SRC} tidak ada")
    os.makedirs(DST, exist_ok=True)

    moved = 0
    kept = 0
    unknown = 0
    for name in sorted(os.listdir(SRC)):
        src = os.path.join(SRC, name)
        if not os.path.isdir(src):
            continue
        ver = spine_version(src)
        if ver is None:
            unknown += 1
            continue
        if ver.startswith("3."):
            dst = os.path.join(DST, name)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.move(src, dst)
            moved += 1
        else:
            kept += 1

    print(f"tetap (2.1.27) : {kept} -> {SRC}")
    print(f"pindah (3.8.99): {moved} -> {DST}")
    print(f"tak terbaca    : {unknown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
