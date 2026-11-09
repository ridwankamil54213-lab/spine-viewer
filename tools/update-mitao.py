#!/usr/bin/env python3
"""Perbarui aset 蜜桃乌托邦 (Peach Utopia) lewat pipeline iOS.

Kenapa iOS (2026-11)
====================
Rilis Android 2.50.1 memakai skema v3: bundle `IDOLNAB3` (XChaCha20-Poly1305,
solver ada di `tools/mitao/idol_rs_v3.py`) tetapi kunci master MANIFEST-nya
disembunyikan di Obfuz VM, jadi manifest Android belum bisa dibuka. Rilis iOS
1.6.2 memakai v2 (`IDOLRS1` + `IDOLAB2`) dan kuncinya diketahui. Isi manifest
keduanya identik (plain_len cuma beda 1 byte = panjang string versi), jadi
pipeline iOS dipakai sebagai sumber aset. Berkas bundle-nya sendiri spesifik
platform: FileHash iOS ditolak endpoint Android, jadi seluruh alur (endpoint,
kunci, dekripsi) harus iOS, jangan dicampur. Lihat `tools/mitao/README.md`.

Alur (tanpa APK 198 MB)
=======================
  * --check : POST /resource/url -> release_id, lalu ambil berkas
             `PackageManifest_DefaultPackage.version` (teks kecil) untuk versi
             live. Bandingkan dengan state. Tidak mengunduh manifest penuh.
  * --apply : ambil `PackageManifest_DefaultPackage_<versi>.bytes` dari CDN,
             dekrip `IDOLRS1`/`IDOLAB2` via `tools/mitao/idol_v2.py`, parse
             YooAsset, lalu unduh + dekrip HANYA bundle skeleton yang baru,
             ekstrak .skel/.atlas/.png, pasang ke assets/mitao-utopia tanpa
             menimpa yang sudah ada.
  * --manifest-only : jalankan cuma langkah manifest (aman untuk verifikasi,
             tidak mengunduh bundle).

Kontrak server: stdout HANYA blok JSON hasil, progres ke stderr.
Interpreter: /srv/venv-spine/bin/python (tidak punya Crypto/cryptography;
`idol_v2.py` memakai fallback CLI openssl).
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
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE_DIR = os.path.join(HERE, "mitao")
sys.path.insert(0, MODULE_DIR)
import mitao_manifest as mf  # noqa: E402
import idol_v2 as v2  # noqa: E402

PYTHON = os.environ.get("PY", "/srv/venv-spine/bin/python")

# State sengaja di luar repo supaya clone tetap kecil.
STATE_DIR = os.environ.get("MITAO_STATE", "/srv/spine-assets/mitao")
MANIFEST_PATH = os.path.join(STATE_DIR, "manifest.json")
BUNDLE_DIR = os.path.join(STATE_DIR, "bundles")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

# Pohon aset yang dipindai viewer (relatif repo, JANGAN /opt/spine-viewer).
ASSET_DIR = os.environ.get("MITAO_OUT", os.path.join(ROOT, "assets", "mitao-utopia"))
EXTRACTOR = os.path.join(MODULE_DIR, "extract-spine.py")
THUMBS_TOOL = os.path.join(MODULE_DIR, "refresh-thumbs.py")
NAMES_TOOL = os.path.join(MODULE_DIR, "refresh-names.py")

API_BASE = "https://pxapi.jhdwxp.com"
PLATFORM = "18game"
RESOURCE_TYPE = v2.RESOURCE_TYPE           # "ios_cn_release"
SCOPE = v2.SCOPE                          # "Release_Game18_iOS/ios_cn_release"
MASTER_KEY = v2.MASTER_KEY
UNITY_UA = "UnityPlayer/2022.3.51f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"
CDN_UA = "%E8%9C%9C%E6%A1%83%E4%B9%8C%E6%89%98%E9%82%A6/0 CFNetwork/1408.0.4 Darwin/22.5.0"
CDN_HEADERS = {
    "User-Agent": CDN_UA,
    "X-Unity-Version": "2022.3.51f1",
    "Accept": "*/*",
    "Accept-Language": "zh-TW,zh-Hant;q=0.9",
}

# Kandidat skeleton 2D: rawdata_spine_* DAN prefabs_spine_* (skill/avg/cutin
# ikut hilang kalau cuma rawdata). Prefab bukan skeleton tersaring saat
# ekstraksi (tidak ada pasangan .skel + .atlas).
SKELETON_MARKERS = ("rawdata_spine_", "prefabs_spine_")
BATCH_SIZE = 20


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _ver_eq(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        return tuple(int(x) for x in str(a).split(".")) == \
            tuple(int(x) for x in str(b).split("."))
    except (ValueError, AttributeError):
        return False


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:  # noqa: BLE001
            pass
    return {}


def save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)


def model_count() -> int:
    if not os.path.isdir(ASSET_DIR):
        return 0
    return len([d for d in os.listdir(ASSET_DIR)
                if os.path.isdir(os.path.join(ASSET_DIR, d))])


def spine_bundles(manifest: dict) -> dict:
    return {
        b["BundleName"]: b
        for b in manifest["Bundles"]
        if any(p in b["BundleName"] for p in SKELETON_MARKERS)
    }


def post_json(path: str, body: dict, timeout: int = 40,
              retries: int = 3) -> dict:
    data = json.dumps(body).encode()
    hdrs = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UNITY_UA,
        "X-Unity-Version": "2022.3.51f1",
    }
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(API_BASE + path, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"request gagal {path}: {last}")


def cdn_get(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers=CDN_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def release_info() -> tuple[str, str]:
    """(release_id, base_url) untuk rilis iOS live."""
    r = post_json("/resource/url", {
        "access_protocol": 1, "platform": PLATFORM,
        "resource_type": RESOURCE_TYPE,
    })
    if r.get("code") != 0:
        raise RuntimeError(f"/resource/url -> {r}")
    d = r["data"]
    return d["release_id"], (d.get("base_urls") or [""])[-1]


def resolve_files(release_id: str, files: list) -> dict:
    """{nama berkas -> URL bertanda tangan}, dibatasi 20 nama per request."""
    out = {}
    for i in range(0, len(files), BATCH_SIZE):
        part = files[i:i + BATCH_SIZE]
        r = post_json("/resource/access/batch", {
            "platform": PLATFORM, "resource_type": RESOURCE_TYPE,
            "release_id": release_id, "files": part,
        })
        if r.get("code") != 0:
            log(f"  ! batch {i // BATCH_SIZE + 1} ditolak: {r.get('msg')}")
            continue
        fs = (r.get("data") or {}).get("files") or []
        items = fs.items() if isinstance(fs, dict) else [
            (x.get("file") or x.get("name"),
             x.get("urls") or ([x["url"]] if x.get("url") else []))
            for x in fs if isinstance(x, dict)]
        for name, urls in items:
            if not name:
                continue
            if isinstance(urls, str):
                out[name] = urls
            elif isinstance(urls, (list, tuple)) and urls:
                out[name] = urls[-1]
    return out


def live_manifest_version(release_id: str) -> str:
    urls = resolve_files(release_id, ["PackageManifest_DefaultPackage.version"])
    u = urls.get("PackageManifest_DefaultPackage.version")
    if not u:
        raise RuntimeError("URL PackageManifest_DefaultPackage.version tidak ada")
    return cdn_get(u, timeout=30).decode("utf-8", "replace").strip()


def fetch_manifest(release_id: str) -> tuple[str, dict]:
    """Ambil + dekrip + parse manifest YooAsset iOS. (versi, dict)."""
    version = live_manifest_version(release_id)
    fname = f"PackageManifest_DefaultPackage_{version}.bytes"
    urls = resolve_files(release_id, [fname])
    u = urls.get(fname)
    if not u:
        raise RuntimeError(f"URL {fname} tidak ada")
    blob = cdn_get(u, timeout=90)
    plain = v2.decrypt_manifest(blob)
    manifest = mf.parse(plain)
    # `sign` berupa bytes -> tidak bisa di-JSON.
    if isinstance(manifest.get("sign"), bytes):
        manifest["sign"] = manifest["sign"].hex()
    return version, manifest


def check() -> dict:
    """Murah: tanya release_id + versi manifest (teks kecil), bandingkan state."""
    state = load_state()
    have = model_count()
    version = None
    release_id = None
    version_error = None
    try:
        release_id, _base = release_info()
        version = live_manifest_version(release_id)
    except Exception as exc:  # noqa: BLE001
        version_error = str(exc)

    stored = {}
    if os.path.exists(MANIFEST_PATH):
        try:
            stored = json.load(open(MANIFEST_PATH))
        except Exception as exc:  # noqa: BLE001
            version_error = f"{version_error or ''} | manifest rusak: {exc}".strip(" |")

    installed = state.get("manifest_version") or stored.get("PackageVersion")
    if not state.get("baseline_models"):
        state["baseline_models"] = have
        state["bootstrapped_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)
    previous = installed or f"baseline:{state['baseline_models']}-model"

    # Hot-update bisa mengganti release_id tanpa menaikkan nomor versi.
    changed = bool(version and (
        not installed or not _ver_eq(version, installed)
        or release_id != state.get("release_id")))
    total = len(spine_bundles(stored)) if stored else 0

    if version_error and version is None:
        note = f"Gagal memeriksa versi iOS: {version_error}"
    elif not stored:
        note = "Belum ada katalog tersimpan — putar --apply untuk seed."
    elif not changed:
        note = f"Sudah versi terbaru iOS {version} — {total} bundle skeleton."
    elif version and installed and not _ver_eq(version, installed):
        note = f"Versi iOS baru {version} — putar --apply."
    else:
        note = "Katalog iOS perlu disinkron (bundle belum lengkap) — putar --apply."

    return {
        "ok": True,
        "mode": "check",
        "version": version,
        "installed": installed,
        "previous": previous,
        "catalog": stored.get("PackageVersion"),
        "resource_type": RESOURCE_TYPE,
        "release_id": release_id,
        "changed": changed,
        "new": 0,
        "total": total,
        "have": have,
        "asset_dir": ASSET_DIR,
        "samples": [],
        "note": note,
        "version_error": version_error,
    }


def apply_update(workers: int = 6, manifest_only: bool = False,
                 replace: bool = False) -> dict:
    """Ambil manifest iOS, unduh + dekrip bundle skeleton baru, ekstrak, pasang."""
    os.makedirs(STATE_DIR, exist_ok=True)
    t0 = time.time()
    release_id, base = release_info()
    version, manifest = fetch_manifest(release_id)
    new_pkg_version = manifest.get("PackageVersion")
    log(f"manifest iOS : {new_pkg_version} (rilis {version}), "
        f"{len(manifest['Bundles'])} bundle")

    state = load_state()
    platform_changed = state.get("platform") != "ios"
    old_manifest = None
    if os.path.exists(MANIFEST_PATH) and not platform_changed:
        try:
            old_manifest = json.load(open(MANIFEST_PATH))
        except Exception:  # noqa: BLE001
            old_manifest = None
    old_bundles = spine_bundles(old_manifest) if old_manifest else {}
    cur = spine_bundles(manifest)
    old_names, new_names = set(old_bundles), set(cur)
    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)
    changed = sorted(
        n for n in (new_names & old_names)
        if cur[n].get("FileHash") != old_bundles[n].get("FileHash"))
    changed_set = set(changed)

    # Tulis katalog baru SETELAH diff dihitung, supaya --check berikutnya murah.
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    def have_ok(path):
        try:
            if os.path.getsize(path) < 8:
                return False
            with open(path, "rb") as f:
                return f.read(8).startswith(b"UnityFS")
        except OSError:
            return False

    todo = [n for n in sorted(new_names)
            if n in changed_set or not have_ok(os.path.join(BUNDLE_DIR, n))]
    log(f"skeleton: {len(cur)} total · +{len(added)} baru · "
        f"{len(changed)} berubah · {len(removed)} hilang")
    log(f"unduh   : {len(todo)} bundle")

    if manifest_only:
        return {
            "ok": True,
            "mode": "manifest-only",
            "version": version,
            "catalog": new_pkg_version,
            "resource_type": RESOURCE_TYPE,
            "release_id": release_id,
            "bundles": len(manifest["Bundles"]),
            "skeleton": len(cur),
            "todo": len(todo),
            "added": len(added),
            "changed": len(changed),
            "removed": len(removed),
            "asset_dir": ASSET_DIR,
            "seconds": round(time.time() - t0, 1),
            "note": "Hanya manifest; tidak ada bundle yang diunduh.",
        }

    done = failed = 0
    errors = []
    os.makedirs(BUNDLE_DIR, exist_ok=True)
    if todo:
        cdn_names = [f"{cur[n]['FileHash']}.bundle" for n in todo]
        hash2name = {f"{cur[n]['FileHash']}.bundle": n for n in todo}
        resolved = resolve_files(release_id, cdn_names)

        def get(cdn_name):
            bundle = hash2name[cdn_name]
            dest = os.path.join(BUNDLE_DIR, bundle)
            url = resolved.get(cdn_name)
            if not url:
                return f"{bundle}: tidak ada URL bertanda tangan"
            try:
                blob = cdn_get(url, timeout=120)
                plain = v2.decrypt_bundle(
                    blob, bundle, master_key=MASTER_KEY,
                    derive_bundle=True, scope=SCOPE)
                with open(dest, "wb") as f:
                    f.write(plain)
                return None
            except Exception as exc:  # noqa: BLE001
                return f"{bundle}: {exc}"

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for err in ex.map(get, cdn_names):
                if err:
                    failed += 1
                    if len(errors) < 8:
                        errors.append(err)
                else:
                    done += 1

    state = load_state()
    state["platform"] = "ios"
    state["resource_type"] = RESOURCE_TYPE
    state["live_version"] = version
    state["manifest_version"] = version
    state["catalog_version"] = new_pkg_version
    state["release_id"] = release_id
    state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["skeleton_bundles"] = len(cur)
    save_state(state)

    # Ekstraksi penuh (bisa menit). Dengan --replace hasilnya di-STAGING dulu,
    # divalidasi, baru ditukar dengan pohon aset lama — kalau UnityPy gagal
    # membaca bundle iOS, pustaka lama tetap utuh.
    extracted = 0
    new_models = []
    already_had = 0
    extract_error = None
    extract_log = ""
    replace_result = None
    staging_dir = os.path.join(STATE_DIR, "extract_tmp")
    moved = False
    do_extract = bool(done) or replace
    if do_extract:
        shutil.rmtree(staging_dir, ignore_errors=True)
        os.makedirs(staging_dir, exist_ok=True)
        try:
            proc = subprocess.run(
                [PYTHON, EXTRACTOR, "--bundles", BUNDLE_DIR,
                 "--out", staging_dir, "--game", "."],
                cwd=HERE, capture_output=True, text=True,
                timeout=7200, check=False)
            extract_log = (proc.stdout or "")[-500:] + (proc.stderr or "")[-500:]
            if proc.returncode != 0:
                extract_error = f"extract-spine.py exit {proc.returncode}"
        except Exception as exc:  # noqa: BLE001
            extract_error = str(exc)

        folders = [d for d in sorted(os.listdir(staging_dir))
                   if os.path.isdir(os.path.join(staging_dir, d))] \
            if os.path.isdir(staging_dir) else []

        def valid(d):
            fs = os.listdir(os.path.join(staging_dir, d))
            return (any(f.endswith((".skel", ".json")) for f in fs)
                    and any(f.endswith(".atlas") for f in fs)
                    and any(f.endswith(".png") for f in fs))

        good = [d for d in folders if valid(d)]

        if replace:
            if extract_error or len(good) < 50:
                replace_result = {
                    "replaced": False,
                    "reason": f"staging cuma {len(good)} model valid dari "
                              f"{len(folders)} — swap dibatalkan, aset lama utuh",
                    "staged": len(folders), "valid": len(good),
                }
            else:
                backup = os.path.join(
                    STATE_DIR,
                    "android-backup-" + time.strftime("%Y%m%d-%H%M%S"))
                old_count = model_count()
                if os.path.isdir(ASSET_DIR):
                    shutil.move(ASSET_DIR, backup)
                shutil.move(staging_dir, ASSET_DIR)
                moved = True
                replace_result = {
                    "replaced": True, "backup": backup,
                    "old_models": old_count, "staged": len(folders),
                    "valid": len(good), "new_models": len(good),
                }
                extracted = len(good)
                new_models = good[:12]
        else:
            os.makedirs(ASSET_DIR, exist_ok=True)
            for name in folders:
                src = os.path.join(staging_dir, name)
                dst = os.path.join(ASSET_DIR, name)
                if os.path.exists(dst):
                    already_had += 1
                    continue
                shutil.move(src, dst)
                extracted += 1
                if len(new_models) < 12:
                    new_models.append(name)
    if not moved:
        shutil.rmtree(staging_dir, ignore_errors=True)

    # Model `equip_*` sengaja tidak dipakai di pustaka (keputusan user
    # 2026-11-08). Ekstraksi bundle iOS tetap bisa menghasilkannya, jadi
    # bersihkan di sini supaya --apply / --replace tidak mengembalikannya.
    equip_removed = 0
    if os.path.isdir(ASSET_DIR):
        for name in os.listdir(ASSET_DIR):
            p = os.path.join(ASSET_DIR, name)
            if name.startswith("equip_") and os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
                equip_removed += 1

    # Thumbnail = langkah kosmetik: gagalnya TIDAK boleh menggagalkan apply.
    # Sumbernya folder hasil extract-all.py; kalau belum ada, cukup peringatan.
    thumb_result = None
    try:
        proc = subprocess.run(
            [PYTHON, THUMBS_TOOL], cwd=HERE, capture_output=True,
            text=True, timeout=300, check=False)
        thumb_result = (json.loads(proc.stdout) if proc.returncode == 0
                        else {"ok": False,
                              "error": (proc.stderr or proc.stdout)[-300:]})
    except Exception as exc:  # noqa: BLE001
        thumb_result = {"ok": False, "error": str(exc)}
    if not thumb_result.get("ok"):
        log(f"PERINGATAN: thumbnail tidak disegarkan: {thumb_result.get('error')}")

    # Nama karakter juga langkah kosmetik: data/mitao-names.json dari tabel
    # lokalisasi hasil extract-all.py. Gagal = peringatan, apply tetap sukses.
    names_result = None
    try:
        proc = subprocess.run(
            [PYTHON, NAMES_TOOL], cwd=HERE, capture_output=True,
            text=True, timeout=120, check=False)
        names_result = (json.loads(proc.stdout) if proc.returncode == 0
                        else {"ok": False,
                              "error": (proc.stderr or proc.stdout)[-300:]})
    except Exception as exc:  # noqa: BLE001
        names_result = {"ok": False, "error": str(exc)}
    if not names_result.get("ok"):
        log(f"PERINGATAN: nama karakter tidak disegarkan: {names_result.get('error')}")

    return {
        "ok": failed == 0 and not extract_error and
              (not replace or bool(replace_result and replace_result["replaced"])),
        "mode": "apply",
        "version": version,
        "catalog": new_pkg_version,
        "resource_type": RESOURCE_TYPE,
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
        "replace": replace_result,
        "equip_removed": equip_removed,
        "thumbnail": thumb_result,
        "names": names_result,
        "seconds": round(time.time() - t0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="laporkan status (murah, tanpa unduh manifest penuh)")
    ap.add_argument("--apply", action="store_true",
                    help="unduh + ekstrak skeleton baru")
    ap.add_argument("--manifest-only", action="store_true",
                    help="dengan --apply: cukup segarkan manifest, tanpa unduh bundle")
    ap.add_argument("--replace", action="store_true",
                    help="dengan --apply: ganti SELURUH pohon aset dengan hasil iOS "
                         "(backup Android lama di MITAO_STATE)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if args.check:
        try:
            print(json.dumps(check(), indent=1, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": f"pemeriksaan gagal: {exc}"},
                             indent=1, ensure_ascii=False))
            return 1
    elif args.apply:
        try:
            result = apply_update(args.workers, args.manifest_only, args.replace)
        except Exception as exc:  # noqa: BLE001
            # Tanpa ini traceback masuk stderr & stdout kosong -> runUpdater()
            # cuma bisa bilang "Pembaru tidak mengembalikan JSON".
            log(f"GAGAL: {exc}")
            result = {"ok": False, "error": str(exc), "asset_dir": ASSET_DIR}
        print(json.dumps(result, indent=1, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
