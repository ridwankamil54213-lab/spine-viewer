#!/usr/bin/env python3
"""マブラヴ ガールズガーデンX (Muv-Luv Girls Garden X) spine extractor.

Sumber resmi (client Unity WebGL):
  bundle spine ada di Addressables "spine_catalog" -> rlp/<hash>.bundle,
  diunduh dari:
    https://assets.muvluv-girls-garden.com/production-public/<ver>/BundleAssets/X/WebGL/ASTC/<hash>.bundle
  (pola ditemukan dari request live; TANPA subfolder rlp/).

Tahap 1: baca spine_catalog.bin -> daftar hash bundle.
Tahap 2: unduh tiap bundle (concurrent).
Tahap 3: ekstrak spine (.skel/.atlas/PNG) per model ke out_dir.
"""
import os, sys, io, json, struct, logging, concurrent.futures as cf, urllib.request, time

logging.disable(logging.CRITICAL)
import UnityPy
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f3"
import AddressablesTools as A
import warnings
warnings.simplefilter("ignore")

VER = "a13f7627-175c-4f2a-b6b6-77bef89011ad"
BASE = f"https://assets.muvluv-girls-garden.com/production-public/{VER}"
BUNDLE_URL = BASE + "/BundleAssets/X/WebGL/ASTC/{h}.bundle"
CATALOG = "/opt/mlv/cat/spine_catalog.bin"


def bundle_hashes():
    cat = A.parse(open(CATALOG, "rb").read())
    hs = set()
    for k in cat.Resources:
        if k.endswith(".bundle"):
            hs.add(k[:-7])  # buang ".bundle"
    return sorted(hs)


def download(h, dest):
    fp = os.path.join(dest, h + ".bundle")
    if os.path.exists(fp) and os.path.getsize(fp) > 0:
        return h, "skip"
    try:
        req = urllib.request.Request(BUNDLE_URL.format(h=h), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
        if not data or data[:1] == b"<":
            return h, "kosong"
        open(fp, "wb").write(data)
        return h, len(data)
    except Exception as e:
        return h, "err:" + str(e)[:40]


def ta_body(ob):
    raw = ob.get_raw_data()
    if len(raw) < 4:
        return "", b""
    n = struct.unpack("<i", raw[0:4])[0]
    if not (0 < n < 400):
        return "", raw
    q = 4 + n; q += (4 - (q % 4)) % 4
    sz = struct.unpack("<i", raw[q:q + 4])[0]
    return raw[4:4 + n].decode("utf-8", "replace"), raw[q + 4:q + 4 + sz]


def extract(bundle_path, out_root):
    name = os.path.basename(bundle_path)[:-7]
    d = open(bundle_path, "rb").read()
    o = d.rfind(b"UnityFS")
    if o < 0:
        return None
    env = UnityPy.load(io.BytesIO(d[o:]))
    skel = {}; atlas = {}; tex = {}
    for ob in env.objects:
        t = ob.type.name
        if t == "TextAsset":
            nm, body = ta_body(ob)
            low = nm.lower()
            if low.endswith(".atlas"):
                atlas[nm[:-6]] = body
            elif body[:9] == b'{"skeleton' or body[:1] == b"\x00" or (not low.endswith(".json") and nm):
                skel.setdefault(nm, body)
        elif t == "Texture2D":
            try:
                r = ob.read(); tex[r.m_Name] = r
            except Exception:
                pass
    made = 0
    for nm in list(skel.keys()):
        if nm not in atlas:
            # coba cocokkan tanpa suffix angka/underscore
            cand = [a for a in atlas if a == nm or a.split("_")[0] == nm.split("_")[0]]
            if not cand:
                continue
            an = cand[0]
        else:
            an = nm
        dest = os.path.join(out_root, nm)
        os.makedirs(dest, exist_ok=True)
        open(os.path.join(dest, nm + ".skel"), "wb").write(skel[nm])
        atl = atlas[an].decode("utf-8", "replace")
        open(os.path.join(dest, nm + ".atlas"), "w", encoding="utf-8").write(atl)
        # salin tekstur yang dirujuk atlas
        for ln in atl.splitlines():
            s = ln.strip()
            if s.lower().endswith((".png", ".jpg", ".webp")) and ":" not in s:
                base = os.path.basename(s); stem = os.path.splitext(base)[0]
                r = tex.get(stem)
                if r is not None:
                    try:
                        img = r.image
                        if img is not None:
                            if img.mode != "RGBA":
                                img = img.convert("RGBA")
                            img.save(os.path.join(dest, base))
                    except Exception:
                        pass
        made += 1
    return name if made else None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    dest = "/opt/mlv/bundles"
    out = "/opt/spine-viewer/assets/muvluv"
    os.makedirs(dest, exist_ok=True); os.makedirs(out, exist_ok=True)
    hs = bundle_hashes()
    print(f"bundle spine: {len(hs)}", flush=True)
    if mode in ("all", "download", "dl"):
        done = 0; t0 = time.time()
        with cf.ThreadPoolExecutor(max_workers=12) as ex:
            for h, res in ex.map(lambda h: download(h, dest), hs):
                done += 1
                if done % 100 == 0:
                    print(f"  dl {done}/{len(hs)} ({time.time()-t0:.0f}s)", flush=True)
        print("download selesai", flush=True)
    if mode in ("all", "extract", "x"):
        files = sorted(f for f in os.listdir(dest) if f.endswith(".bundle"))
        ok = 0; t0 = time.time()
        for i, f in enumerate(files):
            try:
                r = extract(os.path.join(dest, f), out)
                if r: ok += 1
            except Exception as e:
                print(f"  gagal {f}: {str(e)[:60]}", flush=True)
            if (i + 1) % 100 == 0:
                print(f"  extract {i+1}/{len(files)} ok={ok} ({time.time()-t0:.0f}s)", flush=True)
        print(f"SELESAI extract={ok}/{len(files)}", flush=True)


if __name__ == "__main__":
    main()
