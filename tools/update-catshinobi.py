#!/usr/bin/env python3
"""Perbarui model Spine Cat Shinobi (ねこ親方 / com.cookapps.catshinobi).

Cat Shinobi adalah Unity Addressables: skeleton-nya berada di dalam bundle
`assets/aa/Android/*.bundle`. Game ini mengemas ~546 skeleton di satu bundle
`defaultlocalgroup_assets_all_*.bundle`.

Sumber APK: APKPure, selalu versi TERBARU
    https://d.apkpure.com/b/XAPK/com.cookapps.catshinobi?version=latest
XAPK itu zip berisi beberapa APK; yang dibutuhkan hanya UnityDataAssetPack.apk
(548 MB dari total 710 MB), jadi updater membaca central directory lewat HTTP
Range lalu mengunduh HANYA entri tersebut. Kalau versi di server berubah,
updater otomatis mengambilnya; kalau sama, unduhan dilewati.

Alur:
    1. Baca daftar entri XAPK (Range 3 MB terakhir), cari UnityDataAssetPack.apk.
    2. Unduh entri itu saja ke WORK/UnityDataAssetPack.apk (md5 tidak tersedia
       di APKPure, jadi ukuran dipakai sebagai penanda versi).
    3. unzip `assets/aa/Android/*.bundle` ke direktori kerja.
    4. Scan bundle: kumpulkan TextAsset .skel/.atlas + metadata Texture2D.
    5. Bandingkan dengan folder yang sudah ada di assets/catshinobi -> baru.
    6. Ekstrak HANYA yang baru ke assets/catshinobi/<nama>/.

Catatan penting (warisan dari extract-catshinobi.py):
  * TextAsset di-decode lewat get_raw_data() + parser manual; obj.read().m_Script
    merusak .skel biner.
  * Jangan obj.read() Texture2D saat scan (decode pixel mahal). Baca m_Width/
    m_Height saja, pilih yang TERBESAR untuk nama duplikat, lalu decode hanya
    halaman yang benar-benar dirujuk atlas.

Pemakaian:
    /srv/venv-spine/bin/python tools/update-catshinobi.py --check
    /srv/venv-spine/bin/python tools/update-catshinobi.py --apply
    /srv/venv-spine/bin/python tools/update-catshinobi.py --apply --force    # paksa unduh ulang
    /srv/venv-spine/bin/python tools/update-catshinobi.py --check --apk /opt/catshinobi/UnityDataAssetPack.apk
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

import UnityPy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.environ.get("CS_OUT", os.path.join(ROOT, "assets", "catshinobi"))
WORK = os.environ.get("CS_WORK", "/srv/spine-assets/catshinobi-update")
APK_CACHE = os.path.join(WORK, "UnityDataAssetPack.apk")
BUNDLE_ROOT = os.path.join(WORK, "bundles")
BUNDLE_DIR = os.path.join(BUNDLE_ROOT, "assets", "aa", "Android")

# Sumber resmi APK: APKPure melayani XAPK (zip berisi beberapa APK). Yang kita
# butuhkan hanya UnityDataAssetPack.apk di dalamnya — 548 MB dari total 710 MB.
# URL ini selalu menunjuk versi terbaru ("version=latest"), jadi setiap kali
# updater dijalankan ia memeriksa versi terbaru lebih dulu.
XAPK_URL = os.environ.get(
    "CS_XAPK_URL",
    "https://d.apkpure.com/b/XAPK/com.cookapps.catshinobi?version=latest",
)
TARGET_ENTRY = "UnityDataAssetPack.apk"
UA = "Mozilla/5.0 (Linux; Android 13)"
PKG = "com.cookapps.catshinobi"
ADB = os.environ.get("ADB", "adb")
SERIAL = os.environ.get("ADB_SERIAL", "127.0.0.1:15555")

SPINE_EXTS = (".skel", ".atlas")


def safe(name):
    return os.path.basename(str(name)).replace("\\", "/").split("/")[-1].strip()


def _log(msg):
    """Baris progres ke stderr: server menampilkannya sebagai log live."""
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


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


def _http_open(url, headers=None, method="GET"):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, method=method)
    return urllib.request.urlopen(req, timeout=60)


def xapk_entries(url):
    """Baca daftar entri XAPK tanpa mengunduh seluruh berkas.

    XAPK adalah zip; central directory-nya ada di akhir berkas. Jadi cukup
    ambil ~3 MB terakhir lewat HTTP Range, lalu parse sendiri. Ini menghindari
    unduhan 710 MB hanya untuk mengetahui nama dan offset entri.
    """
    with _http_open(url) as r:
        final = r.geturl()
        total = int(r.headers.get("content-length") or 0)
    if total <= 0:
        raise RuntimeError("server tidak memberi content-length")

    tail_len = min(3 * 1024 * 1024, total)
    start = total - tail_len
    with _http_open(final, {"Range": f"bytes={start}-{total - 1}"}) as r:
        tail = r.read()

    idx = tail.rfind(b"PK\x05\x06")
    if idx < 0:
        raise RuntimeError("central directory XAPK tidak ditemukan")
    cd_size, cd_off = struct.unpack("<II", tail[idx + 12:idx + 20])
    if cd_off < start:
        raise RuntimeError("central directory di luar jendela Range")
    cd = tail[cd_off - start: cd_off - start + cd_size]

    out = []
    p = 0
    while p < len(cd) - 46 and cd[p:p + 4] == b"PK\x01\x02":
        comp = struct.unpack("<I", cd[p + 20:p + 24])[0]
        nlen = struct.unpack("<H", cd[p + 28:p + 30])[0]
        elen = struct.unpack("<H", cd[p + 30:p + 32])[0]
        clen = struct.unpack("<H", cd[p + 32:p + 34])[0]
        off = struct.unpack("<I", cd[p + 42:p + 46])[0]
        name = cd[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        out.append({"name": name, "comp": comp, "off": off, "dataoff": off + 30 + nlen + elen})
        p += 46 + nlen + elen + clen
    return final, total, out


def download_latest_apk(force=False):
    """Unduh UnityDataAssetPack.apk versi TERBARU dari APKPure.

    Hanya entri itu yang diambil (548 MB dari 710 MB XAPK), memakai HTTP Range
    di offset yang sudah dihitung. Kalau ukuran entri sama dengan berkas yang
    sudah ada dan tidak `force`, unduhan dilewati — jadi menjalankan updater
    berkali-kali tidak membuang bandwidth.

    Kembalikan (path, versi_string).
    """
    _log("memeriksa versi terbaru di APKPure…")
    final, total, entries = xapk_entries(XAPK_URL)
    target = next((e for e in entries if e["name"] == TARGET_ENTRY), None)
    if not target:
        raise RuntimeError(f"{TARGET_ENTRY} tidak ada di XAPK (entri: {[e['name'] for e in entries]})")

    # Versi ikut di nama berkas unduhan APKPure: "…_2.1.59_APKPure.xapk"
    m = re.search(r"_([0-9]+(?:\.[0-9]+)+)_APKPure", urllib.parse.unquote(final))
    version = m.group(1) if m else "unknown"

    os.makedirs(WORK, exist_ok=True)
    if (not force and os.path.exists(APK_CACHE)
            and os.path.getsize(APK_CACHE) == target["comp"]):
        _log(f"APK cache sudah versi terbaru ({version}, {target['comp']/2**20:.0f} MB) — lewati unduhan")
        return APK_CACHE, version

    _log(f"mengunduh {TARGET_ENTRY} v{version} ({target['comp']/2**20:.0f} MB)…")
    tmp = APK_CACHE + ".part"
    got = 0
    end = target["dataoff"] + target["comp"] - 1
    last = 0.0
    with _http_open(final, {"Range": f"bytes={target['dataoff']}-{end}"}) as r, open(tmp, "wb") as fh:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if time.time() - last > 10:
                last = time.time()
                _log(f"  {got/2**20:.0f} / {target['comp']/2**20:.0f} MB")
    if got != target["comp"]:
        os.unlink(tmp)
        raise RuntimeError(f"unduhan tidak lengkap: {got} != {target['comp']}")
    os.replace(tmp, APK_CACHE)
    _log("unduhan selesai")
    return APK_CACHE, version


def pull_bundles(force=False, apk_path=None, apk_version=None):
    """Pastikan bundle ada di BUNDLE_DIR.

    Sumber utama: APK terbaru dari APKPure. `apk_path` (argumen --apk) masih
    didukung untuk memakai berkas lokal, mis. saat offline.

    Ekstraksi selalu diulang dari APK yang dipakai, supaya tidak ada bundle
    basi tertinggal saat game diperbarui.
    """
    global APK_CACHE
    if apk_path:
        APK_CACHE = apk_path
        _log(f"memakai APK lokal: {apk_path}")
    elif not (os.path.isdir(BUNDLE_DIR) and any(f.endswith(".bundle") for f in os.listdir(BUNDLE_DIR))) or force:
        APK_CACHE, _ver = download_latest_apk(force=force)
    else:
        # Bundle sudah ada; tetap periksa versi terbaru supaya pembaruan tidak
        # terlewat. Kalau ukurannya sama, unduhan dilewati oleh download_latest_apk.
        APK_CACHE, _ver = download_latest_apk(force=False)

    _log("ekstrak bundle dari APK…")
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
        _log(f"scan {fname}…")
        try:
            env = UnityPy.load(path)
        except Exception:
            _log(f"  gagal memuat {fname}")
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


def check(apk_path=None, force=False):
    try:
        pull_bundles(apk_path=apk_path, force=force)
        texts, tex_objs, skels = discover()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "new": 0, "installed": len(installed())}
    have = installed()
    names = {s.rsplit(".", 1)[0] for s in skels}
    baru = sorted(names - have)
    _log(f"ditemukan {len(names)} skeleton, {len(have)} sudah ada, {len(baru)} baru")
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


def apply_update(limit=0, apk_path=None, force=False):
    try:
        pull_bundles(apk_path=apk_path, force=force)
        texts, tex_objs, skels = discover()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "extracted": 0}

    have = installed()
    names = {s.rsplit(".", 1)[0] for s in skels}
    baru = sorted(names - have)
    if limit:
        baru = baru[:limit]
    _log(f"mengekstrak {len(baru)} model baru")

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
        _log(f"  OK {stem} ({got} halaman)")

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
    ap.add_argument("--apk", default=None,
                    help="pakai APK lokal; default: unduh versi terbaru dari APKPure")
    ap.add_argument("--force", action="store_true",
                    help="paksa unduh ulang walau ukuran cache sama")
    ap.add_argument("--bundles", default=None, help="pakai direktori bundle lokal")
    a = ap.parse_args()

    global BUNDLE_DIR
    if a.bundles:
        BUNDLE_DIR = a.bundles

    if a.apply:
        print(json.dumps(apply_update(limit=a.limit, apk_path=a.apk, force=a.force),
                         indent=1, ensure_ascii=False))
    elif a.check:
        print(json.dumps(check(apk_path=a.apk, force=a.force), indent=1, ensure_ascii=False))
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
