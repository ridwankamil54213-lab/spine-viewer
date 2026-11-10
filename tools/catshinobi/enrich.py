#!/usr/bin/env python3
"""Bangun thumbnail ilustrasi + family varian untuk model Cat Shinobi.

Semua sumber LOKAL (tanpa jaringan):

  * ``/srv/spine-assets/catshinobi-update/bundles/assets/aa/Android``
    bundle hasil ekstraksi APK oleh ``tools/update-catshinobi.py`` — berisi
    Sprite ilustrasi karakter (``CharThumb_*``, ``CharInfoThumb_*``,
    ``char_*``, ``Icon_Profile_*``), BUKAN halaman atlas Spine.
  * ``data/catshinobi-names.json`` tabel lokalisasi resmi game.
  * ``assets/catshinobi/`` folder model yang sudah terpasang.

Keluaran:

  * ``public/thumbs/catshinobi/<id>.webp`` + ``_manifest.json``
  * ``data/catshinobi-family.json`` (dibaca server untuk picker varian)
  * cache ``/srv/spine-assets/catshinobi-update/sprites/<id>.png`` supaya
    ``--offline`` bisa regenerasi tanpa menyentuh bundle 648 MB lagi.

Jalankan::

    /srv/venv-spine/bin/python tools/catshinobi/enrich.py
    /srv/venv-spine/bin/python tools/catshinobi/enrich.py --offline

Thumb sengaja memakai **ilustrasi karakter**, bukan potongan atlas.
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
from collections import defaultdict

import UnityPy
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.environ.get("CS_WORK", "/srv/spine-assets/catshinobi-update")
BUNDLE_DIR = os.environ.get(
    "CS_BUNDLE_DIR", os.path.join(WORK, "bundles", "assets", "aa", "Android"))
SPRITE_CACHE = os.environ.get("CS_SPRITE_CACHE", os.path.join(WORK, "sprites"))
ASSETS = os.environ.get("CS_ASSETS", os.path.join(ROOT, "assets", "catshinobi"))
NAMES = os.environ.get("CS_NAMES", os.path.join(ROOT, "data", "catshinobi-names.json"))
THUMBS = os.environ.get("CS_THUMBS", os.path.join(ROOT, "public", "thumbs", "catshinobi"))
FAMILY_OUT = os.environ.get("CS_FAMILY", os.path.join(ROOT, "data", "catshinobi-family.json"))

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f2"
NUM = re.compile(r"(\d{3,6})")
SPRITE_NAME = re.compile(
    r"^(CharThumb_|CharInfoThumb_|char_[a-z]|Icon_Profile_|NekoTalk_Portrait)", re.I)
SLUG_BAD = re.compile(r"[^\w.\-/]+")

# form_label() dipakai bersama dengan generator nama supaya label varian
# di picker tidak beda dengan metadata karakter.
_spec = importlib.util.spec_from_file_location(
    "cs_names", os.path.join(ROOT, "tools", "catshinobi-names.py"))
if _spec is None or _spec.loader is None:
    raise RuntimeError("tidak bisa memuat tools/catshinobi-names.py")
_cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cs)
form_label = _cs.form_label


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def numeric(folder):
    m = NUM.search(folder)
    return m.group(1) if m else None


def model_id(folder):
    """Samakan dengan slug id di src/server.js (spasi/tanda baca -> '-')."""
    return "catshinobi/" + SLUG_BAD.sub("-", folder)


def model_folders():
    out = []
    for f in sorted(os.listdir(ASSETS)):
        d = os.path.join(ASSETS, f)
        if not os.path.isdir(d):
            continue
        if not any(x.lower().endswith(".skel") for x in os.listdir(d)):
            continue
        out.append(f)
    return out


def shared_base(n, char_ids):
    """Id karakter dasar untuk id turunan (10003 -> 10001)."""
    for b in sorted(char_ids, key=int):
        if len(b) == len(n) and b != n and b.endswith("01") and b[:3] == n[:3]:
            return b
    return None


def best_sprite_key(name, size):
    """Skor pemilihan ilustrasi: potret/standing lebih diutamakan."""
    w, h = size
    if not w or not h:
        return -1
    ratio = w / h
    if not (0.30 <= ratio <= 1.25) or w < 120 or h < 160:
        return -1
    score = w * h
    if name.startswith(("CharThumb_", "CharInfoThumb_")):
        score += 120_000
    elif name.lower().startswith("char_"):
        score += 60_000
    return score


def collect_sprites(offline):
    """Pilih satu Sprite ilustrasi terbaik per id karakter, simpan PNG cache."""
    os.makedirs(SPRITE_CACHE, exist_ok=True)
    if offline:
        log("mode offline: pakai cache sprite saja")
        return {os.path.splitext(f)[0]: os.path.join(SPRITE_CACHE, f)
                for f in os.listdir(SPRITE_CACHE) if f.endswith(".png")}

    files = sorted(f for f in os.listdir(BUNDLE_DIR) if f.endswith(".bundle"))
    log(f"memindai {len(files)} bundle untuk Sprite ilustrasi…")
    best = {}          # id -> (score, name, bundle, path_id)
    seen = set()
    for bi, fname in enumerate(files, 1):
        try:
            env = UnityPy.load(os.path.join(BUNDLE_DIR, fname))
        except Exception:
            continue
        for obj in env.objects:
            if obj.type.name != "Sprite":
                continue
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            name = str(tree.get("m_Name", ""))
            if not name or not SPRITE_NAME.match(name):
                continue
            n = numeric(name)
            if not n:
                continue
            rect = tree.get("m_Rect") or {}
            try:
                w = float(rect.get("width", 0) or 0)
                h = float(rect.get("height", 0) or 0)
            except (TypeError, ValueError):
                w = h = 0
            score = best_sprite_key(name, (w, h))
            if score < 0:
                continue
            key = (n, name)
            if key in seen:
                continue
            seen.add(key)
            if score > best.get(n, (-1,))[0]:
                best[n] = (score, name, fname, obj.path_id)
        del env
        if bi % 5 == 0:
            log(f"  bundle {bi}/{len(files)} · kandidat {len(best)} id")
    log(f"kandidat sprite: {len(best)} id, mengekstrak…")
    with open(os.path.join(SPRITE_CACHE, "_index.json"), "w", encoding="utf-8") as fh:
        json.dump({n: v[1] for n, v in best.items()}, fh,
                  ensure_ascii=False, indent=1, sort_keys=True)

    # Ekstrak pemenang dikelompokkan per bundle: UnityPy.load() untuk berkas
    # ratusan MB itu mahal, jadi setiap bundle dibuka TEPAT SATU KALI.
    # Versi awal membuka ulang per id (233x) dan kehabisan memori.
    by_bundle = defaultdict(list)
    for n, (_score, name, fname, path_id) in best.items():
        by_bundle[fname].append((n, name, path_id))
    paths = {}
    done = 0
    for fname, items in by_bundle.items():
        try:
            env = UnityPy.load(os.path.join(BUNDLE_DIR, fname))
            index = {o.path_id: o for o in env.objects}
        except Exception as exc:
            log(f"  gagal buka {fname}: {str(exc)[:70]}")
            continue
        for n, name, path_id in items:
            dest = os.path.join(SPRITE_CACHE, f"{n}.png")
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                paths[n] = dest
                done += 1
                continue
            try:
                obj = index.get(path_id)
                if obj is None:
                    continue
                im = obj.read().image
                if not im or im.width < 10 or im.height < 10:
                    continue
                im.save(dest)
                paths[n] = dest
                done += 1
            except Exception as exc:
                log(f"  gagal {n} ({name}): {str(exc)[:70]}")
        del env, index
        log(f"  sprite {done}/{len(best)} · {fname[:40]}")
    return paths


def build_thumbs(paths, folders, char_ids):
    os.makedirs(THUMBS, exist_ok=True)
    manifest = {}
    by_id = defaultdict(list)
    for f in folders:
        n = numeric(f)
        if n:
            by_id[n].append(f)

    # id tanpa sprite langsung memakai ilustrasi karakter dasarnya.
    def sprite_for(n):
        if n in paths:
            return n
        b = shared_base(n, char_ids)
        return b if b and b in paths else None

    written = set()
    for n, group in by_id.items():
        src_id = sprite_for(n)
        if not src_id:
            continue
        out_name = f"{n}.webp"
        dest = os.path.join(THUMBS, out_name)
        if out_name not in written:
            src = paths[src_id]
            # Idempoten: jangan encode ulang kalau WebP sudah lebih baru
            # dari PNG sumber. method=4 jauh lebih cepat dari 6 dengan
            # kualitas yang sama untuk ilustrasi ukuran kartu.
            if not (os.path.exists(dest) and os.path.getsize(dest) > 0
                    and os.path.getmtime(dest) >= os.path.getmtime(src)):
                with Image.open(src) as im:
                    im = im.convert("RGBA")
                    im.thumbnail((240, 360), Image.Resampling.LANCZOS)
                    im.save(dest, "WEBP", quality=82, method=4)
            written.add(out_name)
        for f in group:
            manifest[model_id(f)] = out_name
    return manifest, by_id


def build_families(by_id, names_models, char_ids):
    families = []
    for n, group in sorted(by_id.items(), key=lambda x: (len(x[0]), x[0])):
        if len(group) < 2:
            continue
        ids = [model_id(f) for f in group]
        # Root diutamakan model Battle biasa, lalu LD, lalu sisanya.
        root_i = next((i for i, f in enumerate(group)
                       if re.match(r"^Char_\d", f)), None)
        if root_i is None:
            root_i = next((i for i, f in enumerate(group)
                           if f.startswith("Char_LD_")), 0)
        root = ids[root_i]

        used = defaultdict(int)
        members = []
        for f, mid in zip(group, ids):
            label = form_label(f)
            used[label] += 1
            if used[label] > 1:
                label = f"{label} {used[label]}"
            members.append({"id": mid, "label": label})

        rec = names_models.get(root) or {}
        name = (rec.get("name") or "").strip()
        costume = (rec.get("costume") or "").strip()
        if name:
            fam_name = f"{name} — {costume}" if costume else name
        else:
            # Jangan mengarang nama karakter; pakai penanda id yang jujur.
            base = shared_base(n, char_ids)
            fam_name = f"Set {n}" + (f" ({base})" if base else "")
        families.append({"root": root, "name": fam_name, "members": members})
    return {"families": families}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="jangan baca bundle APK; pakai cache sprite saja")
    args = ap.parse_args()

    raw = json.load(open(NAMES, encoding="utf-8"))
    names_models = raw.get("models", {})
    char_ids = list(raw.get("characters", {}))
    folders = model_folders()
    log(f"{len(folders)} model · {len(names_models)} bernama · {len(char_ids)} karakter")

    paths = collect_sprites(args.offline)
    if not paths:
        raise RuntimeError("tidak ada sprite ilustrasi; jalankan tanpa --offline dulu")
    log(f"{len(paths)} ilustrasi siap")

    manifest, by_id = build_thumbs(paths, folders, char_ids)
    with open(os.path.join(THUMBS, "_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1, sort_keys=True)

    fam = build_families(by_id, names_models, char_ids)
    with open(FAMILY_OUT, "w", encoding="utf-8") as fh:
        json.dump(fam, fh, ensure_ascii=False, indent=1)

    print(json.dumps({
        "ok": True,
        "models": len(folders),
        "named": len(names_models),
        "sprites": len(paths),
        "thumbs": len(set(manifest.values())),
        "thumbKeys": len(manifest),
        "families": len(fam["families"]),
        "familyMembers": sum(len(f["members"]) for f in fam["families"]),
        "thumbsDir": THUMBS,
        "family": FAMILY_OUT,
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
