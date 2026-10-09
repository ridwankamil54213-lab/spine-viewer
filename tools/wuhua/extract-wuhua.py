#!/usr/bin/env python3
"""物华弥新 / Neo Artifacts (com.cipaishe.wuhua.google) extractor — final.

Bundle UnityFS dgn blok ter-XOR. Metode (live2dhub #5896):
    key = data[51];  XOR data[50:end] ^= key   (end dicari per-file)
Isi: TextAsset .skel/.atlas (Spine 3.8.95) + Texture2D. Karakter utama ada di CDN.
"""
import io, os, sys, struct, glob, re, shutil, argparse, logging, collections
logging.disable(logging.CRITICAL)
import contextlib
import UnityPy
UnityPy.config.FALLBACK_UNITY_VERSION = "2018.4.36f1"
from PIL import Image

START = 50
KEY_CAND = range(60, 260)


@contextlib.contextmanager
def mute_fd2():
    """Bungkam 'Error parsing file ...' yang dicetak UnityPy ke stderr."""
    import os as _os
    saved = _os.dup(2)
    devnull = _os.open(_os.devnull, _os.O_WRONLY)
    _os.dup2(devnull, 2)
    try:
        yield
    finally:
        _os.dup2(saved, 2)
        _os.close(devnull)
        _os.close(saved)


def ta_parts(ob):
    try:
        raw = ob.get_raw_data()
        n = struct.unpack("<i", raw[0:4])[0]
        if not (0 < n < 400):
            return "", b""
        q = 4 + n; q += (4 - (q % 4)) % 4
        sz = struct.unpack("<i", raw[q:q + 4])[0]
        return raw[4:4 + n].decode("utf-8", "replace"), raw[q + 4:q + 4 + sz]
    except Exception:
        return "", b""


def decrypt(raw):
    if raw[:7] != b"UnityFS":
        return None
    with mute_fd2():
        for end in KEY_CAND:
            e = bytearray(raw)
            for i in range(START, end):
                e[i] ^= raw[51]
            try:
                env = UnityPy.load(io.BytesIO(bytes(e)))
                if any(True for _ in env.objects):
                    return bytes(e)
            except Exception:
                continue
    return None


def tex_to_png(ob):
    try:
        d = ob.read()
        img = d.image
        if img is None:
            return d.m_Name, None
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        return d.m_Name, img
    except Exception:
        return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    bundles = sorted(glob.glob(os.path.join(a.pack, "**", "*.ab"), recursive=True))
    models = collections.defaultdict(dict)   # name -> {skel, atlas}
    pool = {}                                # "name.png" -> PIL.Image
    ends = collections.Counter()
    for bf in bundles:
        dec = decrypt(open(bf, "rb").read())
        if dec is None:
            continue
        with mute_fd2():
            env = UnityPy.load(io.BytesIO(dec))
            for ob in env.objects:
                t = ob.type.name
                if t == "TextAsset":
                    nm, blob = ta_parts(ob)
                    low = nm.lower()
                    if low.endswith(".skel"):
                        models[nm[:-5]]["skel"] = blob
                    elif low.endswith(".atlas"):
                        models[nm[:-6]]["atlas"] = blob
                elif t == "Texture2D":
                    nm, img = tex_to_png(ob)
                    if img is not None:
                        pool[os.path.splitext(nm)[0] + ".png"] = img
    print(f"  bundle terdekripsi: {sum(1 for _ in []) or len([b for b in bundles])}")
    print(f"  TextAsset model: {sum(1 for m in models.values() if m.get('skel') and m.get('atlas'))}")
    print(f"  tekstur ter-decode: {len(pool)}")

    made = withpg = 0
    for name, m in sorted(models.items()):
        if not (m.get("skel") and m.get("atlas")):
            continue
        d = os.path.join(a.out, name)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, name + ".skel"), "wb").write(m["skel"])
        atl = m["atlas"].decode("utf-8", "replace")
        open(os.path.join(d, name + ".atlas"), "w").write(atl)
        pages = [os.path.basename(x.strip()) for x in atl.splitlines()
                 if re.search(r"\.(png|jpg|webp)\s*$", x.strip(), re.I)]
        n = 0
        for pg in pages:
            key = os.path.splitext(pg)[0] + ".png"
            if key in pool:
                pool[key].save(os.path.join(d, pg)); n += 1
        made += 1
        withpg += (n > 0)
    print(f"  ditulis: {made} model | dgn tekstur: {withpg}")


if __name__ == "__main__":
    main()
