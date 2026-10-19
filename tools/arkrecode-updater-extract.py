"""Ekstrak 7 bundle Spine Ark Re:Code ke assets/arkrecode-h/."""
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
BASE = 'https://erdpu.gzxhcjz.com/GamePatch/Android/'
CACHE = '/opt/arkupd/bundles'
OUT = '/opt/spine-viewer/assets/arkrecode-h'

cat = json.loads(urllib.request.urlopen(
    urllib.request.Request(BASE + 'catalog_112681.json', headers=UA), timeout=120, context=ctx).read())
bundles = [i for i in cat['m_InternalIds'] if i.endswith('.bundle')]
skelb = [b for b in bundles if 'skeletondata' in b.lower() or '.skel' in b.lower()]

os.makedirs(OUT, exist_ok=True)
report = []
for b in skelb:
    fn = b.rsplit('/', 1)[-1]
    p = os.path.join(CACHE, fn)
    if not os.path.exists(p):
        continue
    env = UnityPy.load(p)
    texts = {}
    texs = {}
    for o in env.objects:
        if o.type.name == 'TextAsset':
            d = o.read()
            nm = getattr(d, 'm_Name', '?')
            dat = getattr(d, 'm_Script', None)
            if dat is None:
                raw = getattr(d, 'script', None)
                dat = raw
            if isinstance(dat, str):
                # UnityPy mendekode .skel biner dengan surrogateescape
                # (0xc8 -> \udcc8). latin-1 memberi pemetaan 1 char = 1 byte,
                # jadi byte aslinya pulih utuh.
                try:
                    dat = dat.encode('latin-1')
                except UnicodeEncodeError:
                    dat = dat.encode('utf8', 'surrogateescape')
            texts[nm] = dat
        elif o.type.name == 'Texture2D':
            d = o.read()
            texs[getattr(d, 'm_Name', 'tex')] = d

    # nama model = dari file .skel
    skelname = next((n for n in texts if n.lower().endswith('.skel')), None)
    if not skelname:
        continue
    model = re.sub(r'\.skel$', '', skelname, flags=re.I)
    d = os.path.join(OUT, model)
    os.makedirs(d, exist_ok=True)

    # simpan skel + atlas
    open(os.path.join(d, f'{model}.skel'), 'wb').write(texts[skelname])
    atlasname = next((n for n in texts if n.lower().endswith('.atlas')), None)
    if atlasname:
        open(os.path.join(d, f'{model}.atlas'), 'wb').write(texts[atlasname])

    # simpan texture dengan nama sesuai atlas
    atlas_txt = texts.get(atlasname, b'').decode('utf8', 'replace') if atlasname else ''
    pages = re.findall(r'^(\S+\.png)\s*$', atlas_txt, re.M)
    saved = []
    for i, (tn, tex) in enumerate(texs.items()):
        try:
            img = tex.image
            target = pages[i] if i < len(pages) else f'{tn}.png'
            img.save(os.path.join(d, target))
            saved.append(target)
        except Exception as e:
            print('  tex gagal', tn, e)

    # baca versi spine dari binary
    ver = '?'
    md = texts[skelname]
    m = re.search(rb'\d+\.\d+\.\d+', md[:300])
    if m:
        ver = m.group(0).decode()
    bones = '?'
    try:
        j = json.loads(md)
        bones = len(j.get('bones', []))
    except Exception:
        pass

    print(f'{model}: skel={len(md)}B atlas={len(texts.get(atlasname, b""))}B '
          f'png={saved} spine={ver} bones(json)={bones}')
    report.append({'model': model, 'spine': ver, 'png': saved, 'bundle': fn})

json.dump(report, open('/opt/arkupd/extracted.json', 'w'), indent=1, ensure_ascii=False)
print('\nselesai:', len(report), 'model')
