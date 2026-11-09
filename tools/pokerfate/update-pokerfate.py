#!/usr/bin/env python3
"""Updater aset Spine PokerFate — kontrak --check / --apply untuk panel UI.

Alur (semua lokal, tidak ada endpoint game selain HEAD/Range ke APK resmi):

    APK -> ekstrak assets/aa -> dekripsi XENC -> ekspor Spine -> assets/

Sumber algoritma XENC: live2dhub.com/t/topic/6530 ("PokerFate 解包").
Konstanta S/C diverifikasi terhadap APK live lewat `--probe` (HTTP Range,
tanpa mengunduh 1,6 GB): XENC -> UnityFS -> UnityPy bisa membuka objeknya.

Kontrak server (src/server.js runUpdater):
  * stdout HANYA blok JSON hasil; progres & stdout sub-proses ke stderr.
  * --check murah: 1 HEAD + baca state, tidak mengunduh apa pun.
  * --apply boleh lama (background); idempoten kalau versi APK belum berubah.
  * --probe: verifikasi kripto murah lewat HTTP Range, untuk regresi.

State: data/pokerfate-update-state.json. Direktori kerja & backup di luar repo
(POKERFATE_STATE, default /srv/spine-assets/pokerfate). Aset selalu relatif
repo (ROOT/assets/pokerfate), JANGAN hardcode /opt/... karena service systemd
jalan dengan WorkingDirectory=/root/spine-viewer.

Pemakaian:
    /srv/venv-spine/bin/python tools/pokerfate/update-pokerfate.py --check
    /srv/venv-spine/bin/python tools/pokerfate/update-pokerfate.py --probe
    /srv/venv-spine/bin/python tools/pokerfate/update-pokerfate.py --apply
    ... --apply --force          # paksa unduh+ekspor ulang
    ... --apply --skip-publish   # ekspor ke staging saja
"""
from __future__ import annotations

import argparse
import email.utils
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from decrypt import decrypt_bytes, looks_valid  # noqa: E402

APK_URL = "https://aws.poker-fate.com/dl/PokerFate_Android.apk"
ASSETS = os.environ.get("POKERFATE_OUT", os.path.join(ROOT, "assets", "pokerfate"))
STATE_DIR = os.environ.get("POKERFATE_STATE", "/srv/spine-assets/pokerfate")
STATE_FILE = os.path.join(ROOT, "data", "pokerfate-update-state.json")
WORK = os.environ.get("POKERFATE_WORK", os.path.join(STATE_DIR, "work"))
PY = os.environ.get("PY", "/srv/venv-spine/bin/python")
MIN_MODELS = 100
APK_OVERRIDE = None


def log(msg: str) -> None:
    """Progres SELALU ke stderr: stdout dikhususkan untuk blok JSON hasil."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    kw.setdefault("stdout", sys.stderr)  # jangan cemari stdout JSON
    kw.setdefault("stderr", sys.stderr)
    return subprocess.run(cmd, check=False, **kw)


# --------------------------------------------------------------------------
# Versi remote (1 request HEAD)
# --------------------------------------------------------------------------

def head_signature() -> dict:
    req = urllib.request.Request(APK_URL, method="HEAD",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        etag = (r.headers.get("ETag") or "").strip()
        lastmod = (r.headers.get("Last-Modified") or "").strip()
        size = int(r.headers.get("Content-Length") or 0)
    try:
        version = email.utils.parsedate_to_datetime(lastmod).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        version = etag.strip('"')[:16] or "unknown"
    return {
        "etag": etag, "lastModified": lastmod, "size": size,
        "sig": f"{etag}|{lastmod}|{size}", "version": version,
    }


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, ensure_ascii=False)


def model_count(root: str | None = None) -> int:
    # Jangan taruh ASSETS sebagai default argumen: nilainya dibekukan saat
    # definisi fungsi, sehingga --assets override tidak pernah terbaca.
    target: str = str(root or ASSETS)
    if not os.path.isdir(target):
        return 0
    return len([d for d in os.listdir(target)
                if os.path.isdir(os.path.join(target, d)) and not d.startswith(".")])


def valid_models(root: str) -> int:
    """Folder model yang benar-benar punya .skel + .atlas + .png."""
    if not os.path.isdir(root):
        return 0
    n = 0
    for d in os.listdir(root):
        p = os.path.join(root, d)
        if not os.path.isdir(p) or d.startswith("."):
            continue
        fs = os.listdir(p)
        if (any(f.lower().endswith(".skel") for f in fs)
                and any(f.lower().endswith(".atlas") for f in fs)
                and any(f.lower().endswith(".png") for f in fs)):
            n += 1
    return n


# --------------------------------------------------------------------------
# --check : murah, tanpa unduh
# --------------------------------------------------------------------------

def check() -> dict:
    state = load_state()
    have = model_count()
    if not state.get("baseline_models"):
        state["baseline_models"] = have
        state["bootstrapped_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)
    error = None
    try:
        sig = head_signature()
    except Exception as exc:  # noqa: BLE001
        sig, error = None, str(exc)
    if sig and not state.get("sig"):
        # Bootstrap: aset yang ada dianggap berasal dari rilis ini.
        state["sig"] = sig["sig"]
        state["version"] = sig["version"]
        state["models"] = have
        state["apk_size"] = sig["size"]
        save_state(state)
    changed = bool(sig and (
        (state.get("sig") and sig["sig"] != state["sig"])
        or have < int(state.get("models") or have)))
    previous = state.get("version") or f"baseline:{state['baseline_models']}-model"
    version = sig["version"] if sig else state.get("version")
    if error:
        note = f"Gagal memeriksa versi APK: {error}"
    elif changed:
        note = f"APK baru {version} — putar Perbarui aset."
    else:
        note = f"Sudah versi terbaru {version} — {have} model."
    return {
        "ok": True, "mode": "check",
        "version": version, "installed": state.get("version"),
        "previous": previous, "changed": changed, "new": 0,
        "have": have, "expected": int(state.get("models") or have),
        "asset_dir": ASSETS, "apk_size": sig["size"] if sig else state.get("apk_size"),
        "note": note, "version_error": error,
    }


# --------------------------------------------------------------------------
# --probe : verifikasi XENC ke APK live lewat HTTP Range (tanpa unduh 1,6 GB)
# --------------------------------------------------------------------------

def _range(rng: str, timeout: int = 60) -> tuple[bytes, dict]:
    req = urllib.request.Request(APK_URL, headers={
        "User-Agent": "Mozilla/5.0", "Range": rng})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), dict(r.headers)


def probe() -> dict:
    """Ambil SATU bundle dari ZIP APK via Range, dekrip, buka dengan UnityPy."""
    t0 = time.time()
    req = urllib.request.Request(APK_URL, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        total = int(r.headers["Content-Length"])
    tail_n = min(1 << 20, total)
    tail, _ = _range(f"bytes={total - tail_n}-{total - 1}")
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise RuntimeError("EOCD ZIP tidak ditemukan")
    cd_size = struct.unpack_from("<I", tail, eocd + 12)[0]
    cd_off = struct.unpack_from("<I", tail, eocd + 16)[0]
    if cd_off >= total - tail_n:
        cd = tail[cd_off - (total - tail_n):][:cd_size]
    else:
        cd, _ = _range(f"bytes={cd_off}-{cd_off + cd_size - 1}")
    entries, p = [], 0
    while p + 46 <= len(cd) and cd[p:p + 4] == b"PK\x01\x02":
        method = struct.unpack_from("<H", cd, p + 10)[0]
        csize = struct.unpack_from("<I", cd, p + 20)[0]
        nlen, xlen, clen = struct.unpack_from("<HHH", cd, p + 28)
        lho = struct.unpack_from("<I", cd, p + 42)[0]
        name = cd[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        entries.append((name, method, csize, lho))
        p += 46 + nlen + xlen + clen
    cand = sorted((e for e in entries if "assets/aa/" in e[0]
                   and e[0].lower().endswith(".bundle")), key=lambda e: e[2])
    if not cand:
        raise RuntimeError("tidak ada bundle assets/aa/* di APK")
    name, method, csize, lho = cand[0]
    blob, _ = _range(f"bytes={lho}-{lho + 30 + len(name) + 512 + csize - 1}")
    nlen, xlen = struct.unpack_from("<HH", blob, 26)
    comp = blob[30 + nlen + xlen:30 + nlen + xlen + csize]
    raw = comp if method == 0 else zlib.decompressobj(-15).decompress(comp)
    was_enc = raw[:4] == b"XENC"
    plain, _ = decrypt_bytes(raw)
    ok = was_enc and looks_valid(plain)
    objects = 0
    if ok:
        import UnityPy
        objects = len(list(UnityPy.load(io.BytesIO(plain)).objects))
        ok = objects > 0
    return {
        "ok": ok, "mode": "probe", "apk_size": total,
        "central_entries": len(entries), "asset_bundles": len(cand),
        "bundle": name, "encrypted": was_enc, "magic": plain[:8].decode("latin1"),
        "unityfs": plain.startswith(b"UnityFS"), "objects": objects,
        "bytes_downloaded": tail_n + len(blob),
        "seconds": round(time.time() - t0, 1),
    }


# --------------------------------------------------------------------------
# --apply
# --------------------------------------------------------------------------

def download_apk(dest: str, expect_size: int) -> str:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) == expect_size:
        log(f"APK sudah ada ({expect_size / 2**30:.2f} GiB), dilewati")
        return dest
    tmp = dest + ".part"
    log(f"mengunduh {APK_URL} ({expect_size / 2**30:.2f} GiB)")
    with urllib.request.urlopen(APK_URL, timeout=180) as resp, open(tmp, "wb") as fh:
        done, last = 0, 0.0
        while True:
            chunk = resp.read(4 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if time.time() - last > 15:
                last = time.time()
                log(f"  {done / 2**30:.2f} / {expect_size / 2**30:.2f} GiB")
    os.replace(tmp, dest)
    return dest


def find_bundles(root: str) -> list:
    out = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".bundle"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def extract_apk(apk: str, out_dir: str) -> None:
    marker = os.path.join(out_dir, ".extracted")
    if os.path.exists(marker):
        log("bundle sudah diekstrak, dilewati")
        return
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    log("mengekstrak assets/aa dari APK (7z)")
    res = run(["7z", "x", "-y", f"-o{out_dir}", apk, "assets/aa/*"])
    if res.returncode != 0:
        raise RuntimeError("7z gagal mengekstrak APK")
    open(marker, "w").close()


def preflight(bundles: list) -> None:
    """Dekrip SATU bundle dulu dan buka dengan UnityPy.

    Tutorial 6530 memperingatkan: hanya memeriksa 8 byte magic bisa tertipu
    \"dekripsi palsu\" (xorshift affine, ratusan konstanta lolos). Membuka
    objek UnityPy membuktikan seluruh struktur plaintext benar sebelum kita
    memproses 529 bundle.
    """
    import UnityPy
    for path in bundles[:5]:
        with open(path, "rb") as fh:
            raw = fh.read()
        if raw[:4] != b"XENC":
            continue
        # Harus berkas PENUH: looks_valid() membandingkan field ukuran di
        # header UnityFS dengan panjang plaintext, jadi potongan 4 KB selalu
        # dianggap "dekripsi palsu".
        plain, enc = decrypt_bytes(raw)
        if not enc or not looks_valid(plain):
            continue
        objs = list(UnityPy.load(io.BytesIO(plain)).objects)
        if not objs:
            continue
        log(f"preflight OK: {os.path.basename(path)} -> UnityFS, {len(objs)} objek")
        return
    raise RuntimeError(
        "preflight dekripsi XENC gagal: konstanta S/C tidak cocok dengan APK ini. "
        "Lihat live2dhub.com/t/topic/6530 untuk konstanta versi baru.")


def decrypt_all(src_root: str, plain_dir: str) -> int:
    os.makedirs(plain_dir, exist_ok=True)
    bundles = find_bundles(src_root)
    log(f"bundle ditemukan: {len(bundles)}")
    preflight(bundles)
    done = failed = 0
    for i, path in enumerate(bundles, 1):
        dst = os.path.join(plain_dir, os.path.basename(path))
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            done += 1
            continue
        with open(path, "rb") as fh:
            plain, enc = decrypt_bytes(fh.read())
        if enc and not looks_valid(plain):
            failed += 1
            continue
        with open(dst, "wb") as fh:
            fh.write(plain)
        done += 1
        if i % 40 == 0 or i == len(bundles):
            log(f"  dekripsi {i}/{len(bundles)} (gagal {failed})")
    if failed:
        raise RuntimeError(f"{failed} bundle gagal didekripsi; proses dihentikan")
    log(f"dekripsi selesai: {done} berkas")
    return done


def export_all(plain_dir: str, out_dir: str) -> list:
    log("mengekspor Spine (UnityPy)")
    res = run([PY, os.path.join(HERE, "export_spine.py"), plain_dir, out_dir])
    if res.returncode != 0:
        raise RuntimeError("export_spine.py gagal")
    manifest_path = os.path.join(out_dir, "_manifest.json")
    if not os.path.exists(manifest_path):
        raise RuntimeError("manifest ekspor tidak ada")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    ok = [m for m in manifest if m.get("status") == "ok"]
    log(f"model diekspor: {len(ok)}")
    return manifest


def publish(out_dir: str, have: int) -> tuple[int, str]:
    """Validasi staging, backup pohon lama, lalu pasang secara atomik."""
    good = valid_models(out_dir)
    need = max(MIN_MODELS, int(have * 0.8))
    if good < need:
        raise RuntimeError(
            f"staging cuma {good} model valid (butuh >= {need}); "
            "pohon aset lama dibiarkan utuh")
    os.makedirs(STATE_DIR, exist_ok=True)
    backup = os.path.join(STATE_DIR,
                          "backup-" + time.strftime("%Y%m%d-%H%M%S"))
    tmp = ASSETS + ".new"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp, exist_ok=True)
    copied = 0
    for entry in sorted(os.listdir(out_dir)):
        src = os.path.join(out_dir, entry)
        if not os.path.isdir(src):
            continue
        shutil.copytree(src, os.path.join(tmp, entry), dirs_exist_ok=True)
        copied += 1
    index = {}
    for slug in sorted(os.listdir(tmp)):
        d = os.path.join(tmp, slug)
        if not os.path.isdir(d):
            continue
        fs = os.listdir(d)
        index[slug] = {
            "skel": sorted(f for f in fs if f.lower().endswith(".skel")),
            "atlas": sorted(f for f in fs if f.lower().endswith(".atlas")),
        }
    with open(os.path.join(tmp, "_index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)
    if os.path.isdir(ASSETS):
        shutil.move(ASSETS, backup)
    shutil.move(tmp, ASSETS)
    log(f"{copied} model dipasang; backup lama di {backup}")
    return copied, backup


def apply_update(force: bool = False, keep_temp: bool = False,
                 skip_publish: bool = False) -> dict:
    t0 = time.time()
    state = load_state()
    have = model_count()
    sig = head_signature()
    if (not force and sig["sig"] == state.get("sig")
            and have >= int(state.get("models") or 0)):
        return {"ok": True, "mode": "apply", "skipped": True,
                "version": sig["version"], "have": have, "downloaded": 0,
                "extracted": 0, "published": 0,
                "note": "Versi APK belum berubah — apply idempoten, tidak ada unduhan.",
                "seconds": round(time.time() - t0, 1)}

    apk = APK_OVERRIDE or os.path.join(WORK, "PokerFate_Android.apk")
    apk_dir = os.path.join(WORK, "apk")
    plain_dir = os.path.join(WORK, "plain")
    out_dir = os.path.join(WORK, "out")
    os.makedirs(WORK, exist_ok=True)
    if APK_OVERRIDE:
        if not os.path.isfile(APK_OVERRIDE):
            raise RuntimeError(f"APK lokal tidak ada: {APK_OVERRIDE}")
        apk = APK_OVERRIDE
        downloaded = 0
        log(f"pakai APK lokal: {apk} (unduhan dilewati)")
    else:
        download_apk(apk, sig["size"])
        downloaded = sig["size"]
    extract_apk(apk, apk_dir)
    n_bundles = decrypt_all(apk_dir, plain_dir)
    manifest = export_all(plain_dir, out_dir)
    ok_models = len([m for m in manifest if m.get("status") == "ok"])

    published = 0
    backup = None
    if not skip_publish:
        published, backup = publish(out_dir, have)
        state["sig"] = sig["sig"]
        state["version"] = sig["version"]
        state["apk_size"] = sig["size"]
        state["models"] = model_count()
        state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)

    if not keep_temp:
        for d in (apk_dir, plain_dir, out_dir):
            shutil.rmtree(d, ignore_errors=True)
        log("direktori kerja dibersihkan (--keep-temp untuk menyimpan)")

    return {
        "ok": True, "mode": "apply", "skipped": False,
        "version": sig["version"], "downloaded": downloaded,
        "bundles": n_bundles, "exported": ok_models,
        "published": published, "have": model_count(),
        "asset_dir": ASSETS, "state": STATE_FILE,
        "backup": backup, "seconds": round(time.time() - t0, 1),
    }


def main() -> int:
    global WORK, ASSETS, APK_OVERRIDE
    ap = argparse.ArgumentParser(description="Updater aset Spine PokerFate")
    ap.add_argument("--check", action="store_true", help="status murah (HEAD + state)")
    ap.add_argument("--apply", action="store_true", help="unduh + ekspor + pasang")
    ap.add_argument("--probe", action="store_true",
                    help="verifikasi XENC ke APK live via HTTP Range (murah)")
    ap.add_argument("--force", action="store_true", help="paksa apply walau versi sama")
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--skip-publish", action="store_true")
    ap.add_argument("--apk", default=None,
                    help="pakai APK lokal (lewati unduhan; untuk uji/offline)")
    ap.add_argument("--work", default=None, help="override direktori kerja")
    ap.add_argument("--assets", default=None, help="override direktori assets")
    args = ap.parse_args()
    if args.work:
        WORK = args.work
    if args.assets:
        ASSETS = args.assets
    if args.apk:
        APK_OVERRIDE = os.path.abspath(args.apk)

    if args.check:
        try:
            print(json.dumps(check(), indent=1, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": f"pemeriksaan gagal: {exc}"}))
            return 1
    elif args.probe:
        try:
            print(json.dumps(probe(), indent=1, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "mode": "probe", "error": str(exc)}))
            return 1
    elif args.apply:
        try:
            result = apply_update(args.force, args.keep_temp, args.skip_publish)
        except Exception as exc:  # noqa: BLE001
            log(f"GAGAL: {exc}")
            result = {"ok": False, "mode": "apply", "error": str(exc),
                      "asset_dir": ASSETS}
        print(json.dumps(result, indent=1, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    else:
        print(json.dumps({"ok": False,
                          "error": "pilih --check, --probe, atau --apply"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
