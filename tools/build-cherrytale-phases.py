#!/usr/bin/env python3
"""Bangun titik lompat fase H-scene CherryTale.

Sumber: dump/textassets/SecretHCGClickGameScenesData.txt (kolom story,
defaultAnima, clickAnima, feverClickAnima). Scene dicocokkan ke stem kita lewat
prefiks setelah akhiran _hcgN(_M) dibuang.

Keluaran: public/cherrytale-phases.json  { "<model id>": [{label, anim}] }
"""
import json
import os
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ct"
OUT = "/opt/spine-viewer/public/cherrytale-phases.json"
COLS = ((3, "Idle"), (5, "Spasm"), (6, "Insert"), (8, "Thrust"))

scenes = {}
for line in open(os.path.join(SRC, "dump", "textassets", "SecretHCGClickGameScenesData.txt"),
                 encoding="utf-8", errors="ignore"):
    p = line.split("|")
    if len(p) > 10 and p[2] and p[2] != "story":
        scenes.setdefault(p[2].lower(), p)

ids = [m["id"].split("/", 1)[1] for m in json.load(open("/tmp/models.json"))["models"]
       if m["game"] == "cherrytale" and "_hcg" in m["id"]]
anims = {m["id"].split("/", 1)[1]: set(m.get("animations") or [])
         for m in json.load(open("/tmp/models.json"))["models"] if m["game"] == "cherrytale"}


def key(i):
    s = re.sub(r"_spine$", "", re.sub(r"^img_hcg_dynamic_", "", i))
    return re.sub(r"_hcg\d?(_\d)?$", "", s)


out = {}
for mid in ids:
    k = key(mid)
    row = scenes.get(k) or next((v for s, v in scenes.items() if s.startswith(k)), None)
    if not row:
        continue
    seen, phases = set(), []
    for col, _label in COLS:
        anim = row[col].strip()
        if anim and anim != "-1" and anim not in seen and anim in anims.get(mid, ()):
            seen.add(anim)
            phases.append({"label": anim.replace("_", " "), "anim": anim})
    if phases:
        out[f"cherrytale/{mid}"] = phases

json.dump(out, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
print(f"{len(out)} model dengan fase -> {OUT}")
print("contoh:", list(out.items())[:1])
