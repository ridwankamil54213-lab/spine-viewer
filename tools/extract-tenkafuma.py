#!/usr/bin/env python3
"""Extract Spine models from TenkaFuma (com.pinkcore.tkfm.erolabs) bundles.

Pipeline:
  /sdcard/Android/data/<pkg>/files/data/*.bundle   (7.3 GB, downloaded)
    -> buang 1 byte prefix -> UnityPy -> TextAsset (.skel/.atlas) + Texture2D (.png)

WHY strip 1 byte first:
  Every bundle here starts with a stray byte (0x39 / 0x7b = '{') BEFORE the
  real "UnityFS" magic. UnityPy reads from offset 0, misparses it, and
  returns ZERO objects WITHOUT raising — a silent empty result, not an error.
  Always sanity-check `len(env.objects) > 0` after loading.

WHY get_raw_data() instead of obj.read().m_Script:
  UnityPy decodes TextAsset.m_Script into a `str`, which CORRUPTS binary
  .skel bytes. get_raw_data() returns untouched bytes; we parse Unity's
  TextAsset layout ourselves:
      int32 name_len / char[] name (padded to 4) / int32 size / byte[] data

PERF: never obj.read() a Texture2D during the scan — ranking 2,600 textures
by decoded pixels took >15 min on a smaller game. Read m_Width/m_Height from
the cheap typetree, decode ONLY the pages an atlas actually references.

Families seen: sound* (788, audio), cb* (302, character), cg* (231, CG),
cf*/scg*/ln*/hp* — only some hold skeletons, so scan by CONTENT.

Usage:
  /srv/venv-spine/bin/python tools/extract-tenkafuma.py
"""
import collections
import io
import os
import re
import struct
import sys

import UnityPy

DATA = os.environ.get(
    "DATA",
    "/srv/redroid/data14/media/0/Android/data/com.pinkcore.tkfm.erolabs/files/data",
)
OUT = os.environ.get("OUT", "/srv/spine-assets/tenkafuma")

TEXT_ASSET = 49
TEXTURE2D = 28
SPINE_EXTS = (".skel", ".atlas", ".json")
PREFIX_SKIP = 1          # stray byte before the UnityFS magic


def type_id(obj) -> int:
    t = obj.type
    try:
        v = getattr(t, "value", t)
        if isinstance(v, int):
            return v
        s = str(v)
        return int(s) if s.isdigit() else -1
    except Exception:
        return -1


def safe(name: str) -> str:
    return os.path.basename(str(name)).replace("\\", "/").split("/")[-1].strip()


def parse_text_asset(raw: bytes):
    """Unity TextAsset: int32 name_len, name (4-aligned), int32 size, data."""
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
    """Page filenames declared in .atlas text.

    A bare (unindented) line ending in an image extension names a page.
    A MULTI-PAGE atlas declares several — see the Poker Fate bug: the
    original code `break`ed at the first non-image line, so only page 1 was
    ever extracted. A region name cannot end in an image extension, so
    just skip non-page lines and keep scanning.
    """
    out = []
    try:
        text = blob.decode("utf-8", "replace")
    except Exception:
        return out
    for line in text.splitlines():
        if not line.strip() or line.startswith((" ", "\t")):
            continue
        low = line.strip().lower()
        if low.endswith((".png", ".jpg", ".jpeg", ".webp")):
            out.append(line.strip())
    return out


def declared_sizes(blob: bytes):
    sizes = {}
    try:
        text = blob.decode("utf-8", "replace")
    except Exception:
        return sizes
    lines = text.splitlines()
    for i, line in enumerate(lines):
        low = line.strip().lower()
        if low.endswith((".png", ".jpg", ".jpeg", ".webp")) and not line.startswith((" ", "\t")):
            name = line.strip()
            for j in range(i + 1, min(i + 6, len(lines))):
                s = lines[j].strip().lower()
                if s.startswith("size:"):
                    try:
                        w, h = s[5:].split(",")
                        sizes[name] = (int(w), int(h))
                    except Exception:
                        pass
                    break
    return sizes


def load_bundle(path):
    """Load with the stray prefix removed; return env or None."""
    with open(path, "rb") as fh:
        raw = fh.read()
    for skip in (PREFIX_SKIP, 0):
        try:
            env = UnityPy.load(io.BytesIO(raw[skip:]))
            if len(env.objects) > 0:
                return env
        except Exception:
            continue
    return None


def apply_alpha_mask(dest, fnm, stem_pg, tex_meta, stats):
    """Composite <stem>_alpha into the saved page's alpha channel.

    The colour texture carries no alpha (its alpha channel is flat 255) and
    the "_alpha" twin carries a greyscale mask in RGB (R == G == B). Without
    this, transparent regions render as garbage — red/black/white blocks.
    """
    twin = tex_meta.get(stem_pg + "_alpha") or tex_meta.get(stem_pg + "2_alpha")
    if not twin:
        # Some pages genuinely have no mask (fully opaque art).
        stats["png-tanpa-mask"] += 1
        return
    try:
        from PIL import Image
        rgb = Image.open(os.path.join(dest, fnm)).convert("RGBA")
        msk = twin[1].read().image.convert("RGBA")
        if msk.size != rgb.size:
            msk = msk.resize(rgb.size)
        # The mask lives in R (== G == B); its own alpha channel is flat 255.
        mask = msk.split()[0]
        out = rgb.copy()
        out.putalpha(mask)
        out.save(os.path.join(dest, fnm))
        stats["png-digabung-alpha"] += 1
    except Exception:
        stats["png-gagal-gabung"] += 1


def main():
    if not os.path.isdir(DATA):
        print("ERROR: direktori tidak ada:", DATA)
        return 1
    bundles = sorted(f for f in os.listdir(DATA) if f.endswith(".bundle"))

    # ONLY="<substring>" re-extracts just the matching bundles — used to fix a
    # handful of models without re-scanning all 1,794 (a ~15 min job).
    only = os.environ.get("ONLY")
    if only:
        needles = [s.strip().lower() for s in only.split(",") if s.strip()]
        bundles = [f for f in bundles
                   if any(n in f.lower() for n in needles)]
        print("MODE TERBATAS:", needles)

    print("bundle ditemukan:", len(bundles))

    os.makedirs(OUT, exist_ok=True)
    stats = collections.Counter()
    empty = []

    for idx, fname in enumerate(bundles, 1):
        # Skip the obvious audio families — 788 sound* bundles hold no Spine
        # and scanning them just burns time. Content scan still decides.
        path = os.path.join(DATA, fname)
        env = load_bundle(path)
        if env is None:
            empty.append(fname)
            stats["kosong/gagal"] += 1
            continue

        texts, tex_meta = {}, {}
        for obj in env.objects:
            kind = type_id(obj)
            if kind == TEXT_ASSET:
                try:
                    name, data = parse_text_asset(obj.get_raw_data())
                except Exception:
                    continue
                if not name or not data:
                    continue
                if not name.lower().endswith(SPINE_EXTS):
                    continue
                nm = safe(name)
                if nm not in texts or len(data) > len(texts[nm]):
                    texts[nm] = data
            elif kind == TEXTURE2D:
                try:
                    d = obj.read_typetree()
                    if not d:
                        continue
                    nm = safe(str(d.get("m_Name", "")))
                    if not nm:
                        continue
                    w = int(d.get("m_Width", 0) or 0)
                    h = int(d.get("m_Height", 0) or 0)
                except Exception:
                    continue
                px = w * h
                cur = tex_meta.get(nm)
                if cur is None or px > cur[0]:
                    tex_meta[nm] = (px, obj)
        del env

        skels = [n for n in texts if n.lower().endswith(".skel")]
        atlases = [n for n in texts if n.lower().endswith(".atlas")]
        if not skels or not atlases:
            stats["bukan-spine"] += 1
            continue

        # Pair skeleton -> atlas by EXACT stem only.
        #
        # DO NOT fall back to prefix matching across stems. Bundles here ship
        # several skeletons and atlases whose counts do not match
        # (cg10134 has 4 skeletons but only 3 atlases), and an earlier prefix
        # fallback merged unrelated atlases into one folder: two atlases'
        # regions coexisted under one page set, coordinates collided, and the
        # model rendered scrambled. It also caused "Region not found in atlas".
        #
        # A skeleton with no same-stem atlas gets the atlas with the MOST
        # regions (the most complete), never a merged set.
        def region_count(blob):
            try:
                txt = blob.decode("utf-8", "replace")
            except Exception:
                return 0
            n = 0
            for l in txt.splitlines():
                if not l or l.startswith((" ", "\t")):
                    continue
                s = l.strip()
                if s.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    continue
                if ":" in s:
                    continue
                n += 1
            return n

        atlas_by_stem = {}
        for a in atlases:
            atlas_by_stem.setdefault(a.rsplit(".", 1)[0], []).append(a)

        fallback = max(atlases, key=lambda a: region_count(texts[a])) if atlases else None

        for sk in skels:
            stem = sk.rsplit(".", 1)[0]
            cands = atlas_by_stem.get(stem)
            if not cands:
                # Orphan skeleton: this bundle's skeleton and atlas counts
                # differ, so pair it with the most complete atlas instead of
                # dropping it.
                cands = [fallback] if fallback else []
                stats["atlas-pinjaman"] += 1
            if not cands:
                stats["tanpa-atlas"] += 1
                continue

            dest = os.path.join(OUT, stem)
            os.makedirs(dest, exist_ok=True)
            with open(os.path.join(dest, sk), "wb") as fh:
                fh.write(texts[sk])
            stats[".skel"] += 1

            want = {}
            for a in cands:
                with open(os.path.join(dest, a), "wb") as fh:
                    fh.write(texts[a])
                stats[".atlas"] += 1
                for pg in atlas_pages(texts[a]):
                    want[safe(pg).lower()] = safe(pg)

            # TenkaFuma stores colour and alpha in SEPARATE Texture2Ds:
            #     <page>        -> RGB only, alpha channel is flat 255
            #     <page>_alpha  -> a greyscale mask in RGB (R == G == B), alpha flat 255
            # Exporting the colour texture alone leaves every transparent area
            # filled with garbage pixels, which renders as red/black/white blocks
            # over the model (the "broken face" report).
            #
            # Fix: after writing a page, look for its "_alpha" twin and composite
            # the mask into the saved PNG's alpha channel.
            for key, pg in want.items():
                stem_pg = pg.rsplit(".", 1)[0] if "." in pg else pg
                entry = tex_meta.get(pg) or tex_meta.get(stem_pg)
                if not entry:
                    for tn, tv in tex_meta.items():
                        if tn.lower() == stem_pg.lower():
                            entry = tv
                            break
                if not entry:
                    continue
                fnm = pg if pg.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) else pg + ".png"
                fnm = safe(fnm)
                try:
                    entry[1].read().image.save(os.path.join(dest, fnm))
                    stats["png"] += 1
                    apply_alpha_mask(dest, fnm, stem_pg, tex_meta, stats)
                except Exception:
                    pass
            stats["model"] += 1

        if idx % 100 == 0:
            print(f"  ...{idx}/{len(bundles)} (model {stats['model']})", flush=True)

    print("\n=== hasil ===")
    for k, v in stats.most_common():
        print(f"  {v:6d}  {k}")
    if empty:
        print("bundle kosong/gagal:", len(empty), empty[:5])

    # Verification: declared page size vs real PNG
    def real_size(p):
        try:
            from PIL import Image
            with Image.open(p) as im:
                return im.size
        except Exception:
            pass
        try:
            with open(p, "rb") as f:
                d = f.read(33)
            if d[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", d[16:24])
        except Exception:
            pass
        return None

    bad = []
    for dp, _, fs in os.walk(OUT):
        low = [f.lower() for f in fs]
        if not any(f.endswith(".skel") for f in low):
            continue
        if not any(f.endswith(".atlas") for f in low):
            bad.append((dp, "no atlas"))
            continue
        if not any(f.endswith((".png", ".jpg", ".jpeg", ".webp")) for f in low):
            bad.append((dp, "no png"))
            continue
        for a in [f for f in fs if f.lower().endswith(".atlas")]:
            with open(os.path.join(dp, a), "rb") as fh:
                blob = fh.read()
            for pg, (dw, dh) in declared_sizes(blob).items():
                real = real_size(os.path.join(dp, safe(pg)))
                if not real:
                    bad.append((dp, f"page hilang {pg}"))
                    continue
                rw, rh = real
                rx, ry = dw / rw, dh / rh
                if abs(rx - 1) > 0.01 or abs(ry - 1) > 0.01:
                    kind = "half-res OK" if abs(rx - ry) < 0.02 else "SALAH FILE"
                    bad.append((dp, f"{kind} {pg} {dw}x{dh} vs {rw}x{rh}"))

    print("\n=== verifikasi ===")
    print("folder bermasalah:", len(bad))
    for d, why in bad[:20]:
        print("   ", os.path.basename(d), "->", why)

    total = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fs in os.walk(OUT)
        for f in fs
    )
    print(f"total ukuran: {total/1073741824:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
