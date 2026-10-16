#!/usr/bin/env python3
"""Integrate the BenNoSleep/czn-animation-viewer rigs into spine-viewer.

Each repo rig dir is  rigs/<slug>/{skeleton.json(gzip), skeleton.atlas, <page>.webp}
with the atlas referencing "<slug>.webp". The spine-viewer scanner keys a model
by its stem, so both skeleton.json and skeleton.atlas (stem "skeleton") collapse
to one name. Rename to the folder slug and gunzip the JSON:

    rigs/<slug>/  ->  <slug>.json  <slug>.atlas  <slug>.webp
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "/opt/re-targets/czn-repo/rigs"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/opt/spine-viewer/assets/czn-rigs"
CATALOG = sys.argv[3] if len(sys.argv) > 3 else "/opt/re-targets/czn-repo/index.json"


def _atlas_page(atlas_path):
    """Return the texture page name the atlas declares (line before 'size:')."""
    import re as _re
    try:
        lines = open(atlas_path, encoding="latin1").read().splitlines()
    except OSError:
        return None
    img = _re.compile(r"\.(png|webp|jpg|jpeg)$", _re.I)
    for i, ln in enumerate(lines):
        if i + 1 < len(lines) and _re.match(r"\s*size:", lines[i + 1]) and img.search(ln.strip()):
            return ln.strip()
    return None


def load_json(path) -> bytes:
    """Return plain UTF-8 JSON bytes, gunzipping if needed."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def main():
    os.makedirs(OUT, exist_ok=True)
    # slug -> metadata (name, kind, thumb) from the repo catalog
    meta = {}
    try:
        cat = json.load(open(CATALOG, encoding="utf-8"))
        for r in cat.get("rigs", []):
            meta[r.get("slug") or r.get("id")] = r
    except Exception as e:  # noqa: BLE001
        print("catalog skip:", e)

    n_ok = n_skip = 0
    names = {}
    # Preserve names already written (czn-rigs.py runs before czn-thumbs.py, but a
    # plain dump of only the new rigs would wipe the catalog).
    try:
        names = json.load(open(os.path.join(OUT, "_names.json"), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        names = {}
    for slug in sorted(os.listdir(SRC)):
        d = os.path.join(SRC, slug)
        if not os.path.isdir(d):
            continue
        files = os.listdir(d)
        sj = next((f for f in files if f.lower() in ("skeleton.json", "skeleton.skel") or f.lower().endswith(".json")), None)
        sa = next((f for f in files if f.lower().endswith(".atlas")), None)
        if not sj or not sa:
            n_skip += 1
            continue
        img = next((f for f in files if f.lower().endswith((".webp", ".png", ".jpg", ".jpeg"))), None)
        dest = os.path.join(OUT, slug)
        # skip if already done
        if os.path.exists(os.path.join(dest, slug + ".json")) and os.path.exists(os.path.join(dest, slug + ".atlas")):
            n_skip += 1
            continue
        os.makedirs(dest, exist_ok=True)
        js = load_json(os.path.join(d, sj))
        open(os.path.join(dest, slug + ".json"), "wb").write(js)
        shutil.copy(os.path.join(d, sa), os.path.join(dest, slug + ".atlas"))
        if img:
            # The atlas declares the page by its ORIGINAL name (e.g. 1001001.webp),
            # not after the folder slug, so keep that name or the viewer can't
            # resolve the texture (see tools/czn-fix-webp.py).
            page = _atlas_page(os.path.join(d, sa)) or img
            shutil.copy(os.path.join(d, img), os.path.join(dest, page))
        m = meta.get(slug, {})
        if m.get("name"):
            names[slug] = {"name": m.get("name"), "kind": m.get("kind"), "subtype": m.get("subtype")}
        n_ok += 1
    json.dump(names, open(os.path.join(OUT, "_names.json"), "w"), ensure_ascii=False, indent=1)
    print(f"rigs converted: {n_ok}  skipped: {n_skip}  names: {len(names)}")


if __name__ == "__main__":
    main()
