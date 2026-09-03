#!/usr/bin/env python3
"""Convert Project QT Spine 2.1.27 skeletons to Spine 3.8 JSON.

SUPERSEDED -- DO NOT USE FOR THE VIEWER.

The conversion here is byte-faithful: triangles, UVs and weighted vertices
all come out identical to the 2.1.27 source. But the result STILL RENDERS
SCRAMBLED in pixi-spine 3.8. That runtime's weighted-mesh path desynchronises
on the 5-11 bones per vertex these models use, which is a runtime limitation
rather than a data problem -- proven by loading the ORIGINAL .skel in a native
2.1.27 viewer, where every model draws correctly.

The working approach is prepare_native.py: keep the original .skel files and
let the client route this game to vendor/spine2127.

Kept only as a record of what was tried.

Original approach, for the record:
    .skel (2.1.27 binary) + .atlas + texture pages
      -> spBinaryReader      -> skeleton data -> 2.1.27 JSON   (temp)
      -> spine21_to_spine38  -> 3.8.75 JSON                    (final)

    pixi-spine (4.0.6) ships runtimes for 3.7/3.8/4.0/4.1 only, so rather than
    writing a 2.x reader we reuse two upstream tools:
      - brachna/SpineConverter2.1.27  -> spBinaryReader (skel -> json 2.1.27)
      - dddyyy1024/...converter       -> 2.1.27 json -> 3.8 json
    The two repos ship slightly different spJsonReader signatures, so this
    script keeps dddyyy's copies of the shared modules and pulls ONLY
    spBinaryReader from brachna (the piece dddyyy removed).
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import UnityPy  # noqa: E402
from spBinaryReader import spBinaryReader  # noqa: E402
from spJsonWriter import spJsonWriter  # noqa: E402

UnityPy.config.FALLBACK_UNITY_VERSION = "2020.3.33f1"
TEXT_ASSET, TEXTURE2D = 49, 28
CONVERTER = os.path.join(HERE, "spine21_to_spine38.py")
PYTHON = "/root/venv-ls/bin/python"


def parse_text_asset(raw):
    nl = struct.unpack_from("<i", raw, 0)[0]
    off = (4 + nl + 3) & ~3
    dl = struct.unpack_from("<i", raw, off)[0]
    off += 4
    return raw[off : off + dl]


def read_bundle(path):
    """Pull (skel_bytes, atlas_name, atlas_bytes, [(tex_name, image)]) out."""
    env = UnityPy.load(path)
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
            name = d.m_Name or ""
            data = parse_text_asset(obj.get_raw_data())
            if name.endswith(".skel"):
                skel = data
            elif name.endswith(".atlas"):
                atlas = (name, data)
        elif tid == str(TEXTURE2D):
            try:
                d = obj.read()
                img = d.image
                if img is not None:
                    texs.append((d.m_Name or "skeleton", img))
            except Exception:
                continue
    return skel, atlas, texs


def cleanup_failed(d):
    """Remove a half-converted model folder.

    A failed conversion leaves _raw.skel behind, and the viewer scanner treats
    every folder under assets/ as a candidate -- so a leftover folder would
    show up as a broken model in the library. Clear it out instead.
    """
    try:
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        os.rmdir(d)
    except OSError:
        pass


def convert_one(src, name, out):
    skel, atlas, texs = read_bundle(src)
    if not skel or not atlas:
        return "no skeleton/atlas"

    d = os.path.join(out, name)
    os.makedirs(d, exist_ok=True)

    tmp_skel = os.path.join(d, "_raw.skel")
    tmp_json = os.path.join(d, "_raw21.json")
    with open(tmp_skel, "wb") as f:
        f.write(skel)
    data = spBinaryReader().readSkeletonDataFile(tmp_skel)
    spJsonWriter().writeSkeletonDataFile(data, tmp_json)

    atlas_name = atlas[0]
    with open(os.path.join(d, atlas_name), "wb") as f:
        f.write(atlas[1])

    for tname, img in texs:
        try:
            img.save(os.path.join(d, tname + ".png"))
        except Exception:
            continue

    final_json = os.path.join(d, name + ".json")
    r = subprocess.run(
        [PYTHON, CONVERTER, "_raw21.json", name + ".json", "--target-version", "3.8.75", "--copy-assets"],
        cwd=d,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not os.path.exists(final_json):
        return "converter failed: " + r.stderr[-200:]

    for t in (tmp_skel, tmp_json):
        try:
            os.remove(t)
        except OSError:
            pass
    return None


def main():
    src_dir = sys.argv[1]
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(f for f in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, f)))
    ok = fail = 0
    errors = []
    for i, f in enumerate(files, 1):
        name = os.path.splitext(f)[0]
        try:
            err = convert_one(os.path.join(src_dir, f), name, out_dir)
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
        if err:
            fail += 1
            errors.append("%s: %s" % (name, err))
            cleanup_failed(os.path.join(out_dir, name))
        else:
            ok += 1
        if i % 10 == 0 or i == len(files):
            print("  %d/%d ok=%d fail=%d" % (i, len(files), ok, fail), flush=True)

    print("\nDONE ok=%d fail=%d" % (ok, fail))
    if errors:
        with open(os.path.join(out_dir, "_errors.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(errors))
        print("errors -> %s" % os.path.join(out_dir, "_errors.txt"))
        for e in errors[:10]:
            print("  " + e)


if __name__ == "__main__":
    main()
