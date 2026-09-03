#!/usr/bin/env python3
"""Rebuild the Brown Dust 2 asset tree into one symlink farm.

Target layout (mirrors Jelosus2/BD2-L2D-Viewer's src/assets/spines/):

    /srv/spine-assets/bd2/
      char/char000101/            <- model (Utama)
      char/char000101/cutscene/   <- variant "Cutscene"
      char/char000502/            <- model
      char/char000502/censored/   <- variant "Censored"
      npc/npc000001/              <- model
      illust/illust_dating/illust_dating1/
      misc/colosseumskip/
      avatar/body/avatarbodyaccessory_1006/

Nothing is moved or copied: every leaf is a symlink to the original file, so
disk usage is unchanged and the original dump stays authoritative.

This is IDEMPOTENT — rerunning it rebuilds the tree from the current source.
"""
import os
import re
import shutil
import sys

SRC = "/srv/spine-assets/bd2-assets/spine"
DST = "/srv/spine-assets/bd2"

CHAR = os.path.join(SRC, "char")
CUT = os.path.join(SRC, "cutscenes")
NPC = os.path.join(SRC, "npc")
ILLUST = os.path.join(SRC, "illust")
MISC = os.path.join(SRC, "misc")
AVATAR = os.path.join(SRC, "avatar")

MODEL_EXT = (".skel", ".json", ".atlas", ".png", ".webp", ".jpg", ".jpeg", ".txt")

stats = {"models": 0, "links": 0, "skipped": 0, "missing": [], "empty": []}


def reset(dst):
    if os.path.isdir(dst) and not os.path.islink(dst):
        shutil.rmtree(dst)
    elif os.path.exists(dst):
        os.remove(dst)


def walk_group(src_dir, dst_dir, label):
    """Recursively mirror a group whose nesting depth varies; any directory
    holding a skeleton+atlas pair becomes a model."""
    found = 0
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        lower = [f.lower() for f in files]
        has_skel = any(f.endswith((".skel", ".json")) for f in lower)
        has_atlas = any(f.endswith((".atlas", ".txt")) for f in lower)
        if not (has_skel and has_atlas):
            continue
        rel = os.path.relpath(root, src_dir)
        target = os.path.join(dst_dir, rel) if rel != "." else dst_dir
        if link_tree(root, target, f"{label}/{rel}"):
            found += 1
    return found


def ensure(path):
    os.makedirs(path, exist_ok=True)


def link_tree(src_dir, dst_dir, label):
    """Symlink every asset file in src_dir (non-recursive) into dst_dir.
    Returns True if at least one skeleton+atlas pair was linked."""
    try:
        names = sorted(os.listdir(src_dir))
    except OSError as e:
        stats["missing"].append(f"{label}: {e}")
        return False

    files = [
        n for n in names
        if n.lower().endswith(MODEL_EXT)
        and os.path.isfile(os.path.join(src_dir, n))
    ]
    if not files:
        # A folder holding only bg/ textures has no skeleton — it was never a
        # model, so count it as empty rather than broken.
        stats["empty"].append(label)
        return False

    ensure(dst_dir)
    for n in files:
        s = os.path.join(src_dir, n)
        d = os.path.join(dst_dir, n)
        if os.path.lexists(d):
            os.remove(d)
        os.symlink(s, d)
        stats["links"] += 1

    has_skel = any(n.lower().endswith((".skel", ".json")) for n in files)
    has_atlas = any(n.lower().endswith((".atlas", ".txt")) for n in files)
    if not (has_skel and has_atlas):
        stats["missing"].append(f"{label}: incomplete (skel={has_skel} atlas={has_atlas})")
        return False
    return True


def main():
    reset(DST)
    ensure(DST)

    chars = sorted(os.listdir(CHAR)) if os.path.isdir(CHAR) else []
    cuts = sorted(os.listdir(CUT)) if os.path.isdir(CUT) else []

    # ---- characters -----------------------------------------------------
    # Censored variants (char000502_c) become "censored/" under their base.
    censored = {c[:-2]: c for c in chars if c.endswith("_c")}
    plain = [c for c in chars if not c.endswith("_c")]

    for c in plain:
        dst = os.path.join(DST, "char", c)
        if link_tree(os.path.join(CHAR, c), dst, f"char/{c}"):
            stats["models"] += 1
        base = os.path.basename(c)
        if base in censored:
            src_c = os.path.join(CHAR, censored[base])
            if os.path.isdir(os.path.join(CHAR, censored[base], )):
                pass
            if link_tree(src_c, os.path.join(dst, "censored"), f"char/{c}/censored"):
                stats["models"] += 1

    # ---- cutscenes nested under their character -------------------------
    # cutscene_char000101 -> char/char000101/cutscene
    # Some source folders hold only bg/ textures and no skeleton — they were
    # never renderable models, so skip them instead of crying about them.
    orphan_cut = []
    empties = []
    for cut in cuts:
        m = re.search(r"char(\d{6})", cut)
        parent = "char" + m.group(1) if m else None
        if parent and parent in plain:
            dst = os.path.join(DST, "char", parent, "cutscene")
            if link_tree(os.path.join(CUT, cut), dst, f"cutscene->{parent}"):
                stats["models"] += 1
            else:
                empties.append(f"{cut} (induk {parent})")
        else:
            orphan_cut.append(cut)

    # Orphans keep their own folder under cutscene/ so nothing is lost.
    for cut in orphan_cut:
        dst = os.path.join(DST, "cutscene", cut)
        if link_tree(os.path.join(CUT, cut), dst, f"cutscene-orphan/{cut}"):
            stats["models"] += 1

    # ---- npc ------------------------------------------------------------
    for n in sorted(os.listdir(NPC)) if os.path.isdir(NPC) else []:
        if not os.path.isdir(os.path.join(NPC, n)):
            continue
        if link_tree(os.path.join(NPC, n), os.path.join(DST, "npc", n), f"npc/{n}"):
            stats["models"] += 1

    # ---- illust --------------------------------------------------------
    # Nesting depth varies: illust_dating/illust_dating1 is one level, but
    # illust/avatar/body/avatarbodyaccessory_1006 is two. Walk recursively and
    # treat any directory holding a skeleton+atlas pair as a model.
    if os.path.isdir(ILLUST):
        for group in sorted(os.listdir(ILLUST)):
            gsrc = os.path.join(ILLUST, group)
            if not os.path.isdir(gsrc):
                continue
            stats["models"] += walk_group(gsrc, os.path.join(DST, "illust", group), f"illust/{group}")

    # ---- misc -----------------------------------------------------------
    if os.path.isdir(MISC):
        for leaf in sorted(os.listdir(MISC)):
            lsrc = os.path.join(MISC, leaf)
            if not os.path.isdir(lsrc):
                continue
            if link_tree(lsrc, os.path.join(DST, "misc", leaf), f"misc/{leaf}"):
                stats["models"] += 1

    # ---- avatar (nested: body/avatarbodyaccessory_1006) -----------------
    if os.path.isdir(AVATAR):
        for group in sorted(os.listdir(AVATAR)):
            gsrc = os.path.join(AVATAR, group)
            if not os.path.isdir(gsrc):
                continue
            for leaf in sorted(os.listdir(gsrc)):
                lsrc = os.path.join(gsrc, leaf)
                if not os.path.isdir(lsrc):
                    continue
                if link_tree(lsrc, os.path.join(DST, "avatar", group, leaf), f"avatar/{group}/{leaf}"):
                    stats["models"] += 1

    print(f"model   : {stats['models']}")
    print(f"symlink : {stats['links']}")
    print(f"masalah : {len(stats['missing'])}")
    for m in stats["missing"][:20]:
        print("   ", m)
    print(f"kosong  : {len(stats['empty'])} (folder tanpa skeleton, dilewati)")
    for m in stats["empty"][:10]:
        print("   ", m)
    return 0 if stats["models"] else 1


if __name__ == "__main__":
    sys.exit(main())
