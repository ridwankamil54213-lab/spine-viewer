#!/usr/bin/env python3
"""Extract Spine assets from Lost Sword Unity Addressable bundles.

Pipeline:
    XAPK -> UnityStreamingAssetsPack.apk -> assets/aa/Android/*.bundle
         -> UnityPy get_raw_data() -> TextAsset (.skel/.atlas) + Texture2D (.png)

WHY get_raw_data() INSTEAD OF obj.read():
    For these bundles UnityPy decodes TextAsset.m_Script into a `str`, which
    corrupts the binary .skel (bytes >= 0x80 can't round-trip through any text
    encoding — latin-1 raises UnicodeEncodeError). get_raw_data() returns the
    untouched bytes; we then parse Unity's TextAsset layout ourselves:

        int32  name_len
        char[] name            (padded to 4)
        int32  data_len
        byte[] data

Texture2D still goes through obj.read() -> .image (Pillow), which is fine
because image pixels aren't binary-opaque in the same way.

Run with the venv that has UnityPy + Pillow:
    /root/venv-ls/bin/python /root/extract-lostsword.py
"""
import collections
import os
import struct
import sys

import UnityPy

BUNDLE_DIR = "/root/ls-apk/bundles/assets/aa/Android"
OUT = "/root/lostsword-apk"

# Unity class IDs (stable across versions)
TEXT_ASSET = 49
TEXTURE2D = 28
SPINE_EXTS = (".skel", ".atlas", ".json")


def type_id(obj) -> int:
    """Numeric Unity class id (ClassIDType enum | int | numeric str)."""
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
        name = raw[4 : 4 + n].decode("utf-8", "replace")
        pos = 4 + n
        pos += (4 - (pos % 4)) % 4  # pad to 4-byte boundary
        size = struct.unpack("<i", raw[pos : pos + 4])[0]
        if not (0 <= size <= len(raw) - pos - 4):
            return name, None
        return name, raw[pos + 4 : pos + 4 + size]
    except Exception:
        return None, None


def derive_group(fname: str) -> str:
    base = os.path.basename(fname).lower()
    if "lobbyunit" in base:
        return "lobbyunit"
    if "prefabs_pet" in base or "_pet_" in base:
        return "pet"
    if "prefabs_unit" in base or "prefabs/" in base:
        return "unit"
    if "atlas" in base:
        return "atlas"
    return "lainnya"


def main():
    bundles = sorted(f for f in os.listdir(BUNDLE_DIR) if f.endswith(".bundle"))
    print("bundle ditemukan:", len(bundles))

    os.makedirs(OUT, exist_ok=True)
    stats = collections.Counter()
    failures = []
    used = set()

    for idx, fname in enumerate(bundles, 1):
        path = os.path.join(BUNDLE_DIR, fname)
        try:
            env = UnityPy.load(path)
        except Exception as e:
            failures.append((fname, "load: %s" % e))
            continue

        texts, imgs = [], []
        for obj in env.objects:
            kind = type_id(obj)
            if kind == TEXT_ASSET:
                try:
                    name, data = parse_text_asset(obj.get_raw_data())
                    if name and data and name.lower().endswith(SPINE_EXTS):
                        texts.append((safe(name), data))
                except Exception:
                    continue
            elif kind == TEXTURE2D:
                try:
                    d = obj.read()
                    nm = getattr(d, "m_Name", None) or getattr(d, "name", "") or ""
                    imgs.append((safe(nm), d.image))
                except Exception:
                    continue

        skel = [(n, b) for n, b in texts if n.lower().endswith(".skel")]
        atlas = [(n, b) for n, b in texts if n.lower().endswith(".atlas")]
        if not skel or not atlas:
            stats["bukan-spine"] += 1
            continue

        stem = skel[0][0].rsplit(".", 1)[0]
        group = derive_group(fname)
        dest = os.path.join(OUT, group, stem)
        # characters can repeat across groups; never overwrite a sibling
        n = 1
        while dest.lower() in used:
            n += 1
            dest = os.path.join(OUT, group, "%s_%d" % (stem, n))
        used.add(dest.lower())
        os.makedirs(dest, exist_ok=True)

        for nm, blob in skel + atlas:
            with open(os.path.join(dest, nm), "wb") as fh:
                fh.write(blob)
            stats[".skel" if nm.lower().endswith(".skel") else ".atlas"] += 1

        # Match textures against the pages the atlas declares. Atlas says
        # "Agravaine.png" but the Texture2D's m_Name is "Agravaine" (no
        # extension), so compare stems.
        refs = referenced_pages(atlas)
        ref_stems = {r.rsplit(".", 1)[0] for r in refs}
        for nm, im in imgs:
            stem = nm.rsplit(".", 1)[0] if "." in nm else nm
            if refs and stem.lower() not in ref_stems:
                continue
            fnm = nm if nm.lower().endswith(".png") else nm + ".png"
            try:
                im.save(os.path.join(dest, fnm))
                stats["png"] += 1
            except Exception:
                pass

        stats["model"] += 1
        if idx % 50 == 0:
            print("  ...%d/%d (model %d)" % (idx, len(bundles), stats["model"]), flush=True)

    print("\n=== hasil ===")
    for k, v in stats.most_common():
        print("   %5d  %s" % (v, k))
    print("\nbundle gagal:", len(failures))
    for f, why in failures[:8]:
        print("   ", f, "->", why)

    bad = []
    for dp, _, fs in os.walk(OUT):
        low = [f.lower() for f in fs]
        if not any(f.endswith(".skel") for f in low):
            continue
        if not any(f.endswith(".atlas") for f in low):
            bad.append((dp, "no atlas"))
        elif not any(f.endswith(".png") for f in low):
            bad.append((dp, "no png"))
    print("\nfolder model valid:", stats["model"] - len({d for d, _ in bad}))
    if bad:
        print("folder bermasalah:", len(bad))
        for d, why in bad[:10]:
            print("   ", d, "->", why)

    total = sum(
        os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs
    )
    print("total ukuran: %.2f GB" % (total / 1024**3))


def referenced_pages(atlas_list):
    """Page filenames declared in the atlas text (first bare line of each page)."""
    out = set()
    for _, blob in atlas_list:
        try:
            text = blob.decode("utf-8", "replace")
        except Exception:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            if line.startswith(" "):
                continue
            if line.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                out.add(line.strip().lower())
            else:
                break  # first non-image bare line = start of regions
    return out


if __name__ == "__main__":
    sys.exit(main())
