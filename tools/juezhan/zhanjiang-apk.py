#!/usr/bin/env python3
"""Ekstrak skeleton Spine dari APK 决战僵尸舞娘 yang TIDAK ada di server.

APK (shell 2.0.5.8) membawa paket `assets/assets/resources` sendiri. Sementara
hot-update server cuma 2.0.4.9. Hasilnya APK punya beberapa skeleton yang LEBIH
BARU (teach role5/8/10/14) plus satu karakter utuh yang tidak ada di server
(role15). Script ini memindainya TANPA jaringan.

Alur:
  1. unzip -o game.apk "assets/assets/resources/import/*" -d apk-res
  2. baca config.<hash>.json (uuid -> path) + package.manifest (uuid -> native
     file) dari APK
  3. tiap import/*.json yang punya `sp.SkeletonData` -> .atlas + .json
  4. halaman PNG dari Texture2D yang dirujuk objek (dependency d[1])
  5. tulis <out>/<role>_<kategori>/ ; tulis ulang kalau versi APK lebih baru

    zhanjiang-apk.py --apk game.apk --out /opt/spine-viewer/assets/juezhan
"""
import argparse
import glob
import json
import os
import re
import shutil
import zipfile

B64 = {c: i for i, c in enumerate(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}


def log(*a):
    print(*a, flush=True)


def decode_uuid(u: str) -> str:
    if not u or len(u) != 22:
        return u
    o = u[0] + u[1]
    for i in range(2, 22, 2):
        l = B64[u[i]]
        r = B64[u[i + 1]]
        o += "%x%x%x" % (l >> 2, ((l & 3) << 2) | (r >> 4), r & 0xF)
    return "%s-%s-%s-%s-%s" % (o[:8], o[8:12], o[12:16], o[16:20], o[20:32])


def parse_cocos(raw: bytes):
    d = json.loads(raw.decode("utf-8", "replace"))
    fields = d[3][0][1]
    obj = None
    for r in reversed(d):
        if isinstance(r, list) and r and isinstance(r[0], list) and len(r[0]) > 1:
            obj = r[0]
            break
    if not obj:
        return None, None
    return {nm: val for nm, val in zip(fields[:len(obj) - 1], obj[1:])}, d


def clean(path: str) -> str:
    # path gaya "tafang/role/role7/art/painting" -> "role7_painting"
    n = path.replace("tafang/role/", "").replace("/", "_")
    for a, b in [("_art_painting", "_painting"), ("_battle_qAni_battleRole", "_battle"),
                 ("_battle_popFrontAni_front", "_front"), ("_battle_popBackAni_back", "_back"),
                 ("_story_剧情1_剧情1", "_story1"), ("_story_剧情2_剧情2", "_story2"),
                 ("_teach_teachBg", "_teachbg"), ("_teach_teach1", "_teach1"),
                 ("_teach_teach", "_teach")]:
        n = n.replace(a, b)
    return n


def existing_hashes(out_root: str) -> set:
    """hash skeleton yang sudah ada di pohon tujuan (dibaca dari .json-nya)."""
    out = set()
    for f in glob.glob(os.path.join(out_root, "*", "*.json")):
        try:
            h = (json.load(open(f, encoding="utf-8")).get("skeleton") or {}).get("hash")
            if h:
                out.add(h)
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scan", default="/opt/juezhan/apk-res",
                    help="hasil unzip assets/assets/resources/import/*")
    ap.add_argument("--force", action="store_true",
                    help="timpa juga model yang versinya sudah ada (default: skip)")
    args = ap.parse_args()

    # 1. config + package.manifest dari APK
    with zipfile.ZipFile(args.apk) as z:
        cfg_name = next(n for n in z.namelist()
                        if re.search(r"assets/assets/resources/config\.[0-9a-f]+\.json$", n))
        cfg = json.loads(z.read(cfg_name).decode("utf-8-sig"))
        pm = json.loads(z.read("assets/assets/package.manifest").decode("utf-8-sig"))
    log(f"config    : {cfg_name}")
    log(f"manifest  : versi {pm.get('version')}, {len(pm['assets'])} aset")

    paths, uuids, types = cfg["paths"], cfg["uuids"], cfg["types"]
    # NB: config bisa "packed" (paths per-pack, 0-based) — kalau index di luar
    # uuids, ulangi blok uuids (Cocos memakai offset global).
    ti = types.index("sp.SkeletonData")
    n_uu = len(uuids)
    sk2path = {}
    for k, v in paths.items():
        idx = int(k)
        u = uuids[idx] if idx < n_uu else uuids[idx % n_uu]
        if v[1] == ti:
            sk2path[decode_uuid(u)] = v[0]
    log(f"spine     : {len(sk2path)} path di config\n")

    # uuid -> file native
    nat = {}
    for k in pm["assets"]:
        if "/native/" in k:
            nat[os.path.basename(k)] = k

    have = existing_hashes(args.out)
    os.makedirs(args.out, exist_ok=True)

    files = glob.glob(os.path.join(args.scan, "**", "*.json"), recursive=True)
    new = upd = 0
    for f in sorted(files):
        try:
            raw = open(f, "rb").read()
        except OSError:
            continue
        if b"sp.SkeletonData" not in raw[:4000]:
            continue
        rec, arr = parse_cocos(raw)
        if not rec or "_skeletonJson" not in rec:
            continue
        sj = rec["_skeletonJson"]
        h = ((sj or {}).get("skeleton") or {}).get("hash") if isinstance(sj, dict) else None
        uuid = os.path.basename(f).rsplit(".", 2)[0]
        p = sk2path.get(uuid, "")
        key = clean(p) if p else "apk_" + uuid[:8]
        name = re.sub(r'[<>:"/\\|?*]+', "_", rec.get("_name") or "model")
        dest = os.path.join(args.out, key)
        exists = os.path.isdir(dest)

        if exists and h and h in have and not args.force:
            continue          # sudah ada & hash-nya sama -> lewati
        os.makedirs(dest, exist_ok=True)
        atlas = rec.get("_atlasText") or ""
        open(os.path.join(dest, f"{name}.atlas"), "w", encoding="utf-8").write(atlas)
        open(os.path.join(dest, f"{name}.json"), "w", encoding="utf-8").write(
            sj if isinstance(sj, str) else json.dumps(sj, ensure_ascii=False))

        # Halaman PNG: texture uuid ada di dependency objek (d[1]). Beberapa
        # atlas punya >1 halaman — ambil SEMUA dependency texture, petakan ke
        # halaman atlas secara berurutan.
        dep = arr[1] if len(arr) > 1 and isinstance(arr[1], list) else []
        pages = [l.strip() for l in atlas.splitlines()
                 if l.strip().lower().endswith((".png", ".jpg", ".webp")) and " " not in l.strip()]
        tex = 0
        got = []
        for cu in dep:
            tf = decode_uuid(cu)
            src = None
            for base, key2 in nat.items():
                if base.startswith(tf):
                    # key2 gaya "assets/resources/native/ea/<uuid>.<hash>.png".
                    # Paket APK berada di "assets/assets/", hasil unzip di
                    # <scan>/assets/... — coba beberapa kemungkinan supaya paket
                    # `startup` dan `resources` dua-duanya ketemu.
                    for c in (os.path.join(args.scan, "assets", key2),
                              os.path.join(args.scan, key2),
                              os.path.join(os.path.dirname(args.scan), key2)):
                        if os.path.exists(c):
                            src = c
                            break
                    if src:
                        break
            if src and src.lower().endswith((".png", ".jpg", ".webp")):
                got.append(src)
        for i, src in enumerate(got):
            if i < len(pages):
                shutil.copy2(src, os.path.join(dest, pages[i]))
                tex += 1

        (upd if exists else new).__class__  # no-op
        if exists:
            upd += 1
        else:
            new += 1
        log(f"  {'UPDATE' if exists else 'BARU  '} {key:<24} {name:<12} tex={'v' if tex else 'x'}")

    log(f"\nSELESAI baru={new} update={upd} -> {args.out}")


if __name__ == "__main__":
    main()
