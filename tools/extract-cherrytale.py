#!/usr/bin/env python3
"""Unduh dan ekstrak model Spine dari Cherry Tale (88kongque).

Pipeline:
    bundleMap.txt (assetID|bundleName)
        -> saring bundle spine (617)
        -> unduh https://pfdd.88kongque.com/patch/files/<bundleName>
        -> UnityPy -> TextAsset (.skel 4.0.64 + .atlas) + Texture2D (.png)

Tentang dekripsi
    Script referensi (violet-wdream/.Scripts CherryTaleDecrypt.py) melakukan
    dua hal: menukar tiga byte pada indeks [0x3FB, 0xD99, 0x197C] dengan
    pasangannya dari ekor, lalu mengganti string versi "2018.3.5f1" dengan
    "2020.3.41f1".

    Bundle yang diunduh dari CDN ini TIDAK memerlukan keduanya: magic
    UnityFS ada di offset 0 dan string versinya sudah "2020.3.41f1", jadi
    UnityPy membacanya langsung. Karena itu skrip ini tidak mendekripsi.
    Kalau kelak menemui bundle yang gagal diparse, jalankan dulu
    CherryTaleDecrypt.py pada folder unduhannya.

Jebakan utama: berkas ganda dalam satu bundle
    Satu bundle bisa memuat beberapa TextAsset dengan NAMA SAMA pada
    resolusi berbeda (li02_01_CG.skel 426 KB dan 2,8 KB; atlas 119 B dan
    2,7 KB). Mengambil yang pertama akan menyimpan yang kecil, padahal
    atlas mendeklarasikan koordinat versi besar — modelnya lalu tampil
    sebagai pecahan acak. Karenanya yang disimpan adalah yang PALING BESAR
    per nama. Aturan yang sama berlaku untuk tekstur.

Pemakaian
    /srv/venv-spine/bin/python tools/extract-cherrytale.py
    /srv/venv-spine/bin/python tools/extract-cherrytale.py --limit 10
"""
from __future__ import annotations

import argparse
import os
import re
import struct
import sys
import urllib.request
from collections import Counter

import UnityPy

MAP = os.environ.get("MAP", "/srv/spine-assets/cherrytale/bundleMap.txt")
BASE_URL = os.environ.get("BASE_URL", "https://pfdd.88kongque.com/patch/files/")
OUT = os.environ.get("OUT", "/srv/spine-assets/cherrytale-models")
CACHE = os.environ.get("CACHE", "/srv/spine-assets/cherrytale-bundles")

TEXT_ASSET = 49
TEXTURE2D = 28
UA = "UnityPlayer/2020.3.41f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"


def type_id(obj) -> int:
    t = obj.type
    try:
        v = getattr(t, "value", t)
        return int(v) if str(v).isdigit() else -1
    except Exception:
        return -1


def parse_text_asset(raw: bytes):
    """int32 nama / nama (pad 4) / int32 ukuran / data."""
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
    return re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(str(name))).strip("_")


def read_map(path: str) -> list[tuple[str, str]]:
    """Kembalikan (assetID, bundleName) dari bundleMap.txt."""
    with open(path, encoding="utf8", errors="replace") as f:
        raw = f.read()
    out = []
    for line in raw.split("\n"):
        # Baris diakhiri pemisah '┤' dan memakai CRLF.
        line = line.rstrip("┤").strip()
        if not line or "|" not in line:
            continue
        a, b = line.split("|", 1)
        a, b = a.strip(), b.strip()
        if not a or not b or a.lower() == "assetid":
            continue
        out.append((a, b))
    return out


def spine_entries(records) -> list[tuple[str, str]]:
    return [(a, b) for a, b in records if "spine" in b.lower()]


def fetch(bundle_name: str, dest: str) -> bool:
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return True
    req = urllib.request.Request(BASE_URL + bundle_name, headers={"User-Agent": UA})
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


def extract(bundle_path: str, out_root: str, asset_id: str) -> tuple[str, int]:
    try:
        with open(bundle_path, "rb") as f:
            env = UnityPy.load(f.read())
    except Exception:
        return "parse-gagal", 0

    # Kumpulkan TextAsset, simpan hanya yang terbesar per nama.
    best_text: dict[str, bytes] = {}
    tex_objs: dict[str, object] = {}
    for obj in env.objects:
        tid = type_id(obj)
        if tid == TEXT_ASSET:
            name, data = parse_text_asset(obj.get_raw_data())
            if not name or not data:
                continue
            key = safe(name)
            if key not in best_text or len(data) > len(best_text[key]):
                best_text[key] = data
        elif tid == TEXTURE2D:
            try:
                r = obj.read()
                nm = getattr(r, "m_Name", None) or getattr(r, "name", None)
                if not nm:
                    continue
                key = safe(nm)
                prev = tex_objs.get(key)
                if prev is None:
                    tex_objs[key] = r
                else:
                    # Pertahankan yang berukuran lebih besar.
                    try:
                        if (r.m_Width * r.m_Height) > (prev.m_Width * prev.m_Height):
                            tex_objs[key] = r
                    except Exception:
                        pass
            except Exception:
                continue

    if not best_text:
        return "tanpa-teks", 0

    atlas_key = next((k for k in best_text if k.lower().endswith(".atlas")), None)
    stem = safe(os.path.splitext(atlas_key)[0]) if atlas_key else safe(sorted(best_text)[0])
    if not stem:
        return "nama-kosong", 0

    model_dir = os.path.join(out_root, safe(asset_id) or stem)
    os.makedirs(model_dir, exist_ok=True)
    written = 0

    for key, data in best_text.items():
        low = key.lower()
        if low.endswith(".atlas"):
            dest = os.path.join(model_dir, stem + ".atlas")
        elif low.endswith(".skel") or (data[:1] != b"{" and b"4.0." in data[:64]):
            # Skeleton biner 4.x: magic panjang lalu string versi.
            dest = os.path.join(model_dir, stem + ".skel")
        elif data[:1] == b"{" and b'"skeleton"' in data[:200]:
            dest = os.path.join(model_dir, stem + ".json")
        else:
            continue
        with open(dest, "wb") as f:
            f.write(data)
        written += 1

    # Simpan hanya halaman tekstur yang disebut atlas.
    atlas_path = os.path.join(model_dir, stem + ".atlas")
    if os.path.exists(atlas_path):
        try:
            with open(atlas_path, encoding="utf8", errors="replace") as f:
                lines = f.read().split("\n")
            for ln in lines:
                s = ln.strip()
                if not s or s.startswith(("size:", "format:", "filter:",
                                          "repeat:", "pma:", "scale:")):
                    continue
                if re.search(r"\.(png|jpg|jpeg)$", s, re.I):
                    tex = tex_objs.get(safe(os.path.splitext(s)[0]))
                    if tex is None:
                        continue
                    try:
                        tex.image.save(os.path.join(model_dir, safe(s)))
                        written += 1
                    except Exception:
                        continue
        except Exception:
            pass

    return ("ok" if written else "kosong"), written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="hentikan setelah N bundle")
    ap.add_argument("--keep-bundles", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    if not os.path.exists(MAP):
        sys.exit(f"bundleMap tidak ada: {MAP}")

    records = read_map(MAP)
    entries = spine_entries(records)
    print(f"Map        : {MAP}")
    print(f"Record     : {len(records)}")
    print(f"Bundle spine: {len(entries)}")
    print(f"Base URL   : {BASE_URL}")
    print(f"Hasil      : {OUT}\n")

    if args.limit:
        entries = entries[:args.limit]

    stats = Counter()
    files = 0
    for i, (asset_id, bundle) in enumerate(entries, 1):
        cache_path = os.path.join(CACHE, safe(bundle))
        if not fetch(bundle, cache_path):
            stats["unduh-gagal"] += 1
            continue
        status, n = extract(cache_path, OUT, asset_id)
        stats[status] += 1
        files += n
        if not args.keep_bundles:
            try:
                os.remove(cache_path)
            except Exception:
                pass
        if i % 25 == 0 or i == len(entries):
            print(f"  {i}/{len(entries)}  berkas={files}  {dict(stats)}")

    print(f"\nSelesai. Berkas ditulis: {files}")
    print("Status:", dict(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
