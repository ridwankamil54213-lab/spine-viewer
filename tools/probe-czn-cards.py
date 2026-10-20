#!/usr/bin/env python3
"""Cari SEMUA berkas kartu CZN yang tersedia di sumber terbuka.

Sumber : https://wiki.e7bot.top/api/assets/file/czn/data/card_illustration/
         (terbuka, tanpa enkripsi — hanya berkas gambarnya)

Tidak ada indeks publik, jadi nama berkas harus ditebak. Wiki sendiri
menyebut kategori kartu: Start, Unique, Ego Skill, Collapse, Support, Other.
Pola namanya <prefix>_<charid>_<nn>, dengan beberapa varian berawalan angka
(collapse_2_<charid>_<nn>).

Skrip ini memindai kombinasi prefix × charid × nn, lalu menulis hasilnya ke
assets/czn-cards/index.json (format sama dengan download-czn-cards.py) supaya
viewer tidak perlu tahu apa-apa soal pola nama.

Dipakai:
  python3 tools/probe-czn-cards.py --dry-run      # hanya laporkan, tak menulis
  python3 tools/probe-czn-cards.py                # pindai + tulis index
  python3 tools/probe-czn-cards.py --download     # + unduh .webp/.webm baru
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://wiki.e7bot.top/api/assets/file/czn/data/card_illustration"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "czn-cards")
INDEX = os.path.join(OUT, "index.json")
RIGS = os.path.join(ROOT, "assets", "czn-rigs", "_names.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://wiki.e7bot.top/",
    "Accept": "*/*",
}

# Prefix yang dipakai wiki untuk kategori kartu. "collapse_2" adalah varian
# dari collapse (kartu hasil transformasi).
PREFIXES = ["unique", "start", "collapse", "collapse_2", "ego", "support", "other"]
MAX_NN = 24


def head(url: str, timeout: int = 20) -> bool:
    """True kalau berkas ada (200). 404 = tidak ada, bukan error."""
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(2048)
            return r.status == 200
    except urllib.error.HTTPError:
        return False
    except Exception:  # noqa: BLE001
        return False


def charids() -> list[str]:
    """Id karakter dari _names.json (kolom `thumb` berisi "<charid>.png")."""
    ids: set[str] = set()
    try:
        names = json.load(open(RIGS))
    except Exception:  # noqa: BLE001
        return []
    for rec in names.values():
        if not isinstance(rec, dict):
            continue
        t = str(rec.get("thumb") or "")
        stem = t.split(".")[0]
        if stem.isdigit():
            ids.add(stem)
    # Id yang sudah ada di index juga ikut, jaga-jaga kalau _names.json berubah.
    try:
        for cid in json.load(open(INDEX)):
            if str(cid).isdigit():
                ids.add(str(cid))
    except Exception:  # noqa: BLE001
        pass
    return sorted(ids, key=lambda s: int(s))


def probe_all(ids: list[str], workers: int = 12) -> dict[str, list[dict]]:
    """Kembalikan {charid: [{kind, file}]} untuk semua berkas yang ditemukan."""
    jobs = [(cid, p, f"{i:02d}") for cid in ids for p in PREFIXES for i in range(1, MAX_NN + 1)]
    found: dict[str, list[dict]] = {cid: [] for cid in ids}

    def one(job):
        cid, prefix, nn = job
        name = f"{prefix}_{cid}_{nn}"
        ok = head(f"{BASE}/{name}.webp")
        return (cid, prefix, nn, name, ok)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for cid, prefix, nn, name, ok in ex.map(one, jobs):
            if ok:
                found[cid].append({"kind": prefix, "file": f"{name}.webp"})
            done += 1
            if done % 300 == 0:
                total = sum(len(v) for v in found.values())
                sys.stderr.write(f"  {done}/{len(jobs)} · {total} kartu\n")
                sys.stderr.flush()
    return found


def download_missing(found: dict[str, list[dict]], workers: int = 8) -> dict[str, int]:
    """Unduh .webp (dan .webm bila ada) untuk entri baru."""
    def fetch(url: str, dest: str) -> bool:
        if os.path.isfile(dest) and os.path.getsize(dest) > 512:
            return True
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return True
        except Exception:  # noqa: BLE001
            return False

    jobs = []
    for cid, cards in found.items():
        for c in cards:
            stem = c["file"][:-5]
            jobs.append((f"{BASE}/{stem}.webp", os.path.join(OUT, cid, f"{stem}.webp"), cid, stem, "webp"))
            jobs.append((f"{BASE}/{stem}.webm", os.path.join(OUT, cid, f"{stem}.webm"), cid, stem, "webm"))

    stats = {"webp": 0, "webm": 0}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch, u, d): (cid, stem, kind) for u, d, cid, stem, kind in jobs}
        for fut, (cid, stem, kind) in list(futs.items()):
            if fut.result():
                stats[kind] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()

    ids = charids()
    if not ids:
        print(json.dumps({"ok": False, "error": "tidak ada id karakter; cek assets/czn-rigs/_names.json"}))
        return 1
    sys.stderr.write(f"memindai {len(ids)} karakter × {len(PREFIXES)} pola × {MAX_NN} nomor\n")

    t0 = time.time()
    found = probe_all(ids, a.workers)
    total = sum(len(v) for v in found.values())
    per_kind: dict[str, int] = {}
    for cards in found.values():
        for c in cards:
            per_kind[c["kind"]] = per_kind.get(c["kind"], 0) + 1

    sys.stderr.write(f"selesai pindai dalam {time.time()-t0:.0f}s: {total} kartu\n")
    for k, v in sorted(per_kind.items(), key=lambda kv: -kv[1]):
        sys.stderr.write(f"  {k:12} {v}\n")

    result = {
        "ok": True,
        "characters": len(ids),
        "cards": total,
        "perKind": per_kind,
        "seconds": round(time.time() - t0, 1),
    }
    if a.dry_run:
        print(json.dumps(result, indent=1))
        return 0

    # Gabung dengan index lama: entri lama dipertahankan walau tidak ditemukan
    # lagi (mungkin sudah dihapus di sumber, tapi berkasnya masih dipakai).
    try:
        old = json.load(open(INDEX))
    except Exception:  # noqa: BLE001
        old = {}

    stats = {"webp": 0, "webm": 0}
    if a.download:
        stats = download_missing(found, workers=8)

    index = {}
    for cid, cards in found.items():
        if not cards:
            continue
        cards.sort(key=lambda c: (c["kind"], c["file"]))
        rec = dict(old.get(cid) or {})
        rec["cards"] = []
        for c in cards:
            stem = c["file"][:-5]
            rec["cards"].append(
                {
                    "kind": c["kind"],
                    "file": c["file"],
                    "video": os.path.isfile(os.path.join(OUT, cid, f"{stem}.webm")),
                }
            )
        index[cid] = rec

    os.makedirs(OUT, exist_ok=True)
    with open(INDEX, "w") as f:
        json.dump(index, f, indent=1, ensure_ascii=False, sort_keys=True)

    result.update(
        {
            "written": sum(len(r["cards"]) for r in index.values()),
            "charactersWithCards": len(index),
            "downloaded": stats,
        }
    )
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
