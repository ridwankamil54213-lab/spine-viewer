#!/usr/bin/env python3
"""Pembaru Azur Lane Live2D (azurlane-l2d).

Sumber  : CDN resmi Azur Lane, lewat gate TCP game (sama seperti azlassets).
          Gate memberi daftar versi per tipe aset; tipe `L2D` adalah Live2D.
          Hashfile tipe itu berisi satu baris per bundle:
              live2d/<nama>,<ukuran>,<md5>
          Berkasnya diunduh dari <cdn>/android/resource/<md5>.
Layout  : assets/azurlane-l2d/<nama>/ — sama seperti hasil extractor
          tools/azurlane/extract-azurlane-l2d.py.

Alur    : --check = hubungi gate, ambil hashfile L2D, diff dengan
          hashes-live2d.csv lokal (266 entri). --apply = unduh bundle baru /
          berubah, ekstrak ke assets/azurlane-l2d/.

Mengapa tidak memanggil `azl` langsung: perintah `azl download` selalu
memeriksa SEMUA tipe aset (AZL, BGM, CV, MANGA, MAP, ...) dan tidak punya
mode dry-run. Updater ini hanya menyentuh tipe L2D, jadi --check selesai
dalam hitungan detik tanpa menyentuh 2,9 GB cache.

Butuh: pip install azlassets (untuk parsing protobuf gate + client config).
Progres -> stderr; hasil JSON -> stdout (kontrak /api/update/:game).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
DEST = os.path.join(ASSETS, "azurlane-l2d")
STATE_DIR = os.environ.get("AZL_L2D_STATE_DIR", "/srv/spine-assets/azurlane-l2d-update")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

# Cache unduhan mentah (bundle Unity) — terpisah dari hasil ekstrak.
CACHE = os.environ.get("AZL_L2D_CACHE", "/opt/games/azurlane/ClientAssets")

CLIENT = os.environ.get("AZL_L2D_CLIENT", "JP")  # JP = paling banyak Live2D
UA = "Azurlane Asset Manager Bot"  # UA yang diterima CDN; UA lain -> 403
WORKERS = 4

UUID_RE = re.compile(rb"[0-9a-f]{32}")


def _log(msg: str) -> None:
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_state(d: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".part"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def hash_file_path() -> str:
    return os.path.join(CACHE, CLIENT, "hashes-live2d.csv")


def load_local_hashes() -> dict[str, str]:
    """nama_bundle -> md5 dari hashes-live2d.csv yang ditulis `azl`.

    Kunci dinormalkan tanpa awalan `live2d/` supaya bisa dibandingkan dengan
    hashfile server yang di-strip dengan cara yang sama. Tanpa ini semua
    entri terlihat "baru" sekaligus "hilang".
    """
    out: dict[str, str] = {}
    p = hash_file_path()
    if not os.path.isfile(p):
        return out
    with open(p) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) != 3:
                continue
            path = parts[0]
            name = path.split("/", 1)[1] if "/" in path else path
            out[name] = parts[2]
    return out


def installed_stems() -> set[str]:
    try:
        return {d for d in os.listdir(DEST) if os.path.isdir(os.path.join(DEST, d))}
    except FileNotFoundError:
        return set()


# --------------------------------------------------------------------------- #
# Gate & hashfile
# --------------------------------------------------------------------------- #
def fetch_remote_hashes() -> tuple[str, dict[str, tuple[str, int]]]:
    """Versi L2D terbaru + {nama_bundle: (md5, ukuran)}.

    Memakai azlassets untuk urusan protobuf gate dan client config — itu satu-
    satunya bagian yang rumit (socket + protobuf). Sisanya ditangani di sini.
    """
    try:
        from azlassets import config, downloader, protobuf
        from azlassets.classes import Client
        from azlassets.downloadmgr import try_parse_version_string
    except ImportError:
        raise SystemExit(
            "azlassets tidak terpasang. Jalankan: /srv/venv-spine/bin/pip install azlassets"
        )

    cc = config.load_client_config(Client[CLIENT])
    _log(f"gate {cc.gateip}:{cc.gateport} · cdn {cc.cdnurl}")
    vr = protobuf.get_version_response(cc.gateip, cc.gateport)
    if not vr:
        raise SystemExit("gate tidak menjawab permintaan versi")

    l2d = None
    versions = {}
    for v in vr.pb.version:
        if not v.startswith("$"):
            continue
        r = try_parse_version_string(v.strip(), True)
        if not r:
            continue
        versions[r.version_type.name] = r.version
        if r.version_type.name == "L2D":
            l2d = r
    if l2d is None:
        raise SystemExit("gate tidak mengirim versi L2D")

    _log(f"versi L2D terbaru: {l2d.version}")

    async def _get() -> str | None:
        async with downloader.AzurlaneAsyncDownloader(cc.cdnurl, useragent=UA) as dl:
            # download_hashes mengirim rawstring utuh ($l2dhash$<ver>$<hash>),
            # bukan hanya hash-nya — memakai vhash saja menghasilkan 403.
            return await dl.download_hashes(l2d)

    txt = asyncio.run(_get())
    if not txt:
        raise SystemExit("hashfile L2D tidak bisa diunduh")

    remote: dict[str, tuple[str, int]] = {}
    for line in txt.splitlines():
        parts = line.strip().split(",")
        if len(parts) != 3:
            continue
        path, size, md5 = parts
        if not path.startswith("live2d/"):
            continue
        name = path.split("/", 1)[1]
        try:
            remote[name] = (md5, int(size))
        except ValueError:
            continue
    return l2d.version, remote


# --------------------------------------------------------------------------- #
# Unduh bundle
# --------------------------------------------------------------------------- #
def bundle_url(md5: str) -> str:
    # CDN JP: https://blhxstatic.yo-star.com/android/resource/<md5>
    from azlassets import config
    from azlassets.classes import Client

    cc = config.load_client_config(Client[CLIENT])
    return f"{cc.cdnurl}/android/resource/{md5}"


def download_bundle(md5: str, size: int, dest_dir: str) -> str | None:
    """Unduh satu bundle ke cache. Kembalikan path, atau None kalau gagal."""
    import urllib.request

    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, md5)
    if os.path.isfile(dest) and os.path.getsize(dest) == size:
        return dest
    url = bundle_url(md5)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        if len(data) != size:
            _log(f"  ukuran tidak cocok {md5[:8]}: {len(data)} != {size}")
            return None
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        return dest
    except Exception as e:  # noqa: BLE001
        _log(f"  gagal unduh {md5[:8]}: {e}")
        return None


# --------------------------------------------------------------------------- #
# Ekstrak Live2D dari bundle Unity
# --------------------------------------------------------------------------- #
def _textasset_body(ob) -> tuple[str, bytes]:
    """TextAsset -> (nama, isi). Format mentah: panjang(n) + nama + padding + panjang + isi."""
    import struct

    raw = ob.get_raw_data()
    if len(raw) < 4:
        return "", b""
    n = struct.unpack("<i", raw[0:4])[0]
    if not (0 < n < 400):
        return "", raw
    q = 4 + n
    q += (4 - (q % 4)) % 4
    sz = struct.unpack("<i", raw[q : q + 4])[0]
    return raw[4 : 4 + n].decode("utf-8", "replace"), raw[q + 4 : q + 4 + sz]


def extract_bundle(bundle: str, name: str, out_root: str) -> int:
    """Keluarkan .moc3 + tekstur + physics dari bundle Unity.

    Meniru extractor yang sudah terbukti (tools/azurlane/extract-azurlane-l2d.py),
    termasuk dua detail yang mudah salah:

      1. Bundle diawali data lain sebelum `UnityFS`; UnityPy harus diberi
         potongan mulai dari kemunculan TERAKHIR `UnityFS`, bukan seluruh file.
      2. moc3 diambil sebagai `raw[k:]` dari MonoBehaviour-nya. Header MOC3
         TIDAK menyimpan ukuran total di offset 60 (field itu nol di sini),
         jadi membaca field ukuran akan gagal total — percobaan pertama
         updater ini melakukan itu dan mengekstrak 0 berkas.

    Mengembalikan jumlah berkas yang ditulis.
    """
    import io

    try:
        import UnityPy  # type: ignore
    except ImportError:
        _log("  UnityPy tidak terpasang — jalankan: pip install UnityPy")
        return 0

    UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f3"
    data = open(bundle, "rb").read()
    if b"MOC3" not in data:
        return 0
    off = data.rfind(b"UnityFS")
    try:
        env = UnityPy.load(io.BytesIO(data[off:]))
        objs = list(env.objects)
    except Exception as e:  # noqa: BLE001
        _log(f"  UnityPy gagal memuat bundle: {e}")
        return 0

    moc3 = None
    physics = None
    textures = []
    for ob in objs:
        t = ob.type.name
        if t == "MonoBehaviour" and moc3 is None:
            raw = ob.get_raw_data()
            k = raw.find(b"MOC3")
            if k >= 0:
                moc3 = raw[k:]
        elif t == "TextAsset":
            nm, body = _textasset_body(ob)
            if "physics" in nm.lower() and body:
                physics = body
        elif t == "Texture2D":
            try:
                textures.append((ob.read().m_Name or "", ob.read()))
            except Exception:  # noqa: BLE001
                pass

    if not moc3:
        return 0

    out_dir = os.path.join(out_root, name)
    os.makedirs(out_dir, exist_ok=True)
    written = 0
    with open(os.path.join(out_dir, f"{name}.moc3"), "wb") as f:
        f.write(moc3)
    written += 1

    if physics:
        with open(os.path.join(out_dir, f"{name}.physics3.json"), "wb") as f:
            f.write(physics)
        written += 1

    tex_files = []
    for i, (tn, r) in enumerate(textures):
        try:
            img = r.image
            if img is None:
                continue
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            fn = (tn or f"texture_{i:02d}") + ".png"
            img.save(os.path.join(out_dir, fn))
            tex_files.append(fn)
            written += 1
        except Exception:  # noqa: BLE001
            pass
    tex_files.sort()

    # model3.json disintesis di sini supaya folder langsung bisa dibaca viewer;
    # server juga menyintesis ulang saat scan, jadi ini hanya jaring pengaman.
    model3 = {
        "Version": 3,
        "Name": name,
        "FileReferences": {
            "Moc": f"{name}.moc3",
            "Textures": tex_files,
            "Physics": f"{name}.physics3.json" if physics else None,
            "Motions": {},
        },
    }
    with open(os.path.join(out_dir, f"{name}.model3.json"), "w", encoding="utf-8") as f:
        json.dump(model3, f, indent=1, ensure_ascii=False)

    return written


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if not (a.check or a.apply):
        a.check = True

    saved = load_state()
    version, remote = fetch_remote_hashes()
    local = load_local_hashes()
    installed = installed_stems()

    # Nama model dari path hash. Hashfile memakai nama bundle yang sama
    # dengan folder hasil ekstrak, jadi tidak perlu tabel tambahan.
    names = sorted(remote)
    baru = [n for n in names if n not in local]
    berubah = [n for n in names if n in local and local[n] != remote[n][0]]
    hilang = [n for n in local if n not in remote]

    _log(f"server {len(names)} bundle · lokal {len(local)} · terpasang {len(installed)}")
    _log(f"baru {len(baru)} · berubah {len(berubah)} · hilang {len(hilang)}")
    for n in baru[:20]:
        _log(f"  BARU  {n}")

    changed = bool(baru or berubah) or version != saved.get("version")
    result = {
        "ok": True,
        "version": version,
        "previous": saved.get("version") or None,
        "changed": changed,
        "total": len(names),
        "installed": len(installed),
        "new": len(baru),
        "changedFiles": len(berubah),
        "removed": len(hilang),
        "ids": baru,
    }

    if a.check or not (baru or berubah):
        save_state({**saved, "version": version if not (baru or berubah) else saved.get("version"),
                    "checkedAt": int(time.time())})
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    todo = baru + berubah
    if a.limit:
        todo = todo[: a.limit]

    cache_dir = os.path.join(CACHE, CLIENT, "AssetBundles", "live2d")
    os.makedirs(DEST, exist_ok=True)

    _log(f"mengunduh {len(todo)} bundle…")
    downloaded: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {
            ex.submit(download_bundle, remote[n][0], remote[n][1], cache_dir): n for n in todo
        }
        for fut in futs:
            n = futs[fut]
            path = fut.result()
            if path:
                downloaded.append((n, path))
                _log(f"  ok {n}")

    _log(f"mengekstrak {len(downloaded)} bundle…")
    added = 0
    failed: list[str] = []
    for n, path in downloaded:
        try:
            wrote = extract_bundle(path, n, DEST)
        except Exception as e:  # noqa: BLE001
            _log(f"  ekstrak gagal {n}: {e}")
            wrote = 0
        if wrote:
            added += 1
        else:
            failed.append(n)

    # Perbarui hashfile lokal supaya --check berikutnya tidak mengulang.
    hf = hash_file_path()
    os.makedirs(os.path.dirname(hf), exist_ok=True)
    with open(hf, "w") as f:
        for n in names:
            f.write(f"live2d/{n},{remote[n][1]},{remote[n][0]}\n")
    with open(os.path.join(CACHE, CLIENT, "version-live2d.txt"), "w") as f:
        f.write(version)

    new_ids = [f"azurlane-l2d/{n}" for n in todo if os.path.isdir(os.path.join(DEST, n))]
    result.update(
        {
            "added": added,
            "failedFiles": len(failed),
            "failed": failed,
            "new_ids": new_ids,
        }
    )
    save_state(
        {
            "version": version,
            "appliedAt": int(time.time()),
            "added": added,
            "new_ids": new_ids,
        }
    )
    _log(f"=== selesai: +{added} model, gagal {len(failed)}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
