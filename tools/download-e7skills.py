#!/usr/bin/env python3
"""Unduh animasi skill Epic Seven (animated WebP) dari e7codex.com.

Bentuknya BUKAN skeleton: berkas .webp berisi animasi siap pakai (25 frame,
1280x723, loop) yang dirender sebagai <img> oleh image stage viewer.
Didaftarkan sebagai model "format: image" sehingga muncul di pustaka.

Lokasi sumber: https://e7codex.com/assets/<id>/skill_sk_<id>_<n>.webp
Daftar berkas diambil dari field `skills` di units.json — 381 dari 848
model punya, total 421 berkas (sebagian model punya 2-3 skill).

Disimpan ke assets/epic7-skill/skill_<id>_<n>.webp. Id model dibentuk
scanModels() dari nama folder, jadi satu folder per berkas:
  assets/epic7-skill/<id>_skill<n>/<berkas>.webp

Dipakai:
  python3 tools/download-e7skills.py --check
  python3 tools/download-e7skills.py --limit 5
  python3 tools/download-e7skills.py
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
UNITS_URL = f"{BASE}/data/units.json"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "epic7-skill")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": f"{BASE}/",
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


def job_list(units: list[dict]) -> list[dict]:
    """Satu entri per berkas skill: {id, url, folder, file, label}."""
    out = []
    for u in units:
        skills = u.get("skills") or []
        uid = u["id"]
        for path in skills:
            base = os.path.basename(path)
            # skill_sk_c1091_3.webp -> nomor 3 (urutan skill di game)
            stem = os.path.splitext(base)[0]
            num = stem.rsplit("_", 1)[-1]
            out.append(
                {
                    "id": uid,
                    "url": f"{BASE}/{path}",
                    "folder": f"{uid}_skill{num}",
                    "file": base,
                    "label": f"Skill {num}",
                    "name": u.get("name") or u.get("hero_name") or uid,
                }
            )
    return out


def one(job: dict) -> dict:
    d = os.path.join(OUT, job["folder"])
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, job["file"])
    try:
        data = fetch(job["url"])
    except Exception as e:  # noqa: BLE001
        return {**job, "ok": False, "err": str(e)[:100]}
    # Cek magic RIFF....WEBP: kalau situs membalas HTML (blokir), jangan
    # simpan berkas rusak yang akan tampil sebagai gambar gagal.
    if len(data) < 16 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return {**job, "ok": False, "err": f"bukan WEBP ({data[:12]!r})"}
    with open(dest, "wb") as f:
        f.write(data)
    return {**job, "ok": True, "bytes": len(data)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    print(f"mengambil daftar: {UNITS_URL}")
    units = json.loads(fetch(UNITS_URL))
    jobs = job_list(units)
    print(f"{len(jobs)} berkas skill dari {len({j['id'] for j in jobs})} model")
    if args.check:
        return 0
    if args.limit:
        jobs = jobs[: args.limit]

    os.makedirs(OUT, exist_ok=True)
    results = []
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one, j): j for j in jobs}
        for fut in as_completed(futs):
            results.append(fut.result())
            done += 1
            if done % 50 == 0 or done == len(jobs):
                okn = sum(1 for r in results if r["ok"])
                print(f"  {done}/{len(jobs)} · ok {okn} · {time.time()-t0:.0f}s", flush=True)

    good = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    total = sum(r.get("bytes", 0) for r in good)
    print(f"\nselesai: {len(good)} berhasil, {len(bad)} gagal, {total/1e6:.0f} MB, {time.time()-t0:.0f}s")
    for r in bad[:20]:
        print(f"  GAGAL {r['id']}/{r['file']}: {r['err']}")
    with open("/tmp/e7skills-report.json", "w") as f:
        json.dump({"ok": len(good), "bad": len(bad), "results": results}, f, indent=1)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
