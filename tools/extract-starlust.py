#!/usr/bin/env python3
"""Unduh dan ekstrak model Spine dari Star Lust (Erolabs / pinkcore).

Pipeline:
    catalog_*.json (Addressables, dari CDN)
        -> daftar bundle "…spine…bundle" (3.503 buah)
        -> unduh dari https://ls-download.pinkcore.net/Erolabs/Android/prod/<ver>/
        -> UnityPy -> TextAsset (.skel ber-JSON + .atlas) + Texture2D (.png)

Kenapa tidak perlu dekripsi
    Bundle Star Lust TIDAP dienkripsi: magic "UnityFS" langsung di offset 0
    dan UnityPy membacanya apa adanya. Ini beda dari game lain di repo ini
    (Megaha:Re memakai fake header sebelum UnityFS kedua; TenkaFuma me-
    nyisipkan satu byte sebelum magic). Karena itu tidak ada langkah potong
    header di sini.

Kenapa ekstensi .skel tidak ada
    TextAsset skeleton-nya bernama polos ("CGCharacter_01_1"), TANPA
    ekstensi, sedangkan atlas-nya memakai ".atlas". Keduanya dibedakan dari
    isinya: skeleton-nya JSON yang berawalan {"skeleton":{"hash":…,"spine":…}}
    (versi 4.0.64). Jadi ekstensi ditambahkan sendiri saat menyimpan.

Kenapa nama file harus dibersihkan
    Nama TextAsset bisa mengandung karakter yang tidak sah di Linux, dan
    beberapa model punya nama yang sama di bundle berbeda. Direktori
    modelnya diambil dari ID-nya (bagian sebelum hash bundle) supaya unik.

Pemakaian
    /srv/venv-spine/bin/python tools/extract-starlust.py
    /srv/venv-spine/bin/python tools/extract-starlust.py --limit 20   # uji
    OUT=/srv/spine-assets/starlust /srv/venv-spine/bin/python tools/extract-starlust.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import urllib.request
import urllib.error
from collections import Counter

import UnityPy

CATALOG = os.environ.get(
    "CATALOG", "/tmp/pc/catalog.json")
BASE_URL = os.environ.get(
    "BASE_URL",
    "https://ls-download.pinkcore.net/Erolabs/Android/prod/1.37.0.0.2/")
OUT = os.environ.get("OUT", "/srv/spine-assets/starlust")
CACHE = os.environ.get("CACHE", "/srv/spine-assets/starlust-bundles")

TEXT_ASSET = 49
TEXTURE2D = 28
PLACEHOLDER = "{LSGlobalConfig.AssetLoadPath}/"
UA = "UnityPlayer/2021.3.45f2 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"


def type_id(obj) -> int:
    """UnityPy memakai enum; ambil nilai int-nya dengan aman."""
    t = obj.type
    try:
        v = getattr(t, "value", t)
        return int(v) if str(v).isdigit() else -1
    except Exception:
        return -1


def parse_text_asset(raw: bytes):
    """Susunan TextAsset Unity: int32 nama / nama (pad 4) / int32 ukuran / data."""
    try:
        n = struct.unpack("<i", raw[0:4])[0]
        if not (0 < n < 512):
            return None, None
        pos = 4 + n
        pos += -pos % 4
        size = struct.unpack("<i", raw[pos:pos + 4])[0]
        pos += 4
        if not (0 <= size <= len(raw) - pos):
            return None, None
        return raw[4:4 + n].decode("utf8", "replace"), raw[pos:pos + size]
    except Exception:
        return None, None


def safe(name: str) -> str:
    """Buang karakter yang tidak aman dipakai sebagai nama berkas."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(str(name))).strip("_")


def spine_bundles(catalog_path: str) -> list[str]:
    """Ambil daftar bundle Spine dari katalog Addressables."""
    with open(catalog_path, encoding="utf8") as f:
        doc = json.load(f)
    ids = doc.get("m_InternalIds") or []
    out = []
    for x in ids:
        if not isinstance(x, str) or "spine" not in x.lower():
            continue
        if not x.lower().endswith(".bundle"):
            continue
        out.append(x.replace(PLACEHOLDER, ""))
    # Urutkan supaya hasilnya bisa diulang (dan gampang dilanjut).
    return sorted(set(out))


def model_id(bundle_name: str) -> str:
    """Direktori model: "<jenis>/<id>" supaya tidak numpuk di satu folder.

    Nama bundle berbentuk
    "characterspine_assets_character_00000101_<hash32>.bundle". Tanpa ini
    semua model masuk satu direktori "characterspine" dan saling timpa
    bila namanya beririsan.
    """
    stem = bundle_name[:-len(".bundle")] if bundle_name.endswith(".bundle") else bundle_name
    parts = stem.split("_")
    # parts[0] = jenis (characterspine / cgcharacterspine)
    # gabungkan sampai sebelum hash 32-hex terakhir
    kept = []
    for p in parts:
        if re.fullmatch(r"[0-9a-f]{32}", p):
            break
        kept.append(p)
    kind = kept[0] if kept else (parts[0] if parts else stem)
    rest = "_".join(kept[1:]) if len(kept) > 1 else stem
    return os.path.join(safe(kind), safe(rest) or "model")


def fetch(bundle_name: str, dest: str) -> bool:
    """Unduh satu bundle. Lewati kalau sudah ada dan ukurannya wajar."""
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return True
    url = BASE_URL + bundle_name
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        if not data.startswith(b"UnityFS"):
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def extract(bundle_path: str, out_root: str) -> tuple[str, int]:
    """Ekstrak satu bundle. Kembalikan (status, jumlah berkas)."""
    try:
        with open(bundle_path, "rb") as f:
            env = UnityPy.load(f.read())
    except Exception:
        return "parse-gagal", 0

    texts = []   # (nama, data)
    textures = {}  # nama -> objek (jangan di-decode saat memindai)
    for obj in env.objects:
        tid = type_id(obj)
        if tid == TEXT_ASSET:
            name, data = parse_text_asset(obj.get_raw_data())
            if name and data:
                texts.append((name, data))
        elif tid == TEXTURE2D:
            try:
                r = obj.read()
                nm = getattr(r, "m_Name", None) or getattr(r, "name", None)
                if nm:
                    textures[safe(nm)] = r
            except Exception:
                continue

    if not texts:
        return "tanpa-teks", 0

    # Tentukan nama model dari atlas (paling bisa diandalkan).
    atlas_name = next((n for n, _ in texts if n.lower().endswith(".atlas")), None)
    stem = safe(os.path.splitext(atlas_name)[0]) if atlas_name else safe(texts[0][0])
    if not stem:
        return "nama-kosong", 0

    model_dir = os.path.join(out_root, model_id(os.path.basename(bundle_path)))
    os.makedirs(model_dir, exist_ok=True)
    written = 0

    for name, data in texts:
        low = name.lower()
        if low.endswith(".atlas"):
            path = os.path.join(model_dir, stem + ".atlas")
            with open(path, "wb") as f:
                f.write(data)
            written += 1
        elif data[:1] == b"{" and b'"skeleton"' in data[:200]:
            # Skeleton ber-JSON tanpa ekstensi.
            path = os.path.join(model_dir, stem + ".json")
            with open(path, "wb") as f:
                f.write(data)
            written += 1
        elif low.endswith((".skel", ".json", ".txt")):
            path = os.path.join(model_dir, safe(name))
            with open(path, "wb") as f:
                f.write(data)
            written += 1

    # Halaman tekstur yang benar-benar disebut atlas.
    try:
        atlas_path = os.path.join(model_dir, stem + ".atlas")
        if os.path.exists(atlas_path):
            with open(atlas_path, encoding="utf8", errors="replace") as f:
                lines = f.read().split("\n")
            pages = []
            for ln in lines:
                s = ln.strip()
                # Baris halaman: nama berkas tanpa spasi, sebelum blok region.
                if s and not s.startswith(("size:", "format:", "filter:", "repeat:", "pma:")) \
                        and not s[0].isspace() and re.search(r"\.(png|jpg|jpeg)$", s, re.I):
                    pages.append(s)
            for page in pages:
                key = safe(os.path.splitext(page)[0])
                tex = textures.get(key)
                if tex is None:
                    continue
                dest = os.path.join(model_dir, safe(page))
                try:
                    img = tex.image
                    img.save(dest)
                    written += 1
                except Exception:
                    continue
    except Exception:
        pass

    return "ok" if written else "kosong", written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0,
                    help="hentikan setelah N bundle (0 = semua)")
    ap.add_argument("--keep-bundles", action="store_true",
                    help="simpan berkas .bundle yang diunduh")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    if not os.path.exists(CATALOG):
        sys.exit(f"Katalog tidak ada: {CATALOG}\n"
                 f"Unduh dulu: {BASE_URL}catalog_*.json")

    bundles = spine_bundles(CATALOG)
    print(f"Katalog    : {CATALOG}")
    print(f"Bundle     : {len(bundles)}")
    print(f"Base URL   : {BASE_URL}")
    print(f"Hasil      : {OUT}\n")

    if args.limit:
        bundles = bundles[:args.limit]

    stats = Counter()
    files = 0
    for i, name in enumerate(bundles, 1):
        cache_path = os.path.join(CACHE, name)
        if not fetch(name, cache_path):
            stats["unduh-gagal"] += 1
            continue
        status, n = extract(cache_path, OUT)
        stats[status] += 1
        files += n
        if not args.keep_bundles:
            try:
                os.remove(cache_path)
            except Exception:
                pass
        if i % 25 == 0 or i == len(bundles):
            print(f"  {i}/{len(bundles)}  berkas={files}  {dict(stats)}")

    print(f"\nSelesai. Berkas ditulis: {files}")
    print("Status:", dict(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
