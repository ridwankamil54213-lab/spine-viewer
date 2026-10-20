#!/usr/bin/env python3
"""Bangun katalog nama + metadata Epic Seven dari e7codex.

Membaca units.json (sudah diunduh oleh download-e7codex.py) lalu menulis:

  assets/epic7/_names.json      id -> {name, kind, rarity, attribute, role, ...}
  assets/epic7/<id>/thumb.png   potret kecil untuk kartu galeri (kalau ada)

Server memakai _names.json lewat applyEpic7Names() untuk mengisi `name` dan
`character` pada tiap model, mengikuti pola yang sudah dipakai CZN dan
Make Drama (lihat applyCznNames / applyMadNames di src/server.js).

Rarity di units.json berupa angka (1-5); di sini diubah jadi bintang agar
kartu dan tooltip langsung terbaca ("5★" bukan "5").

Dipakai:
  python3 tools/fetch-e7codex-meta.py            # tulis _names.json + thumbnail
  python3 tools/fetch-e7codex-meta.py --no-thumbs
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://e7codex.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets", "epic7")
UNITS_URL = f"{BASE}/data/units.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": f"{BASE}/",
    "Accept": "*/*",
}

# Label yang enak dibaca untuk nilai mentah di units.json.
ROLE_LABEL = {
    "knight": "Knight",
    "ranger": "Ranger",
    "mage": "Mage",
    "assassin": "Assassin",
    "warrior": "Warrior",
    "manauser": "Manauser",
}
ATTR_LABEL = {
    "fire": "Fire",
    "ice": "Ice",
    "wind": "Wind",
    "light": "Light",
    "dark": "Dark",
}


def fetch(url: str, timeout: int = 60) -> bytes:
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(1.5 * (attempt + 1) if e.code == 403 else 0.7 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def clean_name(x: dict) -> str:
    """Nama yang layak tampil: hero_name dulu, lalu name, lalu id."""
    for key in ("hero_name", "name"):
        v = (x.get(key) or "").strip()
        if v:
            return v
    return x["id"]


def build_record(x: dict) -> dict:
    """Satu entri _names.json dari satu entri units.json."""
    rec: dict = {"kind": x.get("kind") or "unit"}
    name = clean_name(x)
    rec["name"] = name
    # hero_name dipakai kalau berbeda dari name (mis. varian "Powered up
    # Mercedes" punya hero_name "Mercedes") — kartu memakai `name`, tooltip
    # bisa menyebut keduanya.
    hero = (x.get("hero_name") or "").strip()
    if hero and hero != name:
        rec["hero"] = hero

    rar = x.get("rarity")
    if isinstance(rar, int) and rar > 0:
        # Bintang lebih cepat dibaca daripada angka telanjang.
        rec["rarity"] = "★" * min(rar, 6)
        rec["rarityNum"] = rar

    attr = x.get("attribute")
    if attr:
        rec["element"] = ATTR_LABEL.get(attr, attr.title())

    role = x.get("role")
    if role:
        rec["class"] = ROLE_LABEL.get(role, role.title())

    slug = (x.get("slug") or "").strip()
    if slug:
        rec["slug"] = slug
    rel = x.get("released")
    if rel:
        rec["released"] = rel
    if x.get("has_combat"):
        rec["combat"] = True
    return rec


def download_thumb(x: dict, outdir: str) -> bool:
    thumb = x.get("thumb")
    if not thumb:
        return False
    dest = os.path.join(outdir, "thumb.png")
    if os.path.exists(dest) and os.path.getsize(dest) > 512:
        return True
    try:
        data = fetch(f"{BASE}/{thumb}", timeout=90)
        if not data[:4] == b"\x89PNG":
            return False
        with open(dest, "wb") as f:
            f.write(data)
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-thumbs", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if not os.path.isdir(ASSETS):
        print(f"folder model tidak ada: {ASSETS}")
        print("jalankan tools/download-e7codex.py dulu")
        return 1

    print(f"mengambil {UNITS_URL}")
    units = json.loads(fetch(UNITS_URL))

    catalog: dict[str, dict] = {}
    for x in units:
        uid = x.get("id")
        if not uid:
            continue
        catalog[uid] = build_record(x)

    out = os.path.join(ASSETS, "_names.json")
    with open(out, "w") as f:
        json.dump(catalog, f, indent=1, ensure_ascii=False, sort_keys=True)
    print(f"_names.json ditulis: {len(catalog)} entri -> {out}")

    if args.no_thumbs:
        return 0

    todo = [x for x in units if x.get("thumb") and os.path.isdir(os.path.join(ASSETS, x["id"]))]
    print(f"mengunduh {len(todo)} thumbnail…")
    ok = 0
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(download_thumb, x, os.path.join(ASSETS, x["id"])): x for x in todo}
        for fut in as_completed(futs):
            if fut.result():
                ok += 1
            done += 1
            if done % 100 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} · ok {ok} · {time.time()-t0:.0f}s", flush=True)

    print(f"selesai: {ok}/{len(todo)} thumbnail, {time.time()-t0:.0f} detik")
    return 0


if __name__ == "__main__":
    sys.exit(main())
