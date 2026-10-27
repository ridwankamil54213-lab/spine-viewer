#!/usr/bin/env python3
"""Tambah model Spine Mahjong Soul (雀魂) dari ArtHub viewer.

Sumber
======

ArtHub (https://github.com/Talors1225/arthub-viewer-web) mempublikasikan
asetnya di Cloudflare R2 dan memberi index JSON di GitHub Pages:

    index   : https://talors1225.github.io/arthub-viewer-web/majsoul/characters.json
    bucket  : https://pub-bdd986c6ec274f53b01df62ac49e02e2.r2.dev/majsoul/assets_raw/

Tidak ada enkripsi sama sekali: .skel biner (Spine 4.2.08), .atlas, dan .png
semuanya bisa diunduh langsung. Ini kebalikan total dari pipeline Mitao
Utopia yang manifest-nya terkunci Obfuz.

Struktur index (per entri `layers`):

    { "skel":  "assets_raw/myassets/spine/40010703/1/yuanxiao_gf_1.skel.txt",
      "atlas": "assets_raw/myassets/spine/40010703/1/yuanxiao_gf_1.atlas.txt",
      "dir":   "assets_raw/myassets/spine/40010703/1/" }

Nama berkas di CDN memakai akhiran .skel.txt / .atlas.txt, sedangkan viewer
mengenali .skel / .atlas — jadi keduanya diganti saat disimpan.

Pemakaian
=========
    python update-majsoul.py --check          # hitung saja
    python update-majsoul.py --apply          # unduh semua
    python update-majsoul.py --apply --limit 20
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import urllib.parse
import urllib.request

INDEX_URL = "https://talors1225.github.io/arthub-viewer-web/majsoul/characters.json"
BUCKET = "https://pub-bdd986c6ec274f53b01df62ac49e02e2.r2.dev"

HERE = os.path.dirname(os.path.abspath(__file__))
# Script ini ada di <repo>/tools/, jadi repo = satu tingkat di atas HERE.
# (Sempat salah pakai "..", ".." sehingga hasilnya /opt/assets.)
REPO = os.path.abspath(os.path.join(HERE, ".."))
OUT_DIR = os.environ.get("MAJSOUL_OUT") or os.path.join(REPO, "assets", "majsoul")

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36"


def log(*a) -> None:
    print(*a, flush=True)


def fetch(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"{url} gagal: {last}")


def load_index() -> list[dict]:
    """Kembalikan daftar layer (satu layer = satu model Spine)."""
    data = json.loads(fetch(INDEX_URL).decode("utf-8", "replace"))
    layers: list[dict] = []
    for ch in data.get("characters", []):
        if ch.get("layers"):
            layers.extend(ch["layers"])
        elif ch.get("skel"):
            layers.append(ch)
    # buang duplikat berdasarkan id
    seen, out = set(), []
    for l in layers:
        key = l.get("id") or l.get("skel")
        if key in seen:
            continue
        seen.add(key)
        out.append(l)
    return out


def atlas_pages(atlas_text: str) -> list[str]:
    """Nama halaman PNG yang dirujuk atlas."""
    pages = []
    for line in atlas_text.splitlines():
        s = line.strip()
        if s.lower().endswith((".png", ".jpg", ".jpeg")) and ":" not in s:
            pages.append(s)
    return pages


def convert_atlas(text: str) -> str:
    """`bounds:` (Spine 3.x) -> `xy:`/`size:` (Spine 4.x) bila perlu."""
    if "bounds:" not in text:
        return text
    out = []
    for line in text.splitlines():
        if line.strip().startswith("bounds:"):
            ind = line[: len(line) - len(line.lstrip())]
            _, vals = line.strip().split(":", 1)
            x, y, w, h = [v.strip() for v in vals.split(",")]
            out.append(f"{ind}xy: {x}, {y}")
            out.append(f"{ind}size: {w}, {h}")
        elif line.strip().startswith("scale:"):
            continue
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def model_name(layer: dict) -> str:
    """Nama folder unik dan aman untuk path."""
    base = layer.get("base") or os.path.basename(str(layer.get("dir", "")).rstrip("/"))
    grp = layer.get("group") or ""
    sub = layer.get("sub") or ""
    parts = [p for p in (grp, sub, base) if p]
    name = "_".join(parts) if parts else (layer.get("id") or "model")
    return "".join(c if c.isalnum() or c in "_-." else "_" for c in name)


def download_one(layer: dict) -> tuple[str, int, str | None]:
    """Unduh satu model. Kembalikan (nama, jumlah_berkas, error)."""
    name = model_name(layer)
    dest = os.path.join(OUT_DIR, name)
    skel_path = str(layer.get("skel") or "")
    atlas_path = str(layer.get("atlas") or "")
    if not skel_path or not atlas_path:
        return name, 0, "index tidak lengkap"

    try:
        skel_raw = fetch(f"{BUCKET}/majsoul/{urllib.parse.quote(skel_path)}")
        atlas_raw = fetch(f"{BUCKET}/majsoul/{urllib.parse.quote(atlas_path)}")
    except Exception as e:  # noqa: BLE001
        return name, 0, str(e)[:70]

    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, f"{name}.skel"), "wb") as fh:
        fh.write(skel_raw)
    atlas_text = convert_atlas(atlas_raw.decode("utf-8", "replace"))
    with open(os.path.join(dest, f"{name}.atlas"), "w", encoding="utf-8") as fh:
        fh.write(atlas_text)

    # Unduh setiap halaman PNG yang dirujuk atlas; atlas menunjuk nama berkas,
    # jadi nama itulah yang harus dipakai di disk (bukan nama model).
    n = 2
    base_dir = os.path.dirname(atlas_path)
    for page in atlas_pages(atlas_text):
        src = f"{base_dir}/{page}" if base_dir else page
        url_dir = os.path.dirname(src)
        # Nama halaman di atlas sering beda kapitalisasi dari berkas aslinya
        # (atlas: `Character_XNY_sy_Back.png`, CDN: `character_xny_sy_back.png`).
        # Diuji berurutan: apa adanya, lalu versi huruf kecil/besar, lalu
        # dengan garis bawah/spasi dibuang.
        stem, _, ext = page.rpartition(".")
        variants = [
            page,
            page.lower(),
            stem.lower() + "." + ext.lower(),
            stem.replace("_", "").lower() + "." + ext.lower(),
        ]
        png = None
        for variant in variants:
            try:
                png = fetch(f"{BUCKET}/majsoul/{urllib.parse.quote(url_dir + '/' + variant)}")
                break
            except Exception:
                continue
        if png is None:
            continue
        with open(os.path.join(dest, page), "wb") as fh:
            fh.write(png)
        n += 1
    return name, n, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Ambil Spine Mahjong Soul dari ArtHub")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    log("membaca index Mahjong Soul…")
    layers = load_index()
    log(f"model di index: {len(layers)}")

    os.makedirs(OUT_DIR, exist_ok=True)
    existing = {
        d for d in os.listdir(OUT_DIR)
        if os.path.isdir(os.path.join(OUT_DIR, d))
    }
    log(f"sudah ada di viewer: {len(existing)}")

    todo = [l for l in layers if model_name(l) not in existing]
    log(f"belum ada: {len(todo)}")
    if args.limit:
        todo = todo[: args.limit]

    if not args.apply:
        log(json.dumps({
            "total": len(layers),
            "have": len(existing),
            "new": len(todo),
            "note": "putar --apply untuk mengunduh",
        }, indent=1))
        return 0

    ok = 0
    failed: list[str] = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_one, l): l for l in todo}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            try:
                name, n, err = fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append(str(e)[:60])
                continue
            if err:
                failed.append(f"{name}: {err}")
            else:
                ok += 1
            if i % 20 == 0 or i == len(todo):
                log(f"  {i}/{len(todo)} | ok {ok} | gagal {len(failed)}")

    log(json.dumps({
        "ok": ok,
        "gagal": len(failed),
        "sampel_gagal": failed[:5],
    }, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
