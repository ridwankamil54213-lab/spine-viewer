#!/usr/bin/env python3
"""Unduh ANIMASI kartu skill CZN (.webm), pelengkap tools/download-czn-cards.py.

Kartu skill punya dua bentuk di sumber yang sama:

  <nama>.webp   ilustrasi diam          (selalu ada)
  <nama>.webm   animasi kartu          (hanya sebagian)

Dari 321 kartu: 167 punya .webm (semuanya kartu "unique"), 88 kartu "start"
tidak punya animasi, dan 66 kartu unique juga tidak (kartu lama).

Hasil disimpan di folder yang sama dengan .webp:
  assets/czn-cards/<charid>/<nama>.webm

index.json diperbarui: tiap entri kartu mendapat flag `video` bernilai true
kalau .webm-nya ada. Viewer memakai flag itu untuk memilih <video> (webm)
duluan, dan jatuh ke <img> (webp) kalau tidak ada.

Dipakai:
  python3 tools/download-czn-card-videos.py --check
  python3 tools/download-czn-card-videos.py --limit 2
  python3 tools/download-czn-card-videos.py
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

BASE = "https://wiki.e7bot.top/api/assets/file/czn/data/card_illustration"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "czn-cards")
INDEX = os.path.join(OUT, "index.json")

EBML = b"\x1a\x45\xdf\xa3"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://wiki.e7bot.top/",
    "Accept": "*/*",
}


def fetch(url: str, timeout: int = 60, retries: int = 3) -> bytes | None:
    """None kalau 404 — artinya kartu itu memang tidak punya animasi."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
            time.sleep(1.2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def one(job: tuple[str, str]) -> tuple[str, str, bool]:
    cid, stem = job
    d = os.path.join(OUT, cid)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"{stem}.webm")
    if os.path.isfile(dest) and os.path.getsize(dest) > 1024:
        return (cid, stem, True)
    try:
        data = fetch(f"{BASE}/{stem}.webm")
    except Exception as e:  # noqa: BLE001
        print(f"  {stem}: {e}", file=sys.stderr, flush=True)
        return (cid, stem, False)
    if data is None:
        return (cid, stem, False)
    if data[:4] != EBML:
        return (cid, stem, False)
    with open(dest, "wb") as f:
        f.write(data)
    return (cid, stem, True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah KARAKTER")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    try:
        index = json.load(open(INDEX))
    except Exception:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "index.json tidak terbaca; jalankan download-czn-cards.py dulu"}, indent=1))
        return 1

    # Hanya kartu "unique": kartu "start" tidak punya animasi sama sekali
    # (0 dari 88), jadi tidak perlu ditembak dan hanya membuang waktu.
    jobs: list[tuple[str, str]] = []
    for cid, rec in index.items():
        for c in rec.get("cards", []):
            if c.get("kind") != "unique":
                continue
            if c.get("video"):
                continue
            jobs.append((cid, c["file"].replace(".webp", "")))

    print(f"{len(jobs)} kandidat animasi", file=sys.stderr, flush=True)
    if a.check:
        have = sum(
            1
            for rec in index.values()
            for c in rec.get("cards", [])
            if c.get("video")
        )
        print(json.dumps({"ok": True, "kandidat": len(jobs), "sudah_ada": have}, indent=1))
        return 0
    if a.limit:
        keep = {cid for cid, _ in jobs[: a.limit * 12]}
        jobs = [j for j in jobs if j[0] in keep]

    t0 = time.time()
    got: dict[str, set[str]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, j): j for j in jobs}
        for fut in as_completed(futs):
            cid, stem, ok = fut.result()
            if ok:
                got.setdefault(cid, set()).add(stem)
            done += 1
            if done % 25 == 0 or done == len(jobs):
                total = sum(len(v) for v in got.values())
                print(f"  {done}/{len(jobs)} · {total} animasi", file=sys.stderr, flush=True)

    # Perbarui index: tandai kartu yang punya .webm.
    changed = 0
    for cid, rec in index.items():
        for c in rec.get("cards", []):
            stem = c["file"].replace(".webp", "")
            has = os.path.isfile(os.path.join(OUT, cid, f"{stem}.webm"))
            if bool(c.get("video")) != has:
                c["video"] = has
                changed += 1
    with open(INDEX, "w") as f:
        json.dump(index, f, indent=1, ensure_ascii=False, sort_keys=True)

    total = sum(1 for rec in index.values() for c in rec.get("cards", []) if c.get("video"))
    print(
        json.dumps(
            {
                "ok": True,
                "animasi": total,
                "kartu": sum(len(r.get("cards", [])) for r in index.values()),
                "index_diperbarui": changed,
                "seconds": round(time.time() - t0, 1),
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
