#!/usr/bin/env python3
"""Ekstrak Spine Divine Throne (Cocos Creator 2.x) dari asset pack.

Struktur (semua di dalam split_install_time_asset_pack.apk, prefix
`assets/assets/<pack>/`):

  config.<hash>.json   Cocos: {types, uuids, paths}. Untuk tiap nama spine ada
                       entri `spine/<kategori>/<Nama>` bertipe `sp.SkeletonData`
                       (uuid A) dan `cc.Texture2D` (uuid B, uuid BERBEDA).
  import/<xx>/<...>.json
                       Serialisasi Cocos. Di dalamnya ada record
                       `sp.SkeletonData` = [ci, "<Nama>", ".bin", <atlasText
                       LENGKAP>, [textureNames], [textures]].
  native/<xx>/<uuid36>.<hash>.bin     skeleton Spine BINER (3.8.99)
  native/<xx>/<uuid36>.<hash>.astc    halaman tekstur (ASTC, header kustom)

Karena viewer spine-viewer sudah bisa memuat `.skel` biner (auto-deteksi versi),
tidak perlu konverter: cukup salin .bin -> .skel.

ASTC header (16 B): `13 AB A1 5C`, byte4=block_x, byte5=block_y,
byte7..9=le24 width, byte10..12=le24 height, data di offset 16.
Decode via texture2ddecoder.decode_astc(w,h,bx,by) lalu TUKAR kanal R/B.

Jalankan:
    python extract-throne.py --pack /opt/throne/pack --out /opt/spine-viewer/assets/throne
"""
import argparse
import glob
import json
import os
import re
import struct
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import texture2ddecoder as t2d
from PIL import Image

ASTC_MAGIC = bytes.fromhex("13aba15c")
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


def decode_astc(buf: bytes):
    if buf[:4] != ASTC_MAGIC:
        raise ValueError(f"bukan ASTC: {buf[:4].hex()}")
    bx, by = buf[4], buf[5]
    w = int.from_bytes(buf[7:10], "little")
    h = int.from_bytes(buf[10:13], "little")
    data = buf[16:]
    try:
        rgba = t2d.decode_astc(data, w, h, bx, by)
    except TypeError:
        out = bytearray(w * h * 4)
        t2d.decode_astc(data, w, h, bx, by, out)
        rgba = bytes(out)
    b = bytearray(rgba)
    b[0::4], b[2::4] = rgba[2::4], rgba[0::4]
    return w, h, bytes(b)


def load_config(pack_dir: Path):
    cfgs = sorted(glob.glob(str(pack_dir / "config.*.json")))
    if not cfgs:
        return None
    d = json.load(open(cfgs[0], encoding="utf-8"))
    return d


def skeleton_records(pack_dir: Path):
    """name -> {"atlas": str, "texnames": [...]} dari record sp.SkeletonData."""
    out = {}
    for f in glob.glob(str(pack_dir / "import" / "**" / "*.json"), recursive=True):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, list) or len(d) < 6:
            continue
        classes = d[3]
        ci = None
        for i, c in enumerate(classes):
            if isinstance(c, list) and c and c[0] == "sp.SkeletonData":
                ci = i
                break
        if ci is None:
            continue

        def walk(o):
            if isinstance(o, list):
                # record: [<id>, "<Nama>", ".bin", "<atlasText...>", [texnames], [textures]]
                if (len(o) >= 4 and isinstance(o[1], str) and o[2] == ".bin"
                        and isinstance(o[3], str) and "size:" in o[3]):
                    out[o[1]] = {"atlas": o[3],
                                 "texnames": (o[4] if len(o) > 4 else []) or []}
                for x in o:
                    walk(x)
        walk(d[5])
    return out


def native_file(pack_root: Path, uuid36: str):
    """Cari file native <uuid36>.<hash>.<ext> di semua pack."""
    for d in glob.glob(str(pack_root / "*" / "native" / uuid36[:2])):
        for f in os.listdir(d):
            if f.startswith(uuid36):
                return os.path.join(d, f)
    return None


def do_pack(args):
    pack_root, pack_dir, out_root = args
    cfg = load_config(Path(pack_dir))
    if not cfg:
        return (pack_dir, "no config", 0, 0)
    types, uuids, paths = cfg["types"], cfg["uuids"], cfg["paths"]
    try:
        ti = types.index("sp.SkeletonData")
        txi = types.index("cc.Texture2D")
    except ValueError:
        return (pack_dir, "no sp.SkeletonData", 0, 0)

    skel = {}   # name -> skeleton uuid36
    tex = {}    # name -> texture uuid36
    for k, v in paths.items():
        i = int(k)
        u = decode_uuid(uuids[i]) if i < len(uuids) else None
        nm = v[0]
        if not nm.startswith("spine/"):
            continue
        base = nm.split("/")[-1]
        if v[1] == ti:
            skel[base] = u
        elif v[1] == txi:
            tex[base] = u

    recs = skeleton_records(Path(pack_dir))
    pack_name = os.path.basename(pack_dir)
    ok = fail = 0
    for name, su in sorted(skel.items()):
        rec = recs.get(name)
        if not rec or not rec.get("atlas"):
            continue
        bin_path = native_file(pack_root, su)
        if not bin_path:
            fail += 1
            continue
        tu = tex.get(name)
        astc_path = native_file(pack_root, tu) if tu else None
        dest = Path(out_root) / pack_name / name
        dest.mkdir(parents=True, exist_ok=True)
        try:
            # skeleton: .bin -> .skel (biner, viewer auto-deteksi versi)
            (dest / f"{name}.skel").write_bytes(open(bin_path, "rb").read())
            # atlas (page sudah .png)
            atlas = rec["atlas"]
            (dest / f"{name}.atlas").write_text(atlas, encoding="utf-8")
            # texture: .astc -> .png
            if astc_path:
                w, h, rgba = decode_astc(open(astc_path, "rb").read())
                Image.frombytes("RGBA", (w, h), rgba).save(dest / f"{name}.png")
            ok += 1
        except Exception as e:
            fail += 1
            (dest / "ERROR.txt").write_text(f"{type(e).__name__}: {e}")
    return (pack_dir, None, ok, fail)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True, help="root pack (berisi assets/assets/*)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--packs", default="", help="filter nama pack (comma), mis. common")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    pack_root = Path(args.pack) / "assets" / "assets"
    dirs = [d for d in sorted(pack_root.iterdir()) if d.is_dir()]
    if args.packs:
        want = set(args.packs.split(","))
        dirs = [d for d in dirs if d.name in want]
    log(f"pack: {[d.name for d in dirs]}")

    tasks = [(pack_root, str(d), args.out) for d in dirs]
    tot_ok = tot_fail = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for d, err, ok, fail in ex.map(do_pack, tasks):
            tot_ok += ok
            tot_fail += fail
            log(f"  {os.path.basename(d):16} ok={ok:4} fail={fail:3} {err or ''}")
    log(f"SELESAI ok={tot_ok} fail={tot_fail}")


if __name__ == "__main__":
    main()
