"""Ekstrak ilustrasi CG (.png) dari bundle /game/cg/ ke assets/arkrecode-cg."""
import json
import os
import re
import shutil

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = '2022.3.62f2'
ROOT = '/opt/arkupd/webgl-all'
OUT = '/opt/spine-viewer/assets/arkrecode-cg'
os.makedirs(OUT, exist_ok=True)

# bundle di path /game/cg/ atau yang memuat texture besar
files = []
for dp, _, fns in os.walk(ROOT):
    for f in fns:
        if not f.endswith('.bundle'):
            continue
        full = os.path.join(dp, f)
        if '/game/cg/' in full.replace('\\', '/'):
            files.append(full)
print('bundle CG:', len(files), flush=True)

saved = 0
skip = 0
for i, p in enumerate(files, 1):
    # nama unik dari path relatif
    relp = os.path.relpath(p, ROOT).replace('\\', '/')
    # ambil bagian setelah /game/cg/  -> a0001/img_xxx.bundle
    m = re.search(r'/game/cg/(.+?)/', '/' + relp)
    group = m.group(1) if m else 'lain'
    try:
        env = UnityPy.load(p)
    except Exception:
        skip += 1
        continue
    for o in env.objects:
        if o.type.name != 'Texture2D':
            continue
        d = o.read()
        w, h = d.m_Width, d.m_Height
        if w < 256 or h < 256:
            continue
        name = re.sub(r'[^A-Za-z0-9_.-]', '_', getattr(d, 'm_Name', 'tex'))
        ddir = os.path.join(OUT, group)
        os.makedirs(ddir, exist_ok=True)
        target = os.path.join(ddir, f'{name}.png')
        if os.path.exists(target):
            continue
        try:
            d.image.save(target)
            saved += 1
        except Exception:
            pass
    if i % 100 == 0:
        print(f'  {i}/{len(files)}  disimpan={saved}', flush=True)

print(f'\nSELESAI: png disimpan={saved} bundle-dilewati={skip}')
