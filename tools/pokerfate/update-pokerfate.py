#!/usr/bin/env python3
"""Updater aset Spine PokerFate untuk spine-viewer.

Alur lengkap (semuanya lokal, tidak ada endpoint game yang dipanggil):

    APK  ->  ekstrak bundle  ->  dekripsi XENC  ->  ekspor Spine  ->  assets/

Pemakaian:
    python update-pokerfate.py                 # pakai APK yang sudah ada
    python update-pokerfate.py --download       # unduh APK dulu
    python update-pokerfate.py --apk /path.apk
    python update-pokerfate.py --keep-temp      # simpan apk/plain/out

Kenapa skrip terpisah dari tools/ lain: pipeline PokerFate butuh tiga tahap
berat (1,4 GB dekripsi per berkas, ekstraksi 529 bundle) dan bergantung pada
UnityPy, jadi tidak cocok dijalankan di dalam proses server.

Catatan versi: konstanta dekripsi terikat pada versi APK. Skrip ini
memverifikasi hasil dekripsi dan BERHENTI kalau header bukan UnityFS, alih-
alih melanjutkan dengan data sampah.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

APK_URL = "https://aws.poker-fate.com/dl/PokerFate_Android.apk"
DEFAULT_WORK = "/opt/games/pokerfate"
ASSETS_SUBDIR = "pokerfate"

sys.path.insert(0, HERE)
from decrypt import decrypt_file  # noqa: E402
from convert_atlas import convert as convert_atlas  # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, **kw)


def download_apk(dest: str) -> str:
    if os.path.exists(dest) and os.path.getsize(dest) > 100 * 1024 * 1024:
        log(f"APK sudah ada, dilewati: {dest} ({os.path.getsize(dest)/2**30:.2f} GB)")
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    log(f"mengunduh {APK_URL}")
    with urllib.request.urlopen(APK_URL, timeout=120) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        last = 0.0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if time.time() - last > 10:
                last = time.time()
                pct = (done / total * 100) if total else 0
                log(f"  {done/2**30:.2f} GB / {total/2**30:.2f} GB ({pct:.1f}%)")
    os.replace(tmp, dest)
    log("unduhan selesai")
    return dest


def extract_apk(apk: str, out_dir: str) -> None:
    marker = os.path.join(out_dir, ".extracted")
    if os.path.exists(marker):
        log("bundle sudah pernah diekstrak, dilewati")
        return
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    log("mengekstrak assets/aa dari APK")
    res = run(["7z", "x", "-y", f"-o{out_dir}", apk, "assets/aa/*"],
              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if res.returncode != 0:
        raise SystemExit("7z gagal mengekstrak APK")
    open(marker, "w").close()


def find_bundles(root: str) -> list[str]:
    out = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".bundle"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def decrypt_all(src_root: str, plain_dir: str) -> list[str]:
    os.makedirs(plain_dir, exist_ok=True)
    bundles = find_bundles(src_root)
    log(f"bundle ditemukan: {len(bundles)}")
    done = 0
    failed = 0
    for i, path in enumerate(bundles, 1):
        dst = os.path.join(plain_dir, os.path.basename(path))
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            done += 1
            continue
        status = decrypt_file(path, dst)
        if status == "gagal":
            failed += 1
        else:
            done += 1
        if i % 40 == 0 or i == len(bundles):
            log(f"  dekripsi {i}/{len(bundles)} (gagal: {failed})")
    if failed:
        raise SystemExit(
            f"{failed} bundle gagal didekripsi. Konstanta S/C kemungkinan tidak "
            "cocok dengan versi APK ini. Proses dihentikan."
        )
    log(f"dekripsi selesai: {done} berkas")
    return bundles


def export_all(plain_dir: str, out_dir: str) -> dict:
    log("mengekspor Spine (UnityPy)")
    before = set(os.listdir(out_dir)) if os.path.isdir(out_dir) else set()
    res = run([sys.executable, os.path.join(HERE, "export_spine.py"), plain_dir, out_dir])
    if res.returncode != 0:
        raise SystemExit("export_spine.py gagal")
    after = set(os.listdir(out_dir))
    baru = sorted(x for x in (after - before) if os.path.isdir(os.path.join(out_dir, x)))
    manifest_path = os.path.join(out_dir, "_manifest.json")
    manifest = []
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    ok = [m for m in manifest if m.get("status") == "ok"]
    log(f"model siap: {len(ok)} (baru: {len(baru)})")
    return {"manifest": manifest, "ok": ok, "baru": baru}


def publish(out_dir: str, assets_dir: str) -> int:
    """Salin hasil ke assets/ dengan penanda versi, ganti secara atomik."""
    dest = os.path.join(assets_dir, ASSETS_SUBDIR)
    tmp = dest + ".new"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp, exist_ok=True)

    copied = 0
    for entry in sorted(os.listdir(out_dir)):
        src = os.path.join(out_dir, entry)
        if not os.path.isdir(src):
            continue
        target = os.path.join(tmp, entry)
        shutil.copytree(src, target, dirs_exist_ok=True)
        copied += 1

    # Tulis indeks: slug -> daftar berkas, supaya server bisa memetakan cepat.
    index = {}
    for slug in sorted(os.listdir(tmp)):
        d = os.path.join(tmp, slug)
        if not os.path.isdir(d):
            continue
        skels = sorted(f for f in os.listdir(d) if f.lower().endswith(".skel"))
        atlas = sorted(f for f in os.listdir(d) if f.lower().endswith(".atlas"))
        index[slug] = {"skel": skels, "atlas": atlas}
    with open(os.path.join(tmp, "_index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)

    old = dest + ".old"
    if os.path.isdir(old):
        shutil.rmtree(old)
    if os.path.isdir(dest):
        os.rename(dest, old)
    os.rename(tmp, dest)
    if os.path.isdir(old):
        shutil.rmtree(old, ignore_errors=True)

    log(f"{copied} model dipasang ke {dest}")
    return copied


def main() -> int:
    ap = argparse.ArgumentParser(description="Updater aset Spine PokerFate")
    ap.add_argument("--apk", default=os.path.join(DEFAULT_WORK, "PokerFate_Android.apk"),
                    help="path APK")
    ap.add_argument("--download", action="store_true", help="unduh APK dulu")
    ap.add_argument("--work", default=DEFAULT_WORK, help="direktori kerja")
    ap.add_argument("--assets", default=os.path.join(REPO, "assets"),
                    help="direktori assets spine-viewer")
    ap.add_argument("--keep-temp", action="store_true",
                    help="jangan hapus apk/plain/out setelah selesai")
    ap.add_argument("--skip-publish", action="store_true", help="ekspor saja, jangan pasang")
    args = ap.parse_args()

    os.makedirs(args.work, exist_ok=True)
    apk = args.apk
    if args.download or not os.path.exists(apk):
        apk = download_apk(apk)

    apk_dir = os.path.join(args.work, "apk")
    plain_dir = os.path.join(args.work, "plain")
    out_dir = os.path.join(args.work, "out")

    extract_apk(apk, apk_dir)
    decrypt_all(apk_dir, plain_dir)
    hasil = export_all(plain_dir, out_dir)

    if not hasil["ok"]:
        raise SystemExit("tidak ada model yang berhasil diekspor")

    if not args.skip_publish:
        publish(out_dir, args.assets)

    if not args.keep_temp:
        for d in (apk_dir, plain_dir):
            shutil.rmtree(d, ignore_errors=True)
        log("direktori sementara dihapus (pakai --keep-temp untuk menyimpan)")

    log(f"selesai: {len(hasil['ok'])} model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
