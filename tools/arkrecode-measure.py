"""Ukur ukuran total dengan PATH LENGKAP (bukan cuma nama file)."""
import json
import re
import ssl
import urllib.request
import concurrent.futures as cf
from collections import defaultdict

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0'}
ROOT = 'https://erdpu.gzxhcjz.com/GamePatch/'

cat = json.loads(urllib.request.urlopen(
    urllib.request.Request(ROOT + 'WebGL/catalog_115700.json', headers=UA), timeout=180, context=ctx).read())
bundles = [i for i in cat['m_InternalIds'] if i.endswith('.bundle')]
print('bundle:', len(bundles))


def rel(i):
    m = re.match(r'https?://[^/]+/(.*)$', i)
    return m.group(1) if m else i


def cat_of(r):
    low = r.lower()
    if 'skeletondata' in low or '.skel' in low:
        return 'spine'
    if '/game/cg/' in low:
        return 'ilustrasi-cg'
    if '/hero/h' in low:
        return 'hero-h-scene'
    if '/bg/' in low:
        return 'background'
    if '/sound/' in low or '/audio/' in low:
        return 'audio'
    if 'spine' in low:
        return 'spine-lain'
    if 'effect' in low:
        return 'effect'
    if 'img' in low:
        return 'image-lain'
    return 'other'


def head(i):
    r = rel(i)
    for _ in range(2):
        try:
            req = urllib.request.Request(ROOT + r, headers=UA, method='HEAD')
            with urllib.request.urlopen(req, timeout=40, context=ctx) as resp:
                cl = resp.headers.get('Content-Length')
                if cl is not None:
                    return cat_of(r), int(cl)
        except Exception:
            pass
    return cat_of(r), None


stats = defaultdict(lambda: {'n': 0, 'bytes': 0, 'fail': 0})
with cf.ThreadPoolExecutor(16) as ex:
    for c, size in ex.map(head, bundles):
        s = stats[c]
        s['n'] += 1
        if size is None:
            s['fail'] += 1
        else:
            s['bytes'] += size

print(f"\n{'kategori':16s} {'jumlah':>7s} {'404':>6s} {'total':>11s} {'rata2':>9s}")
tot = 0
for k, v in sorted(stats.items(), key=lambda x: -x[1]['bytes']):
    ok = v['n'] - v['fail']
    avg = v['bytes'] / ok / 1e6 if ok else 0
    print(f"{k:16s} {v['n']:7d} {v['fail']:6d} {v['bytes']/1e9:8.2f} GB {avg:7.1f} MB")
    tot += v['bytes']
print(f"{'TOTAL':16s} {len(bundles):7d} {'':6s} {tot/1e9:8.2f} GB")
