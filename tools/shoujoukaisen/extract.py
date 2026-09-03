#!/usr/bin/env python3
"""Extract Spine models from the Shoujou Kaisen (少女廻戦) XAPK.

Layout: the XAPK holds unityAssets.apk, and inside it every model is a UnityFS
bundle named `*.asset` under assets/assets/model/.

GOTCHA — 18 junk bytes: each bundle starts with a stray 18-byte prefix
("UnityFS\\0\\0\\0\\0\\x08 5.x.x\\0") before the real UnityFS header begins at
offset 18. UnityPy reads from offset 0, misparses it, and reports the bundle as
"encrypted" (which it is not). Stripping those 18 bytes makes it parse.

Each bundle then holds exactly one model:
    <Name>.skel     (TextAsset, Spine 3.8.97)
    <Name>.atlas    (TextAsset)
    <Name>.png      (Texture2D)

Spine 3.8.97 is readable by pixi-spine directly, so unlike Project QT these
need no conversion and no legacy viewer.
"""
import io
import os
import shutil
import struct
import sys
import zipfile

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f2"
TEXT_ASSET, TEXTURE2D = 49, 28


def parse_text_asset(raw):
    """TextAsset payload: int32 name_len, name (padded to 4), int32 len, data."""
    nl = struct.unpack_from("<i", raw, 0)[0]
    off = (4 + nl + 3) & ~3
    dl = struct.unpack_from("<i", raw, off)[0]
    off += 4
    return raw[off: off + dl]


def strip_prefix(data):
    """Drop the junk prefix if present, else return as-is.

    Every bundle starts with a stray copy of "UnityFS\x00\x00\x00\x00\x08"
    followed by a Unity version string. The version string varies in length,
    so the real header does NOT always begin at a fixed offset — find where
    the second signature actually starts instead of hard-coding 18.
    """
    first = data.find(b"UnityFS\x00")
    if first != 0:
        return data
    second = data.find(b"UnityFS\x00", first + 1)
    if second == -1:
        return data
    return data[second:]


def extract_bundle(data, out_dir, stem, extra_tex_data=()):
    """Write skel/atlas/png from one bundle. Returns None or an error string.

    Some models ship their Texture2D in a separate `<name>_texture.asset`
    bundle, so any extra bundles are mined for images too.
    """
    data = strip_prefix(data)
    try:
        env = UnityPy.load(io.BytesIO(data))
    except Exception as e:
        return f"load: {type(e).__name__}: {str(e)[:80]}"

    # Some bundles carry MORE THAN ONE skeleton (e.g. ganning01 has a 594 KB
    # skel and a truncated 410 B one under the same name). Last-wins picked the
    # broken one, so collect them all and choose the largest — matching the
    # atlas by its stem when possible.
    skels = []
    atlases = []
    texs = []
    for obj in env.objects:
        tid = str(obj.type)
        if tid == str(TEXT_ASSET):
            try:
                d = obj.read()
            except Exception:
                continue
            try:
                payload = parse_text_asset(obj.get_raw_data())
            except Exception:
                continue
            name = d.m_Name or ""
            if name.lower().endswith(".skel"):
                skels.append((name, payload))
            elif name.lower().endswith(".atlas"):
                atlases.append((name, payload))
        elif tid == str(TEXTURE2D):
            try:
                d = obj.read()
                if d.image is not None:
                    texs.append((d.m_Name or "texture", d.image))
            except Exception:
                continue

    for blob in extra_tex_data:
        try:
            env2 = UnityPy.load(io.BytesIO(strip_prefix(blob)))
        except Exception:
            continue
        for obj in env2.objects:
            if str(obj.type) != str(TEXTURE2D):
                continue
            try:
                d = obj.read()
                if d.image is not None:
                    texs.append((d.m_Name or "texture", d.image))
            except Exception:
                continue

    if not skels or not atlases:
        return "no skel+atlas"
    if not texs:
        return "no texture"

    # Both sets share the same name, so pairing by stem is meaningless — the
    # real set is the LARGEST skel paired with the LARGEST atlas. (Matching by
    # stem picked the truncated atlas and every region lookup failed.)
    skel = max(skels, key=lambda kv: len(kv[1]))
    atlas = max(atlases, key=lambda kv: len(kv[1]))

    os.makedirs(out_dir, exist_ok=True)
    # Name files after the model so the viewer can match them up.
    ext = os.path.splitext(skel[0])[1] or ".skel"
    with open(os.path.join(out_dir, stem + ext), "wb") as f:
        f.write(skel[1])
    # Atlas keeps its original name; the page reference inside points to the png.
    with open(os.path.join(out_dir, atlas[0]), "wb") as f:
        f.write(atlas[1])
    for tname, img in texs:
        try:
            img.save(os.path.join(out_dir, tname + ".png"))
        except Exception:
            continue
    return None


def iter_bundles(z, prefix="assets/assets/model/"):
    for n in z.namelist():
        if n.startswith(prefix) and n.endswith(".asset") and "_texture" not in n:
            yield n


def main():
    apk = sys.argv[1]
    out_root = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    os.makedirs(out_root, exist_ok=True)

    z = zipfile.ZipFile(apk)
    all_names = set(z.namelist())
    names = sorted(iter_bundles(z))
    if limit:
        names = names[:limit]
    print(f"bundles: {len(names)}", flush=True)

    ok = skip = fail = 0
    errors = []
    for i, n in enumerate(names, 1):
        stem = os.path.splitext(n.rsplit("/", 1)[-1])[0]
        dest = os.path.join(out_root, stem)
        if os.path.isdir(dest) and os.listdir(dest):
            skip += 1
            continue
        extras = []
        tex_name = f"assets/assets/model/{stem}_texture.asset"
        if tex_name in all_names:
            try:
                with z.open(tex_name) as src:
                    extras.append(src.read())
            except Exception:
                pass
        try:
            with z.open(n) as src:
                data = src.read()
            err = extract_bundle(data, dest, stem, extras)
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:80]}"
        if err:
            fail += 1
            errors.append(f"{stem}: {err}")
            shutil.rmtree(dest, ignore_errors=True)
        else:
            ok += 1
        if i % 200 == 0 or i == len(names):
            print(f"  {i}/{len(names)} ok={ok} skip={skip} fail={fail}", flush=True)

    print(f"\nDONE ok={ok} skip={skip} fail={fail}")
    if errors:
        with open(os.path.join(out_root, "_errors.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(errors))
        print("first errors:")
        for e in errors[:10]:
            print("  " + e)


if __name__ == "__main__":
    main()
