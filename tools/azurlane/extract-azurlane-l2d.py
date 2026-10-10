#!/usr/bin/env python3
"""Azur Lane (碧蓝航线) Live2D extractor.

Sumber resmi: azlassets (github.com/nobbyfix/AzurLane-AssetDownloader) menarik
AssetBundle langsung dari CDN game. untuk L2D:
    azl download <CLIENT>          # whitelist "live2d/" di config
    -> <assetdir>/<CLIENT>/AssetBundles/live2d/<name>   (1 bundle per model)

Tiap bundle = Cubism-SDK-in-Unity: MonoBehaviour CubismMoc (berisi .moc3 mentah,
magic "MOC3"), Texture2D (halaman), TextAsset <name>.physics3, AnimationClip.

Keluaran (dibaca viewer sebagai format live2d / cubism4):
    <out>/<name>/<name>.moc3
    <out>/<name>/<name>.physics3.json   (opsional)
    <out>/<name>/texture_NN.png
    <out>/<name>/<name>.model3.json      (sintetis; viewer juga menyintesis sendiri)

Pakai:
    python extract-azurlane-l2d.py <bundle_dir> <out_dir> [--only NAME]
"""
import io, os, sys, json, logging, struct, time

logging.disable(logging.CRITICAL)
import UnityPy
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f3"


def textasset_body(ob):
    """TextAsset -> (name, bytes). UnityPy m_Script sudah berupa isi teks."""
    raw = ob.get_raw_data()
    if len(raw) < 4:
        return "", b""
    n = struct.unpack("<i", raw[0:4])[0]
    if not (0 < n < 400):
        return "", raw
    q = 4 + n
    q += (4 - (q % 4)) % 4
    sz = struct.unpack("<i", raw[q:q + 4])[0]
    return raw[4:4 + n].decode("utf-8", "replace"), raw[q + 4:q + 4 + sz]


def extract_one(path, out_root):
    name = os.path.basename(path)
    dest = os.path.join(out_root, name)
    data = open(path, "rb").read()
    if b"MOC3" not in data:
        return False, "tanpa MOC3"
    o = data.rfind(b"UnityFS")
    try:
        env = UnityPy.load(io.BytesIO(data[o:]))
        objs = list(env.objects)
    except Exception as e:
        return False, f"load: {e}"

    moc3 = None
    physics = None
    textures = []
    for ob in objs:
        t = ob.type.name
        if t == "MonoBehaviour" and moc3 is None:
            raw = ob.get_raw_data()
            k = raw.find(b"MOC3")
            if k >= 0:
                moc3 = raw[k:]
        elif t == "TextAsset":
            nm, body = textasset_body(ob)
            if "physics" in nm.lower() and body:
                physics = body
        elif t == "Texture2D":
            try:
                r = ob.read()
                textures.append((r.m_Name, r))
            except Exception:
                pass

    if not moc3:
        return False, "MOC3 tidak ditemukan di objek"

    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, name + ".moc3"), "wb") as f:
        f.write(moc3)
    if physics:
        with open(os.path.join(dest, name + ".physics3.json"), "wb") as f:
            f.write(physics)

    tex_files = []
    for i, (tn, r) in enumerate(textures):
        nm = tn or f"texture_{i:02d}"
        try:
            img = r.image
            if img is None:
                continue
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            fn = nm + ".png"
            img.save(os.path.join(dest, fn))
            tex_files.append(fn)
        except Exception:
            pass
    # fallback name biar urut
    tex_files.sort()

    model3 = {
        "Version": 3,
        "Name": name,
        "FileReferences": {
            "Moc": name + ".moc3",
            "Textures": tex_files,
            "Physics": (name + ".physics3.json") if physics else None,
            "Motions": {},
        },
    }
    with open(os.path.join(dest, name + ".model3.json"), "w", encoding="utf-8") as f:
        json.dump(model3, f, indent=1, ensure_ascii=False)
    return True, f"{len(tex_files)} tex"


def main():
    src = sys.argv[1]
    out = sys.argv[2]
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    os.makedirs(out, exist_ok=True)
    files = sorted(f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f)))
    if only:
        files = [f for f in files if f == only]
    ok = fail = 0
    t0 = time.time()
    for i, fn in enumerate(files):
        good, msg = extract_one(os.path.join(src, fn), out)
        if good:
            ok += 1
        else:
            fail += 1
            print(f"  GAGAL {fn}: {msg}", flush=True)
        if (i + 1) % 25 == 0:
            print(f"  ..{i+1}/{len(files)} ok={ok} ({time.time()-t0:.0f}s)", flush=True)
    print(f"  SELESAI total={len(files)} ok={ok} gagal={fail} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
