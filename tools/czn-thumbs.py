#!/usr/bin/env python3
"""Materialise CZN thumbnails + name/thumb maps for the spine-viewer.

Inputs (from the cloned BenNoSleep/czn-animation-viewer):
  czn-repo/thumbs/*.png                 (174 portraits)
  czn-repo/cutins/thumbs/*.png          (951 cut-in thumbs)
  czn-repo/index.json                   (rigs/cutins with slug,name,kind,thumb)

Outputs:
  public/thumbs/czn-rigs/<file>.png            + _manifest.json  (id -> file)
  public/thumbs/czn-cutins-cg/<file>.png       + _manifest.json
  assets/czn-rigs/_names.json                  (slug -> {name,kind,subtype,thumb})
"""
import json, os, shutil, sys

REPO = sys.argv[1] if len(sys.argv) > 1 else "/opt/re-targets/czn-repo"
VIEW = sys.argv[2] if len(sys.argv) > 2 else "/opt/spine-viewer"

repo_thumbs = os.path.join(REPO, "thumbs")
cutin_thumbs = os.path.join(REPO, "cutins", "thumbs")
index = json.load(open(os.path.join(REPO, "index.json"), encoding="utf-8"))

# The name maps live next to the assets; make sure both exist even when the
# viewer tree is fresh (an updater re-run on a partial tree, a test view, …).
os.makedirs(os.path.join(VIEW, "assets", "czn-rigs"), exist_ok=True)
os.makedirs(os.path.join(VIEW, "assets", "czn-cutins-cg"), exist_ok=True)

# ---- czn-rigs: copy repo thumbs, map rig slug -> thumb file ----
t1 = os.path.join(VIEW, "public", "thumbs", "czn-rigs")
os.makedirs(t1, exist_ok=True)
if os.path.isdir(repo_thumbs):
    for f in os.listdir(repo_thumbs):
        if f.lower().endswith(".png"):
            shutil.copy(os.path.join(repo_thumbs, f), os.path.join(t1, f))

names = {}
man1 = {}
for r in index.get("rigs", []):
    slug = r.get("slug") or r.get("id")
    thumb = r.get("thumb") or ""
    base = os.path.basename(thumb)
    names[slug] = {"name": r.get("name"), "kind": r.get("kind"),
                   "subtype": r.get("subtype"), "thumb": base or None}
    if base and os.path.exists(os.path.join(t1, base)):
        man1["czn-rigs/" + slug] = base
json.dump(names, open(os.path.join(VIEW, "assets", "czn-rigs", "_names.json"), "w"),
          ensure_ascii=False, indent=1)
json.dump(man1, open(os.path.join(t1, "_manifest.json"), "w"), ensure_ascii=False, indent=1)

# ---- czn-cutins-cg: copy cut-in thumbs, map gallery id -> thumb file ----
t2 = os.path.join(VIEW, "public", "thumbs", "czn-cutins-cg")
os.makedirs(t2, exist_ok=True)
if os.path.isdir(cutin_thumbs):
    for f in os.listdir(cutin_thumbs):
        if f.lower().endswith(".png"):
            shutil.copy(os.path.join(cutin_thumbs, f), os.path.join(t2, f))
man2 = {}
for c in index.get("cutins", []):
    slug = c.get("slug") or c.get("id")
    base = os.path.basename(c.get("thumb") or "")
    if base and os.path.exists(os.path.join(t2, base)):
        man2["czn-cutins-cg/" + slug] = base
json.dump(man2, open(os.path.join(t2, "_manifest.json"), "w"), ensure_ascii=False, indent=1)

# ---- name maps for the cutin gallery (slug -> name) ----
cutin_names = {c.get("slug") or c.get("id"): {"name": c.get("name"), "kind": c.get("kind")}
               for c in index.get("cutins", [])}
json.dump(cutin_names, open(os.path.join(VIEW, "assets", "czn-cutins-cg", "_names.json"), "w"),
          ensure_ascii=False, indent=1)

print(f"rigs thumbs: {len(os.listdir(t1))-1} files, {len(man1)} manifest entries")
print(f"cutin thumbs: {len(os.listdir(t2))-1} files, {len(man2)} manifest entries")
print(f"rig names: {len(names)}  cutin names: {len(cutin_names)}")
