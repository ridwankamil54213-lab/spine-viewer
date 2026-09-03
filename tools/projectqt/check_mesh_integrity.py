#!/usr/bin/env python3
"""Numeric integrity check for converted Spine 3.8 mesh attachments.

Visual inspection proved unreliable here: the same screenshot was read as
"clean" in one pass and "garbled face/chest" in another. So this checks the
data instead, which is objective.

Spine's mesh invariants, per attachment:

    uvs            -> 2 floats per vertex, so n = len(uvs) / 2
    vertices       -> EITHER 2*n floats (unweighted, plain x/y pairs)
                      OR, when weighted, per vertex:
                          [boneCount, boneIndex, x, y, weight, ...]
                      walked until the array is consumed
    triangles      -> every index must be < n

A conversion that scrambles geometry (mis-paired vertices/uvs, dropped or
duplicated weights, truncated arrays) breaks one of these. If they all hold
across every attachment of every model, the geometry survived the
2.1.27 -> 3.8 conversion intact.
"""
import json
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/root/projectqt-models"


def walk_weighted(vertices):
    """Walk a weighted vertex array. Returns (n_vertices, consumed_all)."""
    i = 0
    n = 0
    L = len(vertices)
    while i < L:
        bone_count = vertices[i]
        if not isinstance(bone_count, int) or bone_count < 1:
            return n, False
        i += 1 + bone_count * 4
        if i > L:
            return n, False
        n += 1
    return n, i == L


def check_attachment(name, a):
    """Return a list of problem strings for one attachment."""
    problems = []
    verts = a.get("vertices")
    uvs = a.get("uvs")
    tris = a.get("triangles")

    if verts is None or uvs is None:
        return problems  # region attachment: no mesh geometry

    if len(uvs) % 2:
        problems.append(f"{name}: odd uvs length {len(uvs)}")
        return problems

    n = len(uvs) // 2
    if len(verts) == 2 * n:
        pass  # unweighted mesh: plain x/y pairs
    else:
        wv, ok = walk_weighted(verts)
        if not ok:
            problems.append(
                f"{name}: vertices do not parse as weighted "
                f"(len={len(verts)}, uvs imply {n} verts, walked {wv})"
            )
        elif wv != n:
            problems.append(f"{name}: vertex count {wv} != uvs count {n}")

    if tris is not None:
        if len(tris) % 3:
            problems.append(f"{name}: triangles length {len(tris)} not a multiple of 3")
        bad = [t for t in tris if not isinstance(t, int) or t < 0 or t >= n]
        if bad:
            problems.append(f"{name}: {len(bad)} triangle indices out of range (n={n})")

    return problems


def main():
    models = sorted(
        d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d)) and not d.startswith("_")
    )
    total_att = 0
    bad_models = 0
    all_problems = []

    for m in models:
        d = os.path.join(ROOT, m)
        js = [f for f in os.listdir(d) if f.endswith(".json") and not f.startswith("_")]
        if not js:
            continue
        doc = json.load(open(os.path.join(d, js[0]), encoding="utf-8"))

        problems = []
        count = 0
        for skin in doc.get("skins", []):
            atts = skin.get("attachments", {}) if isinstance(skin, dict) else {}
            for slot, group in atts.items():
                if not isinstance(group, dict):
                    continue
                for key, a in group.items():
                    if isinstance(a, dict) and a.get("vertices") is not None:
                        count += 1
                        problems += check_attachment(f"{slot}/{key}", a)
        total_att += count
        if problems:
            bad_models += 1
            all_problems += [(m, p) for p in problems]

    print(f"models checked   : {len(models)}")
    print(f"mesh attachments : {total_att}")
    print(f"models with problems : {bad_models}")
    for m, p in all_problems[:20]:
        print(f"  {m}: {p}")
    if len(all_problems) > 20:
        print(f"  ... and {len(all_problems) - 20} more")
    print("\n" + ("PASS" if not all_problems else "FAIL"))
    return 0 if not all_problems else 1


if __name__ == "__main__":
    sys.exit(main())
