#!/usr/bin/env python3
"""Ekstrak model Spine dari bundle Haze Reverb (com.tingzhou.cwcxtw.qooapp).

Game Unity + IL2CPP + YooAsset. Bundle ada di
    /sdcard/Android/data/<pkg>/files/yoo/ResPackage/CacheFiles/<2hex>/<hash>/__data

Alur sebelum script ini:
  1. tools/hazereverb-find.sh  -> grep binary ".skel" di perangkat, 300/4.004 bundle
  2. tools/hazereverb-pull.sh  -> tarik __data ke /srv/spine-assets/hazereverb-raw

Perbedaan dengan TenkaFuma — PENTING:
  - Bundle UnityFS murni. TIDAK ada byte aneh di awal, jadi tidak perlu
    mencoba skip=1 (TenkaFuma punya 1 byte sampah sebelum magic UnityFS
    dan UnityPy diam-diam mengembalikan 0 object).
  - TIDAK ada texture `_alpha` terpisah. Diverifikasi dengan
    tools/hazereverb-probe.py: semua texture sudah membawa alpha sendiri
    (mis. lihui_aertaiya_dz: 54.9% piksel benar-benar transparan).
    Jadi tidak perlu composite mask seperti TenkaFuma.

Penamaan aset:
  dongzuo_juese_<nama>.skel   karakter (动作角色 = "karakter aksi")
  lihui_<nama>_dz.skel        ilustrasi / CG (立绘)
Satu bundle bisa berisi beberapa skeleton + atlas, jadi pairing harus
hati-hati (lihat aturan pairing di bawah).

Pemakaian:
    python3 tools/extract-hazereverb.py
    ONLY=aertaiya python3 tools/extract-hazereverb.py   # hanya yang cocok
"""
import collections
import io
import os
import struct
import sys

import UnityPy

DATA = os.environ.get("DATA", "/srv/spine-assets/hazereverb-raw")
OUT = os.environ.get("OUT", "/srv/spine-assets/hazereverb")

SKEL_EXT = (".skel", ".json")
ATLAS_EXT = (".atlas", ".atlas.txt")


def type_id(obj) -> int:
    t = getattr(obj, "type", None)
    return getattr(t, "value", t) if t is not None else -1


def safe(name: str) -> str:
    """Bersihkan nama file; pertahankan karakter non-ASCII (nama Cina)."""
    out = []
    for ch in name:
        out.append(ch if (ch.isalnum() or ch in "._-") else "_")
    return "".join(out).strip("._") or "unnamed"


def parse_text_asset(raw: bytes):
    """Unity TextAsset: int32 name_len, name (padding 4), int32 size, data.

    JANGAN pakai obj.read().m_Script — ia mengembalikan str dan merusak
    data biner .skel (tidak ada encoding yang round-trip).
    """
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


def atlas_pages(blob: bytes):
    """Ambil nama halaman (file PNG) yang dideklarasikan atlas."""
    try:
        text = blob.decode("utf-8", "replace")
    except Exception:
        return []
    pages, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip().rstrip("\r")
        if not s:
            continue
        low = s.lower()
        if low.endswith((".png", ".jpg", ".jpeg", ".webp")):
            # Baris halaman tidak ber-indentasi; region di bawahnya ber-indentasi.
            if line[:1] not in (" ", "\t"):
                pages.append(s)
    return pages


def load_bundle(path):
    """Haze Reverb: UnityFS murni, tanpa byte sampah di awal."""
    with open(path, "rb") as fh:
        raw = fh.read()
    # Coba langsung; kalau gagal, coba skip 1 byte (berjaga-jaga bila
    # sebagian bundle ternyata mengikuti pola TenkaFuma).
    for skip in (0, 1):
        try:
            env = UnityPy.load(io.BytesIO(raw[skip:]))
            if len(env.objects) > 0:
                return env, skip
        except Exception:
            continue
    return None, None


def pick_texture(stem, tex_meta, seen):
    """Pilih Texture2D untuk satu halaman atlas.

    Aturan (dipelajari dari TenkaFuma, jangan dilonggarkan):
      1. stem PERSIS. `dongzuo_juese_aertaiya` dan `dongzuo_juese_aertaiya_a`
         berbeda — mencocokkan awalan akan menukar texture dan menghasilkan
         region acak / "Region not found".
      2. Baru kalau tidak ada yang persis, lewati (lebih baik tidak ada
         texture daripada salah).
    """
    if stem in tex_meta:
        return tex_meta[stem]
    low = stem.lower()
    for name, entry in tex_meta.items():
        if name.lower() == low:
            return entry
    return None


def main():
    if not os.path.isdir(DATA):
        print("ERROR: direktori tidak ada:", DATA)
        return 1

    # Kumpulkan semua __data
    bundles = []
    for dirpath, _dirnames, filenames in os.walk(DATA):
        if "__data" in filenames:
            bundles.append(os.path.join(dirpath, "__data"))
    bundles.sort()

    only = os.environ.get("ONLY")
    if only:
        needles = [s.strip().lower() for s in only.split(",") if s.strip()]
        bundles = [b for b in bundles
                   if any(n in b.lower() for n in needles)]
        print("MODE TERBATAS:", needles)

    print("bundle ditemukan:", len(bundles))
    os.makedirs(OUT, exist_ok=True)
    stats = collections.Counter()
    failed = []

    for idx, path in enumerate(bundles, 1):
        env, skip = load_bundle(path)
        if env is None:
            failed.append(path)
            stats["kosong/gagal"] += 1
            continue
        if skip:
            stats["pakai-skip-1"] += 1

        # Kumpulkan TextAsset (skeleton/atlas) dan Texture2D
        texts = {}
        tex_meta = {}
        for obj in env.objects:
            k = type_id(obj)
            if k == 49:  # TextAsset
                nm, data = parse_text_asset(obj.get_raw_data())
                if nm and data is not None:
                    texts[nm] = data
            elif k == 28:  # Texture2D
                # JANGAN obj.read() di sini — hanya baca nama.
                try:
                    dd = obj.read_typetree()
                    nm = str(dd.get("m_Name", "") or "")
                    if nm:
                        tex_meta[nm] = (nm, obj)
                except Exception:
                    pass

        skeletons = {n: d for n, d in texts.items()
                     if n.lower().endswith(SKEL_EXT)}
        atlases = {n: d for n, d in texts.items()
                   if n.lower().endswith(ATLAS_EXT)}
        if not skeletons or not atlases:
            stats["bukan-spine"] += 1
            continue

        # Pasangkan skeleton -> atlas lewat stem yang sama
        pairs = []
        for sname in sorted(skeletons):
            stem = sname.rsplit(".", 1)[0]
            aname = None
            for cand in (stem + ".atlas", stem + ".atlas.txt"):
                if cand in atlases:
                    aname = cand
                    break
            if aname is None:
                # Tidak ada atlas se-stem: pakai atlas di bundle yang sama
                # kalau cuma satu (lebih baik daripada diam-diam kosong).
                if len(atlases) == 1:
                    aname = next(iter(atlases))
                    stats["atlas-pinjaman"] += 1
                else:
                    stats["skeleton-tanpa-atlas"] += 1
                    continue
            pairs.append((stem, sname, aname))

        for stem, sname, aname in pairs:
            dest = os.path.join(OUT, safe(stem))
            os.makedirs(dest, exist_ok=True)

            # tulis skeleton
            with open(os.path.join(dest, safe(sname)), "wb") as fh:
                fh.write(skeletons[sname])
            stats[".skel"] += 1

            # tulis atlas
            with open(os.path.join(dest, safe(aname)), "wb") as fh:
                fh.write(atlases[aname])
            stats[".atlas"] += 1

            # tulis halaman texture atlas
            used = set()
            for pg in atlas_pages(atlases[aname]):
                pstem = pg.rsplit(".", 1)[0]
                entry = pick_texture(pstem, tex_meta, used)
                if not entry:
                    stats["halaman-tanpa-texture"] += 1
                    continue
                used.add(entry[0])
                fnm = safe(entry[0] + ".png")
                try:
                    img = entry[1].read().image
                    img.save(os.path.join(dest, fnm))
                    stats["png"] += 1
                except Exception:
                    stats["png-gagal"] += 1

            stats["model"] += 1

        if idx % 50 == 0:
            print(f"  ...{idx}/{len(bundles)} (model {stats['model']})", flush=True)

    print("\n=== hasil ===")
    for k, v in sorted(stats.items()):
        print(f"{v:8d}  {k}")

    if failed:
        print(f"\ngagal dimuat: {len(failed)}")
        for f in failed[:5]:
            print("   ", f)

    # Verifikasi: folder tanpa skeleton atau tanpa atlas
    print("\n=== verifikasi ===")
    bad = 0
    if os.path.isdir(OUT):
        for d in sorted(os.listdir(OUT)):
            p = os.path.join(OUT, d)
            if not os.path.isdir(p):
                continue
            files = os.listdir(p)
            has_s = any(f.lower().endswith(SKEL_EXT) for f in files)
            has_a = any(f.lower().endswith(ATLAS_EXT) for f in files)
            has_p = any(f.lower().endswith(".png") for f in files)
            if not (has_s and has_a and has_p):
                bad += 1
                if bad <= 10:
                    print(f"   {d}: skel={has_s} atlas={has_a} png={has_p}")
    print("folder tidak lengkap:", bad)
    print("keluaran:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
