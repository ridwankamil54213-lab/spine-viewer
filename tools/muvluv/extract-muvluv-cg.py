#!/usr/bin/env python3
"""Ekstrak CG / illust マブラヴ ガールズガーデンX (muvluv) dari Addressables.

Model spine ada di `spine_catalog.bin` (sudah diurus tools/muvluv/fetch-extract.py).
Gambar CG/illust TIDAK ada di situ: mereka di `ui_catalog.bin`, satu bundle per
gambar (UnityFS berisi satu Texture2D). Keluarga yang dipakai:

  TMB/    CG karakter          (1920x1080)
  TCBX/   CG H eksplisit       (1920x1080)
  TFB/    CG cerita            (1920x1080)
  TMCB/   CG episode / foto    (1920x1080)
  TMGIB/  ilustrasi mecha/TSF  (1920x1080)
  ICV/    portrait illustrasi  (360x640)

URL bundle: BundleAssets/X/WebGL/ASTC/<hash>.bundle (TANPA 'rlp/'), sama seperti
model spine. Hash bundle diambil dari dependency katalog ('rlp/<hash>.bundle').

Pakai:  /srv/venv-spine/bin/python tools/muvluv/extract-muvluv-cg.py [prefix ...]
"""
import os
import re
import sys
import urllib.request

import AddressablesTools as A
import UnityPy

CATALOG = "/opt/mlv/cat/ui_catalog.bin"
OUT = "/opt/spine-viewer/assets/muvluv-cg"
CACHE = "/opt/mlv/ui_bundles"
BASE = "https://assets.muvluv-girls-garden.com/production-public/a13f7627-175c-4f2a-b6b6-77bef89011ad"
URL = BASE + "/BundleAssets/X/WebGL/ASTC/{h}.bundle"
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

FAMILIES = {
    "TMB": "cg_chara",
    "TCBX": "cg_h",
    "TFB": "cg_story",
    "TMCB": "cg_episode",
    "TMGIB": "cg_mecha",
    "ICV": "illust_portrait",
}


def bundle_hash(loc):
    for d in (getattr(loc, "Dependencies", None) or []):
        m = re.search(r"([0-9a-f]{32})", str(getattr(d, "InternalId", "")))
        if m:
            return m.group(1)
    return None


def fetch(h):
    os.makedirs(CACHE, exist_ok=True)
    fp = os.path.join(CACHE, h + ".bundle")
    if not os.path.exists(fp):
        req = urllib.request.Request(URL.format(h=h), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            open(fp, "wb").write(r.read())
    return fp


def main():
    wanted = sys.argv[1:] or list(FAMILIES)
    cat = A.parse(open(CATALOG, "rb").read())
    os.makedirs(OUT, exist_ok=True)
    total = 0
    for prefix in wanted:
        tag = FAMILIES.get(prefix, prefix.lower())
        keys = [k for k in cat.Resources if k.startswith(prefix + "/")]
        ok = 0
        for k in sorted(keys):
            h = bundle_hash(cat.Resources[k][0])
            if not h:
                continue
            stem = k.split("/", 1)[1]
            try:
                env = UnityPy.load(open(fetch(h), "rb").read())
            except Exception:
                continue
            best = None
            for o in env.objects:
                if o.type.name != "Texture2D":
                    continue
                d = o.read()
                if best is None or d.m_Width * d.m_Height > best[0]:
                    best = (d.m_Width * d.m_Height, d)
            if not best:
                continue
            d = best[1]
            best[1].image.save(os.path.join(OUT, f"{tag}_{stem}.png"))
            ok += 1
        print(f"  {prefix} ({tag}): {ok}/{len(keys)}")
        total += ok
    print(f"SELESAI {total} PNG -> {OUT}")


if __name__ == "__main__":
    main()
