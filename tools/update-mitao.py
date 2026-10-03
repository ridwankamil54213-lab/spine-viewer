#!/usr/bin/env python3
"""Perbarui aset 蜜桃乌托邦 (Peach Utopia) ke pohon aset spine-viewer.

Backend-nya sama seperti downloader di /opt/mitao: ambil APK -> manifest
YooAsset -> unduh bundle `rawdata_spine_*` yang belum ada -> dekripsi IDOLAB2
-> ekstrak .skel/.atlas/.png -> pasang ke assets/mitao-utopia.

Kenapa APK, bukan cuma API: manifest (daftar bundle + versi paket) hanya ada
di dalam APK. Ukurannya ~197 MB, dan kalau kita mengunduhnya di setiap
`--check` itu konyol — jadi:

  * --check  : cukup baca PackageManifest yang SUDAH kita simpan (yang terakhir
               dipakai --apply). Tidak menyentuh jaringan sama sekali, jadi
               tombol "Perbarui aset" di UI selalu murah. Versi terbaru
               dilaporkan dari /resource/url (release_id, mis. ...-2.48.3).
  * --apply  : unduh APK, bandingkan manifest baru dengan yang tersimpan,
               unduh + ekstrak HANYA skeleton yang baru, lalu pasang model
               baru (tanpa menimpa yang sudah ada).

Dipanggil oleh server lewat GET /api/update/mitao (tombol di UI). Bisa juga
dijalankan langsung:

    /srv/venv-spine/bin/python tools/update-mitao.py --check
    /srv/venv-spine/bin/python tools/update-mitao.py --apply
    /srv/venv-spine/bin/python tools/update-mitao.py --apply --apk /path/game.apk
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
import zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
# Pipeline 蜜桃乌托邦 (API + dekripsi + parser manifest + ekstraktor) tinggal di
# tools/mitao/ supaya modulnya bisa dipakai ulang / diuji sendiri.
MODULE_DIR = os.path.join(HERE, "mitao")
sys.path.insert(0, MODULE_DIR)
import mitao_api as api  # noqa: E402
import mitao_manifest as mf  # noqa: E402

PYTHON = os.environ.get("PY", "/srv/venv-spine/bin/python")

# State (APK + manifest + bundle) sengaja TIDAK di dalam repo, supaya clone
# bersih tetap kecil. Bisa ditimpa lewat env.
STATE_DIR = os.environ.get("MITAO_STATE", "/srv/spine-assets/mitao")
APK_PATH = os.path.join(STATE_DIR, "game.apk")
MANIFEST_PATH = os.path.join(STATE_DIR, "manifest.json")
BUNDLE_DIR = os.path.join(STATE_DIR, "bundles")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

# Pohon aset yang dibaca viewer. Keluarannya <ASSET_DIR>/<variant>_<id>/.
ASSET_DIR = os.environ.get("MITAO_OUT", "/opt/spine-viewer/assets/mitao-utopia")
EXTRACTOR = os.path.join(MODULE_DIR, "extract-spine.py")

# Hanya skeleton 2D yang bisa dilihat viewer. `prefabs_spine_mesh_*` (3D) dan
# `prefabs_spine_ui_*` (prefab UI) TIDAK menghasilkan model — lihat
# references/mitao-extraction.md.
SKELETON = "rawdata_spine_"

APK_TIMEOUT = 900


def log(*a):
    print(*a, flush=True)


def _ver_eq(a: str, b: str) -> bool:
    """Samakan versi: "2.48.3" == "2.48.3". Kalau dua-duanya titik-angka,
    bandingkan sebagai tuple supaya "2.9" != "2.10"."
    """
    if a == b:
        return True
    try:
        return tuple(int(x) for x in str(a).split(".")) == tuple(int(x) for x in str(b).split("."))
    except ValueError:
        return False


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


def spine_bundles(manifest: dict) -> dict:
    """{bundle name -> info} untuk skeleton 2D saja."""
    return {
        b["BundleName"]: b
        for b in manifest["Bundles"]
        if SKELETON in b["BundleName"]
    }


def catalog_from_apk(path: str) -> dict:
    """Baca PackageManifest_*.bytes dari APK -> dict manifest."""
    with zipfile.ZipFile(path) as z:
        names = [
            n for n in z.namelist()
            if re.search(r"assets/yoo/DefaultPackage/PackageManifest_.*\.bytes$", n)
        ]
        if not names:
            raise RuntimeError("PackageManifest tidak ada di dalam APK")
        raw = z.read(names[0])
    return mf.parse(raw)


def download_apk(url: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=APK_TIMEOUT) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1024 * 256)
    os.replace(tmp, dest)


def check() -> dict:
    """Murah: baca katalog tersimpan + tanya versi terbaru. Tanpa unduh APK."""
    state = load_state()
    local_manifest = MANIFEST_PATH if os.path.exists(MANIFEST_PATH) else None

    # Versi live dari API (kecil): release_id memuat versinya.
    version = None
    version_error = None
    try:
        release_id, _base, apk_url = api.get_release()
        version = release_id.rsplit("-", 1)[-1] if release_id else None
        state["apk_url"] = apk_url
    except Exception as exc:
        version_error = str(exc)

    if not local_manifest:
        return {
            "version": version,
            "installed": None,
            "previous": None,
            "changed": True,
            "total": 0,
            "new": 0,
            "have": 0,
            "samples": [],
            "note": "Belum ada katalog tersimpan — putar --apply untuk seed.",
            "version_error": version_error,
        }

    manifest = json.load(open(local_manifest))
    stored = spine_bundles(manifest)

    have = 0
    if os.path.isdir(ASSET_DIR):
        have = len([d for d in os.listdir(ASSET_DIR) if os.path.isdir(os.path.join(ASSET_DIR, d))])

    installed = state.get("live_version") or manifest.get("PackageVersion")
    changed = bool(version and installed and version != installed)

    return {
        "version": version,
        "installed": installed,
        "previous": installed,
        "catalog": manifest.get("PackageVersion"),
        "changed": changed,
        # "new" = skeleton di katalog lokal yang belum pernah kita ekstrak.
        # Ini yang dibaca UI sebagai "ada yang baru".
        "new": 0,
        "total": len(stored),
        "have": have,
        "samples": [],
        "note": "Katalog tersimpan; putar --apply untuk mengambil versi terbaru."
        if not changed
        else f"Versi baru {version} — putar --apply.",
        "version_error": version_error,
    }


def apply_update(apk_override: str = "", workers: int = 6, keep_apk: bool = True) -> dict:
    """Unduh APK, bandingkan manifest, ambil + ekstrak skeleton baru, pasang."""
    os.makedirs(STATE_DIR, exist_ok=True)
    version = None
    apk_url = None
    release_id = None
    downloaded_apk = False
    try:
        release_id, _base, apk_url = api.get_release()
        version = release_id.rsplit("-", 1)[-1] if release_id else None
    except Exception:
        pass

    # 1. APK. PENTING: APK yang tersimpan bisa dari versi lama, jadi jangan
    #    asal pakai. Ground truth-nya adalah versi di dalam APK itu sendiri
    #    (PackageVersion manifest), bukan catatan state — catatan bisa hilang.
    #    Kalau APK tak ada / PackageVersion-nya beda dari versi live, unduh
    #    yang baru. Tanpa ini pembaru tak akan pernah melihat versi baru
    #    setelah APK pertama kali di-cache.
    if apk_override:
        apk = apk_override
    else:
        cached = APK_PATH if os.path.exists(APK_PATH) else None
        cached_pkg = None
        if cached:
            try:
                cached_pkg = catalog_from_apk(cached).get("PackageVersion")
            except Exception:
                cached_pkg = None  # APK rusak/tidak terbaca -> unduh ulang
        stale = (
            not cached
            or not (version and cached_pkg and _ver_eq(version, cached_pkg))
        )
        if stale and apk_url:
            log(f"mengunduh APK {version or ''} dari {apk_url[:80]}…")
            download_apk(apk_url, APK_PATH)
            apk = APK_PATH
            downloaded_apk = True
        else:
            apk = cached
            if cached_pkg:
                log(f"APK tersimpan dipakai (katalog {cached_pkg})")
            else:
                log("APK tersimpan tidak terbaca — memakai apa adanya")

    # 2. Manifest baru vs lama.
    assert apk, "APK tidak tersedia"
    manifest = catalog_from_apk(apk)
    new_pkg_version = manifest.get("PackageVersion")
    old_manifest = json.load(open(MANIFEST_PATH)) if os.path.exists(MANIFEST_PATH) else None
    old_bundles = spine_bundles(old_manifest) if old_manifest else {}

    cur = spine_bundles(manifest)
    old_names = set(old_bundles)
    new_names = set(cur)
    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)
    # Bundle yang isinya berubah (hash beda) juga perlu diambil ulang.
    changed = sorted(
        n for n in (new_names & old_names)
        if cur[n].get("FileHash") != old_bundles[n].get("FileHash")
    )

    # Berkas yang sudah ada & masih cocok tidak diunduh lagi. PENTING: jangan
    # bandingkan dengan info["FileSize"] — itu ukuran TERENKRIPSI di CDN,
    # sedangkan yang kita simpan sudah didekripsi (selalu lebih kecil), jadi
    # perbandingan itu selalu gagal dan mengunduh ulang semuanya. Cukup cek
    # bahwa berkasnya ada dan berheader UnityFS.
    changed_set = set(changed)

    def have_ok(path):
        try:
            if os.path.getsize(path) < 8:
                return False
            with open(path, "rb") as f:
                return f.read(8).startswith(b"UnityFS")
        except OSError:
            return False

    todo = []
    for n in sorted(new_names):
        dest = os.path.join(BUNDLE_DIR, n)
        if n not in changed_set and have_ok(dest):
            continue
        todo.append(n)

    log(f"katalog : {new_pkg_version} (lama {old_manifest.get('PackageVersion') if old_manifest else '-'})")
    log(f"skeleton: {len(cur)} total · +{len(added)} baru · {len(changed)} berubah · {len(removed)} hilang")
    log(f"unduh   : {len(todo)} bundle (yang hilang/berubah + baru)")

    # 3. Unduh bundle baru (resolve URL + dekripsi persis seperti download.py).
    done = failed = 0
    errors = []
    if todo:
        if not release_id:
            raise RuntimeError("tidak bisa mengambil release_id dari /resource/url")
        names = [f"{cur[n]['FileHash']}.bundle" for n in todo]
        hash2name = {f"{cur[n]['FileHash']}.bundle": n for n in todo}
        resolved = api.batch_urls(release_id, names)
        master_key = bytes.fromhex(api.MASTER_KEY_HEX)
        os.makedirs(BUNDLE_DIR, exist_ok=True)

        def get(cdn_name):
            bundle = hash2name[cdn_name]
            dest = os.path.join(BUNDLE_DIR, bundle)
            url = resolved.get(cdn_name)
            if not url:
                return f"{bundle}: tidak ada URL bertanda tangan"
            try:
                with urllib.request.urlopen(url, timeout=120) as r:
                    blob = r.read()
                plain = api.decrypt_bundle(blob, bundle, master_key) if api.is_container(blob) else blob
                with open(dest, "wb") as f:
                    f.write(plain)
                return None
            except Exception as exc:
                return f"{bundle}: {exc}"

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for err in ex.map(get, names):
                if err:
                    failed += 1
                    if len(errors) < 8:
                        errors.append(err)
                else:
                    done += 1

    # Simpan katalog baru SEBELUM ekstraksi, supaya --check berikutnya murah.
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    state = load_state()
    state["live_version"] = version
    state["catalog_version"] = new_pkg_version
    # Versi APK yang kita simpan — dipakai untuk memutuskan perlu unduh ulang
    # APK atau tidak di jalankan berikutnya.
    state["apk_version"] = new_pkg_version
    state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["skeleton_bundles"] = len(cur)
    save_state(state)

    if not keep_apk and downloaded_apk:
        try:
            os.remove(APK_PATH)
        except OSError:
            pass

    # 4. Ekstrak ulang HANYA kalau ada yang baru diunduh (ekstraksi penuh
    #    butuh beberapa menit). Definisikan tmp_out di luar `if` supaya sisa
    #    direktori sementara selalu dibersihkan.
    extracted = 0
    new_models = []
    already_had = 0
    extract_error = None
    extract_log = ""
    tmp_out = os.path.join(STATE_DIR, "extract_tmp")
    if done:
        shutil.rmtree(tmp_out, ignore_errors=True)
        os.makedirs(tmp_out, exist_ok=True)
        try:
            proc = subprocess.run(
                [PYTHON, EXTRACTOR, "--bundles", BUNDLE_DIR, "--out", tmp_out, "--game", "."],
                cwd=HERE, capture_output=True, text=True, timeout=7200, check=False,
            )
            extract_log = (proc.stdout or "")[-500:] + (proc.stderr or "")[-500:]
        except Exception as exc:
            extract_error = str(exc)

        # 5. Pasang model baru tanpa menimpa yang lama.
        if os.path.isdir(tmp_out):
            os.makedirs(ASSET_DIR, exist_ok=True)
            for name in sorted(os.listdir(tmp_out)):
                src = os.path.join(tmp_out, name)
                if not os.path.isdir(src):
                    continue
                dst = os.path.join(ASSET_DIR, name)
                if os.path.exists(dst):
                    already_had += 1
                    continue
                shutil.move(src, dst)
                extracted += 1
                if len(new_models) < 12:
                    new_models.append(name)
    shutil.rmtree(tmp_out, ignore_errors=True)

    return {
        "version": version,
        "catalog": new_pkg_version,
        "added": len(added),
        "changed": len(changed),
        "removed": len(removed),
        "downloaded": done,
        "failed": failed,
        "extracted": extracted,
        "new_models": new_models,
        "already_had": already_had,
        "asset_dir": ASSET_DIR,
        "extract_error": extract_error,
        "extract_log": extract_log,
        "errors": errors,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="hanya laporkan status (murah, tanpa jaringan APK)")
    ap.add_argument("--apply", action="store_true", help="unduh + ekstrak skeleton baru")
    ap.add_argument("--apk", default="", help="pakai APK lokal ini, jangan unduh")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--drop-apk", action="store_true", help="hapus APK setelah selesai (hemat ~197 MB)")
    args = ap.parse_args()

    if args.check:
        print(json.dumps(check(), indent=1, ensure_ascii=False))
    elif args.apply:
        print(json.dumps(apply_update(args.apk, args.workers, keep_apk=not args.drop_apk),
                         indent=1, ensure_ascii=False))
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
