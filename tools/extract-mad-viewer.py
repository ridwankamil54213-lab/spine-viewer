#!/usr/bin/env python3
"""Extract Make Drama (MAD) skins from the anyabot/MAD-Viewer content library.

MAD-Viewer (https://github.com/anyabot/MAD-Viewer) is a Next.js viewer whose
assets are NOT bundled: each skin is a folder of loose files under GitHub repos
`MAD-assets-1` / `MAD-assets-2`, described by `public/data/cdn.json` (a sticky
unit->bucket map) and listed by `public/data/skin_list.json` (the gallery index).

Per skin the folder holds `<Name>.skel` (Spine binary) + `<Name>.atlas` +
texture PNG pages (+ `spine.json`, a behaviour sidecar we ignore). The atlas
declares its page by the ORIGINAL name (`AF_CH0009.png`), so keep that name.

We copy each skin into `assets/mad-drama/<unit>/`, renaming the skeleton+atlas to
the unit name (the scanner pairs skel/atlas by stem and names the model from the
folder), and write thumbnails + a name map.

Library metadata: `public/data/skin_list.json` (key, kind, character, stores) and
`public/data/characters.json` (character code -> nameEn).

    /srv/venv-spine/bin/python tools/extract-mad-viewer.py            # all
    /srv/venv-spine/bin/python tools/extract-mad-viewer.py --limit 3  # test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request

REPO = os.environ.get("MAD_REPO", "/opt/re-targets/mad-viewer")
VIEW = os.environ.get("MAD_VIEW", "/opt/spine-viewer")
OUT = os.path.join(VIEW, "assets", "mad-drama")
THUMBS = os.path.join(VIEW, "public", "thumbs", "mad-drama")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
BUCKETS = {"1": "MAD-assets-1", "2": "MAD-assets-2"}


def load(name):
    return json.load(open(os.path.join(REPO, "public", "data", name), encoding="utf-8"))


def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def raw_bases(unit, units, cdn):
    """Candidate raw.githubusercontent base URLs for a unit (tries each bucket)."""
    b = units.get(unit)
    repos = [BUCKETS[b]] if b in BUCKETS else list(BUCKETS.values())
    ref = cdn["families"]["skins"]["buckets"][b]["ref"] if b in BUCKETS else "master"
    return [f"https://raw.githubusercontent.com/{cdn['owner']}/{r}/{ref}/skins/{unit}" for r in repos]


def unit_for(key, units):
    """Pick the unit that actually exists in cdn.json. Prefer uncensored onestore."""
    cands = [key + "__onestore", key + "__google", key]
    present = [c for c in cands if c in units]
    return present[0] if present else None


def grab_skin(skin, units, cdn, out):
    key = skin["key"]
    unit = unit_for(key, units)
    if not unit:
        return key, None, "no unit in cdn.json"
    bases = raw_bases(unit, units, cdn)
    last = "no source"
    for base in bases:
        try:
            listing = json.loads(fetch(f"{base}/files.json"))
            files = [f for f in listing.get("files", []) if isinstance(f, str) and "/" not in f]
            if not any(f.lower().endswith((".skel", ".json")) and f != "spine.json" for f in files):
                return key, None, "no skeleton in files.json"
            blobs = {}
            for f in files:
                blobs[f] = fetch(f"{base}/{urllib.parse.quote(f)}")
            # write: skeleton+atlas renamed to the unit, textures verbatim.
            # `spine.json` is a behaviour sidecar, NOT a skeleton — the scanner
            # treats every .json as a skeleton, so copying it would add a broken
            # phantom model next to the real one.
            dst = os.path.join(out, unit)
            os.makedirs(dst, exist_ok=True)
            skel = next((f for f in files if f.lower().endswith((".skel", ".json")) and f != "spine.json"), None)
            atlas = next((f for f in files if f.lower().endswith(".atlas")), None)
            if not skel or not atlas:
                return key, None, "missing skel/atlas"
            open(os.path.join(dst, unit + os.path.splitext(skel)[1]), "wb").write(blobs[skel])
            open(os.path.join(dst, unit + ".atlas"), "wb").write(blobs[atlas])
            for f in files:
                if f in (skel, atlas, "spine.json"):
                    continue
                open(os.path.join(dst, f), "wb").write(blobs[f])
            return key, unit, None
        except Exception as e:  # noqa: BLE001
            last = str(e)[:120]
    return key, None, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated skin keys")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    skins = load("skin_list.json")["skins"]
    cdn = load("cdn.json")
    chars = load("characters.json")["characters"]
    units = cdn["families"]["skins"]["units"]

    if a.only:
        want = set(a.only.split(","))
        skins = [s for s in skins if s["key"] in want]
    if a.limit:
        skins = skins[: a.limit]

    os.makedirs(OUT, exist_ok=True)
    os.makedirs(THUMBS, exist_ok=True)

    names = {}
    manifest = {}
    icon_dir = os.path.join(REPO, "public", "icons", "skin")
    icons = set(os.listdir(icon_dir)) if os.path.isdir(icon_dir) else set()

    def handle(s):
        key = s["key"]
        k, unit, err = grab_skin(s, units, cdn, OUT)
        if err:
            return key, None, None, err
        # thumbnail: the library's shared Thumbnail_<inner>.webp, keyed per unit
        inner = key.split("__")[0]
        thumb = next((c for c in (f"Thumbnail_{inner.upper()}.webp", f"Thumbnail_Icon_{inner.upper()}.webp") if c in icons), None)
        char = chars.get(s.get("character"), {})
        nm = {
            "name": char.get("nameEn") or char.get("name") or key,
            "kind": s.get("kind"),
            "store": unit.split("__")[1] if "__" in unit else None,
            "character": s.get("character"),
            "animations": s.get("animations"),
        }
        return key, unit, (thumb, nm), None

    results = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, r in enumerate(ex.map(handle, skins), 1):
            results.append(r)
            key, unit, extra, err = r
            if err:
                print(f"  [{i}/{len(skins)}] {key:26} GAGAL {err}", flush=True)
                continue
            thumb, nm = extra
            names[unit] = nm
            if thumb:
                shutil.copy(os.path.join(icon_dir, thumb), os.path.join(THUMBS, thumb))
                manifest[f"mad-drama/{unit}"] = thumb
            print(f"  [{i}/{len(skins)}] {unit:28} {nm['kind']:10} {nm['name'][:24]}", flush=True)

    if not a.only and not a.limit:
        json.dump(names, open(os.path.join(OUT, "_names.json"), "w"), ensure_ascii=False, indent=1)
        json.dump(manifest, open(os.path.join(THUMBS, "_manifest.json"), "w"), ensure_ascii=False, indent=1)
    print(f"\n  models: {len(names)}  thumbs: {len(manifest)}  out: {OUT}")


if __name__ == "__main__":
    main()
