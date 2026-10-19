"""Unduh 7 bundle H-scene dari catalog WebGL baru (catalog_115700)."""
import json
import os
import re
import ssl
import urllib.request

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = '2022.3.62f2'
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0'}
CAT = 'https://erdpu.gzxhcjz.com/GamePatch/WebGL/catalog_115700.json'
BASE = 'https://erdpu.gzxhcjz.com/GamePatch/WebGL/'
OUT = '/opt/spine-viewer/assets/arkrecode-h'
CACHE = '/opt/arkupd/webgl'

os.makedirs(CACHE, exist_ok=True)

cat = json.loads(urllib.request.urlopen(
    urllib.request.Request(CAT, headers=UA), timeout=180, context=ctx).read())
bundles = [i for i in cat['m_InternalIds'] if i.endswith('.bundle')]
skelb = [b for b in bundles if 'skeletondata' in b.lower() or '.skel' in b.lower()]
print('bundle skel WebGL:', len(skelb))

for b in skelb:
    fn = b.rsplit('/', 1)[-1]
    p = os.path.join(CACHE, fn)
    if not os.path.exists(p):
        data = urllib.request.urlopen(
            urllib.request.Request(BASE + fn, headers=UA), timeout=180, context=ctx).read()
        open(p, 'wb').write(data)
    env = UnityPy.load(p)
    texts = {}
    texs = {}
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
    d = os.path.join(OUT, model)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, f'{model}.skel'), 'wb').write(texts[skelname])
    atlasname = next((n for n in texts if n.lower().endswith('.atlas')), None)
    if atlasname:
        open(os.path.join(d, f'{model}.atlas'), 'wb').write(texts[atlasname])
    atlas_txt = texts.get(atlasname, b'').decode('utf8', 'replace')
    pages = re.findall(r'^(\S+\.png)\s*$', atlas_txt, re.M)
    saved = []
    for i, (tn, tex) in enumerate(texs.items()):
        img = tex.image
        target = pages[i] if i < len(pages) else f'{tn}.png'
        img.save(os.path.join(d, target))
        saved.append(f'{target} {os.path.getsize(os.path.join(d,target)):,}B')
    print(f'{model}: skel={len(texts[skelname]):,}B atlas={len(texts.get(atlasname,b"")):,}B png={saved}')
