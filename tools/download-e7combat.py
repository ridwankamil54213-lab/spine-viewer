#!/usr/bin/env python3
"""Unduh rig COMBAT (animasi skill) Epic Seven dari assets.e7codex.com.

Rig combat adalah berkas terpisah dari rig lobby yang sudah diunduh
tools/download-e7codex.py:

  lobby  : e7codex.com/assets/<id>/<id>.{json,atlas,png}   (1 animasi: idle)
  combat : assets.e7codex.com/<id>/combat/<id>.{json,atlas,png}
           (20 animasi: idle, run, skill1, skill2, skill3, attacked, ...)

Host-nya BEDA (assets.e7codex.com) dan path-nya tidak bisa ditebak dari
e7codex.com — /assets/<id>/combat/... memberi 404.

Yang diunduh hanya model yang punya `has_combat: true` di units.json,
karena hanya itu yang benar-benar ada berkasnya (diuji: 21/21 yang
has_combat ada, 0/19 yang tidak).

Ditempatkan di assets/epic7-combat/<id>/ dengan nama berkas <id>.json /
<id>.atlas / halaman atlas apa adanya, sehingga scanModels() menemukannya
sebagai game terpisah ("epic7-combat") dan rig lobby tetap utuh.

Dipakai:
  python3 tools/download-e7combat.py --check
  python3 tools/download-e7combat.py --limit 5
  python3 tools/download-e7combat.py
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
UNITS_URL = "https://e7codex.com/data/units.json"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "epic7-combat")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://e7codex.com/",
    "Accept": "*/*",
}


def fetch(url: str, timeout: int = 90) -> bytes:
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            time.sleep(1.5 * (attempt + 1) if e.code == 403 else 0.8 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def atlas_pages(atlas_text: str) -> list[str]:
    """Nama halaman tekstur dari berkas atlas (baris awal, bukan region)."""
    for line in atlas_text.replace("\r", "").split("\n"):
        s = line.strip()
        if s and s.lower().endswith((".png", ".webp", ".jpg")):
            return [s]
    return []


def one(uid: str) -> dict:
    d = os.path.join(OUT, uid)
    os.makedirs(d, exist_ok=True)
    try:
        atlas = fetch(f"{BASE}/{uid}/combat/{uid}.atlas")
        skel = fetch(f"{BASE}/{uid}/combat/{uid}.json")
    except Exception as e:  # noqa: BLE001
        return {"id": uid, "ok": False, "err": str(e)[:100]}

    with open(os.path.join(d, f"{uid}.atlas"), "wb") as f:
        f.write(atlas)
    with open(os.path.join(d, f"{uid}.json"), "wb") as f:
        f.write(skel)

    pages = 0
    for page in atlas_pages(atlas.decode("utf8", "replace")):
        try:
            data = fetch(f"{BASE}/{uid}/combat/{page}")
            with open(os.path.join(d, page), "wb") as f:
                f.write(data)
            pages += 1
        except Exception:  # noqa: BLE001
            pass

    try:
        j = json.loads(skel)
        bones = len(j.get("bones") or [])
        anims = len(j.get("animations") or {})
    except Exception:  # noqa: BLE001
        bones, anims = 0, 0

    ok = bones > 0 and pages > 0
    return {"id": uid, "ok": ok, "bones": bones, "anims": anims, "pages": pages}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    print(f"mengambil daftar: {UNITS_URL}")
    units = json.loads(fetch(UNITS_URL))
    combat = [u for u in units if u.get("has_combat")]
    print(f"{len(combat)} model punya rig combat (has_combat)")
    if args.check:
        return 0
    if args.limit:
        combat = combat[: args.limit]

    os.makedirs(OUT, exist_ok=True)
    results = []
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one, u["id"]): u for u in combat}
        for fut in as_completed(futs):
            results.append(fut.result())
            done += 1
            if done % 25 == 0 or done == len(combat):
                okn = sum(1 for r in results if r["ok"])
                print(f"  {done}/{len(combat)} · ok {okn} · {time.time()-t0:.0f}s", flush=True)

    good = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    anims = sum(r.get("anims", 0) for r in good)
    print(f"\nselesai: {len(good)} berhasil, {len(bad)} gagal, {anims} animasi total, {time.time()-t0:.0f}s")
    if bad:
        for r in bad[:20]:
            print(f"  GAGAL {r['id']}: {r['err']}")
    with open("/tmp/e7combat-report.json", "w") as f:
        json.dump({"ok": len(good), "bad": len(bad), "animations": anims, "results": results}, f, indent=1)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
