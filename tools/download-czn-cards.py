#!/usr/bin/env python3
"""Unduh ilustrasi kartu skill Chaos Zero Nightmare.

Sumber (terbuka, tanpa enkripsi):
  https://wiki.e7bot.top/api/assets/file/czn/data/card_illustration/<nama>.webp

Pola nama:
  start_<charid>_<nn>     kartu bawaan (Start Cards)
  unique_<charid>_<nn>    kartu unik
  april_card/<nama>_0401  versi April Fool (kalau ada)

<charid> adalah id numerik karakter yang juga dipakai sebagai prefiks id rig
(czn-rigs/1056_01 -> 1056) dan sebagai nama berkas thumb di
assets/czn-rigs/_names.json ("1056.png"). Itulah yang dipakai viewer untuk
menautkan kartu ke karakter.

Kartu tidak punya indeks publik, jadi batas atas nomornya DIPINDAI: untuk
tiap karakter dicoba nn = 01..MAX_NUM dan yang 404 dilewati. Hasilnya
disimpan ke assets/czn-cards/<charid>/<nama>.webp plus index.json berisi
daftar berkas per karakter.

Dipakai:
  python3 tools/download-czn-cards.py --check
  python3 tools/download-czn-cards.py --limit 3
  python3 tools/download-czn-cards.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://wiki.e7bot.top/api/assets/file/czn/data/card_illustration"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
OUT = os.path.join(ASSETS, "czn-cards")
NAMES = os.path.join(ASSETS, "czn-rigs", "_names.json")

# Nomor kartu per karakter jarang lewat 08; 12 memberi ruang aman.
MAX_NUM = 12
KINDS = ("start", "unique")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://wiki.e7bot.top/",
    "Accept": "*/*",
}


def fetch(url: str, timeout: int = 40, retries: int = 3) -> bytes | None:
    """Ambil URL; None kalau 404 (berarti kartu itu memang tidak ada)."""
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


def characters() -> dict[str, str]:
    """charid -> nama karakter, dari kolom `thumb` di _names.json."""
    try:
        names = json.load(open(NAMES))
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    for rec in names.values():
        thumb = rec.get("thumb")
        name = rec.get("name")
        if not thumb or not name:
            continue
        cid = thumb.replace(".png", "")
        if re.fullmatch(r"\d+", cid):
            out.setdefault(cid, name)
    return out


def probe(cid: str) -> list[tuple[str, str]]:
    """Cari nama berkas kartu yang benar-benar ada untuk satu karakter."""
    found = []
    for kind in KINDS:
        for n in range(1, MAX_NUM + 1):
            name = f"{kind}_{cid}_{n:02d}"
            data = fetch(f"{BASE}/{name}.webp")
            if data is None:
                # Dua nomor kosong berturut-turut = akhir daftar; berhenti
                # supaya tidak menembak 20 URL kosong per karakter.
                if n >= 2:
                    break
                continue
            if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
                continue
            found.append((kind, name))
            # Simpan langsung: data sudah di tangan, tidak perlu minta ulang.
            d = os.path.join(OUT, cid)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"{name}.webp"), "wb") as f:
                f.write(data)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    chars = characters()
    if not chars:
        print(json.dumps({"ok": False, "error": "assets/czn-rigs/_names.json tidak terbaca"}, indent=1))
        return 1
    ids = sorted(chars)
    print(f"{len(ids)} karakter", file=sys.stderr, flush=True)
    if a.check:
        have = 0
        for cid in ids:
            d = os.path.join(OUT, cid)
            if os.path.isdir(d):
                have += len([f for f in os.listdir(d) if f.endswith(".webp")])
        print(json.dumps({"ok": True, "karakter": len(ids), "kartu_di_disk": have}, indent=1))
        return 0
    if a.limit:
        ids = ids[: a.limit]

    t0 = time.time()
    index: dict[str, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(probe, cid): cid for cid in ids}
        for fut in as_completed(futs):
            cid = futs[fut]
            try:
                got = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  {cid}: {e}", file=sys.stderr, flush=True)
                got = []
            index[cid] = {
                "name": chars[cid],
                "cards": [{"kind": k, "file": f"{n}.webp"} for k, n in got],
            }
            done += 1
            if done % 10 == 0 or done == len(ids):
                total = sum(len(v["cards"]) for v in index.values())
                print(f"  {done}/{len(ids)} karakter · {total} kartu", file=sys.stderr, flush=True)

    # Gabung dengan index lama supaya --limit tidak menghapus data sebelumnya.
    out_path = os.path.join(OUT, "index.json")
    old = {}
    if os.path.isfile(out_path):
        try:
            old = json.load(open(out_path))
        except Exception:  # noqa: BLE001
            old = {}
    old.update(index)
    os.makedirs(OUT, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(old, f, indent=1, ensure_ascii=False, sort_keys=True)

    total = sum(len(v["cards"]) for v in old.values())
    print(
        json.dumps(
            {
                "ok": True,
                "karakter": len(old),
                "kartu": total,
                "seconds": round(time.time() - t0, 1),
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
