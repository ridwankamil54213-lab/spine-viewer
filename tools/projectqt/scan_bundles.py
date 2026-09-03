#!/usr/bin/env python3
"""Scan Project QT bundles and report which contain a Spine model.

The filename is NOT a reliable signal: only 86 of 1930 bundles say "spine",
but character bundles are named things like "1001_action.unity3d". So this
opens every bundle and checks whether it actually holds a skeleton + atlas.

Opening 1930 bundles fully is slow, so the first pass reads just the asset
names out of each UnityFS (cheap) and only loads objects for the candidates.
"""
import os
import sys

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "2020.3.33f1"
TEXT_ASSET, TEXTURE2D = 49, 28


def bundle_has_spine(path):
    """True when the bundle holds a .skel/.json plus an .atlas."""
    try:
        env = UnityPy.load(path)
    except Exception:
        return None, "load failed"

    names = []
    has_tex = False
    for obj in env.objects:
        tid = str(obj.type)
        if tid == str(TEXT_ASSET):
            try:
                names.append(obj.read().m_Name or "")
            except Exception:
                pass
        elif tid == str(TEXTURE2D):
            if not has_tex:
                try:
                    has_tex = obj.read().image is not None
                except Exception:
                    pass

    skels = [n for n in names if n.lower().endswith((".skel", ".json"))]
    atlases = [n for n in names if n.lower().endswith(".atlas")]
    if skels and atlases:
        return (skels[0], atlases[0], len(names), has_tex), None
    return None, "no skeleton+atlas"


def main():
    src = sys.argv[1]
    report = sys.argv[2] if len(sys.argv) > 2 else None

    files = sorted(f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f)) and not f.startswith("_"))
    hits = {}
    nofit = 0
    errors = []

    for i, f in enumerate(files, 1):
        info, err = bundle_has_spine(os.path.join(src, f))
        if info:
            hits[f] = info
        elif err == "load failed":
            errors.append(f)
        else:
            nofit += 1
        if i % 100 == 0 or i == len(files):
            print(f"  {i}/{len(files)} spine={len(hits)} empty={nofit} err={len(errors)}", flush=True)

    print(f"\nbundles scanned : {len(files)}")
    print(f"with Spine model: {len(hits)}")
    print(f"without         : {nofit}")
    print(f"load errors     : {len(errors)}")

    if report:
        with open(report, "w", encoding="utf-8") as fh:
            for k, v in sorted(hits.items()):
                fh.write(f"{k}\t{v[0]}\t{v[1]}\t{v[2]}\t{v[3]}\n")
            if errors:
                fh.write("\n# load errors\n")
                for e in errors:
                    fh.write(f"{e}\n")
        print("report:", report)


if __name__ == "__main__":
    main()
