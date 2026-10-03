#!/usr/bin/env python3
"""Extract Spine skeletons from 蜜桃乌托邦 `rawdata_spine_*` AssetBundles.

Each bundle holds one or more complete Spine sets:

    TextAsset  "<id>.skel"   binary skeleton (Spine 4.2.x)
    TextAsset  "<id>.atlas"  atlas descriptor
    Texture2D  "<id>"        atlas page image

IMPORTANT: one character has MANY different skeletons, one per bundle variant —
`..._spine_back_10001`, `..._spine_front_10001`, `..._spine_equip_10001`, ...
and each carries a *different* .skel (verified: 9 bundles for id 10001 all have
distinct skeleton hashes). Keying the output folder on the numeric id alone
silently collapses them (9 bundles -> 1 model = data loss). The variant is part
of the bundle name, so it must be part of the output key:

    <out>/<game>/<variant>_<title>/<title>.skel
    <out>/<game>/<variant>_<title>/<title>.atlas
    <out>/<game>/<variant>_<title>/<title>.png

A single bundle may also hold several skeletons (e.g. `loadingnested`); each one
gets its own folder.

Usage:
    extract-spine.py --bundles bundles --out /opt/spine-viewer/assets --game mitao-utopia
"""
import argparse
import collections
import glob
import io
import os
import re
import warnings

import UnityPy

warnings.filterwarnings("ignore")

# ..._rawdata_spine_<variant>_<id>.bundle
BUNDLE_RE = re.compile(r"rawdata_spine_(?P<variant>.+?)_(?P<id>\d+)(?:\.bundle)?$")


def slug(s):
    s = re.sub(r"[^A-Za-z0-9._\-]+", "-", str(s)).strip("-")
    return s or "model"


def get_text(d):
    data = getattr(d, "m_Script", None)
    if data is None:
        data = getattr(d, "script", None)
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    return data


def variant_of(bundle_path):
    """`..._rawdata_spine_back_10001.bundle` -> ('back', '10001')."""
    m = BUNDLE_RE.search(os.path.basename(bundle_path))
    return (m.group("variant"), m.group("id")) if m else ("misc", "0")


def process(path, out_root, game):
    """Return (models_written, files_written, note)."""
    variant, bundle_id = variant_of(path)

    env = UnityPy.load(path)
    texts, tex = [], []
    for o in env.objects:
        try:
            if o.type.name == "TextAsset":
                d = o.read()
                texts.append((getattr(d, "m_Name", "") or "", get_text(d)))
            elif o.type.name == "Texture2D":
                d = o.read()
                tex.append((getattr(d, "m_Name", "") or "", d))
        except Exception:
            continue

    if not texts:
        return 0, 0, "no TextAsset (not a skeleton bundle)"

    # Pair "<title>.skel" with "<title>.atlas" by their shared base name.
    groups = collections.defaultdict(dict)
    for name, data in texts:
        low = name.lower()
        stem = os.path.splitext(name)[0]
        if low.endswith(".skel") or low.endswith(".json"):
            groups[stem]["skel"] = (name, data)
        elif low.endswith(".atlas") or low.endswith(".atlas.txt"):
            groups[stem]["atlas"] = (name, data)

    models = files = 0
    for title_raw, parts in groups.items():
        if "skel" not in parts or "atlas" not in parts:
            continue

        title = slug(title_raw)
        # The variant distinguishes otherwise identical model ids.
        key = slug(f"{variant}_{title}")
        mdir = os.path.join(out_root, game, key)
        os.makedirs(mdir, exist_ok=True)

        ext = ".json" if parts["skel"][0].lower().endswith(".json") else ".skel"
        open(os.path.join(mdir, f"{title}{ext}"), "wb").write(parts["skel"][1])
        open(os.path.join(mdir, f"{title}.atlas"), "wb").write(parts["atlas"][1])
        files += 2

        # Atlas page image -> "<title>.png" (the name the descriptor references).
        page = None
        for tname, timg in tex:
            if tname == title or tname.startswith(title):
                page = timg
                break
        if page is None and len(tex) == 1:
            page = tex[0][1]
        if page is not None:
            try:
                img = page.image
                if img is not None:
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    open(os.path.join(mdir, f"{title}.png"), "wb").write(buf.getvalue())
                    files += 1
            except Exception as e:
                return models, files, f"texture failed for {title}: {e}"
        models += 1
    return models, files, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles", default="bundles")
    ap.add_argument("--out", required=True, help="assets root (game subdir is appended)")
    ap.add_argument("--game", default="mitao-utopia")
    ap.add_argument("--glob", default="*rawdata_spine_*")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.bundles, args.glob)))
    if args.limit:
        files = files[:args.limit]
    out_dir = os.path.join(args.out, args.game)
    print(f"bundle : {len(files)}")
    print(f"output : {out_dir}\n")

    tot_m = tot_f = 0
    notes = []
    for i, f in enumerate(files, 1):
        try:
            m, n, note = process(f, args.out, args.game)
            tot_m += m
            tot_f += n
            if note:
                notes.append((os.path.basename(f), note))
        except Exception as e:
            notes.append((os.path.basename(f), str(e)))
        if i % 25 == 0 or i == len(files):
            print(f"[{i}/{len(files)}] model={tot_m} file={tot_f} catatan={len(notes)}")

    print(f"\nSELESAI model={tot_m} file={tot_f}  ->  {out_dir}")
    if notes:
        print(f"\ncatatan ({len(notes)}):")
        for n, e in notes[:15]:
            print(f"  {n}: {e[:90]}")


if __name__ == "__main__":
    main()
