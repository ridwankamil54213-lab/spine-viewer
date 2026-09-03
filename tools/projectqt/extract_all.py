#!/usr/bin/env python3
"""Extract every Spine model found in Project QT bundles.

Unlike the first pass, this does NOT rely on the bundle name containing
"spine" — scan_bundles.py opens each bundle to check for a real skeleton +
atlas, which turned up many more models (e.g. Pet1018.unity3d).

Naming: most bundles store the skeleton under a generic name like
"skeleton.skel", so the model folder and files are named after the BUNDLE,
otherwise every model would collide on "skeleton.skel". The atlas is copied
under its original name because the atlas page references live inside it.

Output per model:
    <out>/<BundleStem>/<BundleStem>.skel
    <out>/<BundleStem>/<atlas original name>.atlas
    <out>/<BundleStem>/<texture names>.png
"""
import json
import os
import struct
import sys

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "2020.3.33f1"
TEXT_ASSET, TEXTURE2D = 49, 28


def parse_text_asset(raw):
    nl = struct.unpack_from("<i", raw, 0)[0]
    off = (4 + nl + 3) & ~3
    dl = struct.unpack_from("<i", raw, off)[0]
    off += 4
    return raw[off : off + dl]


def extract_one(src, stem, out):
    env = UnityPy.load(src)
    skels = {}
    atlases = {}
    texs = []

    for obj in env.objects:
        tid = str(obj.type)
        if tid == str(TEXT_ASSET):
            try:
                d = obj.read()
            except Exception:
                continue
            name = d.m_Name or ""
            data = parse_text_asset(obj.get_raw_data())
            if name.lower().endswith(".skel"):
                skels[name] = data
            elif name.lower().endswith(".json"):
                skels[name] = data
            elif name.lower().endswith(".atlas"):
                atlases[name] = data
        elif tid == str(TEXTURE2D):
            try:
                d = obj.read()
                if d.image is not None:
                    texs.append((d.m_Name or "skeleton", d.image))
            except Exception:
                continue

    if not skels or not atlases:
        return "no skeleton+atlas"

    d = os.path.join(out, stem)
    os.makedirs(d, exist_ok=True)

    # One skeleton per bundle in practice; if a bundle held several, suffix them.
    for i, (skel_name, payload) in enumerate(sorted(skels.items())):
        target = f"{stem}.skel" if i == 0 else f"{stem}_{i}.skel"
        ext = os.path.splitext(skel_name)[1].lower() or ".skel"
        target = os.path.splitext(target)[0] + ext
        with open(os.path.join(d, target), "wb") as f:
            f.write(payload)

    for atlas_name, payload in atlases.items():
        with open(os.path.join(d, atlas_name), "wb") as f:
            f.write(payload)

    for tname, img in texs:
        try:
            img.save(os.path.join(d, tname + ".png"))
        except Exception:
            continue
    return None


def main():
    src_dir = sys.argv[1]
    out_dir = sys.argv[2]
    report = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(out_dir, exist_ok=True)

    # Only extract bundles scan_bundles.py confirmed hold a Spine model.
    targets = None
    if report and os.path.exists(report):
        targets = set()
        for line in open(report, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            targets.add(line.split("\t")[0])
        print(f"using report: {len(targets)} bundles")

    files = sorted(f for f in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, f)) and not f.startswith("_"))
    if targets is not None:
        files = [f for f in files if f in targets]

    ok = fail = 0
    errors = []
    for i, f in enumerate(files, 1):
        stem = os.path.splitext(f)[0]
        try:
            err = extract_one(os.path.join(src_dir, f), stem, out_dir)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        if err:
            fail += 1
            errors.append(f"{stem}: {err}")
        else:
            ok += 1
        if i % 100 == 0 or i == len(files):
            print(f"  {i}/{len(files)} ok={ok} fail={fail}", flush=True)

    print(f"\nDONE ok={ok} fail={fail}")
    if errors:
        with open(os.path.join(out_dir, "_errors.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(errors))
        for e in errors[:10]:
            print("  " + e)


if __name__ == "__main__":
    main()
