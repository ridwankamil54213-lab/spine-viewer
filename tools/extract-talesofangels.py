#!/usr/bin/env python3
"""Extract Spine skeletons from Tales of Angels (res.magetale.net) bundles.

Tales of Angels ships its resources as content-addressed Unity AssetBundles:
`data.json` lists every file with a hash name, a size and an md5. The Spine
models are not loose files — each is a bundle holding

    <Name>.skel   (TextAsset)
    <Name>.atlas  (TextAsset)
    <Name>        (Texture2D, referenced by the atlas' page line)

so both a UnityBundle reader and an atlas/texture pairing step are needed.

Two things that are easy to get wrong and are handled here:

1. Every downloaded file carries a small header before the real `UnityFS`
   magic (27-39 bytes, an in-house framing). UnityPy needs the payload to
   start at `UnityFS`, so trim to the first occurrence of the magic.

2. A bundle whose raw bytes merely contain the ASCII ".skel" is not
   necessarily a Spine bundle — binary garbage produces the same four
   bytes. Filter on the Spine-Unity `SkeletonData` marker instead, which
   only appears in the real asset bundles (it caught ~460 bundles the
   naive `.skel` filter misses).

Usage:
    pip install UnityPy Pillow
    python3 tools/extract-talesofangels.py --list-url <data.json url> --out assets/talesofangels

The bundles are ~2 GB and expand to ~1.5 GB, so pass --work for a scratch
directory on a volume with room; it is reused across runs.
"""

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import time

PAGE_RE = re.compile(r"^\S+\.(png|jpg|jpeg|webp)$", re.I)
SKEL_RE = re.compile(r"\.skel$", re.I)


def fetch_json(url, dest):
    if not os.path.exists(dest) or os.path.getsize(dest) < 1024:
        print(f"[1/5] fetching {url}")
        subprocess.run(["curl", "-fsSL", "--max-time", "120", "-o", dest, url], check=True)
    return json.load(open(dest))


def download_bundles(data, base, raw):
    """Download every entry into <raw>/<name> (name already contains a shard dir)."""
    files = data["files"]
    cfg = os.path.join(raw, "_curl.cfg")
    if not os.path.exists(cfg):
        os.makedirs(raw, exist_ok=True)
        lines = ["--create-dirs", "--fail", "--location", "--silent", "--show-error"]
        for f in files:
            lines.append(f'url = "{base}/{f["name"]}"')
            lines.append(f'output = "{raw}/{f["name"]}"')
        open(cfg, "w").write("\n".join(lines) + "\n")
    have = sum(1 for f in files if os.path.exists(os.path.join(raw, f["name"])))
    print(f"[2/5] downloading {len(files)} files ({have} already present)")
    if have == len(files):
        return
    subprocess.run(
        ["curl", "-K", cfg, "--parallel", "--parallel-max", "24",
         "--retry", "4", "--retry-delay", "2", "--retry-all-errors", "--max-time", "300"],
        check=True,
    )


def find_candidates(raw):
    """Bundles whose data contains the Spine-Unity SkeletonData marker."""
    allf = []
    for dp, _, fs in os.walk(raw):
        for f in fs:
            if not f.startswith("_curl"):
                allf.append(os.path.join(dp, f))
    allf.sort()
    print(f"[3/5] scanning {len(allf)} bundles for Spine markers")
    out = []
    for p in allf:
        try:
            b = open(p, "rb").read()
        except OSError:
            continue
        if b"SkeletonData" in b or b".skel" in b or b".atlas" in b:
            out.append(p)
    print(f"      {len(out)} candidate bundles")
    return out


def atlas_pages(txt):
    """Page filenames: a bare filename immediately followed by a `size:` line."""
    pages, lines = [], txt.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if PAGE_RE.match(s) and i + 1 < len(lines) and lines[i + 1].strip().lower().startswith("size:"):
            pages.append(s)
    return pages


def extract(cands, out_dir):
    import UnityPy  # imported here so --help works without the dependency

    os.makedirs(out_dir, exist_ok=True)
    models = collections.Counter()
    stats = collections.Counter()
    t0 = time.time()

    for idx, p in enumerate(cands, 1):
        raw = open(p, "rb").read()
        off = raw.find(b"UnityFS")          # trim the in-house framing header
        if off < 0:
            stats["no_magic"] += 1
            continue
        try:
            env = UnityPy.load(raw[off:])
        except Exception:
            stats["load_fail"] += 1
            continue

        skels, atlases, texs = [], {}, {}
        for o in env.objects:
            try:
                if o.type.name == "TextAsset":
                    d = o.read()
                    nm = getattr(d, "m_Name", "") or ""
                    data = d.m_Script
                    if isinstance(data, str):
                        data = data.encode("utf-8", "surrogateescape")
                    low = nm.lower()
                    if low.endswith(".skel"):
                        skels.append((SKEL_RE.sub("", nm), data))
                    elif low.endswith((".atlas", ".atlas.txt")):
                        key = re.sub(r"\.atlas(\.txt)?$", "", nm, flags=re.I)
                        atlases[key] = data.decode("utf-8", "replace")
                elif o.type.name == "Texture2D":
                    d = o.read()
                    texs[getattr(d, "m_Name", "") or ""] = d
            except Exception:
                stats["obj_fail"] += 1

        for stem, skel_bytes in skels:
            at = atlases.get(stem)
            if at is None:
                same = [v for k, v in atlases.items() if k.lower() == stem.lower()]
                at = same[0] if same else next(iter(atlases.values()), None)
            if at is None:
                stats["skel_without_atlas"] += 1
                continue

            d = os.path.join(out_dir, stem)
            prev = os.path.join(d, stem + ".skel")
            if os.path.exists(prev) and os.path.getsize(prev) >= len(skel_bytes):
                continue                     # keep the largest skeleton per stem
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, stem + ".skel"), "wb").write(skel_bytes)
            open(os.path.join(d, stem + ".atlas"), "w").write(at)

            for page in (atlas_pages(at) or [stem + ".png"]):
                want = re.sub(r"\.(png|jpg|jpeg|webp)$", "", page, flags=re.I).lower()
                src = None
                for tn, tobj in texs.items():
                    if re.sub(r"\.(png|jpg|jpeg|webp)$", "", tn, flags=re.I).lower() == want:
                        src = tobj
                        break
                if src is None and texs:
                    src = next(iter(texs.values()))
                if src is None:
                    stats["missing_texture"] += 1
                    continue
                try:
                    src.image.save(os.path.join(d, page))
                except Exception:
                    stats["tex_save_fail"] += 1
            models[stem] += 1

        if idx % 100 == 0:
            print(f"      {idx}/{len(cands)}  models={len(models)}  {time.time()-t0:.0f}s")

    print(f"[4/5] extracted {len(models)} models -> {out_dir}")
    print(f"      stats: {dict(stats)}")
    return models


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-url", required=True, help="URL of the res data.json")
    ap.add_argument("--out", default="assets/talesofangels")
    ap.add_argument("--work", default="/tmp/toa", help="scratch dir for downloads")
    args = ap.parse_args()

    os.makedirs(args.work, exist_ok=True)
    data = fetch_json(args.list_url, os.path.join(args.work, "data.json"))
    # data.json paths are relative to .../<ver>/<platform>/data/
    base = args.list_url.split("?")[0].rsplit("/", 2)[0]
    raw = os.path.join(args.work, "raw")
    print(f"      resVer={data.get('resVer')} files={data.get('fileCount')} "
          f"size={data.get('dataTotalSize')/1024**3:.2f} GiB")

    download_bundles(data, base, raw)
    cands = find_candidates(raw)
    extract(cands, args.out)
    print("[5/5] done — restart the viewer to pick the new models up")


if __name__ == "__main__":
    sys.exit(main())
