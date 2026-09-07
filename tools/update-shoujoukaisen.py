#!/usr/bin/env python3
"""Perbarui aset Shoujou Kaisen (少女廻戦) dari server update resmi.

Alur (semua tanpa enkripsi):
  1. GET  http://sgversion.menaapp.net/version.php?p=android&g=sh&v=<versi>
     -> JSON berisi `data.url` (berisi versi terbaru) dan `data.burl`
        (mirror cadangan), plus `v` = versi terbaru.
  2. GET  <data.url>/versions.csv
     -> manifest 20.016 baris: header versi, lalu
        path,md5,size,flag,?,versi
  3. Bandingkan folder model/ dengan yang sudah ada di pohon aset.
  4. Unduh yang baru, lalu ekstrak Spine-nya (Spine 3.8.97).

Catatan ekstraksi mengikuti tools/shoujoukaisen/README.md:
  * setiap bundle diawali sampah sebelum header UnityFS yang asli — cari
    kemunculan KEDUA "UnityFS\\0" dan buang sebelumnya (panjangnya tidak
    tetap karena ada string versi Unity);
  * tekstur sering ada di bundle terpisah `<nama>_texture.asset`;
  * satu bundle bisa berisi dua skeleton dengan nama sama — pilih yang
    paling besar.

Pemakaian:
    /srv/venv-spine/bin/python tools/update-shoujoukaisen.py --check
    /srv/venv-spine/bin/python tools/update-shoujoukaisen.py --apply
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

VERSION_URL = "http://sgversion.menaapp.net/version.php?p=android&g=sh&v=0.820.1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

STATE_DIR = "/srv/spine-assets/shoujoukaisen"
MANIFEST_DIR = os.path.join(STATE_DIR, "manifest")
DOWNLOAD_DIR = os.path.join(STATE_DIR, "downloads")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
# Pohon aset yang dibaca viewer: assets/shoujoukaisen -> /srv/spine-assets/sk-models
ASSET_DIR = os.environ.get("SK_OUT", "/srv/spine-assets/sk-models")
EXTRACTOR = "/srv/spine-viewer/tools/shoujoukaisen/extract.py"
PYTHON = os.environ.get("PY", "/srv/venv-spine/bin/python")


def load_extractor():
    """Impor extractor khusus game ini sebagai modul.

    tools/shoujoukaisen/extract.py hanya menerima berkas XAPK/ZIP lewat
    CLI-nya, tetapi fungsi `extract_bundle` di dalamnya bisa dipakai
    langsung pada bytes hasil unduhan — jadi tidak perlu membungkus
    unduhan menjadi ZIP hanya untuk mengekstraknya.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("sk_extract", EXTRACTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_update_info() -> dict:
    """Tanya server versi terbaru + URL berkas (dan mirror-nya)."""
    raw = http_get(VERSION_URL, timeout=30).decode("utf-8", "replace")
    obj = json.loads(raw)
    data = obj.get("data", {}) or {}
    base = (data.get("url") or "").rstrip("/")
    if not base:
        raise RuntimeError("server tidak mengembalikan data.url")
    return {
        "version": obj.get("v") or obj.get("tipsV") or "",
        "base": base,
        "mirror": (data.get("burl") or "").rstrip("/"),
    }


def manifest_path(info) -> str:
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    return os.path.join(MANIFEST_DIR, f"versions_{info['version']}.csv")


def load_manifest(info) -> dict:
    """Unduh (atau pakai cache) versions.csv, lalu petakan path -> md5/size."""
    path = manifest_path(info)
    if not os.path.exists(path):
        raw = http_get(f"{info['base']}/versions.csv", timeout=120)
        with open(path, "wb") as f:
            f.write(raw)
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    entries = {}
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        entries[parts[0]] = {"md5": parts[1], "size": int(parts[2] or 0)}
    return entries


def model_names(entries: dict) -> set:
    """Nama model dari manifest: model/<nama>.asset (bukan _texture)."""
    out = set()
    for p in entries:
        if not p.startswith("model/") or not p.endswith(".asset"):
            continue
        if p.endswith("_texture.asset"):
            continue
        out.add(p.split("/")[-1][: -len(".asset")])
    return out


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)


def check() -> dict:
    info = fetch_update_info()
    entries = load_manifest(info)
    names = model_names(entries)
    state = load_state()
    have = set()
    if os.path.isdir(ASSET_DIR):
        have = {n for n in os.listdir(ASSET_DIR) if os.path.isdir(os.path.join(ASSET_DIR, n))}
    baru = sorted(names - have)
    return {
        "version": info["version"],
        "previous": state.get("version"),
        "changed": state.get("version") != info["version"],
        "models_total": len(names),
        "models_have": len(have),
        "new": len(baru),
        "samples": baru[:10],
        "base": info["base"],
    }


def apply_update(limit: int = 0, workers: int = 8) -> dict:
    info = fetch_update_info()
    entries = load_manifest(info)
    names = model_names(entries)
    have = set()
    if os.path.isdir(ASSET_DIR):
        have = {n for n in os.listdir(ASSET_DIR) if os.path.isdir(os.path.join(ASSET_DIR, n))}
    baru = sorted(names - have)
    if limit:
        baru = baru[:limit]

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    done = failed = 0
    errors = []

    def get(name):
        # Unduh skeleton dan, kalau ada, bundle teksturnya.
        targets = [f"model/{name}.asset"]
        if f"model/{name}_texture.asset" in entries:
            targets.append(f"model/{name}_texture.asset")
        last = ""
        for rel in targets:
            dest = os.path.join(DOWNLOAD_DIR, rel.replace("/", "__"))
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                continue
            for host in [info["base"], info["mirror"]]:
                if not host:
                    continue
                try:
                    raw = http_get(f"{host}/{rel}")
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(raw)
                    last = ""
                    break
                except Exception as exc:
                    last = f"{rel}: {exc}"
            if last:
                return last
        return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for err in ex.map(get, baru):
            if err:
                failed += 1
                if len(errors) < 5:
                    errors.append(err)
            else:
                done += 1

    # Ekstrak langsung dari bytes hasil unduhan.
    extracted = 0
    extract_error = None
    seen_new = []
    errors_ext = []
    if done and os.path.isdir(DOWNLOAD_DIR):
        try:
            sk = load_extractor()
        except Exception as exc:
            sk = None
            extract_error = f"tidak bisa memuat extractor: {exc}"
        if sk:
            os.makedirs(ASSET_DIR, exist_ok=True)
            for name in sorted(os.listdir(DOWNLOAD_DIR)):
                if not name.endswith(".asset"):
                    continue
                # nama berkas: model__<nama>.asset / model__<nama>_texture.asset
                stem = name[len("model__"):] if name.startswith("model__") else name
                stem = stem[: -len(".asset")]
                base_stem = stem[: -len("_texture")] if stem.endswith("_texture") else stem
                if base_stem in have:
                    continue  # sudah ada, lewati
                main_path = os.path.join(DOWNLOAD_DIR, f"model__{base_stem}.asset")
                tex_path = os.path.join(DOWNLOAD_DIR, f"model__{base_stem}_texture.asset")
                if not os.path.exists(main_path):
                    continue
                try:
                    main_data = sk.strip_prefix(open(main_path, "rb").read())
                    tex_data = ()
                    if os.path.exists(tex_path):
                        tex_data = (sk.strip_prefix(open(tex_path, "rb").read()),)
                    tmp_out = os.path.join(STATE_DIR, "extract_tmp")
                    shutil.rmtree(tmp_out, ignore_errors=True)
                    os.makedirs(tmp_out, exist_ok=True)
                    err = sk.extract_bundle(main_data, tmp_out, base_stem, tex_data)
                    if err:
                        errors_ext.append(f"{base_stem}: {err}")
                        continue
                    # extract_bundle menulis berkas rata di out_dir (skel,
                    # atlas, png...) — bukan ke dalam subfolder. Kumpulkan
                    # ke satu folder model supaya sesuai tata letak viewer
                    # (<nama>/<nama>.skel).
                    files = [
                        f for f in os.listdir(tmp_out)
                        if os.path.isfile(os.path.join(tmp_out, f))
                    ]
                    if not files:
                        errors_ext.append(f"{base_stem}: tidak ada berkas hasil")
                        continue
                    final = os.path.join(ASSET_DIR, base_stem)
                    if os.path.exists(final):
                        shutil.rmtree(tmp_out, ignore_errors=True)
                        continue
                    os.makedirs(final, exist_ok=True)
                    for f in files:
                        shutil.move(os.path.join(tmp_out, f), os.path.join(final, f))
                    extracted += 1
                    if len(seen_new) < 10:
                        seen_new.append(base_stem)
                except Exception as exc:
                    errors_ext.append(f"{base_stem}: {exc}")
            shutil.rmtree(os.path.join(STATE_DIR, "extract_tmp"), ignore_errors=True)

    state = load_state()
    state["version"] = info["version"]
    state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)

    return {
        "version": info["version"],
        "downloaded": done,
        "failed": failed,
        "extracted": extracted,
        "new_models": seen_new,
        "asset_dir": ASSET_DIR,
        "extract_error": extract_error,
        "extract_errors": errors_ext[:5],
        "errors": errors,
        "dir": DOWNLOAD_DIR,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.apply:
        print(json.dumps(apply_update(limit=args.limit), indent=1, ensure_ascii=False))
    elif args.check:
        print(json.dumps(check(), indent=1, ensure_ascii=False))
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
