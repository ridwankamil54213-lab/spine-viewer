#!/usr/bin/env python3
"""Download OrisRies asset bundles straight from the CDN.

The hot-update files on the device are incomplete: the game never fetches
the R18 CG / foreground bundles during a normal update (see
live2dhub.com/t/topic/3323). The catalog at

    /sdcard/Android/data/com.erolabs.orisries/files/data/art_<ver>.json

lists all ~25k bundles, so we diff it against filelistdata.txt (what the
device actually has) and pull the missing ones from:

    https://assets.orisries.playhorny.com/bundle/Android/art/<filename>

Bundles arrive AES-encrypted and are decrypted by tools/decrypt-orisries.py.

Usage:
    python3 tools/download-orisries.py --all-cg        # missing avgcg/avgfg
    python3 tools/download-orisries.py --missing 200   # first 200 missing
    python3 tools/download-orisries.py --grep avg      # only names matching

Run with the venv that has pycryptodome + requests:
    /srv/venv-spine/bin/python tools/download-orisries.py
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://assets.orisries.playhorny.com/bundle/Android/art/"
DATA = "/srv/spine-assets/orisries"
RAW = os.path.join(DATA, "hot_raw")
OUT = os.path.join(DATA, "cdn_raw")
DECRYPTED = os.path.join(DATA, "cdn_dec")


def catalog_bundles() -> list:
    """Every bundle filename the game's catalog knows about."""
    cats = [f for f in os.listdir(RAW) if f.startswith("art_") and f.endswith(".json")]
    if not cats:
        sys.exit(f"tidak ada art_*.json di {RAW}")
    cat = json.load(open(os.path.join(RAW, sorted(cats)[-1]), encoding="utf-8-sig"))
    names = set()
    for i in cat.get("m_InternalIds", []):
        if isinstance(i, str):
            names.add(i.rsplit("/", 1)[-1])
    return sorted(names)


def have_bundles() -> set:
    p = os.path.join(RAW, "filelistdata.txt")
    if not os.path.exists(p):
        return set()
    return set(open(p, encoding="utf-8-sig").read().split())


def fetch(name: str) -> tuple:
    dest = os.path.join(OUT, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return (name, "skip", 0)
    url = BASE + name
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "UnityPlayer/2022.3.32f1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        with open(dest, "wb") as f:
            f.write(data)
        return (name, "ok", len(data))
    except Exception as exc:
        return (name, f"err {exc}", 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-cg", action="store_true", help="semua avgcg/avgfg/interactivecg yang hilang")
    ap.add_argument("--missing", type=int, metavar="N", help="N bundle hilang pertama")
    ap.add_argument("--grep", metavar="RE", help="hanya nama yang cocok regex ini")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    allb = catalog_bundles()
    have = have_bundles()
    missing = [b for b in allb if b not in have]
    print(f"katalog : {len(allb)} bundle")
    print(f"punya   : {len(have)}")
    print(f"hilang  : {len(missing)}")

    if args.grep:
        rx = re.compile(args.grep, re.I)
        missing = [b for b in missing if rx.search(b)]
        print(f"cocok   : {len(missing)}")
    elif args.all_cg:
        rx = re.compile(r"avgcg|avgfg|interactivecg", re.I)
        missing = [b for b in missing if rx.search(b)]
        print(f"CG/FG   : {len(missing)}")
    elif args.missing:
        missing = missing[: args.missing]

    if not missing:
        print("tidak ada yang diunduh")
        return 0

    ok = err = skip = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for name, status, size in ex.map(fetch, missing):
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                err += 1
                if err <= 5:
                    print(f"  GAGAL {name}: {status}")

    print(f"\nselesai : ok={ok} skip={skip} gagal={err} -> {OUT}")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
