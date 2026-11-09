#!/usr/bin/env python3
"""Bangun data/mitao-names.json dari tabel lokalisasi di bundle iOS.

Sumber (hasil tools/mitao/extract-all.py):
  /srv/spine-assets/mitao/extracted/Assets/Res/Configs/Gen/
    LocalizeConfig_{CN,TW,JP,EN}_Category.json  ->  m_Dict

Kunci `HEROINFO_Name_<id>` berisi nama karakter/monster. Versi EN masih
placeholder (text_en berisi teks Tionghoa / kosong), jadi nama utama diambil
dari JP (nama asli Jepang), fallback TW lalu CN. Ketiga versi tetap disimpan.

Satu id dipakai bersama semua model dengan suffix numerik sama
(front_10001, back_10001, hspecial_10001, ...). Keluaran berupa peta id model
lengkap -> {name, nameCN, nameTW, source}, dibaca applyMitaoNames() di
src/server.js. Idempoten.

Usage:
  /srv/venv-spine/bin/python tools/mitao/refresh-names.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STATE = Path(os.environ.get("MITAO_STATE", "/srv/spine-assets/mitao"))
GEN = STATE / "extracted" / "Assets" / "Res" / "Configs" / "Gen"
ASSETS = ROOT / "assets" / "mitao-utopia"
OUT = ROOT / "data" / "mitao-names.json"

FIELDS = {
    "JP": ("name", "text_jp"),
    "TW": ("nameTW", "text_tw"),
    "CN": ("nameCN", "text_cn"),
}


def num_of(name: str):
    mt = re.search(r"(\d{4,6})$", name)
    return mt.group(1) if mt else None


def main() -> int:
    missing = [f"LocalizeConfig_{k}_Category.json" for k in FIELDS
               if not (GEN / f"LocalizeConfig_{k}_Category.json").is_file()]
    if missing:
        print(json.dumps({"ok": False,
                          "error": f"tabel lokalisasi belum ada: {missing}. "
                                   "Jalankan extract-all.py dulu."}))
        return 1

    tables = {}
    for lang, (key, field) in FIELDS.items():
        d = json.load(open(GEN / f"LocalizeConfig_{lang}_Category.json"))["m_Dict"]
        tables[key] = {
            m.group(1): (v.get(field) or "").strip()
            for k, v in d.items()
            if (m := re.fullmatch(r"HEROINFO_Name_(\d+)", k))
        }

    ids = sorted(set(tables["name"]) | set(tables["nameTW"]) |
                 set(tables["nameCN"]))
    by_id = {}
    for n in ids:
        name = tables["name"].get(n) or tables["nameTW"].get(n) or \
            tables["nameCN"].get(n)
        if not name:
            continue
        by_id[n] = {
            "name": name,
            "nameCN": tables["nameCN"].get(n) or None,
            "nameTW": tables["nameTW"].get(n) or None,
            "source": f"HEROINFO_Name_{n}",
        }

    models = sorted(d.name for d in ASSETS.iterdir() if d.is_dir())
    out = {}
    for model in models:
        rec = by_id.get(num_of(model))
        if rec:
            out[f"mitao-utopia/{model}"] = rec

    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({
        "ok": True,
        "source": str(GEN),
        "tabel": len(ids),
        "id_bernama": len(by_id),
        "model": len(models),
        "model_bernama": len(out),
        "tanpa_nama": len(models) - len(out),
        "bahasa_utama": "JP",
        "out": str(OUT),
        "contoh": {k: out[k] for k in list(out)[:3]},
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
