#!/usr/bin/env python3
"""Relayout Brown Dust 2 assets into a per-character tree.

Structure produced (three levels):

    <Karakter>/<Costume>/<Jenis>/

e.g. Justia/Blood_Glutton/Karakter/char000203.skel
     Justia/Blood_Glutton/Skill Cutscene/cutscene_char000203.skel
     Justia/Blood_Glutton/Interaction/illust_dating3.skel

The character/costume pair comes from the Zormolo/Brown-Dust-2-Assets
repo, which is the only source that maps an opaque asset id (char000203)
onto a character AND a costume. The character/costume NAMES shown in the
UI still come from data/bd2-names.json, which already covers 395 assets.

WHY FILES ARE COPIED INTO THE COSTUME FOLDER
--------------------------------------------
The viewer only builds a "family" (main model + variant dropdown) when the
parent folder is itself a model -- see rootOf() in src/server.js, which
requires `ids.has(parent)`. If the layout were
`Justia/Blood_Glutton/Karakter/...`, then `Justia` and `Justia/Blood_Glutton`
would hold no .skel of their own, no parent id would resolve, and every
model would render as an unrelated top-level entry.

So the character model is placed directly in the costume folder, making
that folder the family root; each variant type becomes a subfolder under
it. Same trick the existing Nikke layout relies on (c010/ holds c010_00.skel
and also c010/aim/).

Symlinks are used rather than copies: the collection is several GB and the
source tree stays authoritative.

Usage:
    python3 tools/relayout-bd2.py            # write into assets/bd2-char/
    python3 tools/relayout-bd2.py --dry-run  # print the plan only
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REF = Path("/srv/bd2ref/assets/spine")
OWN = Path("/srv/spine-assets/bd2")
NAMES = REPO / "data" / "bd2-names.json"
DEST = REPO / "assets" / "bd2-char"

# Categories in the reference repo, most specific first. An asset id can
# appear in more than one; the first match wins.
CATEGORIES = [
    "character",
    "skill_cutscene",
    "interaction",
    "light_novel_talk",
    "npc",
    "miscellaneous",
    "special_animation",
]

# How each category is labelled in the viewer's variant dropdown.
JENIS = {
    "character": "Karakter",
    "skill_cutscene": "Skill Cutscene",
    "interaction": "Interaction",
    "light_novel_talk": "Light Novel Talk",
    "npc": "NPC",
    "miscellaneous": "Lainnya",
    "special_animation": "Special Animation",
    "censored": "Tersensor",
}


def build_reference_map():
    """asset id -> (category, character, costume) from the reference repo."""
    ref = {}
    for cat in CATEGORIES:
        d = REF / cat
        if not d.exists():
            continue
        for skel in d.rglob("*.skel"):
            parts = skel.relative_to(d).parts
            ch = parts[0] if len(parts) >= 2 else None
            co = parts[1] if len(parts) >= 3 else None
            # First (most specific) category wins.
            if skel.stem not in ref:
                ref[skel.stem] = (cat, ch, co)
    return ref


def model_dirs():
    """Every directory under the BD2 tree that holds a .skel, with its files."""
    out = []
    for skel in sorted(OWN.rglob("*.skel")):
        out.append(skel.parent)
    return out


def asset_key(d: Path):
    """Asset id for a model folder, folding cutscene/censored onto the parent.

    Mirrors bd2AssetKey() in src/server.js so the relayout and the name
    lookup agree on what an asset is called.
    """
    name = d.name
    if name in ("cutscene", "censored"):
        return d.parent.name
    return name


def variant_of(d: Path):
    """Which variant a folder holds, or None for the main model.

    A nested `cutscene`/`censored` folder holds the SAME asset as its
    parent but a different variant. Without this, char000101/ and
    char000101/cutscene/ both resolved to the character slot and the
    second one silently overwrote the first.
    """
    name = d.name.lower()
    if name == "cutscene":
        return "skill_cutscene"
    if name == "censored":
        return "censored"
    return None


# Label for the extra variants that live in nested folders, and for the
# "_c" (censored) asset suffix some standalone folders carry.
VARIANT_LABEL = {
    "censored": "Tersensor",
}


def slug(s: str) -> str:
    """Filesystem-safe folder name."""
    return re.sub(r"[^\w.\-]+", "-", s).strip("-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dest", default=str(DEST))
    args = ap.parse_args()

    dest = Path(args.dest)
    ref = build_reference_map()
    names = json.loads(NAMES.read_text()) if NAMES.exists() else {}

    dirs = model_dirs()
    print(f"folder model ditemukan : {len(dirs)}")
    print(f"kamus referensi        : {len(ref)} id")
    print(f"kamus nama             : {len(names)} entri")

    planned = []
    unmapped = []
    seen = set()          # (char, costume, jenis) -> guard against collisions
    for d in dirs:
        key = asset_key(d)
        hit = ref.get(key)
        if not hit:
            # Retry with the skeleton stem -- a folder can hold several
            # models (multi-stem), and the stem is the true asset id.
            stems = {s.stem for s in d.glob("*.skel")}
            for st in sorted(stems):
                if st in ref:
                    hit = ref[st]
                    key = st
                    break
        # A bare *_c folder is the censored twin of the asset without the
        # suffix. It has no entry of its own in the reference repo.
        nested = variant_of(d)
        if not hit and nested and key.endswith("_c"):
            hit = ref.get(key[:-2])
            if hit:
                cat, ch, co = hit
                hit = ("censored", ch, co)
        if not hit:
            unmapped.append((key, str(d.relative_to(OWN))))
            continue
        cat, ch, co = hit
        # A nested cutscene/censored folder overrides the category with its
        # own variant, so it lands beside the main model instead of on top
        # of it.
        if nested:
            cat = nested
        if not ch:
            unmapped.append((key, str(d.relative_to(OWN))))
            continue
        jenis = JENIS.get(cat, cat)
        slot = (ch, co or "", jenis)
        if slot in seen:
            # Two source folders claim one destination (a leftover duplicate
            # tree such as avatar/ vs illust/avatar/). Keep the first.
            continue
        seen.add(slot)
        planned.append({
            "src": d,
            "key": key,
            "cat": cat,
            "char": ch,
            "costume": co,
        })

    print(f"terpetakan             : {len(planned)}")
    print(f"tak terpetakan         : {len(unmapped)}")

    if args.dry_run:
        print("\n=== contoh rencana ===")
        for p in planned[:15]:
            co = p["costume"] or "-"
            j = "" if p["cat"] == "character" else "/" + JENIS.get(p["cat"], p["cat"])
            print(f"  {p['char']}/{co}{j}  <- {p['src'].relative_to(OWN)}")
        print("\n=== tak terpetakan ===")
        for k, rel in unmapped:
            print(f"  {k}  ({rel})")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    made = 0
    skipped = 0
    for p in planned:
        co = p["costume"]
        parts = [slug(p["char"])]
        if co:
            parts.append(slug(co))
        cat = p["cat"]
        # The MAIN model (character) goes DIRECTLY in the costume folder, not
        # in a "Karakter" subfolder of it. rootOf() in src/server.js only
        # groups a variant under a parent when that parent is itself a model
        # (`ids.has(parent)`), so the costume folder must hold a .skel for
        # the cutscene/interaction variants to attach to it. Putting the main
        # model in <costume>/Karakter/ would leave <costume>/ empty, no parent
        # id would resolve, and every variant would render as an unrelated
        # top-level entry.
        if cat != "character":
            parts.append(slug(JENIS.get(cat, cat)))
        target = dest.joinpath(*parts)
        # Skip junk folders: a directory literally named "*.atlas" holds no
        # skeleton of its own and would produce an empty model entry.
        if not any(f.suffix.lower() == ".skel" for f in p["src"].iterdir() if f.is_file()):
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"  GAGAL mkdir {target}: {e}")
            skipped += 1
            continue
        for f in sorted(p["src"].iterdir()):
            if not f.is_file():
                continue
            link = target / f.name
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(f)
                made += 1
            except OSError as e:
                print(f"  GAGAL link {link}: {e}")
                skipped += 1

    print(f"\nsymlink dibuat : {made}")
    print(f"dilewati       : {skipped}")

    # Record what could not be mapped so it can be revisited later.
    report = REPO / "data" / "bd2-unmapped.json"
    report.write_text(json.dumps(
        [{"key": k, "path": r} for k, r in sorted(unmapped)], indent=1, ensure_ascii=False
    ))
    print(f"laporan        : {report.relative_to(REPO)} ({len(unmapped)} entri)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
