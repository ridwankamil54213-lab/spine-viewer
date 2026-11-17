#!/usr/bin/env python3
"""Impor metadata hero dari https://epic7db.com/heroes.

e7codex.com sudah memberi rarity (bintang), elemen, dan class, tetapi tidak
punya zodiac/status effect. Epic7DB menyediakan keduanya sebagai atribut
`<li class="hero" data-name=... data-class=... data-element=... data-stars=...
data-zodiac=... data-statusEffects=...>`.

Hasil: data/epic7db-heroes.json dipakai server untuk menempelkan field
`e7Zodiac` dan `e7Effects` ke model Epic Seven. Pencocokan memakai
`hero_name` + `name` + `slug` dari assets/epic7/_names.json.

Usage:
  python3 tools/import-epic7db-heroes.py
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from pathlib import Path

VIEW = Path(__file__).resolve().parents[1]
PAGE = "https://epic7db.com/heroes"
OUT = VIEW / "data" / "epic7db-heroes.json"
NAMES = VIEW / "assets" / "epic7" / "_names.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    req = urllib.request.Request(PAGE, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r:
        page = r.read().decode("utf-8", "replace")
    heroes = []
    for raw in re.findall(r'<li class="hero"\s+([^>]*)>', page):
        a = dict(re.findall(r'data-([a-zA-Z]+)="([^"]*)"', raw))
        if not a.get("name"):
            continue
        effects = [x.strip() for x in (a.get("statusEffects") or "").split(",") if x.strip()]
        heroes.append({
            "name": html.unescape(a["name"]),
            "class": a.get("class"),
            "element": a.get("element"),
            "stars": int(a["stars"]) if str(a.get("stars", "")).isdigit() else None,
            "zodiac": a.get("zodiac"),
            "effects": effects,
        })
    if len(heroes) < 300:
        raise RuntimeError(f"hero Epic7DB terlalu sedikit: {len(heroes)}")

    names = json.loads(NAMES.read_text(encoding="utf-8"))
    by_name = {}
    for h in heroes:
        for key in (h["name"],):
            by_name[norm(key)] = h

    matched: dict[str, dict] = {}
    unmatched = []
    for cid, rec in names.items():
        candidates = [rec.get("name"), rec.get("hero"), rec.get("slug")]
        hit = None
        for c in candidates:
            if c and norm(c) in by_name:
                hit = by_name[norm(c)]
                break
        if not hit:
            unmatched.append(cid)
            continue
        matched[cid] = {
            "name": hit["name"],
            "zodiac": hit["zodiac"],
            "effects": hit["effects"],
            "stars": hit["stars"],
            "element": hit["element"],
            "class": hit["class"],
        }

    OUT.write_text(json.dumps({
        "source": PAGE,
        "fetchedAt": int(time.time()),
        "heroes": len(heroes),
        "models": len(matched),
        "byModel": matched,
        "unmatched": unmatched[:50],
    }, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "heroes": len(heroes),
        "matchedModels": len(matched),
        "unmatched": len(unmatched),
        "zodiac": len({v["zodiac"] for v in matched.values() if v.get("zodiac")}),
        "effects": len({e for v in matched.values() for e in v.get("effects", [])}),
    }, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
