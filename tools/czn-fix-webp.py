#!/usr/bin/env python3
"""Fix texture page names in assets/czn-rigs.

The repo atlas declares the page by its original name (e.g. `1001001.webp`),
but the first transform wrote `<slug>.webp` (e.g. `model_1001001.webp`), so the
viewer could not resolve the page. Rename each texture to the name the atlas
actually references.
"""
import os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/opt/spine-viewer/assets/czn-rigs"
IMG = re.compile(r"\.(png|webp|jpg|jpeg)$", re.I)

fixed = skipped = 0
for slug in sorted(os.listdir(ROOT)):
    d = os.path.join(ROOT, slug)
    if not os.path.isdir(d):
        continue
    at = os.path.join(d, slug + ".atlas")
    if not os.path.exists(at):
        continue
    lines = open(at, encoding="latin1").read().splitlines()
    pages = [ln.strip() for i, ln in enumerate(lines)
             if i + 1 < len(lines) and re.match(r"\s*size:", lines[i + 1]) and IMG.search(ln.strip())]
    if not pages:
        continue
    page = pages[0]
    imgs = [f for f in os.listdir(d) if IMG.search(f)]
    if page in imgs:
        skipped += 1
        continue
    if not imgs:
        continue
    src = os.path.join(d, imgs[0])
    dst = os.path.join(d, page)
    os.rename(src, dst)
    fixed += 1
print(f"renamed {fixed}, already-correct {skipped}")
