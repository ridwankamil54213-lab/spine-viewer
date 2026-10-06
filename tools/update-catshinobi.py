#!/usr/bin/env python3
"""Perbarui model Spine Cat Shinobi (ねこ親方 / com.cookapps.catshinobi).

Cat Shinobi adalah Unity Addressables: skeleton-nya berada di dalam bundle
`assets/aa/Android/*.bundle` di dalam APK split `split_UnityDataAssetPack.apk`
yang terpasang di perangkat (redroid). Tidak ada CDN terpisah — game ini
mengemas 546 skeleton di satu bundle `defaultlocalgroup_assets_all_*.bundle`.

Alur:
    1. (opsional) `adb pull` split_UnityDataAssetPack.apk dari perangkat.
    2. unzip `assets/aa/Android/*.bundle` ke direktori kerja.
    3. Scan bundle: kumpulkan TextAsset .skel/.atlas + metadata Texture2D.
    4. Bandingkan dengan folder yang sudah ada di assets/catshinobi -> baru.
    5. Ekstrak HANYA yang baru ke assets/catshinobi/<nama>/.

Catatan penting (warisan dari extract-catshinobi.py):
  * TextAsset di-decode lewat get_raw_data() + parser manual; obj.read().m_Script
    merusak .skel biner.
  * Jangan obj.read() Texture2D saat scan (decode pixel mahal). Baca m_Width/
    m_Height saja, pilih yang TERBESAR untuk nama duplikat, lalu decode hanya
    halaman yang benar-benar dirujuk atlas.

Pemakaian:
    /srv/venv-spine/bin/python tools/update-catshinobi.py --check
    /srv/venv-spine/bin/python tools/update-catshinobi.py --apply
    /srv/venv-spine/bin/python tools/update-catshinobi.py --check --apk /opt/catshinobi/split_UnityDataAssetPack.apk
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile

import UnityPy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.environ.get("CS_OUT", os.path.join(ROOT, "assets", "catshinobi"))
WORK = os.environ.get("CS_WORK", "/srv/spine-assets/catshinobi-update")
APK_CACHE = os.path.join(WORK, "split_UnityDataAssetPack.apk")
BUNDLE_ROOT = os.path.join(WORK, "bundles")
BUNDLE_DIR = os.path.join(BUNDLE_ROOT, "assets", "aa", "Android")
PKG = "com.cookapps.catshinobi"
ADB = os.environ.get("ADB", "adb")
SERIAL = os.environ.get("ADB_SERIAL", "127.0.0.1:15555")

SPINE_EXTS = (".skel", ".atlas")


def safe(name):
    return os.path.basename(str(name)).replace("\\", "/").split("/")[-1].strip()


def parse_text_asset(raw):
    try:
        n = struct.unpack("<i", raw[0:4])[0]
        if not (0 < n < 512):
            return None, None
        name = raw[4:4 + n].decode("utf-8", "replace")
        pos = 4 + n
        pos += (4 - (pos % 4)) % 4
        size = struct.unpack("<i", raw[pos:pos + 4])[0]
        if not (0 <= size <= len(raw) - pos - 4):
            return name, None
        return name, raw[pos + 4:pos + 4 + size]
    except Exception:
        return None, None


def atlas_pages(blob):
    out = []
    try:
        text = blob.decode("utf-8", "replace")
    except Exception:
        return out
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            continue
        low = line.strip().lower()
        if low.endswith((".png", ".jpg", ".jpeg", ".webp")):
            out.append(line.strip())
        else:
            break
    return out


def strip_numeric_suffix(stem):
    m = re.match(r"^(.*?)_\d+$", stem)
    return m.group(1) if m else None


def _adb(*args):
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=True)


def device_split_path():
    out = _adb("shell", "pm", "path", PKG).stdout
    return next((l[len("package:"):].strip() for l in out.splitlines()
                 if "split_UnityDataAssetPack.apk" in l), None)


def device_split_size(path):
    for cmd in (["shell", "stat", "-c", "%s", path], ["shell", "wc", "-c", path]):
        out = _adb(*cmd).stdout.strip().split()[0] if _adb(*cmd).stdout.strip() else ""
        if out.isdigit():
            return int(out)
    return -1


def pull_bundles(force=False):
    """Pastikan bundle ada di BUNDLE_DIR.

    Murah saat diulang: kalau ukuran split di perangkat SAMA dengan APK yang
    sudah di-cache, lewati pull+unzip (unduhan 528 MB tidak diulang tiap check);
    kalau beda (game diperbarui) baru ambil ulang.
    """
    have_bundles = (os.path.isdir(BUNDLE_DIR)
                    and any(f.endswith(".bundle") for f in os.listdir(BUNDLE_DIR)))
    if have_bundles and not force:
        dev = device_split_path()
        if not dev:
            return
        size = device_split_size(dev)
        if size > 0 and os.path.exists(APK_CACHE) and os.path.getsize(APK_CACHE) == size:
            return  # cache masih cocok dengan perangkat
    os.makedirs(WORK, exist_ok=True)
    dev = device_split_path()
    if not dev:
        raise RuntimeError("split_UnityDataAssetPack.apk tidak ditemukan di perangkat")
    size = device_split_size(dev)
    need_pull = (not os.path.exists(APK_CACHE)
                 or (size > 0 and os.path.getsize(APK_CACHE) != size))
    if need_pull:
        subprocess.run([ADB, "-s", SERIAL, "pull", dev, APK_CACHE],
                       check=True, capture_output=True, text=True)
    # bersihkan lalu ekstrak ulang supaya tak ada bundle basi
    if os.path.isdir(BUNDLE_ROOT):
        shutil.rmtree(BUNDLE_ROOT, ignore_errors=True)
    os.makedirs(BUNDLE_ROOT, exist_ok=True)
    with zipfile.ZipFile(APK_CACHE) as z:
        for n in z.namelist():
            if n.startswith("assets/aa/Android/") and n.endswith(".bundle"):
                z.extract(n, BUNDLE_ROOT)
    if not any(f.endswith(".bundle") for f in os.listdir(BUNDLE_DIR)):
        raise RuntimeError("tidak ada bundle di %s" % BUNDLE_DIR)


def scan_bundles():
    """Kembalikan (texts, tex_objs, stats)."""
    texts, tex_objs = {}, {}
    for fname in sorted(f for f in os.listdir(BUNDLE_DIR) if f.endswith(".bundle")):
        path = os.path.join(BUNDLE_DIR, fname)
        try:
            env = UnityPy.load(path)
        except Exception:
            continue
        for obj in env.objects:
            if obj.type.name == "TextAsset":
                try:
                    name, data = parse_text_asset(obj.get_raw_data())
                except Exception:
                    continue
                if not name or not data or not name.lower().endswith(SPINE_EXTS):
                    continue
                nm = safe(name)
                if nm not in texts or len(data) > len(texts[nm]):
                    texts[nm] = data
            elif obj.type.name == "Texture2D":
                try:
                    d = obj.read_typetree()
                except Exception:
                    continue
                nm = safe(str(d.get("m_Name", "")))
                if not nm:
                    continue
                px = int(d.get("m_Width", 0) or 0) * int(d.get("m_Height", 0) or 0)
                if nm not in tex_objs or px > tex_objs[nm][0]:
                    tex_objs[nm] = (px, obj)
        del env
    return texts, tex_objs


def installed():
    if not os.path.isdir(ASSET_DIR):
        return set()
    return {n for n in os.listdir(ASSET_DIR) if os.path.isdir(os.path.join(ASSET_DIR, n))}


def discover():
    texts, tex_objs = scan_bundles()
    skels = sorted(n for n in texts if n.lower().endswith(".skel"))
    return texts, tex_objs, skels


def check():
    try:
        pull_bundles()
        texts, tex_objs, skels = discover()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "new": 0, "installed": len(installed())}
    have = installed()
    names = {s.rsplit(".", 1)[0] for s in skels}
    baru = sorted(names - have)
    try:
        ver = "apk-%d" % os.path.getsize(APK_CACHE)
    except OSError:
        ver = "apk"
    return {
        "ok": True,
        "version": ver,
        "total": len(names),
        "installed": len(have),
        "new": len(baru),
        "changed": bool(baru),
        "samples": baru[:20],
        "textures": len(tex_objs),
    }


def apply_update(limit=0):
    try:
        pull_bundles()
        texts, tex_objs, skels = discover()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "extracted": 0}

    have = installed()
    names = {s.rsplit(".", 1)[0] for s in skels}
    baru = sorted(names - have)
    if limit:
        baru = baru[:limit]

    # atlas (dan varian suffix) per stem
    atlases = {n for n in texts if n.lower().endswith(".atlas")}
    atlas_by_stem = {}
    for a in atlases:
        stem = a.rsplit(".", 1)[0]
        atlas_by_stem.setdefault(stem, []).append(a)
        base = strip_numeric_suffix(stem)
        if base and base != stem:
            atlas_by_stem.setdefault(base, []).append(a)

    os.makedirs(ASSET_DIR, exist_ok=True)
    extracted = []
    errors = []
    for stem in baru:
        sk = stem + ".skel"
        if sk not in texts:
            continue
        cands = atlas_by_stem.get(stem) or atlas_by_stem.get(strip_numeric_suffix(stem) or "") or []
        dest = os.path.join(ASSET_DIR, stem)
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, sk), "wb") as fh:
            fh.write(texts[sk])
        want = {}
        for a in cands:
            with open(os.path.join(dest, a), "wb") as fh:
                fh.write(texts[a])
            for pg in atlas_pages(texts[a]):
                want[safe(pg).lower()] = safe(pg)
        got = 0
        for key, pg in want.items():
            stem_pg = pg.rsplit(".", 1)[0] if "." in pg else pg
            entry = tex_objs.get(pg) or tex_objs.get(stem_pg)
            if not entry:
                for tn, tv in tex_objs.items():
                    if tn.lower() == stem_pg.lower():
                        entry = tv
                        break
            if not entry:
                continue
            fnm = pg if pg.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) else pg + ".png"
            try:
                entry[1].read().image.save(os.path.join(dest, safe(fnm)))
                got += 1
            except Exception as exc:  # noqa: BLE001
                errors.append("%s/%s: %s" % (stem, fnm, str(exc)[:60]))
        if not got:
            errors.append("%s: tanpa png" % stem)
        extracted.append(stem)

    return {
        "ok": True,
        "total": len(names),
        "extracted": len(extracted),
        "new_models": extracted[:50],
        "asset_dir": ASSET_DIR,
        "errors": errors[:10],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apk", default=None, help="pakai APK split lokal (lewati adb pull)")
    ap.add_argument("--bundles", default=None, help="pakai direktori bundle lokal")
    a = ap.parse_args()

    global APK_CACHE, BUNDLE_DIR
    if a.apk:
        APK_CACHE = a.apk
    if a.bundles:
        BUNDLE_DIR = a.bundles

    if a.apply:
        print(json.dumps(apply_update(limit=a.limit), indent=1, ensure_ascii=False))
    elif a.check:
        print(json.dumps(check(), indent=1, ensure_ascii=False))
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
