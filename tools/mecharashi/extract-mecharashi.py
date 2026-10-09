#!/usr/bin/env python3
"""钢岚 / Mecharashi extractor (hemat memori).

Bundle assets/ExportAssetBundle/*.b = UnityFS + UnityCN.
Kunci hex "31433743463543423144313841304630" (= bytes 1C7CF5CB1D18A0F0).
Tiap bundle pilot_* memuat Spine lengkap (.skel + .atlas + Texture2D).
Tekstur langsung ditulis ke disk per-model -> tidak menahan semua di RAM.
"""
import glob, os, io, struct, logging, collections, sys, time
logging.disable(logging.CRITICAL)
import UnityPy

KEY = bytes.fromhex("31433743463543423144313841304630")
UnityPy.set_assetbundle_decrypt_key(KEY)

AB = sys.argv[1] if len(sys.argv) > 1 else "mecha_b/assets/ExportAssetBundle"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/opt/games/mecha_out"
TMP = os.path.join(OUT, "_texcache")


def ta_info(ob):
    raw = ob.get_raw_data()
    n = struct.unpack("<i", raw[0:4])[0]
    if not (0 < n < 500):
        return "", b""
    q = 4 + n; q += (4 - (q % 4)) % 4
    sz = struct.unpack("<i", raw[q:q + 4])[0]
    return raw[4:4 + n].decode("utf-8", "replace"), raw[q + 4:q + 4 + sz]


def main():
    os.makedirs(TMP, exist_ok=True)
    fs = sorted(glob.glob(os.path.join(AB, "*.b")))
    made = withpng = 0
    t0 = time.time()
    for i, f in enumerate(fs):
        try:
            env = UnityPy.load(io.BytesIO(open(f, "rb").read()))
            objs = list(env.objects)
        except Exception:
            continue
        skel = {}; atlas = {}; texn = []
        for ob in objs:
            t = ob.type.name
            if t == "TextAsset":
                nm, blob = ta_info(ob)
                low = nm.lower()
                if low.endswith(".skel"):
                    skel[nm[:-5]] = blob
                elif low.endswith(".atlas"):
                    atlas[nm[:-6]] = blob.decode("utf-8", "replace")
                elif blob.lstrip()[:11] == b'{"skeleton':
                    skel[nm] = blob
            elif t == "Texture2D":
                try:
                    rd = ob.read()
                    paths = glob.glob(os.path.join(TMP, rd.m_Name + ".*"))
                    if paths:
                        texn.append(rd.m_Name); continue
                    im = rd.image
                    if im is None:
                        continue
                    if im.mode != "RGBA":
                        im = im.convert("RGBA")
                    im.save(os.path.join(TMP, rd.m_Name + ".png"))
                    texn.append(rd.m_Name)
                except Exception:
                    pass
        for name in set(skel) & set(atlas):
            d = os.path.join(OUT, name); os.makedirs(d, exist_ok=True)
            open(os.path.join(d, name + ".skel"), "wb").write(skel[name])
            atl = atlas[name]
            open(os.path.join(d, name + ".atlas"), "w").write(atl)
            n = 0
            for ln in atl.splitlines():
                s = ln.strip()
                if s.lower().endswith((".png", ".jpg", ".webp")) and ":" not in s:
                    base = os.path.basename(s); stem = os.path.splitext(base)[0]
                    for cand in (stem + ".png", stem + ".jpg", base):
                        src = os.path.join(TMP, cand)
                        if os.path.exists(src):
                            import shutil; shutil.copyfile(src, os.path.join(d, base)); n += 1
                            break
            made += 1; withpng += (n > 0)
        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(fs)}] {time.time()-t0:.0f}s model={made} png={withpng}", flush=True)
    print(f"  bundle={len(fs)} model={made} dgn png={withpng} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
