#!/usr/bin/env python3
"""深蓝终末录 (Shenlan Zhongmolu / "Deep Blue") extractor.

APK (CloudFront signed) memuat assets/prefab/hero/herospines/hero_<id>/*.unity3d.
Tiap bundle = Spine lengkap: TextAsset <Name>.skel + <Name>.atlas + Texture2D.
Tidak ada enkripsi (UnityFS biasa). Tekstur distream ke disk (2048x2048).
"""
import glob, os, io, struct, logging, sys, time, shutil
logging.disable(logging.CRITICAL)
import UnityPy
UnityPy.config.FALLBACK_UNITY_VERSION = "2021.3.0f1"

SRC = sys.argv[1] if len(sys.argv) > 1 else "/opt/games/sl_h"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/opt/games/shenlan_out"
TMP = os.path.join(OUT, "_texcache")


def ta(ob):
    raw = ob.get_raw_data()
    n = struct.unpack("<i", raw[0:4])[0]
    if not (0 < n < 400):
        return "", b""
    q = 4 + n; q += (4 - (q % 4)) % 4
    sz = struct.unpack("<i", raw[q:q + 4])[0]
    return raw[4:4 + n].decode("utf-8", "replace"), raw[q + 4:q + 4 + sz]


def main():
    os.makedirs(TMP, exist_ok=True)
    fs = sorted(glob.glob(os.path.join(SRC, "**", "*.unity3d"), recursive=True))
    print(f"  bundle: {len(fs)}", flush=True)
    made = withpng = 0
    t0 = time.time()
    for i, f in enumerate(fs):
        d = open(f, "rb").read(); o = d.rfind(b"UnityFS")
        if o < 0:
            continue
        try:
            env = UnityPy.load(io.BytesIO(d[o:]))
            objs = list(env.objects)
        except Exception:
            continue
        skel = {}; atlas = {}; texn = []
        for ob in objs:
            t = ob.type.name
            if t == "TextAsset":
                nm, blob = ta(ob)
                low = nm.lower()
                if low.endswith(".skel"):
                    skel[nm[:-5]] = blob
                elif low.endswith(".atlas"):
                    atlas[nm[:-6]] = blob.decode("utf-8", "replace")
                elif blob.lstrip()[:11] == b'{"skeleton':
                    skel[nm] = blob
            elif t == "Texture2D":
                try:
                    rd = ob.read(); nm = rd.m_Name
                    if glob.glob(os.path.join(TMP, nm + ".png")):
                        texn.append(nm); continue
                    im = rd.image
                    if im is None:
                        continue
                    if im.mode != "RGBA":
                        im = im.convert("RGBA")
                    im.save(os.path.join(TMP, nm + ".png"))
                    texn.append(nm)
                except Exception:
                    pass
        for name in set(skel) & set(atlas):
            dest = os.path.join(OUT, name); os.makedirs(dest, exist_ok=True)
            open(os.path.join(dest, name + ".skel"), "wb").write(skel[name])
            atl = atlas[name]
            open(os.path.join(dest, name + ".atlas"), "w").write(atl)
            n = 0
            for ln in atl.splitlines():
                s = ln.strip()
                if s.lower().endswith((".png", ".jpg", ".webp")) and ":" not in s:
                    base = os.path.basename(s); stem = os.path.splitext(base)[0]
                    for cand in (stem + ".png", stem + ".jpg", base):
                        src = os.path.join(TMP, cand)
                        if os.path.exists(src):
                            shutil.copyfile(src, os.path.join(dest, base)); n += 1
                            break
            made += 1; withpng += (n > 0)
    print(f"  SELESAI bundle={len(fs)} model={made} dgn png={withpng} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
