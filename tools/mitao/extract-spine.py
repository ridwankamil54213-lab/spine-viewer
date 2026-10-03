#!/usr/bin/env python3
"""Extract Spine skeletons from 蜜桃乌托邦 (Peach Utopia) AssetBundles.

Each bundle that carries a Spine set holds:

    TextAsset  "<id>.skel"   binary skeleton (Spine 4.2.x)
    TextAsset  "<id>.atlas"  atlas descriptor
    Texture2D  "<id>"        atlas page image

IMPORTANT 1 — never key the output on the numeric id alone.
One character has MANY different skeletons, one per bundle variant
(`..._rawdata_spine_back_10001`, `..._front_10001`, `..._equip_10001`, ...),
and each carries a *different* .skel (verified: 9 bundles for id 10001 all have
distinct hashes). Keying on the id silently collapsed them (9 bundles ->
1 model = data loss). The output key is therefore `<variant>_<title>`.

IMPORTANT 2 — never trust the bundle NAME.
Skeletons do not only live in `rawdata_spine_*` (227 bundles). They also hide in
`prefabs_spine_mesh_skill_*` (18), `prefabs_spine_mesh_avg_*` (4) and
`prefabs_spine_ui_cutin_*` (1) — 23 more models, including the whole "skill"
set that a name filter misses entirely. So the default glob is ALL bundles and
the caller decides from the CONTENTS: a bundle is a skeleton iff it has both a
.skel and a .atlas.

A bundle may also hold several skeletons; each one gets its own folder.

Usage:
    extract-spine.py --bundles bundles --out /opt/spine-viewer/assets --game mitao-utopia
"""
import argparse
import collections
import glob
import io
import os
import re
import warnings

import UnityPy

warnings.filterwarnings("ignore")

# ..._rawdata_spine_<variant>_<id>.bundle
# ..._prefabs_spine_(mesh|ui)_<variant>_<id>.bundle
NAME_RES = [
    re.compile(r"rawdata_spine_(?P<variant>.+?)_(?P<id>\d+)(?:\.bundle)?$"),
    re.compile(r"prefabs_spine_(?:mesh|ui)_(?P<variant>.+?)_(?P<id>\d+)(?:\.bundle)?$"),
]


def slug(s):
    s = re.sub(r"[^A-Za-z0-9._\-]+", "-", str(s)).strip("-")
    return s or "model"


def get_text(d):
    data = getattr(d, "m_Script", None)
    if data is None:
        data = getattr(d, "script", None)
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    return data


def variant_of(bundle_path):
    """`..._rawdata_spine_back_10001.bundle` -> ('back', '10001').

    Falls back to the bundle stem when the name does not match a known pattern,
    so an unexpected bundle still gets a unique (not empty) folder key.
    """
    base = os.path.basename(bundle_path)
    for rx in NAME_RES:
        m = rx.search(base)
        if m:
            return m.group("variant"), m.group("id")
    stem = base.replace(".bundle", "").replace("share_", "").replace("assets_res_", "")
    return slug(stem), ""


def process(path, out_root, game):
    """Return (models_written, files_written, note)."""
    variant, bundle_id = variant_of(path)

    env = UnityPy.load(path)
    texts, tex = [], []
    for o in env.objects:
        try:
            if o.type.name == "TextAsset":
                d = o.read()
                texts.append((getattr(d, "m_Name", "") or "", get_text(d)))
            elif o.type.name == "Texture2D":
                d = o.read()
                tex.append((getattr(d, "m_Name", "") or "", d))
        except Exception:
            continue

    if not texts:
        return 0, 0, "no TextAsset"

    # Split TextAssets into skeletons and atlases.
    skels, atlases = [], []
    for name, data in texts:
        low = name.lower()
        if low.endswith(".skel") or low.endswith(".json"):
            skels.append((name, data))
        elif low.endswith(".atlas") or low.endswith(".atlas.txt"):
            atlases.append((name, data))

    def stem(n):
        return os.path.splitext(n)[0]

    # 1) Pair by shared base name (the usual case, and the only correct way
    #    when one bundle holds several skeletons).
    by_skel = {}
    by_atlas = {}
    for n, d in skels:
        by_skel.setdefault(stem(n), (n, d))
    for n, d in atlases:
        by_atlas.setdefault(stem(n), (n, d))

    pairs = []  # (title, skel(name,data), atlas(name,data))
    for s in list(by_skel):
        if s in by_atlas:
            pairs.append((s, by_skel.pop(s), by_atlas.pop(s)))

    # 2) A lone skeleton + lone atlas with mismatched names still belong
    #    together (e.g. avg_10019: "10019_xixuegui_Front.skel" + "10019.atlas").
    #    The ATLAS owns the page name, so title the pair after the atlas and
    #    write the skeleton under that stem — the viewer pairs by stem.
    if len(by_skel) == 1 and len(by_atlas) == 1:
        a_name, a_data = next(iter(by_atlas.values()))
        pairs.append((stem(a_name), next(iter(by_skel.values())), (a_name, a_data)))

    models = files = 0
    for title_raw, (skel_name, skel_data), (atlas_name, atlas_data) in pairs:
        title = slug(title_raw)
        # The variant distinguishes otherwise identical model ids.
        key = slug(f"{variant}_{title}")
        mdir = os.path.join(out_root, game, key)
        os.makedirs(mdir, exist_ok=True)

        ext = ".json" if skel_name.lower().endswith(".json") else ".skel"
        open(os.path.join(mdir, f"{title}{ext}"), "wb").write(skel_data)
        open(os.path.join(mdir, f"{title}.atlas"), "wb").write(atlas_data)
        files += 2

        # The atlas text names its page; use that exact name so the viewer can
        # resolve it. Falls back to "<title>.png".
        page_name = f"{title}.png"
        try:
            txt = atlas_data.decode("utf-8", "replace") if isinstance(atlas_data, bytes) else str(atlas_data)
            for line in txt.splitlines():
                s = line.strip()
                if re.search(r"\.(png|jpe?g|webp)$", s, re.I) and " " not in s:
                    page_name = s
                    break
        except Exception:
            pass
        page_stem = os.path.splitext(page_name)[0]

        # Prefer the Texture2D that matches the page name, then the title, then
        # the sole texture (a bundle may also carry skill backgrounds/shadows).
        page = None
        for want in (page_name, page_stem, title):
            for tname, timg in tex:
                if tname == want:
                    page = timg
                    break
            if page is not None:
                break
        if page is None:
            for tname, timg in tex:
                if tname.startswith(title) or tname.startswith(page_stem):
                    page = timg
                    break
        if page is None and tex:
            page = tex[0][1]

        if page is not None:
            try:
                img = page.image
                if img is not None:
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    open(os.path.join(mdir, page_name), "wb").write(buf.getvalue())
                    files += 1
            except Exception as e:
                return models, files, f"texture failed for {title}: {e}"
        models += 1
    return models, files, "" if models else "no .skel+.atlas pair"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles", default="bundles")
    ap.add_argument("--out", required=True, help="assets root (game subdir is appended)")
    ap.add_argument("--game", default="mitao-utopia")
    ap.add_argument("--glob", default="*.bundle",
                    help="bundle glob; default scans ALL bundles because "
                         "skeletons hide outside rawdata_spine_* (a name filter "
                         "loses the 23 prefabs_spine_* models)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.bundles, args.glob)))
    if args.limit:
        files = files[:args.limit]
    out_dir = os.path.join(args.out, args.game)
    print(f"bundle : {len(files)}")
    print(f"output : {out_dir}\n")

    tot_m = tot_f = 0
    notes = []
    for i, f in enumerate(files, 1):
        try:
            m, n, note = process(f, args.out, args.game)
            tot_m += m
            tot_f += n
            # "no TextAsset" is the normal case for non-skeleton bundles; only
            # report the surprising failures.
            if note and note != "no TextAsset":
                notes.append((os.path.basename(f), note))
        except Exception as e:
            notes.append((os.path.basename(f), str(e)))
        if i % 100 == 0 or i == len(files):
            print(f"[{i}/{len(files)}] model={tot_m} file={tot_f} catatan={len(notes)}")

    print(f"\nSELESAI model={tot_m} file={tot_f}  ->  {out_dir}")
    if notes:
        print(f"\ncatatan ({len(notes)}):")
        for n, e in notes[:15]:
            print(f"  {n}: {e[:90]}")


if __name__ == "__main__":
    main()
