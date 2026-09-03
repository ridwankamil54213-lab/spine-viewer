#!/usr/bin/env python3
"""Extract Spine models from Depose Girls Unity bundles.

Each spine_*_prefab bundle is a UnityFS archive holding:
    TextAsset   <Name>.skel     - binary skeleton
    TextAsset   <Name>.atlas    - texture atlas descriptor
    Texture2D   <Name>          - the atlas page

Everything else in the bundle (MonoBehaviour SkeletonDataAsset, prefab
GameObject hierarchy, materials) is Unity scaffolding the web viewer can't
use, so it's dropped.

WHY get_raw_data() INSTEAD OF obj.read().m_Script
    UnityPy decodes TextAsset.m_Script into a `str`, which corrupts binary
    payloads (the .skel). get_raw_data() returns untouched bytes; we then
    parse Unity's TextAsset layout ourselves:

        int32  name_len
        char[] name            (padded to 4)
        int32  data_len
        byte[] data

OUTPUT LAYOUT
    <out>/<ModelName>/<ModelName>.skel
    <out>/<ModelName>/<ModelName>.atlas
    <out>/<ModelName>/<ModelName>.png

    One folder per model is exactly the shape the viewer's scanner expects
    (a folder holding a skeleton + atlas is one model).

Textures are saved as-is. Unity's Texture2D formats here are DXT/ETC/BC7
compressed; UnityPy's .image conversion decodes them to plain RGBA PNGs,
which is what the browser needs.

Run with the venv that has UnityPy + Pillow:
    /root/venv-ls/bin/python tools/deposegirls/extract.py --src ... --out ...
"""
import argparse
import json
import os
import struct
import sys
import traceback

import UnityPy

TEXT_ASSET = 49
TEXTURE2D = 28
SPINE_EXTS = (".skel", ".atlas", ".json")


def type_id(obj) -> int:
    """Numeric Unity class id (ClassIDType enum | int | numeric str)."""
    t = obj.type
    try:
        v = getattr(t, "value", t)
        if isinstance(v, int):
            return v
        s = str(v)
        return int(s) if s.isdigit() else -1
    except Exception:
        return -1


def safe(name: str) -> str:
    """Keep only the basename, so a path-like asset name can't escape."""
    return os.path.basename(str(name)).replace("\\", "/").split("/")[-1].strip()


def parse_text_asset(raw: bytes):
    """Unity TextAsset: int32 name_len, name (4-aligned), int32 size, data."""
    try:
        name_len = struct.unpack_from("<i", raw, 0)[0]
        if not 0 <= name_len < len(raw):
            return None
        off = 4 + name_len
        off = (off + 3) & ~3  # pad to 4-byte boundary
        if off + 4 > len(raw):
            return None
        data_len = struct.unpack_from("<i", raw, off)[0]
        off += 4
        if not 0 <= data_len <= len(raw) - off:
            return None
        return raw[off : off + data_len]
    except Exception:
        return None


def extract_bundle(path: str, out: str):
    """Returns (model_name, files_written) or raises."""
    env = UnityPy.load(path)
    texts = []   # (name, bytes)
    images = []  # (name, Image)

    for obj in env.objects:
        tid = type_id(obj)
        try:
            if tid == TEXT_ASSET:
                data = obj.read()
                name = safe(getattr(data, "m_Name", "") or "")
                if not name:
                    continue
                raw = obj.get_raw_data()
                payload = parse_text_asset(raw)
                if payload is None:
                    continue
                texts.append((name, payload))
            elif tid == TEXTURE2D:
                data = obj.read()
                name = safe(getattr(data, "m_Name", "") or "")
                img = data.image
                if name and img is not None:
                    images.append((name, img))
        except Exception:
            # One unreadable object shouldn't kill the whole bundle.
            continue

    # Only keep models that have BOTH a skeleton and an atlas.
    skels = {n: b for n, b in texts if n.lower().endswith((".skel", ".json"))}
    atlases = {n: b for n, b in texts if n.lower().endswith(".atlas")}
    if not skels or not atlases:
        return None

    written = []
    for skel_name, payload in skels.items():
        stem = os.path.splitext(skel_name)[0]
        atlas_name = stem + ".atlas"
        if atlas_name not in atlases:
            continue

        model_dir = os.path.join(out, stem)
        os.makedirs(model_dir, exist_ok=True)

        with open(os.path.join(model_dir, safe(skel_name)), "wb") as f:
            f.write(payload)
        with open(os.path.join(model_dir, atlas_name), "wb") as f:
            f.write(atlases[atlas_name])

        # Multi-page atlases: a model can ship several textures named
        # "<Stem>", "<Stem>2", "<Stem>3" — the atlas lists every one of them
        # and a missing page renders the model invisible. Match any texture
        # whose name starts with the model stem rather than only exact hits.
        pages = 0
        for img_name, img in images:
            if not os.path.splitext(img_name)[0].startswith(stem):
                continue
            try:
                img.save(os.path.join(model_dir, safe(img_name) + ".png"))
                pages += 1
            except Exception:
                continue
        written.append({"model": stem, "pages": pages, "skel": skel_name})

    return written or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="directory of downloaded bundles")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", default=None, help="write a JSON report here")
    args = ap.parse_args()

    UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.20p1"
    os.makedirs(args.out, exist_ok=True)

    files = sorted(
        f for f in os.listdir(args.src) if os.path.isfile(os.path.join(args.src, f))
    )
    files = [f for f in files if not f.startswith("_")]
    if args.limit:
        files = files[: args.limit]

    ok = empty = failed = 0
    models = []
    errors = []

    for i, name in enumerate(files, 1):
        path = os.path.join(args.src, name)
        try:
            res = extract_bundle(path, args.out)
            if res:
                ok += 1
                models.extend(res)
            else:
                empty += 1
        except Exception as e:
            failed += 1
            errors.append(f"{name}: {e}\n{traceback.format_exc(limit=2)}")
        if i % 25 == 0 or i == len(files):
            print(
                f"  {i}/{len(files)}  ok={ok} empty={empty} "
                f"fail={failed} models={len(models)}",
                flush=True,
            )

    print(f"\nDONE bundles={len(files)} ok={ok} empty={empty} failed={failed}")
    print(f"models extracted: {len(models)}")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(
                {"models": models, "errors": errors},
                f,
                ensure_ascii=False,
                indent=1,
            )
        print(f"report: {args.report}")

    if errors:
        err_path = os.path.join(args.out, "_errors.txt")
        with open(err_path, "w", encoding="utf-8") as f:
            f.write("\n".join(errors))
        print(f"errors: {err_path}")


if __name__ == "__main__":
    main()
