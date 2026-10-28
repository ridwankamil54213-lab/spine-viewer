#!/usr/bin/env python3
"""Ekstrak seluruh Spine Otogi Frontier (10 ribu model) ke assets/otogi.

Kenapa skrip sendiri, bukan `resdown.py pipeline`:
resdown mengunduh SEMUA yang cocok filter lalu baru mengekstrak. Untuk 7,2 GB
itu berarti disk harus menampung berkas mentah + hasil ekstrak sekaligus.
Skrip ini memproses per-batch (unduh -> ekstrak -> hapus mentah), jadi ruang
yang dibutuhkan tetap kecil dan pekerjaan bisa dilanjutkan kalau terputus.

Sumber: CSV publik AdditionalAssets.csv (tanpa login), base URL sama
direktori. Setiap baris = satu bundle UnityFS berisi satu model Spine.

Pemakaian:
    python update-otogi.py                 # semua
    python update-otogi.py --limit 100     # uji 100 model dulu
    python update-otogi.py --resume        # lanjutkan yang belum ada
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

CSV_URL = "https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/AssetBundlePatch/AdditionalAssets.csv"
BASE_URL = "https://web-assets.otogi-frontier.com/prodassets/GeneralWebGL/Assets/"
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
EXTRACTOR = os.path.join(REPO, "tools", "extract-unity-spine.py")
DEFAULT_OUT = os.path.join(REPO, "assets", "otogi")
DEFAULT_WORK = "/opt/games/otogi"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_manifest() -> list[tuple[str, str, int]]:
    log("mengambil manifest CSV")
    req = urllib.request.Request(CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", errors="replace")
    rows = [r for r in csv.reader(io.StringIO(raw)) if r and len(r) >= 3]
    spine = [(r[0], r[1], int(r[2])) for r in rows if r[0].lower().startswith("chara/spine/")]
    log(f"aset Spine di manifest: {len(spine)}")
    return spine


def download_one(item: tuple[str, str, int], dest_dir: str) -> tuple[str, bool, str]:
    """Unduh satu bundle, verifikasi md5. Kembalikan (nama, ok, alasan)."""
    name, md5b64, size = item
    base = os.path.basename(name)
    dest = os.path.join(dest_dir, base + ".bundle")
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return name, True, "sudah-ada"
    url = BASE_URL + name
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=120).read()
            if len(data) != size:
                raise ValueError(f"ukuran {len(data)} != {size}")
            expect = base64.b64decode(md5b64).hex()
            got = hashlib.md5(data).hexdigest()
            if expect and got != expect:
                raise ValueError(f"md5 tidak cocok")
            os.makedirs(dest_dir, exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
            return name, True, "ok"
        except Exception as exc:
            if attempt == 2:
                return name, False, str(exc)[:80]
            time.sleep(1.5 * (attempt + 1))
    return name, False, "gagal"


def main() -> int:
    ap = argparse.ArgumentParser(description="Ekstrak Spine Otogi Frontier")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--work", default=DEFAULT_WORK)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=150, help="model per batch")
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    spine = load_manifest()
    if args.limit:
        spine = spine[: args.limit]

    if args.resume and os.path.isdir(args.out):
        sudah = {d for d in os.listdir(args.out) if os.path.isdir(os.path.join(args.out, d))}
        log(f"mode resume: {len(sudah)} folder sudah ada")
    else:
        sudah = set()

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.work, exist_ok=True)

    total = len(spine)
    gagal: list[tuple[str, str]] = []
    selesai = 0

    for start in range(0, total, args.batch):
        chunk = spine[start:start + args.batch]
        raw_dir = os.path.join(args.work, "raw")
        out_dir = os.path.join(args.work, "out")
        for d in (raw_dir, out_dir):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)

        # 1) unduh paralel
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(download_one, it, raw_dir) for it in chunk]
            for fut in as_completed(futures):
                name, ok, reason = fut.result()
                if not ok:
                    gagal.append((name, reason))

        bundles = [os.path.join(raw_dir, f) for f in os.listdir(raw_dir)] if os.path.isdir(raw_dir) else []
        if not bundles:
            continue

        # 2) ekstrak batch ini
        # extract-unity-spine.py membaca BUNDLE_DIR/OUT dari environment,
        # bukan dari argumen CLI. Tanpa env ini ia memakai default
        # /srv/spine-assets/catshinobi-apk/... dan gagal.
        env = dict(os.environ)
        env["BUNDLE_DIR"] = raw_dir
        env["OUT"] = out_dir
        res = subprocess.run(
            [sys.executable, EXTRACTOR],
            capture_output=True, text=True, env=env,
        )
        if res.returncode != 0:
            log(f"  ekstraksi batch gagal: {res.stderr[-200:]}")

        # 3) pindahkan hasil ke out utama
        moved = 0
        if os.path.isdir(out_dir):
            for entry in os.listdir(out_dir):
                src = os.path.join(out_dir, entry)
                if not os.path.isdir(src) or entry.startswith("_"):
                    continue
                dst = os.path.join(args.out, entry)
                if os.path.isdir(dst):
                    continue
                shutil.move(src, dst)
                moved += 1
        selesai += moved
        log(f"  {start + len(chunk)}/{total} | model ditulis: {moved} | total: {selesai} | gagal unduh: {len(gagal)}")

    # Atlas Otogi memakai CRLF dan diawali baris kosong; tanpa normalisasi,
    # runtime membacanya sebagai halaman tanpa nama ("name cannot be null").
    fixer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fix-atlas.py")
    if os.path.exists(fixer):
        subprocess.run([sys.executable, fixer, args.out], check=False)

    log(f"selesai: {selesai} model, gagal {len(gagal)}")
    if gagal:
        p = os.path.join(args.work, "gagal.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(gagal, fh, indent=2, ensure_ascii=False)
        log(f"daftar gagal: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
