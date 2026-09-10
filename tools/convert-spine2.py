#!/usr/bin/env python3
"""Konversi skeleton biner Spine 2.x (.skel) menjadi JSON 2.x.

WHY THIS EXISTS
    Model Spine 2.1.27 (Project QT, Echocalypse) selama ini ditampilkan lewat
    iframe ke penampil GWT vendored. Penampil itu punya loop dan kontrol
    sendiri, jadi timeline, skin, export PNG, dan FPS meter milik kita mati
    semua untuk model-model tersebut.

    Dengan mengubah .skel menjadi .json, model-model itu bisa dimuat oleh
    runtime pixi-spine 3.8/4.1 yang SUDAH ada — sehingga menjadi model biasa
    dan seluruh fitur viewer aktif.

WHY THE EXTERNAL CONVERTER
    Format biner 2.1.27 punya banyak variasi yang tidak terdokumentasi
    (percabangan `nonessential`, lampiran tipe 4/13/63, urutan lampiran FFD
    yang tidak mengikuti nama). Parser buatan sendiri hanya mencapai ~8%
    pada Project QT: file kecil 100%, file besar 0%.

    Converter ini memakai SpineConverter2.1.27 (brachna, MIT) yang diujikan
    terhadap Darkest Dungeon dan mencapai 1294/1323 (97,8%) pada Project QT.
    Jauh lebih baik daripada menebak format.

WHERE THE CONVERTER COMES FROM
    Di-clone otomatis ke /tmp pada kali pertama, atau set SPINE2_CONVERTER
    ke direktori yang sudah ada. Tidak di-vendor ke repo ini karena lisensi
    dan riwayatnya milik proyek lain.

Pemakaian
    /srv/venv-spine/bin/python tools/convert-spine2.py <direktori-atau-berkas>
    /srv/venv-spine/bin/python tools/convert-spine2.py /srv/spine-assets/projectqt-native2/SimGirls_Spine_5
    /srv/venv-spine/bin/python tools/convert-spine2.py <src> --out /srv/spine-assets/qt-json

Keluaran
    Satu direktori per model berisi <nama>.json, dan — bila --copy-assets —
    salinan .atlas serta tekstur yang menyertainya, supaya direktori hasil
    bisa langsung disajikan.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request

REPO = "https://github.com/brachna/SpineConverter2.1.27.git"
DEFAULT_CLONE = "/tmp/SpineConverter2.1.27"

# Ekstensi tekstur yang menemani .atlas.
TEXTURE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def ensure_converter(explicit: str | None = None) -> str:
    """Pastikan converter tersedia; clone bila perlu. Kembalikan direktorinya."""
    if explicit:
        if not os.path.isdir(explicit):
            sys.exit(f"Direktori converter tidak ada: {explicit}")
        return explicit

    env = os.environ.get("SPINE2_CONVERTER")
    if env and os.path.isdir(env):
        return env
    if os.path.isdir(DEFAULT_CLONE):
        return DEFAULT_CLONE

    print(f"Mengambil converter ke {DEFAULT_CLONE} ...", file=sys.stderr)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", REPO, DEFAULT_CLONE],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except Exception as exc:
        sys.exit(
            f"Gagal mengambil converter: {exc}\n"
            f"Ambil manual: git clone --depth 1 {REPO}\n"
            f"lalu set SPINE2_CONVERTER=<direktori>"
        )
    return DEFAULT_CLONE


def find_models(root: str) -> list[str]:
    """Kembalikan direktori model (yang berisi .skel) di bawah root."""
    if os.path.isfile(root):
        return [os.path.dirname(os.path.abspath(root))]
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if any(f.lower().endswith(".skel") for f in filenames):
            out.append(dirpath)
    return sorted(out)


def convert(src: str, out_root: str, copy_assets: bool, converter_dir: str):
    sys.path.insert(0, converter_dir)
    try:
        from spBinaryReader import spBinaryReader
        from spJsonWriter import spJsonWriter
    except ImportError as exc:
        sys.exit(f"Converter tidak bisa diimpor dari {converter_dir}: {exc}")

    models = find_models(src)
    if not models:
        sys.exit(f"Tidak ada .skel di bawah {src}")

    ok, failed = 0, []
    for model_dir in models:
        name = os.path.basename(model_dir.rstrip("/"))
        skels = [f for f in os.listdir(model_dir) if f.lower().endswith(".skel")]
        # Satu direktori bisa berisi beberapa skeleton (varian dorm/base).
        # Semua dikonversi, bukan hanya yang pertama.
        for skel in skels:
            stem = os.path.splitext(skel)[0]
            out_dir = os.path.join(out_root, name)
            os.makedirs(out_dir, exist_ok=True)
            dst = os.path.join(out_dir, stem + ".json")
            try:
                reader = spBinaryReader()
                reader.readFile(os.path.join(model_dir, skel))
                data = reader.readSkeletonData()
                if not data or not data.get("bones"):
                    failed.append((f"{name}/{skel}", "skeleton kosong"))
                    continue
                writer = spJsonWriter()
                writer.writeSkeletonDataFile(data, dst)
                ok += 1
            except Exception as exc:
                failed.append((f"{name}/{skel}",
                               f"{type(exc).__name__}: {str(exc)[:60]}"))
                continue

            if copy_assets:
                for f in os.listdir(model_dir):
                    low = f.lower()
                    if low.endswith(".atlas") or low.endswith(TEXTURE_EXT):
                        shutil.copy2(os.path.join(model_dir, f),
                                     os.path.join(out_dir, f))

    print(f"\nSelesai: OK={ok} GAGAL={len(failed)}")
    for n, m in failed[:15]:
        print(f"  {n}: {m}")
    if len(failed) > 15:
        print(f"  ... dan {len(failed) - 15} lagi")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="direktori game, direktori model, atau berkas .skel")
    ap.add_argument("--out", default=None,
                    help="direktori hasil (default: <src>-json)")
    ap.add_argument("--copy-assets", action="store_true",
                    help="salin .atlas dan tekstur ke direktori hasil")
    ap.add_argument("--converter", default=None,
                    help="direktori SpineConverter2.1.27 (atau set SPINE2_CONVERTER)")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    if not os.path.exists(src):
        sys.exit(f"Tidak ada: {src}")
    out_root = args.out or (src.rstrip("/") + "-json")
    converter_dir = ensure_converter(args.converter)
    print(f"Converter : {converter_dir}")
    print(f"Sumber    : {src}")
    print(f"Hasil     : {out_root}")
    return convert(src, out_root, args.copy_assets, converter_dir)


if __name__ == "__main__":
    sys.exit(main())
