#!/usr/bin/env python3
"""Unduh wallpaper animation (lobby anims) Epic Seven dari e7codex.

Sumber daftar: https://e7codex.com/data/lobby_anims.json (24 entri).
Berkas video:  https://assets.e7codex.com/<video>  (VP9 WebM, sampai 4K)

Bentuknya BUKAN skeleton dan BUKAN gambar: ini klip video, jadi
didaftarkan sebagai model "format: video" dan dirender video stage yang
sudah ada (dipakai Lost Sword untuk cutscene .mp4).

Ditempatkan di assets/epic7-wallpaper/<id>/<id>.webm sehingga scanModels()
menemukannya sebagai game sendiri "epic7-wallpaper".

Sebagian entri punya field `units` berisi id karakter (c5147 dan
sebagainya) — itu dipakai server untuk menjadikan wallpaper sebagai
VARIAN dari kartu karakter tersebut.

Dipakai:
  python3 tools/download-e7wallpapers.py --check
  python3 tools/download-e7wallpapers.py --limit 3
  python3 tools/download-e7wallpapers.py
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

BASE = "https://assets.e7codex.com"
LIST_URL = "https://e7codex.com/data/lobby_anims.json"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "epic7-wallpaper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://e7codex.com/",
    "Accept": "*/*",
}

# Magic WebM: EBML header 1A 45 DF A3.
EBML = b"\x1a\x45\xdf\xa3"


def fetch(url: str, timeout: int = 300) -> bytes:
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            time.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def one(item: dict) -> dict:
    uid = item["id"]
    d = os.path.join(OUT, uid)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"{uid}.webm")
    if os.path.isfile(dest) and os.path.getsize(dest) > 4096:
        return {"id": uid, "ok": True, "bytes": os.path.getsize(dest), "skip": True}
    try:
        data = fetch(f"{BASE}/{item['video']}")
    except Exception as e:  # noqa: BLE001
        return {"id": uid, "ok": False, "err": str(e)[:110]}
    if data[:4] != EBML:
        return {"id": uid, "ok": False, "err": f"bukan WebM ({data[:12]!r})"}
    with open(dest, "wb") as f:
        f.write(data)
    return {"id": uid, "ok": True, "bytes": len(data)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    print(f"mengambil daftar: {LIST_URL}")
    items = json.loads(fetch(LIST_URL))
    total = sum(x.get("bytes", 0) for x in items)
    print(f"{len(items)} wallpaper · {total/1e9:.2f} GB · {sum(1 for x in items if x.get('units'))} punya units")
    if args.check:
        return 0
    if args.limit:
        items = items[: args.limit]

    os.makedirs(OUT, exist_ok=True)
    results = []
    done = 0
    t0 = time.time()
    # Worker sedikit: berkasnya besar (sampai 186 MB), terlalu banyak paralel
    # hanya menghabiskan bandwidth tanpa mempercepat.
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one, it): it for it in items}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            mb = r.get("bytes", 0) / 1e6
            print(f"  {done}/{len(items)} · {r['id']} · {mb:.1f} MB · {r.get('err','')}", flush=True)

    good = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    print(f"\nselesai: {len(good)} berhasil, {len(bad)} gagal, {time.time()-t0:.0f}s")
    # Metadata disalin ke folder assets supaya server bisa membacanya tanpa
    # mengunduh ulang daftar dari internet saat boot.
    with open(os.path.join(ASSETS_META), "w") as f:
        json.dump(items, f, indent=1, ensure_ascii=False)
    print(f"metadata: {ASSETS_META}")
    return 0 if not bad else 1


ASSETS_META = os.path.join(OUT, "_lobby_anims.json")

if __name__ == "__main__":
    sys.exit(main())
