#!/usr/bin/env python3
"""Ambil ikon filter CZN dari wiki e7bot ke public/thumbs/czn-ui/.

Baris filter di wiki memakai:
  img/icon_ego_<ego>.webp + img/bg_ego_<ego>.webp   -> badge ego berlatar gradien
  img/icon_job_<job>.webp                          -> badge job
  PNG bintang 80x80 yang di-embed di chunk GradeFilter (varian CZN)

Nama chunk Vite ber-hash berubah tiap deploy, jadi nama GradeFilter di-resolve
dari bundle utama, bukan di-hardcode. Job `vanguard` tidak punya ikon sendiri
di wiki: `cznJobs` memetakannya ke `icon_job_knight.webp`.

Aset ini sengaja tidak di-commit (public/thumbs/ diabaikan git); jalankan
script ini lagi setelah clone baru.

Usage: python3 tools/czn/fetch-icons.py
"""
from __future__ import annotations

import base64
import re
import urllib.request
from pathlib import Path

WIKI = "https://wiki.e7bot.top"
DATA = WIKI + "/api/assets/file/czn/data/"
OUT = Path(__file__).resolve().parents[2] / "public" / "thumbs" / "czn-ui"
HEADERS = {"User-Agent": "spine-viewer-czn-icons/1.0"}

EGO = ["instinct", "norms", "love", "creed", "narcissism"]
# Job di data wiki -> nama file ikon di repo wiki.
JOBS = {
    "striker": "striker",
    "vanguard": "knight",
    "ranger": "ranger",
    "hunter": "hunter",
    "psionic": "psionic",
    "controller": "controller",
}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Bintang CZN (base64 di dalam chunk GradeFilter).
    html = get(WIKI + "/").decode("utf-8")
    main_js = re.search(r"/js/index-[A-Za-z0-9_-]+\.js", html)
    if not main_js:
        raise RuntimeError("bundle utama wiki tidak ditemukan")
    bundle = get(WIKI + main_js.group(0)).decode("utf-8")
    chunk = re.search(r"GradeFilter-[A-Za-z0-9_-]+\.js", bundle)
    if not chunk:
        raise RuntimeError("chunk GradeFilter tidak ditemukan")
    src = get(WIKI + "/js/" + chunk.group(0)).decode("utf-8")
    star = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", src)
    if not star:
        raise RuntimeError("PNG bintang CZN tidak ditemukan")
    (OUT / "star.png").write_bytes(base64.b64decode(star.group(1)))
    print(f"chunk {chunk.group(0)} -> star.png")

    # 2. Badge ego (ikon + latar).
    for ego in EGO:
        (OUT / f"ego_{ego}.webp").write_bytes(get(DATA + f"img/icon_ego_{ego}.webp"))
        (OUT / f"ego_bg_{ego}.webp").write_bytes(get(DATA + f"img/bg_ego_{ego}.webp"))

    # 3. Badge job.
    for job, wiki_name in JOBS.items():
        (OUT / f"job_{job}.webp").write_bytes(
            get(DATA + f"img/icon_job_{wiki_name}.webp")
        )
    print(f"tersimpan {len(list(OUT.iterdir()))} ikon di {OUT}")


if __name__ == "__main__":
    main()
