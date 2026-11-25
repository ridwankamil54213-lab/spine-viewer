#!/usr/bin/env python3
"""Bangun nama + thumbnail CherryTale dari dump CherryTale_Standalone.

Nama TIDAK diambil dari characters_index.json — registry itu salah untuk ~60
kode (a001 dilabeli Gretel padahal RoleInfoData menautkan a001 ke Milian).
Sumber yang dipakai:

  dump/metadata_summary.json            nama EN + title per kode (dari RoleInfoData)
  dump/textassets/RoleInfoData.txt      pemilik token <kode>_<nn>, untuk varian
                                        yang ternyata karakter lain (a001_03 = Gretel)
  dump/textassets/LanguageSettings_enus.txt  zh -> EN
  viewer/thumbs/*.webp                  thumbnail

Keluaran: data/cherrytale-names.json + public/thumbs/cherrytale/{,_manifest.json}
"""
import collections
import json
import os
import re
import shutil
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ct"
DST = "/opt/spine-viewer"
NAMES = os.path.join(DST, "data", "cherrytale-names.json")
THUMBS = os.path.join(DST, "public", "thumbs", "cherrytale")

meta = json.load(open(os.path.join(SRC, "dump", "metadata_summary.json")))["characters"]
# Cadangan untuk kode yang tidak ada di metadata_summary (cq*, ct*, story_*).
idx = json.load(open(os.path.join(SRC, "dump", "characters_index.json")))
ids = [m["id"].split("/", 1)[1] for m in json.load(open("/tmp/models.json"))["models"]
       if m["game"] == "cherrytale"]
text = os.path.join(SRC, "dump", "textassets")


def stem(i):
    return re.sub(r"_spine$", "", re.sub(r"^img_(cg|hcg)_dynamic_", "", i))


def norm(s):
    return re.sub(r"_spine$", "", s.lower())


trans = {}
for line in open(os.path.join(text, "LanguageSettings_enus.txt"), encoding="utf-8", errors="ignore"):
    line = line.rstrip("\n┤")
    if "|" in line:
        k, v = line.split("|", 1)
        if k and v and "<" not in k:
            trans.setdefault(k.strip(), v.strip())

role_zh, own = {}, collections.defaultdict(set)
for line in open(os.path.join(text, "RoleInfoData.txt"), encoding="utf-8", errors="ignore"):
    p = line.split("|")
    if len(p) > 2 and p[1] not in ("NULL", "null"):
        role_zh[p[0]] = p[1].strip()
    for tok in re.findall(r"\b([a-z]\d{3}_\d{2})_(?:Icon|CG)", line):
        own[tok].add(p[0])


def en_of(role):
    return trans.get(role_zh.get(role, ""))


thumb_dir = os.path.join(SRC, "viewer", "thumbs")
thumbs = sorted(((norm(os.path.splitext(f)[0]), f) for f in os.listdir(thumb_dir)),
                key=lambda p: -len(p[0]))

os.makedirs(THUMBS, exist_ok=True)
names, manifest = {}, {}
for mid in ids:
    s = stem(mid)
    n = norm(s)
    code, tok = s.split("_")[0], "_".join(s.split("_")[:2])
    rec = meta.get(code) or {}
    label = rec.get("name_en") or (idx.get(code) or {}).get("name_en")
    # Varian yang jelas milik karakter lain: semua role pemilik token sepakat
    # pada satu nama yang berbeda dari nama kode.
    alt = {en_of(r) for r in own.get(tok, ())} - {None}
    if len(alt) == 1 and list(alt)[0] != label:
        label = list(alt)[0]
        rec = {}
    if label:
        kind = "HCG" if "hcg" in mid.lower() else "CG"
        seq = next((t for t in reversed(n.split("_")) if t.isdigit()), "")
        sub = rec.get("title_en")
        name = f"{label} — {sub}" if sub else label
        names[mid] = {"name": f"{name} · {kind} {seq}".strip(),
                      "character": label, "kind": kind}
    else:
        # Tak ada di kedua katalog (anniversary / event / UI): judul-kan stem.
        words = [w for w in re.split(r"[_]+", n) if w and w not in ("cg", "hcg", "spine")]
        label = " ".join(w[:1].upper() + w[1:] for w in words)
        if label:
            kind = "HCG" if "hcg" in mid.lower() else "CG"
            names[mid] = {"name": label, "character": label, "kind": kind}
    src = next((f for key, f in thumbs if n.startswith(key)), None)
    if src:
        out = re.sub(r"[^a-z0-9_.-]", "_", mid.lower()) + ".webp"
        shutil.copy2(os.path.join(thumb_dir, src), os.path.join(THUMBS, out))
        manifest[f"cherrytale/{mid}"] = f"cherrytale/{out}"

json.dump(names, open(NAMES, "w"), ensure_ascii=False, indent=1)
json.dump(manifest, open(os.path.join(THUMBS, "_manifest.json"), "w"),
          ensure_ascii=False, indent=1)
print(f"nama: {len(names)}/{len(ids)} | thumb: {len(manifest)}/{len(ids)}")
