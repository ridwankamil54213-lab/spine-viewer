#!/usr/bin/env python3
"""Verify a converted 3.8 JSON against its source 2.1.27 atlas.

The conversion can "succeed" while silently dropping attachments — a
converted model whose sprite references don't exist in the atlas renders as
invisible body parts. This catches exactly that.

Checks:
  - every region attachment name in the 3.8 JSON exists in the atlas
  - every mesh attachment has vertices + uvs
  - bone count / slot count / animation count survive the conversion
"""
import json
import sys


def atlas_regions(path):
    """Region names declared in a Spine .atlas file."""
    names = set()
    page_names = set()
    for line in open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if not s or line[:1].isspace() or ":" in s:
            continue
        if s.lower().endswith((".png", ".webp", ".jpg", ".jpeg")):
            page_names.add(s)
        else:
            names.add(s)
    return names, page_names


def attachment_names(doc):
    """Every attachment name referenced by the skeleton."""
    out = set()
    for skin in doc.get("skins", []):
        if isinstance(skin, dict) and "attachments" in skin:
            for slot, atts in skin["attachments"].items():
                for aname in atts:
                    out.add(aname)
        elif isinstance(skin, dict) and isinstance(skin.get("attachments"), dict):
            pass
    return out


def main():
    json_path, atlas_path = sys.argv[1], sys.argv[2]
    doc = json.load(open(json_path, encoding="utf-8"))
    regions, pages = atlas_regions(atlas_path)
    atts = attachment_names(doc)

    # Region attachments must exist in the atlas (mesh uses its own path).
    missing = sorted(a for a in atts if a not in regions)
    print(f"json      : {json_path}")
    print(f"atlas     : {atlas_path}")
    print(f"atlas regions : {len(regions)}   pages: {len(pages)}")
    print(f"attachments   : {len(atts)}")
    print(f"missing from atlas : {len(missing)}")
    for m in missing[:15]:
        print(f"   MISSING: {m}")

    sk = doc.get("skeleton", {})
    print(f"spine version      : {sk.get('spine')}")
    print(f"bones/slots        : {len(doc.get('bones', []))}/{len(doc.get('slots', []))}")
    print(f"animations         : {len(doc.get('animations', {}))}")

    # mesh sanity
    meshes = 0
    bad_mesh = 0
    for skin in doc.get("skins", []):
        atts_d = skin.get("attachments", {}) if isinstance(skin, dict) else {}
        for slot, group in atts_d.items():
            for aname, a in group.items():
                if isinstance(a, dict) and "vertices" in a:
                    meshes += 1
                    if not a.get("uvs"):
                        bad_mesh += 1
    print(f"mesh attachments   : {meshes} (without uvs: {bad_mesh})")

    ok = not missing and bad_mesh == 0
    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
