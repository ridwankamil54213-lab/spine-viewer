#!/usr/bin/env python3
"""Ekspor Spine dari bundle PokerFate yang sudah didekripsi.

Sumber acuan: tutorial live2dhub.com/t/topic/6530. Poin-poin yang penting dan
sempat jadi jebakan di tutorial itu:

1. `.skel` dan `.atlas` tersimpan sebagai TextAsset, jadi harus dibaca dari
   `m_Script`, bukan `get_raw_data()`. Memakai yang kedua menghasilkan berkas
   sampah/terpotong.

2. Tiap model ditulis ke direktori terpisah. Kalau semua halaman tekstur
   diekspor rata dalam satu folder, halaman bernama sama dari model berbeda
   akan saling menimpa dan model jadi menunjuk tekstur yang salah.

3. Atlas perlu dikonversi dulu (lihat convert_atlas.py), karena PokerFate
   memakai kunci `bounds`/`offsets` yang tidak dikenali Spine.

4. Tekstur dicocokkan ke halaman atlas berdasarkan nama, bukan urutan.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
from typing import Iterable

import UnityPy

# Nama bundle yang memuat Spine peran. Dari inspeksi APK 2026-10:
# gameresrolespine_* (58 berkas) dan subpackage1_assets_rolespine_* (15).
ROLESPINE_HINTS = ("rolespine",)

# Pola nama bundle: <id>_<varian>_<hash32>.bundle
BUNDLE_RE = re.compile(r"^(?P<id>\d+)_(?P<var>\d+)_(?P<hash>[0-9a-f]{32})\.bundle$")
# Bundle non-numerik (mis. `login_<hash>.bundle`, `texture_assets_...`).
GENERIC_RE = re.compile(r"^(?P<stem>.+?)_[0-9a-f]{32}\.bundle$")


def _textasset_bytes(obj) -> bytes:
    """Ambil isi TextAsset sebagai byte MENTAH.

    JANGAN memakai asset.m_Script. Di UnityPy, field itu dideklarasikan
    sebagai `str`, jadi isinya sudah didekode UTF-8 dengan errors="replace":
    setiap byte >0x7F yang bukan UTF-8 valid berubah menjadi '?' (0x3F).

    Untuk .atlas (teks) itu tidak masalah, tapi untuk .skel (biner) fatal —
    terukur pada 1001_1.skel: byte >0x7F turun dari 30,3% menjadi 0,6%.
    Akibatnya runtime membaca panjang string yang salah dan melempar
    "name cannot be null" / "boneData cannot be null".

    Jadi baca ulang dari raw serialisasi objek:
        m_Name     : int32 len + bytes + align(4)
        m_Script   : int32 len + bytes + align(4)
        m_PathName : int32 len + bytes + align(4)
    """
    raw = obj.get_raw_data()

    def read_aligned(b: bytes, off: int) -> tuple[bytes, int]:
        (n,) = struct.unpack_from("<i", b, off)
        off += 4
        chunk = b[off:off + n]
        off += n
        off = (off + 3) & ~3
        return chunk, off

    try:
        _, off = read_aligned(raw, 0)      # m_Name
        script, _ = read_aligned(raw, off)  # m_Script
        return script
    except (struct.error, ValueError):
        # Kalau layout tidak seperti dugaan, jangan kembalikan data rusak.
        raise RuntimeError("gagal membaca byte mentah TextAsset")


def _atlas_page_names(atlas_text: str) -> list[str]:
    """Ambil nama berkas halaman dari baris pertama tiap blok halaman."""
    pages: list[str] = []
    for line in atlas_text.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if not low.endswith(".png"):
            continue
        if any(low.startswith(k) for k in ("size", "format", "filter", "repeat", "pma", "scale")):
            continue
        pages.append(os.path.basename(s))
    return pages


def _save_texture(tex_asset, out_path: str) -> bool:
    try:
        image = tex_asset.image
        if image is None:
            return False
        image.save(out_path)
        return True
    except Exception:
        return False


def export_bundle(bundle_path: str, out_root: str, convert_atlas) -> dict | None:
    name = os.path.basename(bundle_path)
    m = BUNDLE_RE.match(name)
    if m:
        slug = f"{m.group('id')}_{m.group('var')}"
    else:
        g = GENERIC_RE.match(name)
        slug = g.group("stem") if g else os.path.splitext(name)[0]

    try:
        env = UnityPy.load(bundle_path)
    except Exception as exc:
        return {"slug": slug, "status": f"gagal-buka: {exc}"}

    skeletons: list[tuple[str, bytes]] = []
    atlases: list[tuple[str, str]] = []
    textures: dict[str, object] = {}

    for obj in env.objects:
        t = obj.type.name
        if t == "TextAsset":
            try:
                asset = obj.read()
            except Exception:
                continue
            fname = getattr(asset, "m_Name", "") or ""
            low = fname.lower()
            if low.endswith(".skel"):
                try:
                    blob = _textasset_bytes(obj)
                except RuntimeError:
                    continue
                skeletons.append((fname, blob))
            elif low.endswith(".atlas"):
                try:
                    blob = _textasset_bytes(obj)
                except RuntimeError:
                    continue
                atlases.append((fname, blob.decode("utf-8", errors="replace")))
        elif t == "Texture2D":
            try:
                asset = obj.read()
            except Exception:
                continue
            tex_name = getattr(asset, "m_Name", "") or ""
            if not tex_name:
                continue
            # Yang dipakai sebagai halaman atlas biasanya yang bukan avatar/portrait.
            if "avatar" in tex_name.lower():
                continue
            textures[tex_name] = asset

    if not skeletons:
        return {"slug": slug, "status": "tidak-ada-skel"}

    # Satu bundle bisa memuat BEBERAPA model berbeda. Contoh nyata: bundle
    # 1001_3 memuat 1001_3_bishaji, 1003_03, 1003_03_cat, dan 1003_03_huaban.
    # Kalau semuanya ditulis ke satu direktori, server memilih .skel pertama
    # lalu memasangkannya dengan atlas yang salah dan model gagal dimuat
    # ("name cannot be null"). Jadi tiap batang nama (.skel) mendapat
    # direktorinya sendiri, dan atlas dipasangkan berdasarkan batang nama.
    out_root = os.path.join(out_root, slug) if len(skeletons) == 1 else out_root
    os.makedirs(out_root, exist_ok=True)

    written: list[dict] = []
    for skel_name, blob in skeletons:
        stem = os.path.splitext(os.path.basename(skel_name))[0]
        out_dir = os.path.join(out_root, slug if len(skeletons) == 1 else stem)
        os.makedirs(out_dir, exist_ok=True)

        pages_written: list[str] = []
        atlases_written: list[str] = []

        # Atlas yang batang namanya sama dengan .skel ini.
        matching = [
            (an, at) for an, at in atlases
            if os.path.splitext(os.path.basename(an))[0] == stem
        ]
        if not matching:
            # Sebagian bundle menamai atlas sedikit berbeda; ambil yang
            # batang namanya berawalan sama, tapi jangan sampai menyerobot
            # atlas milik model lain.
            matching = [
                (an, at) for an, at in atlases
                if os.path.splitext(os.path.basename(an))[0].startswith(stem)
            ]

        for atlas_name, atlas_text in matching:
            page_names = _atlas_page_names(atlas_text)
            converted = convert_atlas(atlas_text)
            dest = os.path.join(out_dir, os.path.basename(atlas_name))
            with open(dest, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(converted)
            atlases_written.append(os.path.basename(dest))

            for page in page_names:
                page_stem = os.path.splitext(page)[0]
                tex = textures.get(page_stem)
                if tex is None:
                    cand = next((k for k in textures if k == page_stem), None)
                    tex = textures.get(cand) if cand else None
                if tex is None:
                    continue
                if _save_texture(tex, os.path.join(out_dir, page)):
                    pages_written.append(page)

        dest = os.path.join(out_dir, os.path.basename(skel_name))
        with open(dest, "wb") as fh:
            fh.write(blob)

        written.append({
            "slug": slug if len(skeletons) == 1 else stem,
            "status": "ok",
            "skel": [os.path.basename(dest)],
            "atlas": atlases_written,
            "pages": pages_written,
        })

    return written[0] if len(written) == 1 else {"slug": slug, "status": "ok-multi", "models": written}


def export_bundle_single(bundle_path: str, out_root: str, convert_atlas) -> dict | None:
    """Ekspor satu bundle; hasilnya selalu satu dict ringkas (untuk manifest)."""
    res = export_bundle(bundle_path, out_root, convert_atlas)
    if res is None:
        return None
    if res.get("status") == "ok-multi":
        models = res.pop("models")
        return {
            "slug": res["slug"],
            "status": "ok",
            "skel": [s for m in models for s in m["skel"]],
            "atlas": [a for m in models for a in m["atlas"]],
            "pages": [p for m in models for p in m["pages"]],
            "models": [m["slug"] for m in models],
        }
    return res


def iter_bundles(root: str) -> Iterable[str]:
    """Semua berkas .bundle di bawah root.

    Catatan: hasil dekripsi meratakan struktur folder (berkas keluar dengan
    nama dasar saja), jadi filter berdasarkan nama folder tidak bisa dipakai.
    Bundle non-Spine akan tersaring sendiri oleh export_bundle(), yang
    mengembalikan status "tidak-ada-skel" bila tidak menemukan TextAsset
    .skel di dalamnya.
    """
    for dirpath, _, filenames in os.walk(root):
        for fname in sorted(filenames):
            if fname.lower().endswith(".bundle"):
                yield os.path.join(dirpath, fname)


def main() -> int:
    ap = argparse.ArgumentParser(description="Ekspor Spine dari bundle PokerFate terdekripsi")
    ap.add_argument("plain_dir", help="direktori hasil dekripsi")
    ap.add_argument("out_dir", help="direktori keluaran")
    ap.add_argument("--manifest", default=None, help="path manifest JSON (opsional)")
    args = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from convert_atlas import convert as convert_atlas

    os.makedirs(args.out_dir, exist_ok=True)

    results = []
    bundles = list(iter_bundles(args.plain_dir))
    print(f"bundle rolespine ditemukan: {len(bundles)}", flush=True)

    for i, path in enumerate(bundles, 1):
        res = export_bundle_single(path, args.out_dir, convert_atlas)
        if res:
            results.append(res)
            if i % 10 == 0 or i == len(bundles):
                print(f"  {i}/{len(bundles)} {res['slug']} -> {res['status']}", flush=True)

    ok = [r for r in results if r.get("status") == "ok"]
    print(f"\nselesai: {len(ok)} model diekspor, {len(results) - len(ok)} dilewati")

    manifest_path = args.manifest or os.path.join(args.out_dir, "_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
