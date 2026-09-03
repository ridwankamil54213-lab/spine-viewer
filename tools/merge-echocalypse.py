#!/usr/bin/env python3
"""Merge Echocalypse Spine assets from every source into one tree.

The game ships its art in four layers, applied in this order (later
overwrites earlier) — straight from the Live2DHub guide:

    base.apk        assets/res/            (base data)
    files/obb/res                          (downloaded bundle)
    files/upgrade/res                      (hot update)
    files/upgradelang/res                  (localised hot update)

Skeletons are loose files one folder per model (*.skel + *.atlas + *.png),
so merging is a plain recursive copy — no UnityPy involved.

Only *_spine families are taken (knight/effect/pet/back/unite_token/
secretary/buff), which is where every skeleton lives.
"""
import os
import re
import shutil
import sys

# NOTE: the apk layer was extracted earlier and moved to /srv/spine-assets/
# echocalypse, so it is read from there. upgradelang has no "common" level.
BASE = "/srv/redroid/data14/data/com.yoozoo.jgame.us.qooapp/files"
SRC = [
    ("/srv/spine-assets/echocalypse", "apk"),
    (f"{BASE}/obb/res/common", "obb"),
    (f"{BASE}/upgrade/res/common", "upgrade"),
    (f"{BASE}/upgradelang/res", "upgradelang"),
]
OUT = "/srv/spine-assets/echocalypse-merged"

# Only these families hold skeletons.
FAMILIES = re.compile(
    r"(knight_spine|effect_spine|pet_spine|back_spine|unite_token_spine|"
    r"secretary_spine|buff_spine|battle)$"
)
KEEP = re.compile(r"\.(skel|atlas|png|jpg|jpeg|webp)$", re.I)


def merge():
    stats = {name: 0 for _, name in SRC}
    models = set()

    for root, name in SRC:
        if not os.path.isdir(root):
            print(f"  [skip] {name}: {root} tidak ada")
            continue
        n = 0
        for dp, dns, fs in os.walk(root):
            # Only descend into spine families (top-level group under common/)
            rel = os.path.relpath(dp, root)
            top = rel.split(os.sep)[0] if rel != "." else ""
            if rel != "." and not FAMILIES.search(top):
                continue
            for f in fs:
                if not KEEP.search(f):
                    continue
                src = os.path.join(dp, f)
                rel2 = os.path.relpath(src, root)
                dst = os.path.join(OUT, rel2)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # Later source wins; skip identical-size copies for speed.
                if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                    models.add(os.path.dirname(rel2))
                    continue
                shutil.copy2(src, dst)
                n += 1
                models.add(os.path.dirname(rel2))
        stats[name] = n
        print(f"  {name:12s} {n:6d} file disalin")

    print(f"\ntotal model folder: {len(models)}")
    skel = sum(1 for m in models if True)
    # Count actual skeletons on disk.
    n_skel = sum(
        1 for dp, _, fs in os.walk(OUT) for f in fs if f.lower().endswith(".skel")
    )
    print(f"total .skel       : {n_skel}")
    return n_skel


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    merge()
