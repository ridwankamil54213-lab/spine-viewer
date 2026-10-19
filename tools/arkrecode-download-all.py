"""Unduh semua bundle Ark Re:Code catalog WebGL (catalog_115700).

Path lokal mengikuti struktur internal id apa adanya, jadi:
  defaultlocalgroup_assets_assets/game/cg/a0001/img_xxx.bundle
  -> /opt/arkupd/webgl-all/defaultlocalgroup_assets_assets/game/cg/a0001/img_xxx.bundle

Resumable: file yang sudah ada dan ukurannya cocok dilewati. Progres
ditulis ke progress.json setiap 25 file supaya bisa dilanjutkan.
"""
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.request
import concurrent.futures as cf

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0'}
ROOT = 'https://erdpu.gzxhcjz.com/GamePatch/'
DEST = '/opt/arkupd/webgl-all'
PROG = '/opt/arkupd/progress.json'

cat = json.loads(urllib.request.urlopen(
    urllib.request.Request(ROOT + 'WebGL/catalog_115700.json', headers=UA), timeout=180, context=ctx).read())
bundles = [i for i in cat['m_InternalIds'] if i.endswith('.bundle')]


def rel(i):
    m = re.match(r'https?://[^/]+/(.*)$', i)
    return m.group(1) if m else i


items = [(rel(b), b.rsplit('/', 1)[-1]) for b in bundles]
print(f'bundle: {len(items)}', flush=True)

lock = threading.Lock()
done = {'n': 0, 'bytes': 0, 'skip': 0, 'fail': 0}
fails = []


def grab(item):
    r, fn = item
    dst = os.path.join(DEST, r)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        with lock:
            done['skip'] += 1
            done['n'] += 1
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for attempt in range(3):
        try:
            req = urllib.request.Request(ROOT + r, headers=UA)
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                data = resp.read()
            tmp = dst + '.part'
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, dst)
            with lock:
                done['n'] += 1
                done['bytes'] += len(data)
                if done['n'] % 25 == 0:
                    print(f"  {done['n']}/{len(items)}  "
                          f"{done['bytes']/1e9:.2f} GB  skip={done['skip']} fail={done['fail']}",
                          flush=True)
                    json.dump({'n': done['n'], 'bytes': done['bytes'],
                               'skip': done['skip'], 'fail': done['fail'],
                               'fails': fails[-40:]}, open(PROG, 'w'))
            return
        except Exception as e:
            if attempt == 2:
                with lock:
                    done['fail'] += 1
                    fails.append(f'{r} :: {str(e)[:60]}')
    time.sleep(1)


t0 = time.time()
with cf.ThreadPoolExecutor(16) as ex:
    list(ex.map(grab, items))

print(f"\nSELESAI {done['n']}/{len(items)} | {done['bytes']/1e9:.2f} GB baru | "
      f"skip={done['skip']} fail={done['fail']} | {time.time()-t0:.0f}s", flush=True)
json.dump({'n': done['n'], 'bytes': done['bytes'], 'skip': done['skip'],
           'fail': done['fail'], 'fails': fails}, open(PROG, 'w'), indent=1)
if fails:
    print('contoh gagal:', fails[:5])
