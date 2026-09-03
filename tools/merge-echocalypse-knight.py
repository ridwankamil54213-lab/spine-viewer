#!/usr/bin/env python3
"""Merge ONLY the Echocalypse knight_spine models from every source.

Character art is the part people actually want; effect/pet/back/UI spines
are mostly VFX and can be added later on demand.

Four layers, later overwrites earlier (per the Live2DHub guide):
    base.apk         assets/res/common/knight_spine
    files/obb/res/common/knight_spine
    files/upgrade/res/common/knight_spine
    files/upgradelang/res/.../knight_spine

Each model is one folder holding .skel + .atlas + .png, so merging is a
plain recursive copy.
"""
import os
import shutil
import sys

BASE = "/srv/redroid/data14/data/com.yoozoo.jgame.us.qooapp/files"
OUT = "/srv/spine-assets/echocalypse-knight"

SRC = [
    ("/srv/spine-assets/echocalypse/knight_spine", "apk"),
    (f"{BASE}/obb/res/common/knight_spine", "obb"),
    (f"{BASE}/upgrade/res/common/knight_spine", "upgrade"),
]
# upgradelang has no "common" level -- walk it for any knight_spine folder.
EXTRA = [f"{BASE}/upgradelang/res"]

KEEP = (".skel", ".atlas", ".png", ".jpg", ".jpeg", ".webp")


def copy_tree(src, name, models):
    n = 0
    for dp, _, fs in os.walk(src):
        for f in fs:
            if not f.lower().endswith(KEEP):
                continue
            s = os.path.join(dp, f)
            rel = os.path.relpath(s, src)
            d = os.path.join(OUT, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s):
                models.add(os.path.dirname(rel) or ".")
                continue
            shutil.copy2(s, d)
            n += 1
            models.add(os.path.dirname(rel) or ".")
    print(f"  {name:10s} {n:6d} file")
    return n


def main():
    os.makedirs(OUT, exist_ok=True)
    models = set()
    for src, name in SRC:
        if not os.path.isdir(src):
            print(f"  [skip] {name}: {src} tidak ada")
            continue
        copy_tree(src, name, models)

    # upgradelang: cari folder knight_spine di mana saja
    for root in EXTRA:
        if not os.path.isdir(root):
            print(f"  [skip] upgradelang: {root} tidak ada")
            continue
        found = 0
        for dp, dns, _ in os.walk(root):
            if os.path.basename(dp) == "knight_spine":
                found += copy_tree(dp, "upgradelang", models)
        if not found:
            print("  upgradelang: tidak ada knight_spine")

    n_skel = sum(1 for dp, _, fs in os.walk(OUT) for f in fs
                 if f.lower().endswith(".skel"))
    print(f"\nmodel folder : {len([m for m in models if m != '.'])}")
    print(f"total .skel  : {n_skel}")
    return n_skel


if __name__ == "__main__":
    main()
