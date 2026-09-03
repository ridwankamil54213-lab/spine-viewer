#!/usr/bin/env python3
"""Verify every converted Project QT model before it reaches the viewer.

Conversion can "succeed" while producing a model that renders wrong, so this
checks the things that break silently:

  - the 3.8 JSON parses and reports Spine 3.8.x
  - every attachment the JSON references exists as a region in the atlas
    (a missing region = an invisible body part)
  - every declared atlas page file is present on disk
  - textures actually decode (a corrupt PNG renders blank)
  - no temp/converted-leftover files are left in the model folder
"""
import json
import os
import sys

from PIL import Image

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/root/projectqt-models"


def atlas_regions(path):
    regions, pages = set(), []
    for line in open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if not s or line[:1].isspace() or ":" in s:
            continue
        if s.lower().endswith((".png", ".webp", ".jpg", ".jpeg")):
            pages.append(s)
        else:
            regions.add(s)
    return regions, pages


def attachment_names(doc):
    """Region names an attachment actually resolves to.

    An attachment's key is the slot name, but the atlas region it loads is
    `path` when present (mesh/skinnedmesh), else the key itself. Comparing
    against the key alone flags perfectly valid models as broken whenever
    the two differ (e.g. slot "Eye_AX/AZ" with path "Eye_AXZ").
    """
    out = set()
    for skin in doc.get("skins", []):
        atts = skin.get("attachments", {}) if isinstance(skin, dict) else {}
        for slot, group in atts.items():
            if not isinstance(group, dict):
                continue
            for key, a in group.items():
                if isinstance(a, dict) and a.get("path"):
                    out.add(a["path"])
                else:
                    out.add(a.get("name") or key if isinstance(a, dict) else key)
    return out


def main():
    models = sorted(d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d)) and not d.startswith("_"))
    bad_att = bad_page = bad_tex = bad_ver = 0
    total_att = 0

    for m in models:
        d = os.path.join(ROOT, m)
        jsons = [f for f in os.listdir(d) if f.endswith(".json") and not f.startswith("_")]
        atlases = [f for f in os.listdir(d) if f.endswith(".atlas")]
        if not jsons or not atlases:
            print(f"  {m}: MISSING json/atlas  ({os.listdir(d)})")
            bad_att += 1
            continue

        j = os.path.join(d, jsons[0])
        a = os.path.join(d, atlases[0])
        try:
            doc = json.load(open(j, encoding="utf-8"))
        except Exception as e:
            print(f"  {m}: JSON PARSE FAIL {e}")
            bad_ver += 1
            continue

        ver = doc.get("skeleton", {}).get("spine", "?")
        if not ver.startswith("3.8"):
            print(f"  {m}: BAD VERSION {ver}")
            bad_ver += 1

        regions, pages = atlas_regions(a)
        atts = attachment_names(doc)
        total_att += len(atts)
        missing = sorted(x for x in atts if x not in regions)
        if missing:
            bad_att += 1
            print(f"  {m}: {len(missing)} attachments not in atlas, e.g. {missing[:3]}")

        for p in pages:
            if not os.path.exists(os.path.join(d, p)):
                bad_page += 1
                print(f"  {m}: MISSING PAGE {p}")
            else:
                try:
                    Image.open(os.path.join(d, p)).verify()
                except Exception as e:
                    bad_tex += 1
                    print(f"  {m}: CORRUPT TEXTURE {p}: {e}")

        # leftovers from the conversion would register as broken models
        leftovers = [f for f in os.listdir(d) if f.startswith("_")]
        if leftovers:
            print(f"  {m}: LEFTOVER TEMPS {leftovers}")

    print(f"\nmodels            : {len(models)}")
    print(f"attachments total : {total_att}")
    print(f"bad version       : {bad_ver}")
    print(f"missing atlas att : {bad_att}")
    print(f"missing pages     : {bad_page}")
    print(f"corrupt textures  : {bad_tex}")
    ok = not (bad_ver or bad_att or bad_page or bad_tex)
    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
