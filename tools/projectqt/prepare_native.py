#!/usr/bin/env python3
"""Prepare original (un-converted) Spine 2.1.27 models for the viewer.

The pixi-spine 3.8 runtime cannot render these: its weighted-mesh path
desynchronises on the 5-11 bones-per-vertex these models use, so vertices
land thousands of units away (the visible "scramble"). The data itself is
fine — verified by loading the ORIGINAL .skel in a native 2.1.27 viewer,
where every model renders correctly.

So instead of converting, extract the originals as-is:

    <bundle>.unity3d -> <out>/<Name>/<Name>.skel
                        <out>/<Name>/<Name>.atlas
                        <out>/<Name>/skeleton.png [+ more pages]

The viewer then routes this game to the native 2.1.27 runtime instead of
pixi-spine.
"""
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
    skel = None
    atlas = None
    texs = []
    for obj in env.objects:
        tid = str(obj.type)
        if tid == str(TEXT_ASSET):
            try:
                d = obj.read()
            except Exception:
                continue
            data = parse_text_asset(obj.get_raw_data())
            name = d.m_Name or ""
            if name.endswith(".skel"):
                skel = data
            elif name.endswith(".atlas"):
                atlas = data
        elif tid == str(TEXTURE2D):
            try:
                d = obj.read()
                if d.image is not None:
                    texs.append((d.m_Name or "skeleton", d.image))
            except Exception:
                continue

    if not skel or not atlas:
        return "no skeleton/atlas"

    d = os.path.join(out, stem)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, stem + ".skel"), "wb") as f:
        f.write(skel)
    with open(os.path.join(d, stem + ".atlas"), "wb") as f:
        f.write(atlas)
    for tname, img in texs:
        try:
            img.save(os.path.join(d, tname + ".png"))
        except Exception:
            continue
    return None


def main():
    src_dir = sys.argv[1]
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(f for f in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, f)))
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
        if i % 25 == 0 or i == len(files):
            print(f"  {i}/{len(files)} ok={ok} fail={fail}", flush=True)

    print(f"\nDONE ok={ok} fail={fail}")
    if errors:
        with open(os.path.join(out_dir, "_errors.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(errors))
        for e in errors[:10]:
            print("  " + e)


if __name__ == "__main__":
    main()
