#!/usr/bin/env python3
"""Ekstrak spine 异世界后宫物语 (Cocos Creator 2.4, prefix 'GenSanaSneG').

Enkripsi aset — prefix & key ditemukan di string `libcocos2djs.so`:

    prefix = b"GenSanaSneG"   (11 byte di awal tiap file terenkripsi)
    key    = b"mygame!fuck@you~"

    * .json / .atlas (teks)  -> XOR berulang dgn key
    * .png / .jpg (binari)   -> XXTEA (Cocos xxtea) dgn key (ukuran kelipatan 4)
    * .bin                   -> TIDAK terenkripsi (spine biner 3.8.99)

Catatan penting: **nama file import TIDAK sama dengan uuid aset**. Jadi peta
`nama -> record atlas/pages` dibangun dengan memindai SELURUH `import/**/*.json`
sekali. Skeleton biner diambil dari `paths`/`uuids` di `config.json`
(`native/<xx>/<uuid36>.bin`), halaman tekstur dari `textures`/`textureNames`.

Jalankan:
    python extract-ysjh.py --assets x/assets/assets --out /opt/spine-viewer/assets/ysjh
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

SIG = b"GenSanaSneG"
KEY = b"mygame!fuck@you~"
B64 = {c: i for i, c in enumerate(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}
_u32 = lambda x: x & 0xffffffff


def log(*a):
    print(*a, flush=True)


def xxtea_decrypt(data: bytes, key: bytes) -> bytes:
    if len(data) < 8:
        return b""
    n = len(data) // 4
    v = list(struct.unpack("<%dI" % n, data[: n * 4]))
    k = list(struct.unpack("<4I", (key + b"\0" * 16)[:16]))
    q = 6 + 52 // n
    s = _u32(q * 0x9E3779B9)
    y = v[0]
    while s:
        e = (s >> 2) & 3
        for p in range(n - 1, 0, -1):
            z = v[p - 1]
            y = v[p] = _u32(v[p] - _u32((((z >> 5) ^ _u32(y << 2))
                                         + ((y >> 3) ^ _u32(z << 4)))
                                        ^ ((s ^ y) + (k[(p & 3) ^ e] ^ z))))
        z = v[n - 1]
        y = v[0] = _u32(v[0] - _u32((((z >> 5) ^ _u32(y << 2))
                                    + ((y >> 3) ^ _u32(z << 4)))
                                   ^ ((s ^ y) + (k[0 ^ e] ^ z))))
        s = _u32(s - 0x9E3779B9)
    return struct.pack("<%dI" % n, *v)


def decode(buf: bytes, path: str = "") -> bytes:
    if not buf.startswith(SIG):
        return buf
    c = buf[len(SIG):]
    if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return xxtea_decrypt(c, KEY)
    return bytes(c[i] ^ KEY[i % len(KEY)] for i in range(len(c)))


def read(path: str) -> bytes:
    return decode(open(path, "rb").read(), path)


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


def find_record(obj):
    res = {}

    def walk(o):
        if isinstance(o, list):
            if (len(o) >= 4 and isinstance(o[1], str) and o[2] == ".bin"
                    and isinstance(o[3], str) and "size:" in o[3]):
                res[o[1]] = {"atlas": o[3],
                             "pages": (o[4] if len(o) > 4 else []) or [],
                             "textures": (o[5] if len(o) > 5 else []) or []}
            for x in o:
                walk(x)
    walk(obj)
    return res


def index_native(root):
    idx = {}
    for f in glob.glob(os.path.join(root, "native", "*", "*")):
        u = os.path.basename(f).split(".")[0]
        if len(u) == 36:
            idx[u] = f
    return idx


def build_import_map(pack_dir):
    """nama skeleton -> record, dari semua import json (nama file != uuid)."""
    m = {}
    files = glob.glob(os.path.join(pack_dir, "import", "*", "*.json"))
    for i, f in enumerate(files, 1):
        try:
            obj = json.loads(read(f).decode("utf-8", "replace"))
            m.update(find_record(obj))
        except Exception:
            continue
    return m


def page_sizes(atlas_text):
    """Kembalikan [(page_name, (W,H)), ...] dari teks atlas."""
    out = []
    lines = atlas_text.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.lower().endswith(".png") and " " not in s and not ln.startswith((" ", "\t")):
            w = h = 0
            for j in range(i + 1, min(i + 4, len(lines))):
                t = lines[j].strip()
                if t.startswith("size:"):
                    try:
                        a, b = t[5:].split(",")
                        w, h = int(float(a)), int(float(b))
                    except Exception:
                        pass
                    break
            out.append((s, (w, h)))
    return out


def do_pack(args):
    assets_root, pack, out_root, texindex = args
    pack_dir = os.path.join(assets_root, pack)
    cfg_file = os.path.join(pack_dir, "config.json")
    if not os.path.exists(cfg_file):
        return (pack, 0, 0, "no config")
    cfg = json.loads(read(cfg_file).decode("utf-8", "replace"))
    types, uuids, paths = cfg["types"], cfg["uuids"], cfg["paths"]
    if "sp.SkeletonData" not in types:
        return (pack, 0, 0, "no sp.SkeletonData")
    ti = types.index("sp.SkeletonData")

    log(f"[{pack}] indeks import...")
    imap = build_import_map(pack_dir)
    nat = index_native(pack_dir)
    log(f"[{pack}] import records: {len(imap)}  native: {len(nat)}")

    # index dimensi native png (uuid tidak berkorelasi dgn config)
    tex = {}
    if texindex:
        tex = json.load(open(texindex))

    ok = fail = 0
    fails = []
    for k, v in paths.items():
        if v[1] != ti:
            continue
        path = v[0]
        name = path.split("/")[-1]
        i = int(k)
        u36 = decode_uuid(uuids[i]) if i < len(uuids) else None
        rec = imap.get(name)
        bin_path = nat.get(u36) if u36 else None
        if not rec or not bin_path:
            fail += 1
            fails.append(f"{path}: {'no-record' if not rec else ''}{'no-bin' if not bin_path else ''}")
            continue
        try:
            dest = Path(out_root) / pack / safe(path.replace("/", "_"))
            dest.mkdir(parents=True, exist_ok=True)
            stem = safe(name)
            (dest / f"{stem}.skel").write_bytes(open(bin_path, "rb").read())
            atlas = rec["atlas"]
            for pg in rec["pages"]:
                atlas = atlas.replace(pg, pg.rsplit(".", 1)[0] + ".png")
            (dest / f"{stem}.atlas").write_text(atlas, encoding="utf-8")
            # halaman: cocokkan lewat dimensi (tekstur boleh dipakai banyak model)
            for pg, (w, h) in page_sizes(atlas):
                if not w:
                    continue
                cands = tex.get(f"{w}x{h}", [])
                if len(cands) >= 1:
                    src = cands[0]
                    (dest / pg).write_bytes(decode(open(src, "rb").read(), src))
            ok += 1
        except Exception as e:
            fail += 1
            fails.append(f"{path}: {type(e).__name__} {e}")
    if fails:
        log(f"[{pack}] contoh gagal: {fails[:5]}")
    return (pack, ok, fail, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--packs", default="", help="filter pack (comma), mis. resources")
    ap.add_argument("--texindex", default="", help="texindex.py JSON utk cocokkan dimensi")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    packs = [d for d in os.listdir(args.assets)
             if os.path.isdir(os.path.join(args.assets, d))]
    if args.packs:
        want = set(args.packs.split(","))
        packs = [p for p in packs if p in want]
    log(f"pack: {packs}")
    tasks = [(args.assets, p, args.out, args.texindex) for p in packs]
    tot_ok = tot_fail = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for p, ok, fail, err in ex.map(do_pack, tasks):
            tot_ok += ok
            tot_fail += fail
            log(f"  {p:12} ok={ok:5} fail={fail:4} {err or ''}")
    log(f"SELESAI ok={tot_ok} fail={tot_fail}")


if __name__ == "__main__":
    main()
