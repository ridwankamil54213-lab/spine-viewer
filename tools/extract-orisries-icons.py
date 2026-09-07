#!/usr/bin/env python3
"""Buat thumbnail (icon) karakter OrisRies dari bundle cha_cs/cha_pr.

Game ini tidak punya berkas "icon" terpisah — yang dipakai sebagai potret
karakter adalah Texture2D di dalam bundle `cha_cs_*` / `cha_pr_*`. Nama
asetnya (`ar11111_0_0`) memakai id yang SAMA dengan model Spine
(`spinechar_cb1114`, `ar11111`, ...), jadi thumbnail bisa dipetakan ke model
tanpa data tambahan.

Alur:
    1. Kumpulkan semua id model dari folder spine_out (mis. 1114, ar11111).
    2. Untuk tiap bundle cha_cs/cha_pr, baca Texture2D-nya.
    3. Cocokkan nama aset ke id model, lalu simpan PNG berukuran wajar.

Hasilnya ditulis ke public/thumbs/orisries/icons/ beserta _manifest.json
dengan format { "<model_id>": "orisries/icons/<file>.png" } — sama seperti
game lain, jadi server langsung memakainya tanpa perubahan kode.

Pemakaian:
    /srv/venv-spine/bin/python tools/extract-orisries-icons.py
"""
import collections
import io
import os
import sys

import UnityPy
from PIL import Image

UnityPy.config.FALLBACK_UNITY_VERSION = os.environ.get("UNITY_VERSION", "2022.3.32f1")

REPO = "/srv/spine-viewer"
SPINE_OUT = os.environ.get("SPINE_OUT", "/srv/spine-assets/orisries/spine_out")
HOT_DEC = os.environ.get("HOT_DEC", "/srv/spine-assets/orisries/hot_dec")
OUT_DIR = os.path.join(REPO, "public", "thumbs", "orisries", "icons")
MANIFEST = os.path.join(REPO, "public", "thumbs", "orisries", "_manifest.json")
MAX_PX = 256          # thumbnail tidak perlu lebih besar dari ini
TEXTURE2D = "28"


def model_ids() -> set:
    """Id model yang ada di pohon aset, untuk dicocokkan dengan nama tekstur."""
    ids = set()
    if not os.path.isdir(SPINE_OUT):
        return ids
    for name in os.listdir(SPINE_OUT):
        # "ar1142_0" / "cb1114" / "110401" -> kita simpan apa adanya.
        ids.add(name)
        # Juga simpan bagian depan sebelum "_" (ar1142_0 -> ar1142) supaya
        # tekstur ar1142_0_0 bisa cocok dengan model ar1142.
        head = name.split("_")[0]
        if head:
            ids.add(head)
    return ids


def norm(s: str) -> str:
    return s.lower().replace("-", "_")


def pick_best(images: list) -> Image.Image:
    """Ambil tekstur terbesar — bundle bisa berisi beberapa ukuran."""
    return max(images, key=lambda im: im.width * im.height)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    ids = model_ids()
    print(f"model dikenal : {len(ids)}")

    # id -> PIL image terbaik
    best = {}
    stats = collections.Counter()

    files = sorted(
        f for f in os.listdir(HOT_DEC)
        if os.path.isfile(os.path.join(HOT_DEC, f))
        and f.startswith(("cha_cs_", "cha_pr_", "cha_mc_"))
    )
    print(f"bundle potret : {len(files)}")

    for f in files:
        try:
            env = UnityPy.load(os.path.join(HOT_DEC, f))
        except Exception:
            stats["load_fail"] += 1
            continue
        for obj in env.objects:
            if str(obj.type) != TEXTURE2D:
                continue
            try:
                data = obj.read()
                name = getattr(data, "m_Name", "") or ""
                img = data.image
            except Exception:
                stats["decode_fail"] += 1
                continue
            if img is None:
                stats["no_image"] += 1
                continue
            key = norm(name)
            # Cocokkan ke id model: nama tekstur biasanya lebih panjang
            # (ar11111_0_0) daripada id model (ar11111).
            hit = None
            for cand in sorted(ids, key=len, reverse=True):
                if key.startswith(norm(cand)) or norm(cand) in key:
                    hit = cand
                    break
            if not hit:
                stats["no_match"] += 1
                continue
            prev = best.get(hit)
            if prev is None or img.width * img.height > prev.width * prev.height:
                best[hit] = img
                stats["matched"] += 1

    print(f"cocok         : {len(best)} model")

    manifest = {}
    for model_id, img in sorted(best.items()):
        try:
            img = img.convert("RGBA")
            img.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
            fname = f"{model_id}.png"
            img.save(os.path.join(OUT_DIR, fname))
            manifest[f"orisries/{model_id}"] = f"orisries/icons/{fname}"
        except Exception:
            stats["save_fail"] += 1

    with open(MANIFEST, "w", encoding="utf8") as fh:
        import json
        json.dump(manifest, fh, indent=1, ensure_ascii=False)

    print(f"ikon ditulis  : {len(manifest)} -> {OUT_DIR}")
    print(f"manifest      : {MANIFEST}")
    for k, v in stats.most_common():
        print(f"  {k:<16}{v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
