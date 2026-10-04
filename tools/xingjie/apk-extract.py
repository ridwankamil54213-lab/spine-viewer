#!/usr/bin/env python3
"""Scan + ekstrak spine SISA dari APK 性界大战 (yang tidak ada di build H5).

APK (`assets/res/`) memakai build Cocos 2.x yang SAMA seperti H5, tapi seluruh
berkas di `res/` dienkripsi XOR:

    <"xjdzEncrypt" 11 byte> + XOR(isi_asli, key="u40DCSu5hsL3AVfl3QS1")

Key-nya identik dengan `encriptKey` yang bocor di plugin_conf.js H5; di H5 hanya
file PNG yang dibungkus base64 sedangkan di APK semuanya (json/atlas/png/jpg)
XOR dengan key ini.

Tiap `import/**/*.json` yang bertipe `sp.SkeletonData` self-contained:
`_name`, `_skeletonJson`, `_atlasText`, `textures[].__uuid__`, `textureNames`.

Jalankan:
    python apk-scan.py --res <dir>/assets/res --out /tmp/xj-apk --compare /opt/spine-viewer/assets/xingjie
"""
import argparse
import glob
import json
import os
import re
import sys

SIG = b"xjdzEncrypt"
KEY = b"u40DCSu5hsL3AVfl3QS1"
B64 = {c: i for i, c in enumerate(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}


def log(*a):
    print(*a, flush=True)


def decrypt(buf: bytes) -> bytes:
    if not buf.startswith(SIG):
        return buf
    c = buf[len(SIG):]
    return bytes(c[i] ^ KEY[i % len(KEY)] for i in range(len(c)))


def decode_uuid(u: str) -> str:
    if not u or len(u) != 22:
        return u
    o = u[0] + u[1]
    for i in range(2, 22, 2):
        l = B64[u[i]]
        r = B64[u[i + 1]]
        o += "%x%x%x" % (l >> 2, ((l & 3) << 2) | (r >> 4), r & 0xF)
    return "%s-%s-%s-%s-%s" % (o[:8], o[8:12], o[12:16], o[16:20], o[20:32])


def safe(s):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(s)).strip("._ ") or "m"


def scan(res_dir, out_dir, compare_dir=None):
    import_root = os.path.join(res_dir, "import")
    raw_root = os.path.join(res_dir, "raw-assets")

    # buat index raw-assets: uuid36 -> path
    raw_index = {}
    for f in glob.glob(os.path.join(raw_root, "**", "*"), recursive=True):
        if os.path.isfile(f):
            base = os.path.basename(f)
            u = base.split(".")[0]
            if len(u) == 36:
                raw_index[u] = f

    # himpunan hash skeleton yang sudah ada (H5)
    have = set()
    if compare_dir:
        for f in glob.glob(os.path.join(compare_dir, "**", "*.json"), recursive=True):
            try:
                h = (json.load(open(f, encoding="utf-8")).get("skeleton") or {}).get("hash")
                if h:
                    have.add(h)
            except Exception:
                pass
        log(f"# hash skeleton H5: {len(have)}")

    files = glob.glob(os.path.join(import_root, "**", "*.json"), recursive=True)
    log(f"# import json: {len(files)}")

    n_skel = 0
    new = []
    os.makedirs(out_dir, exist_ok=True)
    for i, f in enumerate(files, 1):
        try:
            raw = open(f, "rb").read()
        except OSError:
            continue
        d = decrypt(raw)
        if b"_skeletonJson" not in d[:200000]:
            continue
        try:
            obj = json.loads(d.decode("utf-8", "replace"))
        except Exception:
            continue
        if not isinstance(obj, dict) or obj.get("__type__") != "sp.SkeletonData":
            continue
        n_skel += 1
        sj = obj.get("_skeletonJson") or {}
        h = (sj.get("skeleton") or {}).get("hash") if isinstance(sj, dict) else None
        name = safe(obj.get("_name") or os.path.basename(f)[:8])
        is_new = (h not in have) if (compare_dir and h) else True
        rec = {"file": os.path.relpath(f, res_dir), "name": name, "hash": h,
               "new": is_new, "spine": (sj.get("skeleton") or {}).get("spine") if isinstance(sj, dict) else None,
               "bones": len(sj.get("bones", [])) if isinstance(sj, dict) else 0}
        if is_new:
            new.append(rec)
            # tulis
            dest = os.path.join(out_dir, name)
            os.makedirs(dest, exist_ok=True)
            open(os.path.join(dest, name + ".json"), "w", encoding="utf-8").write(
                json.dumps(sj, ensure_ascii=False))
            open(os.path.join(dest, name + ".atlas"), "w", encoding="utf-8").write(obj.get("_atlasText") or "")
            pages = obj.get("textureNames") or []
            for k, tex in enumerate(obj.get("textures") or []):
                tu = decode_uuid(tex.get("__uuid__"))
                pn = pages[k] if k < len(pages) else f"{name}.png"
                src = raw_index.get(tu)
                if src:
                    open(os.path.join(dest, pn), "wb").write(decrypt(open(src, "rb").read()))
        if i % 4000 == 0:
            log(f"  ...{i}/{len(files)} skel={n_skel} baru={len(new)}")

    log(f"\n# sp.SkeletonData di APK: {n_skel}")
    log(f"# BARU (tidak ada di H5): {len(new)}")
    for r in new:
        log("   ", json.dumps(r, ensure_ascii=False))
    json.dump({"total": n_skel, "new": new}, open(os.path.join(out_dir, "_scan.json"), "w"),
              ensure_ascii=False, indent=1)
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--compare", default=None)
    args = ap.parse_args()
    scan(args.res, args.out, args.compare)


if __name__ == "__main__":
    main()
