"""Ekstrak semua Spine (394 bundle) + ilustrasi CG dari 5.825 bundle ke viewer."""
import json
import os
import re
import shutil

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = '2022.3.62f2'
SKEL_BUNDLES = json.load(open('/opt/arkupd/skel-bundles.json'))
OUT = '/opt/spine-viewer/assets/arkrecode'
ILLUS = '/opt/spine-viewer/assets/arkrecode-cg'
os.makedirs(OUT, exist_ok=True)
os.makedirs(ILLUS, exist_ok=True)

print(f'bundle berisi skel: {len(SKEL_BUNDLES)}', flush=True)
added, existed, failed = 0, 0, 0
illus_count = 0
report = []

for i, p in enumerate(SKEL_BUNDLES, 1):
    try:
        env = UnityPy.load(p)
    except Exception as e:
        failed += 1
        continue
    texts, texs = {}, {}
    for o in env.objects:
        if o.type.name == 'TextAsset':
            d = o.read()
            nm = getattr(d, 'm_Name', '?')
            dat = getattr(d, 'm_Script', None)
            if isinstance(dat, str):
                try:
                    dat = dat.encode('latin-1')
                except UnicodeEncodeError:
                    dat = dat.encode('utf8', 'surrogateescape')
            texts[nm] = dat
        elif o.type.name == 'Texture2D':
            d = o.read()
            texs[getattr(d, 'm_Name', 'tex')] = d

    skelname = next((n for n in texts if n.lower().endswith('.skel')), None)
    if not skelname:
        continue
    model = re.sub(r'\.skel$', '', skelname, flags=re.I)
    # nama folder unik: kalau model sudah ada, pakai nama induk bundle
    target = os.path.join(OUT, model)
    if os.path.isdir(target):
        existed += 1
        continue
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, f'{model}.skel'), 'wb').write(texts[skelname])
    atlasname = next((n for n in texts if n.lower().endswith('.atlas')), None)
    if not atlasname:
        shutil.rmtree(target, ignore_errors=True)
        continue
    open(os.path.join(target, f'{model}.atlas'), 'wb').write(texts[atlasname])
    pages = re.findall(r'^(\S+\.png)\s*$', texts[atlasname].decode('utf8', 'replace'), re.M)
    ok = False
    for j, (tn, tex) in enumerate(texs.items()):
        try:
            img = tex.image
            fn = pages[j] if j < len(pages) else f'{tn}.png'
            img.save(os.path.join(target, fn))
            ok = True
        except Exception:
            pass
    if not ok:
        shutil.rmtree(target, ignore_errors=True)
        failed += 1
        continue
    added += 1
    report.append(model)
    if i % 40 == 0:
        print(f'  {i}/{len(SKEL_BUNDLES)}  tambah={added} ada={existed} gagal={failed}', flush=True)

print(f'\nSELESAI: tambah={added} sudah-ada={existed} gagal={failed}')
json.dump(report, open('/opt/arkupd/extracted-ark.json', 'w'), indent=1)
