"""Rangkum isi 5.825 bundle: hitung TextAsset .skel/.atlas dan Texture2D."""
import os
import collections
import json
import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = '2022.3.62f2'
ROOT = '/opt/arkupd/webgl-all'

files = []
for dp, _, fns in os.walk(ROOT):
    for f in fns:
        if f.endswith('.bundle'):
            files.append(os.path.join(dp, f))
print('bundle di disk:', len(files))

kinds = collections.Counter()
skel_bundles = []
atlas_only = 0
for i, p in enumerate(files):
    try:
        env = UnityPy.load(p)
    except Exception:
        kinds['<gagal-buka>'] += 1
        continue
    has_skel = False
    for o in env.objects:
        t = o.type.name
        if t == 'TextAsset':
            d = o.read()
            nm = (getattr(d, 'm_Name', '') or '').lower()
            if nm.endswith('.skel') or nm.endswith('.skel.bytes'):
                has_skel = True
                kinds['skel'] += 1
            elif nm.endswith('.atlas') or nm.endswith('.atlas.txt'):
                kinds['atlas'] += 1
            else:
                kinds['textasset-lain'] += 1
        elif t == 'Texture2D':
            kinds['texture'] += 1
        elif t == 'AudioClip':
            kinds['audio'] += 1
        elif t == 'Sprite':
            kinds['sprite'] += 1
        else:
            kinds[t] += 1
    if has_skel:
        skel_bundles.append(p)
    if (i + 1) % 500 == 0:
        print(f'  {i+1}/{len(files)} …', flush=True)

print('\njenis objek:')
for k, v in kinds.most_common(15):
    print(f'  {v:7d}  {k}')
print(f'\nbundle berisi .skel: {len(skel_bundles)}')
json.dump(skel_bundles, open('/opt/arkupd/skel-bundles.json', 'w'), indent=1)
