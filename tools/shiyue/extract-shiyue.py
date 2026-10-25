#!/usr/bin/env python3
"""Ekstrak model Spine dari APK game "shiyue" (慾女神話 / 淫欲斗羅).

Alur per model:
    APK -> assets/res/spine/<id>/action.{skel,atlas,png}
        -> dekripsi PNG (XXTEA, kunci JYDYdpyRecDuHQc8)
        -> konversi .skel ke JSON 3.8 (SpineSkeletonDataConverter)
        -> tulis ke assets/<game>/<id>/

Kenapa harus dikonversi: .skel di game ini versi 3.4/3.6 dan runtime
pixi-spine di viewer tidak punya parser binernya (3.8 menghasilkan skeleton
kosong: 0 tulang). SpineSkeletonDataConverter (wang606) punya Binary Reader
asli untuk 3.4-3.6 sehingga bisa menulis ulang ke 3.8 JSON, yang runtime
viewer sudah dukung.

Pemakaian:
    python extract-shiyue.py --apk /path.apk --game yynv
    python extract-shiyue.py --apk /path.apk --game yynv --limit 20
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CONVERTER = os.environ.get("SSDC", "/opt/ssdc/build/SpineSkeletonDataConverter")

sys.path.insert(0, HERE)
from decrypt import decrypt_bytes, is_encrypted  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def skeleton_version(data: bytes) -> str:
    """Ambil string versi Spine dari .skel biner.

    Jangan mengandalkan offset tetap: tata letak header berbeda antar versi.
    Pada 3.6/3.8 ada hash 8 byte lalu string versi; pada 3.4/3.5 langsung
    string versi. Jadi cari pola "x.y.z" di 64 byte pertama dan ambil yang
    bentuknya paling masuk akal.

    Versi salah baca sebelumnya membuat laporan statistik penuh sampah biner
    (mis. "=1725", "root=3") sehingga tidak informatif.
    """
    head = data[:64]
    best = ""
    i = 0
    while i < len(head) - 3:
        if head[i : i + 1].isdigit():
            j = i
            while j < len(head) and (head[j : j + 1].isdigit() or head[j : j + 1] == b"."):
                j += 1
            cand = head[i:j].decode("ascii", "ignore")
            # bentuk yang diharapkan: digit.digit[.digit]
            if cand.count(".") >= 1 and len(cand) >= 3:
                best = cand
                break
            i = j
        else:
            i += 1
    return best or "?"


def main() -> int:
    ap = argparse.ArgumentParser(description="Ekstrak Spine dari game shiyue")
    ap.add_argument("--apk", required=True)
    ap.add_argument("--game", required=True, help="nama folder di assets/")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--target", default="3.8.99", help="versi Spine keluaran")
    args = ap.parse_args()

    out_dir = args.out or os.path.join(REPO, "assets", args.game)
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(CONVERTER):
        log(f"konverter tidak ada: {CONVERTER}")
        return 1

    zf = zipfile.ZipFile(args.apk)
    names = zf.namelist()

    # Kelompokkan per folder model. Nama berkas bervariasi (v00/v01/v012),
    # jadi kunci = <folder>/<stem> dan yang dikumpulkan adalah satu set
    # {json|skel, atlas, png} dengan stem yang sama.
    models: dict[str, dict[str, str]] = {}
    for n in names:
        if not n.startswith("assets/res/spine/") or n.endswith("/"):
            continue
        parts = n.split("/")
        if len(parts) < 5:
            continue
        folder, base = parts[3], parts[4]
        stem, _, ext = base.rpartition(".")
        ext = ext.lower()
        if ext not in ("skel", "json", "atlas", "png"):
            continue
        key = f"{folder}/{stem}"
        models.setdefault(key, {})[ext] = n

    # Hanya yang punya skeleton (json/skel) + atlas + png
    siap = {
        k: v for k, v in models.items()
        if ("json" in v or "skel" in v) and "atlas" in v and "png" in v
    }
    log(f"model ditemukan: {len(siap)}")

    ids = sorted(siap)
    if args.limit:
        ids = ids[: args.limit]

    ok = gagal = 0
    versi_counter: dict[str, int] = {}
    tmp = tempfile.mkdtemp(prefix="shiyue-")

    for i, key in enumerate(ids, 1):
        files = siap[key]
        stem = key.split("/")[-1]
        dest = os.path.join(out_dir, key.replace("/", "_"))
        try:
            os.makedirs(dest, exist_ok=True)

            # Atlas: simpan apa adanya (sudah plain)
            atlas_raw = zf.read(files["atlas"])
            with open(os.path.join(dest, f"{stem}.atlas"), "wb") as fh:
                fh.write(atlas_raw)

            # Satu model bisa memakai BEBERAPA halaman PNG (contoh nyata:
            # 10001/v01.atlas merujuk v01.png DAN v012.png). Kalau hanya
            # halaman utama yang diekstrak, model gagal dengan
            # "Halaman atlas “v012.png” tidak ditemukan". Jadi semua nama
            # halaman dibaca dari atlas lalu dicari di APK.
            pages = []
            for line in atlas_raw.decode("utf-8", "replace").splitlines():
                s = line.strip()
                if s.lower().endswith((".png", ".jpg", ".jpeg")) and ":" not in s:
                    pages.append(s)
            folder = key.split("/")[0]
            for page in pages:
                src = f"assets/res/spine/{folder}/{page}"
                if src not in names:
                    continue
                with open(os.path.join(dest, page), "wb") as fh:
                    fh.write(decrypt_bytes(zf.read(src)))
            if not pages:
                # fallback: halaman utama saja
                with open(os.path.join(dest, f"{stem}.png"), "wb") as fh:
                    fh.write(decrypt_bytes(zf.read(files["png"])))

            dst_json = os.path.join(dest, f"{stem}.json")

            if "json" in files:
                # Sudah JSON (3.7.94) — runtime viewer bisa membacanya langsung.
                raw = zf.read(files["json"])
                versi_counter["json"] = versi_counter.get("json", 0) + 1
                out = decrypt_bytes(raw)
                with open(dst_json, "wb") as fh:
                    fh.write(out)
                ok += 1
            else:
                skel_raw = zf.read(files["skel"])
                ver = skeleton_version(skel_raw)
                versi_counter[ver] = versi_counter.get(ver, 0) + 1
                src_skel = os.path.join(tmp, f"{stem}.skel")
                with open(src_skel, "wb") as fh:
                    fh.write(skel_raw)
                res = subprocess.run(
                    [CONVERTER, src_skel, dst_json, "-v", args.target],
                    capture_output=True, text=True,
                )
                os.unlink(src_skel)
                # Hapus JSON kosong kalau konversi gagal, supaya tidak
                # ada model setengah jadi di assets/
                if res.returncode != 0 or not os.path.exists(dst_json):
                    gagal += 1
                    shutil.rmtree(dest, ignore_errors=True)
                    continue
                ok += 1
        except Exception:
            gagal += 1
            shutil.rmtree(dest, ignore_errors=True)
        if i % 25 == 0 or i == len(ids):
            log(f"  {i}/{len(ids)} | ok {ok} | gagal {gagal}")

    shutil.rmtree(tmp, ignore_errors=True)
    log(f"\nselesai: {ok} model, gagal {gagal}")
    log("versi .skel yang ditemui: " + ", ".join(f"{k}={v}" for k, v in sorted(versi_counter.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
