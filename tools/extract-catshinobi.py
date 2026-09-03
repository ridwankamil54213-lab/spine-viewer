#!/usr/bin/env python3
"""Extract Spine assets from Cat Shinobi (com.cookapps.catshinobi) Unity bundles.

Pipeline:
    split_UnityDataAssetPack.apk -> assets/aa/Android/*.bundle
        -> UnityPy -> TextAsset (.skel/.atlas) + Texture2D (.png)

WHY get_raw_data() INSTEAD OF obj.read().m_Script:
    UnityPy decodes TextAsset.m_Script into a `str`, which CORRUPTS binary
    .skel (bytes >= 0x80 can't round-trip any text encoding; latin-1 raises
    UnicodeEncodeError). get_raw_data() returns untouched bytes; we parse
    Unity's TextAsset layout ourselves:
        int32 name_len / char[] name (padded to 4) / int32 size / byte[] data

PERF: never obj.read() a Texture2D during the scan.
    Reading all 2628 textures up front costs a full pixel decode per object
    and took >15 min without finishing. Instead read only the m_Width /
    m_Height fields (a cheap typetree read) to rank duplicates, then decode
    ONLY the ~524 pages an atlas actually references.

DUPLICATE TEXTURE RULE (from the Ark Re:Code bug):
    A bundle can hold several Texture2D sharing one name at different
    resolutions. Picking the first saves the small one while the atlas still
    declares the big one's coordinates -> the model renders as scrambled
    shards. Keep the LARGEST (by width*height).

Usage:
    /srv/venv-spine/bin/python tools/extract-catshinobi.py
"""
import collections
import os
import re
import struct
import sys

import UnityPy

BUNDLE_DIR = "/srv/spine-assets/catshinobi-apk/bundles/assets/aa/Android"
OUT = "/srv/spine-assets/catshinobi"

TEXT_ASSET = 49
TEXTURE2D = 28
SPINE_EXTS = (".skel", ".atlas", ".json")


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
    """basename, no path separators, no surrounding whitespace."""
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

    A bare (unindented) line ending in an image extension names a page; the
    first bare line that ISN'T an image ends the page block.
    """
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


def declared_sizes(blob: bytes):
    """Map page name -> declared 'size: W,H' from the atlas text."""
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


def strip_numeric_suffix(stem: str):
    """'B001_1' -> 'B001' so a suffixed atlas still pairs with its skeleton."""
    m = re.match(r"^(.*?)_\d+$", stem)
    return m.group(1) if m else None


def main():
    bundles = sorted(
        f for f in os.listdir(BUNDLE_DIR)
        if f.endswith(".bundle") and "localization" not in f.lower()
    )
    print("bundle diproses:", len(bundles), flush=True)
    for b in bundles:
        print("   ", b)

    os.makedirs(OUT, exist_ok=True)

    texts = {}       # safe(name) -> bytes   (.skel/.atlas)
    tex_objs = {}    # safe(name) -> (px, obj)   LARGEST wins, no decode yet
    stats = collections.Counter()

    # ---------------- Pass A: TextAssets + texture METADATA only ----------------
    for fname in bundles:
        path = os.path.join(BUNDLE_DIR, fname)
        try:
            env = UnityPy.load(path)
        except Exception as e:
            print("GAGAL load %s: %s" % (fname, e))
            continue

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
                # Duplicate TextAsset name: keep the larger payload.
                if nm not in texts or len(data) > len(texts[nm]):
                    texts[nm] = data
            elif kind == TEXTURE2D:
                # Cheap field read -- NOT obj.read(), which decodes pixels.
                try:
                    d = obj.read_typetree() if hasattr(obj, "read_typetree") else None
                    if d is None:
                        continue
                    nm = safe(str(d.get("m_Name", "")))
                    if not nm:
                        continue
                    w = int(d.get("m_Width", 0) or 0)
                    h = int(d.get("m_Height", 0) or 0)
                except Exception:
                    continue
                px = w * h
                cur = tex_objs.get(nm)
                if cur is None or px > cur[0]:
                    tex_objs[nm] = (px, obj)

        stats["bundle"] += 1
        print("  scan %s: texts=%d tex=%d" % (fname, len(texts), len(tex_objs)), flush=True)
        del env

    skels = sorted(n for n in texts if n.lower().endswith(".skel"))
    atlases = sorted(n for n in texts if n.lower().endswith(".atlas"))
    print("\nskel:", len(skels), " atlas:", len(atlases), " texture:", len(tex_objs), flush=True)

    # ---------------- Pair skeletons to atlases ----------------
    atlas_by_stem = {}
    for a in atlases:
        stem = a.rsplit(".", 1)[0]
        atlas_by_stem.setdefault(stem, []).append(a)
        base = strip_numeric_suffix(stem)
        if base and base != stem:
            atlas_by_stem.setdefault(base, []).append(a)

    written = 0
    missing_atlas, missing_png = [], []

    for sk in skels:
        stem = sk.rsplit(".", 1)[0]
        cands = atlas_by_stem.get(stem)
        if not cands:
            base = strip_numeric_suffix(stem)
            if base:
                cands = atlas_by_stem.get(base)
        if not cands:
            missing_atlas.append(stem)
            cands = []

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
            fnm = safe(fnm)
            try:
                img = entry[1].read().image          # decode ONLY needed pages
                img.save(os.path.join(dest, fnm))
                stats["png"] += 1
                got += 1
            except Exception as e:
                print("   gagal simpan %s/%s: %s" % (stem, fnm, e), flush=True)

        if not got:
            missing_png.append(stem)
        written += 1
        if written % 50 == 0:
            print("  ...%d/%d model" % (written, len(skels)), flush=True)

    print("\n=== hasil ===")
    for k, v in stats.most_common():
        print("   %6d  %s" % (v, k))
    print("\nmodel ditulis:", written)
    print("tanpa atlas  :", len(missing_atlas), missing_atlas[:10])
    print("tanpa png    :", len(missing_png), missing_png[:10])

    # ---------------- Verification: declared page size vs real PNG ----------------
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
                    bad.append((dp, "page hilang %s" % pg))
                    continue
                rw, rh = real
                rx, ry = dw / rw, dh / rh
                if abs(rx - 1) > 0.01 or abs(ry - 1) > 0.01:
                    kind = "half-res OK" if abs(rx - ry) < 0.02 else "SALAH FILE"
                    bad.append((dp, "%s %s declared %dx%d real %dx%d" % (kind, pg, dw, dh, rw, rh)))

    print("\n=== verifikasi ===")
    print("folder bermasalah:", len(bad))
    for d, why in bad[:25]:
        print("   ", os.path.basename(d), "->", why)

    messy = []
    for dp, dns, fs in os.walk(OUT):
        for d in dns:
            if d != d.strip():
                messy.append(("dir", os.path.join(dp, d)))
        for f in fs:
            if f != f.strip():
                messy.append(("file", os.path.join(dp, f)))
    print("nama mengandung spasi:", len(messy), messy[:10])

    total = sum(
        os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs
    )
    print("total ukuran: %.2f GB" % (total / 1024 ** 3))


if __name__ == "__main__":
    sys.exit(main())
