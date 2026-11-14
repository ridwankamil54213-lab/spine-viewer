#!/usr/bin/env python3
"""Bangun _manifest.json thumbnail CZN untuk game `chaoszero`.

capture-thumbs.cjs menyimpan screenshot kartu wiki sebagai <portraitId>.png
(angka di URL potret, BUKAN id karakter). cards.json berisi pasangan
portraitId -> nama karakter; roster wiki memetakan nama -> charId. Skrip ini
mengganti nama PNG jadi <charId>.png lalu menulis manifest yang memetakan
SETIAP model chaoszero (root maupun varian) ke potret karakternya.

Usage: python3 tools/czn/build-thumb-manifest.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "public" / "thumbs" / "chaoszero"
NAMES = ROOT / "assets" / "chaoszero" / "_names.json"

spec = importlib.util.spec_from_file_location("cznrefresh", ROOT / "tools" / "czn" / "refresh.py")
assert spec is not None and spec.loader is not None, "tools/czn/refresh.py tidak bisa dimuat"
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main() -> None:
    roster = mod.wiki_roster()
    by_name = {str(c.get("name")).strip().lower(): str(k) for k, c in roster.items()}
    cards = json.loads((OUT / "cards.json").read_text(encoding="utf-8"))
    renamed = 0
    for c in cards:
        cid = by_name.get(str(c.get("name")).strip().lower())
        src = OUT / f"{c['id']}.png"
        if not cid or not src.exists():
            print("lewat:", c["id"], c.get("name"))
            continue
        dst = OUT / f"{cid}.png"
        if src != dst:
            src.replace(dst)
            renamed += 1
    names = json.loads(NAMES.read_text(encoding="utf-8"))
    manifest = {
        f"chaoszero/{slug}": f"{rec['charId']}.png"
        for slug, rec in names.items()
        if rec.get("charId") and (OUT / f"{rec['charId']}.png").exists()
    }
    (OUT / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"rename {renamed} PNG | manifest {len(manifest)} model -> {OUT / '_manifest.json'}")


if __name__ == "__main__":
    main()
