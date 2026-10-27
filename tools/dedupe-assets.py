#!/usr/bin/env python3
"""Deteksi & hapus model duplikat di assets/.

Masalah
=======

Viewer ini dibangun dari beberapa sumber yang saling tumpang tindih:

    assets/bd2        — sumber lama (skrip bd2-char / BD2 lengkap)
    assets/bd2-char   — hasil tools/browndust, dikelompokkan per karakter
    assets/bd2-arthub — hasil tools/update-arthub.py (ArtHub)

Model yang sama bisa muncul di dua tempat dengan nama folder berbeda, mis.

    bd2/char/char001197/cutscene/cutscene_char001197.*
    bd2-arthub/cutscene_char001197/cutscene_char001197.*

Skeleton-nya byte-identik dan halaman PNG-nya sama, hanya jumlah halaman yang
kadang berbeda (sumber lama sering lebih lengkap). Hasilnya pengguna melihat
dua entri untuk satu karakter.

Cara kerja
==========

Duplikat dikenali dari hash .skel (bukan nama), lalu dikelompokkan. Dalam satu
grup dipilih SATU pemenang dengan skor:

    1. jumlah halaman PNG terbanyak   (paling lengkap)
    2. jumlah berkas terbanyak
    3. path terpendek                 (sedikit segmen = lebih rapi)
    4. urutan abjad                   (deterministik)

Sisanya dilaporkan sebagai kandidat hapus. Default hanya MELAPOR; hapus harus
memakai --apply. Folder yang dihapus dicatat ke JSON agar bisa dipulihkan
dari sumber aslinya bila salah pilih.

Pemakaian
=========
    python tools/dedupe-assets.py                 # lapor saja
    python tools/dedupe-assets.py --apply         # hapus
    python tools/dedupe-assets.py --roots bd2 bd2-arthub --apply
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
ASSETS = os.path.join(REPO, "assets")

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def log(*a) -> None:
    print(*a, flush=True)


def skel_path(folder: str) -> str | None:
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        if f.endswith(".skel") and os.path.isfile(p):
            return p
    return None


def folder_fingerprint(folder: str) -> str | None:
    """Fingerprint isi model: hash .skel + semua halaman gambar.

    Hanya memakai hash .skel TIDAK cukup: banyak model berbagi skeleton yang
    sama tapi berbeda tekstur (mis. arkrecode/M019_1..3 punya .skel identik
    namun PNG berbeda — itu varian ekspresi/kostum, bukan duplikat). Karena
    itu hash gambar ikut dihitung supaya varian tidak pernah dianggap kembar.
    """
    skel = skel_path(folder)
    if not skel:
        return None
    h = hashlib.sha256()
    with open(skel, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)

    imgs = sorted(f for f in os.listdir(folder) if f.lower().endswith(IMG_EXT))
    if not imgs:
        return None  # tanpa tekstur: tidak bisa dipastikan kembar
    h.update(b"\x00imgs\x00")
    for name in imgs:
        p = os.path.join(folder, name)
        if not os.path.isfile(p):
            continue
        # nama diabaikan (halaman bisa bernama beda antar sumber);
        # isi tiap halaman di-hash berurutan.
        h.update(b"\x00")
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def pages_signature(folder: str) -> set[str]:
    """Hash tiap halaman gambar, untuk memilih pemenang yang paling lengkap."""
    out = set()
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        if not f.lower().endswith(IMG_EXT) or not os.path.isfile(p):
            continue
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out.add(h.hexdigest())
    return out


def score(folder: str) -> tuple:
    """Skor pemenang dalam satu grup duplikat.

    Prioritas: model paling lengkap. "Lengkap" bukan hanya jumlah halaman PNG
    di folder itu sendiri, tetapi juga isi subfoldernya — satu folder karakter
    sering berisi model utama + submodel (cutscene/interaction/skill) yang
    justru punya banyak halaman tambahan. Contoh: bd2/char/char001197 punya
    1 halaman di akar tetapi subfolder cutscene-nya 6 halaman, sehingga lebih
    berharga daripada satu folder datar berisi 1 halaman.
    """
    total_imgs = 0
    total_files = 0
    for root, _dirs, files in os.walk(folder):
        total_files += len(files)
        total_imgs += sum(1 for f in files if f.lower().endswith(IMG_EXT))
    has_sub = any(
        os.path.isdir(os.path.join(folder, d)) for d in os.listdir(folder)
    )
    # pemenang: halaman terbanyak (termasuk subfolder), berkas terbanyak,
    # path terpendek, lalu abjad agar deterministik
    return (total_imgs, has_sub, total_files, -len(folder), folder)


def collect_models(roots: list[str]) -> dict[str, dict]:
    """Semua folder yang berisi .skel, dipetakan ke fingerprint-nya."""
    out: dict[str, dict] = {}
    for root in roots:
        base = os.path.join(ASSETS, root)
        if not os.path.isdir(base):
            continue
        for folder in glob.glob(base + "/**/", recursive=True):
            folder = folder.rstrip("/")
            if not os.path.isdir(folder):
                continue
            fp = folder_fingerprint(folder)
            if not fp:
                continue
            rel = os.path.relpath(folder, ASSETS)
            out[folder] = {
                "fp": fp,
                "rel": rel,
                "imgs": sum(1 for f in os.listdir(folder) if f.lower().endswith(IMG_EXT)),
                "files": len(os.listdir(folder)),
            }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Cari & hapus model duplikat")
    ap.add_argument("--roots", nargs="*", default=None,
                    help="folder di dalam assets/ (default: semua)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", default=None, help="tulis laporan ke berkas JSON")
    args = ap.parse_args()

    roots = args.roots
    if not roots:
        roots = sorted(
            d for d in os.listdir(ASSETS)
            if os.path.isdir(os.path.join(ASSETS, d))
        )

    log(f"memindai {len(roots)} folder game…")
    models = collect_models(roots)
    log(f"model (folder ber-.skel): {len(models)}")

    groups: dict[str, list[str]] = defaultdict(list)
    for folder, info in models.items():
        groups[info["fp"]].append(folder)

    # Grup exact = isi sama persis (skel + semua halaman).
    # Selain itu, dua model bisa berupa SUPERSET/SUBSET: skeleton sama, halaman
    # yang satu merupakan himpunan bagian dari yang lain (sumber lama punya
    # lebih banyak halaman). Itu juga duplikat — pengguna melihat entri ganda —
    # tapi VARIAN TEKSTUR (skel sama, halaman berbeda isi) BUKAN duplikat.
    sig = {f: pages_signature(f) for f in models}
    by_skel: dict[str, list[str]] = defaultdict(list)
    for folder in models:
        s = skel_path(folder)
        if not s:
            continue
        h = hashlib.sha256(open(s, "rb").read()).hexdigest()
        by_skel[h].append(folder)

    subset_pairs = []
    for _h, folders in by_skel.items():
        if len(folders) < 2:
            continue
        folders.sort(key=lambda f: len(sig[f]), reverse=True)
        for i, a in enumerate(folders):
            for b in folders[i + 1:]:
                if not sig[b] or not sig[a]:
                    continue
                if sig[b] <= sig[a] and len(sig[b]) < len(sig[a]):
                    subset_pairs.append((a, b))

    dups = {k: v for k, v in groups.items() if len(v) > 1}
    total_involved = sum(len(v) for v in dups.values())
    log(f"grup duplikat (isi sama persis): {len(dups)} | folder: {total_involved}")
    log(f"pasangan subset (satu lebih lengkap): {len(subset_pairs)}")

    plan = []
    for fp, folders in dups.items():
        folders.sort(key=score, reverse=True)
        keep, drop = folders[0], folders[1:]
        plan.append({
            "fp": fp[:12],
            "keep": os.path.relpath(keep, ASSETS),
            "keep_imgs": models[keep]["imgs"],
            "drop": [
                {"path": os.path.relpath(d, ASSETS), "imgs": models[d]["imgs"]}
                for d in drop
            ],
        })

    will_drop = sum(len(p["drop"]) for p in plan)
    log(f"akan dihapus: {will_drop} folder (menyisakan {len(plan)} model)")
    for p in plan[:12]:
        log(f"\n  SIMPAN {p['keep']}  ({p['keep_imgs']} png)")
        for d in p["drop"]:
            log(f"   hapus {d['path']}  ({d['imgs']} png)")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(plan, fh, indent=1, ensure_ascii=False)
        log(f"\nlaporan: {args.json}")

    if not args.apply:
        log("\n(uji coba — jalankan dengan --apply untuk menghapus)")
        return 0

    removed = 0
    for p in plan:
        for d in p["drop"]:
            path = os.path.join(ASSETS, d["path"])
            try:
                shutil.rmtree(path)
                removed += 1
            except Exception as e:  # noqa: BLE001
                log(f"  gagal hapus {d['path']}: {e}")
    log(f"\ndihapus: {removed} folder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
