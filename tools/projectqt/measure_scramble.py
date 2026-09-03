#!/usr/bin/env python3
"""Measure whether Project QT meshes are scrambled, objectively.

Visual reads proved unreliable: the SAME screenshot was judged "clean" in one
pass and "garbled face/chest" in the next. So this measures the thing that
would actually be wrong if a mesh were scrambled — how far each triangle's
UVs drift from its vertices' relative layout.

For a correctly built mesh, neighbouring vertices that are close in model
space are also close in atlas space; the UV triangle keeps roughly the same
shape as the vertex triangle. A scrambled vertex/UV pairing destroys that
relationship, so the per-triangle aspect distortion blows up.

Metric: for every triangle, compare the edge-length ratios in model space
against the same edges in UV space. A faithful mesh keeps them near 1:1
(allowing for uniform scale + the atlas page's aspect). Scrambling makes the
ratios swing wildly.

This is computed ONLY on unweighted attachments, where the stored x/y are
genuine model-space coordinates — weighted ones store per-bone local coords
and would need the full bone transform chain to interpret.
"""
import json
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/root/projectqt-models"


def edge_stats(tri_pts, tri_uvs):
    """max/min ratio of (model edge / uv edge) across the 3 edges."""
    ratios = []
    for i in range(3):
        ax, ay = tri_pts[i]
        bx, by = tri_pts[(i + 1) % 3]
        au, av = tri_uvs[i]
        bu, bv = tri_uvs[(i + 1) % 3]
        mlen = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        ulen = ((bu - au) ** 2 + (bv - av) ** 2) ** 0.5
        if ulen < 1e-9 or mlen < 1e-6:
            continue
        ratios.append(mlen / ulen)
    if not ratios:
        return None
    return max(ratios) / min(ratios)


def main():
    models = sorted(
        d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d)) and not d.startswith("_")
    )
    rows = []

    for m in models:
        d = os.path.join(ROOT, m)
        jf = [f for f in os.listdir(d) if f.endswith(".json") and not f.startswith("_")]
        if not jf:
            continue
        doc = json.load(open(os.path.join(d, jf[0]), encoding="utf-8"))

        ratios = []
        for skin in doc.get("skins", []):
            atts = skin.get("attachments") or {}
            for slot, group in atts.items():
                for key, a in (group or {}).items():
                    if not isinstance(a, dict):
                        continue
                    uvs, verts, tris = a.get("uvs"), a.get("vertices"), a.get("triangles")
                    if not uvs or not verts or not tris:
                        continue
                    n = len(uvs) // 2
                    if len(verts) != 2 * n:
                        continue  # weighted: needs bone transforms, skip
                    pts = [(verts[2 * i], verts[2 * i + 1]) for i in range(n)]
                    uvp = [(uvs[2 * i], uvs[2 * i + 1]) for i in range(n)]
                    for t in range(0, len(tris) - 2, 3):
                        ia, ib, ic = tris[t], tris[t + 1], tris[t + 2]
                        if max(ia, ib, ic) >= n:
                            continue
                        r = edge_stats(
                            [pts[ia], pts[ib], pts[ic]],
                            [uvp[ia], uvp[ib], uvp[ic]],
                        )
                        if r is not None:
                            ratios.append(r)
        if not ratios:
            continue
        ratios.sort()
        rows.append({
            "model": m,
            "n": len(ratios),
            "median": ratios[len(ratios) // 2],
            "p95": ratios[int(len(ratios) * 0.95)],
            "max": ratios[-1],
        })

    rows.sort(key=lambda r: -r["p95"])
    print(f"models with unweighted mesh triangles: {len(rows)}\n")
    print(f"{'model':34} {'tris':>6} {'median':>8} {'p95':>8} {'max':>10}")
    for r in rows[:15]:
        print(f"{r['model'][:34]:34} {r['n']:6} {r['median']:8.2f} {r['p95']:8.2f} {r['max']:10.1f}")

    bad = [r for r in rows if r["p95"] > 6]
    print(f"\nmodels with p95 distortion > 6x: {len(bad)} of {len(rows)}")
    print("\nNOTE: a faithful mesh keeps these ratios near 1 (uniform scale).")


if __name__ == "__main__":
    main()
