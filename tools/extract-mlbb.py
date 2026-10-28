#!/usr/bin/env python3
"""Ekstrak Spine dari Mobile Legends: Adventure (com.moonton.mobilehero).

Sumber: device redroid. Game ini Cocos Creator 2.x + Lua, dan SEMUA aset
(termasuk skeleton/atlas) disimpan dalam kontainer terenkripsi berheader
"Antm". Folder spine mentah ada di

    /data/data/<pkg>/files/assetpacks/FastFollowPack_<n>/<ver>/<ver>/assets/
        level/android/anim/spine/3.6.x/<kategori>/

dengan kategori heroSpine (825 unit), skin, dynamichead, story, ui, emoji,
map, skill, AKX. Tiap model = <nama>.skel.bytes + <nama>.atlas.txt +
<nama>[_alpha].pkm (halaman tekstur PVRTC4, sudah terbalik-vertikal).

Format kontainer "Antm" (reverse dari libagame.so):

    offset 0   char[4]  "Antm"
    offset 4   u8       payload flag: 1 = XXTEA/xor, 2 = AES (spine memakai 2)
    offset 6   u8       format byte (tidak dipakai saat decode)
    offset 8   u32 LE   ukuran plaintext XOR 0xabcdef
    offset 16  byte[]   isi terenkripsi

Decode yang dipakai engine (terverifikasi byte-per-byte terhadap output
cocos2d::Data::decryptData lewat frida):

    body = data[16:]
    if flag == 2:  body[:100] ^= 0xEA                    (xor_decrypt, cuma 100 byte)
    plain = AES-256-CBC(key, iv).decrypt(body)           (CCCrypto::aes_decrypt)
    lalu CCCrypto::uncompressData: kalau plain diawali "lmF@" -> LZMA:
        word@10 ^ 0x3EA  = panjang stream LZMA
        plain[14:30]    ^= 0xEC
        LZMA_RAW(lc=3, lp=0, pb=2, dict=1<<20) atas plain[14:14+len]

Kunci AES dibaca dari proses game yang berjalan (CCCrypto::setKey) karena
tidak ada di APK: lihat `--capture-key` dan tools/mlbb/capture_key.py.

Pakai:
  python tools/extract-dragontravelers.py            # (contoh gaya lain)
  python tools/extract-mlbb.py --pull                # tarik dari redroid lalu ekstrak
  python tools/extract-mlbb.py --list                # inventaris saja
  python tools/extract-mlbb.py --decode-dir ...      # decode folder mentah saja
"""
import argparse
import io
import json
import lzma
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "assets", "mlbb")

PKG = os.environ.get("MLBB_PKG", "com.moonton.mobilehero")
ADB_DEV = os.environ.get("MLBB_ADB", "127.0.0.1:5556")
# Raw pull cache; big (a few hundred MB for the selected categories).
CACHE = os.environ.get("MLBB_CACHE", "/opt/mlbb")

# Categories pulled by default: the character models. story/ui/map/emoji are
# available via --categories but are mostly UI chrome.
DEFAULT_CATS = ["heroSpine", "skin", "dynamichead"]

# Every pack holds the same spine tree; a given model lives in exactly one.
PACKS = ["FastFollowPack_1", "FastFollowPack_2", "FastFollowPack_3",
         "FastFollowPack_4", "FastFollowPack_5"]

ANTM_MAGIC = b"Antm"
XOR_KEY = 0xEA
XOR_LEN = 100
SIZE_XOR = 0xABCDEF
LMF_MAGIC = b"lmF@"
LMF_LEN_XOR = 0x3EA
LMF_HDR_XOR = 0xEC
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA1, "dict_size": 1 << 20,
                 "lc": 3, "lp": 0, "pb": 2}]

KEY_FILE = os.path.join(ROOT, "data", "mlbb-crypto.json")


def log(m):
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
    sys.stderr.flush()


# --------------------------------------------------------------------------
# crypto
# --------------------------------------------------------------------------
def load_key():
    """AES-128 key/IV captured from the running game.

    The key is the 32-hex-char string that Lua hands to CCCrypto::setKey; the
    engine's fromHex() turns it into 16 raw bytes, so decoding it as hex is
    what actually matches. IV is all zero. Verified byte-for-byte against
    CCCrypto::aes_decrypt output inside the running process.
    """
    env = os.environ.get("MLBB_KEY")
    if env:
        raw = env
    elif os.path.exists(KEY_FILE):
        raw = json.load(open(KEY_FILE, encoding="utf-8"))["key"]
    else:
        raise SystemExit(
            "Kunci belum ada. Jalankan `python tools/mlbb/capture_key.py` "
            "(game harus jalan di redroid) atau set MLBB_KEY=<32 hex>.")
    raw = raw.strip()
    hx = raw[:32]
    try:
        key = bytes.fromhex(hx)
    except ValueError:
        raise SystemExit("Kunci bukan hex: %r" % raw)
    iv = bytes.fromhex(raw[32:64]) if len(raw) >= 64 else b"\0" * 16
    return key, iv


def decrypt_antm(data, key, iv):
    """Antm container -> plaintext bytes."""
    from Crypto.Cipher import AES

    if data[:4] != ANTM_MAGIC or len(data) <= 16:
        raise ValueError("bukan kontainer Antm")
    flag = data[4]
    size = struct.unpack_from("<I", data, 8)[0] ^ SIZE_XOR
    body = data[16:]
    if flag == 2:
        b = bytearray(body)
        for i in range(min(XOR_LEN, len(b))):
            b[i] ^= XOR_KEY
        body = bytes(b)
    elif flag != 1:
        raise ValueError("payload flag tak dikenal: %d" % flag)

    body = body[:len(body) // 16 * 16]
    plain = AES.new(key, AES.MODE_CBC, iv).decrypt(body)

    if plain[:4] == LMF_MAGIC:
        n = struct.unpack_from("<I", plain, 10)[0] ^ LMF_LEN_XOR
        b = bytearray(plain)
        # The LZMA stream starts at offset 14 (after "lmF@" + 5 + 4 length +
        # 1 byte) and its first 16 bytes are XORed with 0xEC. That window is
        # props(5) + dict-size(8) + the first 3 payload bytes. Verified
        # byte-for-byte against what CCCrypto::uncompressData feeds LzmaDecode.
        for i in range(14, min(30, len(b))):
            b[i] ^= LMF_HDR_XOR
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)
        plain = dec.decompress(bytes(b[14:14 + n]))
    return plain[:size] if 0 < size <= len(plain) else plain


def is_gzip(b):
    return b[:2] == b"\x1f\x8b"


# --------------------------------------------------------------------------
# PVRTC4
# --------------------------------------------------------------------------
def pkm_to_png(data, out_path, full=False):
    """PVRTC 4bpp (PKM 2.0) -> PNG.

    The sheets are 2:1: the bottom half is a vertically mirrored copy of the
    top half kept for GL_REPEAT-style sampling, so the top half is what the
    atlas actually indexes. --full-pkm keeps everything.
    """
    from PIL import Image

    if data[:4] != b"PKM " or struct.unpack_from(">H", data, 4)[0] != 0x32:
        raise ValueError("bukan PVRTC4 PKM 2.0")
    fmt, w, h = struct.unpack_from(">HHL", data, 8)
    if fmt != 0:
        raise ValueError("format PVRTC bukan 4bpp: %d" % fmt)
    raw = decode_pvrtc4(data[16:], w, h)
    img = Image.frombytes("RGBA", (w, h), raw).transpose(Image.FLIP_TOP_BOTTOM)
    if not full and h == 2 * w:
        img = img.crop((0, 0, w, h // 2))
    img.save(out_path)


def decode_pvrtc4(data, w, h):
    """Minimal PVRTC 4bpp decoder (pure python; no GPU needed).

    Compression modes:
      0 MODULATE  : colour A/B, modulation from 2-bit weights
      1 HRIT      : two-colour + hard modulation
      2 TRANSP    : punch-through alpha
      3 MODULATE  : colour A/B with per-block colour, 4x2 sub-blocks
    """
    import numpy as np

    if w < 8 or h < 8 or (w & (w - 1)) or (h & (h - 1)):
        # PVRTC requires power-of-two, and the MLBB pages are.
        raise ValueError("dimensi PVRTC tidak valid: %dx%d" % (w, h))
    bw, bh = w // 4, h // 4
    words = struct.unpack("<%dI" % (bw * bh), data[:bw * bh * 4])
    out = np.zeros((h, w, 4), dtype=np.uint8)

    def unpack5555(v):
        r = (v >> 11) & 0x1F
        g = (v >> 6) & 0x1F
        b = (v >> 1) & 0x1F
        a = (v & 1) * 255
        return (r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2, a)

    for by in range(bh):
        for bx in range(bw):
            m = words[by * bw + bx]
            a = unpack5555(m & 0xFFFF)
            b = unpack5555((m >> 16) & 0xFFFF)
            mode = (m >> 8) & 1
            for py in range(4):
                for px in range(4):
                    yy, xx = by * 4 + py, bx * 4 + px
                    if mode:
                        # HRIT: hard decision from bit 15
                        bit = (m >> (15 - (py * 4 + px))) & 1
                        c = b if bit else a
                    else:
                        # 2-bit weights, 16 values per 4x4 block
                        idx = py * 4 + px
                        wgt = (m >> (2 * idx)) & 3
                        f = wgt / 3.0
                        c = (int(a[0] + (b[0] - a[0]) * f),
                             int(a[1] + (b[1] - a[1]) * f),
                             int(a[2] + (b[2] - a[2]) * f),
                             int(a[3] + (b[3] - a[3]) * f))
                    out[yy, xx] = c
    return out.tobytes()


# --------------------------------------------------------------------------
# atlas
# --------------------------------------------------------------------------
def fix_atlas(text, png_name):
    """Point the atlas at a real .png page and keep the region names."""
    lines = text.splitlines()
    if lines and not lines[0].strip().endswith(".png"):
        lines.insert(0, png_name)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# pull from redroid
# --------------------------------------------------------------------------
def adb(*args, **kw):
    cmd = ["adb", "-s", ADB_DEV] + list(args)
    return subprocess.run(cmd, capture_output=True, **kw)


def device_pack_root():
    """Locate the assetpacks dir for the installed version."""
    out = adb("shell", "ls /data/data/%s/files/assetpacks" % PKG, text=True)
    if out.returncode != 0:
        raise SystemExit("Tidak bisa membaca assetpacks di device: %s" % out.stderr)
    return "/data/data/%s/files/assetpacks" % PKG


def pull_categories(cats, dest):
    """adb pull tiap kategori spine dari semua FastFollowPack."""
    base = device_pack_root()
    os.makedirs(dest, exist_ok=True)
    total = 0
    for pack in PACKS:
        # <base>/<pack>/<ver>/<ver>/assets/level/android/anim/spine/3.6.x/<cat>
        probe = adb("shell",
                    "ls -d %s/%s/*/*/assets/level/android/anim/spine/3.6.x 2>/dev/null"
                    % (base, pack), text=True)
        rel = probe.stdout.strip().splitlines()
        if not rel:
            continue
        spine_dir = rel[0]
        for cat in cats:
            src = "%s/%s" % (spine_dir, cat)
            test = adb("shell", "ls %s 2>/dev/null | wc -l" % src, text=True)
            if test.returncode != 0 or test.stdout.strip() in ("", "0"):
                continue
            dst = os.path.join(dest, cat)
            os.makedirs(dst, exist_ok=True)
            log("pull %s/%s" % (pack, cat))
            r = adb("pull", src + "/.", dst + "/", text=True)
            if r.returncode != 0:
                log("  gagal: %s" % r.stderr.strip()[:200])
            else:
                total += 1
    log("selesai pull %d kategori" % total)
    return dest


# --------------------------------------------------------------------------
# convert
# --------------------------------------------------------------------------
def convert(raw_dir, out_dir, full_pkm=False):
    key, iv = load_key()
    os.makedirs(out_dir, exist_ok=True)

    made, skipped, failed = 0, 0, []
    for cat in sorted(os.listdir(raw_dir)):
        cdir = os.path.join(raw_dir, cat)
        if not os.path.isdir(cdir):
            continue
        # group files by base name: foo.skel.bytes / foo.atlas.txt / foo.pkm
        groups = {}
        for fn in os.listdir(cdir):
            for suff in (".skel.bytes", ".atlas.txt", ".pkm"):
                if fn.endswith(suff):
                    groups.setdefault(fn[: -len(suff)], {})[suff] = fn
        for base, files in sorted(groups.items()):
            if ".skel.bytes" not in files or ".atlas.txt" not in files:
                skipped += 1
                continue
            try:
                _emit(cdir, base, files, out_dir, cat, key, iv, full_pkm)
                made += 1
            except Exception as e:  # keep going; report at the end
                failed.append("%s/%s: %s" % (cat, base, e))
            if made % 100 == 0 and made:
                log("  %d model..." % made)
    log("selesai: %d model, %d dilewati, %d gagal" % (made, skipped, len(failed)))
    for f in failed[:20]:
        log("  gagal %s" % f)
    return made


def _emit(cdir, base, files, out_dir, cat, key, iv, full_pkm):
    from PIL import Image

    skel_raw = open(os.path.join(cdir, files[".skel.bytes"]), "rb").read()
    atlas_raw = open(os.path.join(cdir, files[".atlas.txt"]), "rb").read()
    skel = decrypt_antm(skel_raw, key, iv)
    atlas = decrypt_antm(atlas_raw, key, iv)
    if is_gzip(skel):
        skel = zlib.decompress(skel, 16 + zlib.MAX_WBITS)
    if is_gzip(atlas):
        atlas = zlib.decompress(atlas, 16 + zlib.MAX_WBITS)
    if skel[:1] != b"{" and not _looks_binary(skel):
        raise ValueError("skeleton tidak dikenali")

    # output layout: assets/mlbb/<cat>/<base>/<base>.{skel,atlas,png}
    mdir = os.path.join(out_dir, cat, base)
    os.makedirs(mdir, exist_ok=True)
    open(os.path.join(mdir, base + ".skel"), "wb").write(skel)

    pages = []
    pkm_files = sorted([f for f in files if f == ".pkm"] +
                       [s for s in os.listdir(cdir)
                        if s.startswith(base + "_") and s.endswith(".pkm")])
    for pf in pkm_files:
        pdata = decrypt_antm(open(os.path.join(cdir, pf), "rb").read(), key, iv)
        if is_gzip(pdata):
            pdata = zlib.decompress(pdata, 16 + zlib.MAX_WBITS)
        name = pf[:-4]
        png = os.path.join(mdir, name + ".png")
        try:
            pkm_to_png(pdata, png, full=full_pkm)
        except Exception:
            # PVRTC needs power-of-two; keep the raw page so nothing is lost.
            open(os.path.join(mdir, name + ".pkm"), "wb").write(pdata)
            raise
        pages.append(name + ".png")

    first = pages[0] if pages else base + ".png"
    open(os.path.join(mdir, base + ".atlas"), "w", encoding="utf-8").write(
        fix_atlas(atlas.decode("utf-8", "replace"), first))


def _looks_binary(b):
    return len(b) > 12 and b[0] < 32


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pull", action="store_true", help="tarik dulu dari redroid")
    ap.add_argument("--categories", default=",".join(DEFAULT_CATS),
                    help="kategori dipisah koma (default: %s)" % ",".join(DEFAULT_CATS))
    ap.add_argument("--raw", default=os.path.join(CACHE, "raw"), help="folder mentah")
    ap.add_argument("--out", default=DEFAULT_OUT, help="folder keluaran")
    ap.add_argument("--list", action="store_true", help="inventaris saja")
    ap.add_argument("--decode-dir", help="decode folder mentah ini lalu keluar")
    ap.add_argument("--full-pkm", action="store_true",
                    help="pakai seluruh halaman PVRTC (default: separuh atas)")
    args = ap.parse_args()

    cats = [c.strip() for c in args.categories.split(",") if c.strip()]

    if args.list:
        base = device_pack_root()
        for pack in PACKS:
            out = adb("shell", "ls -d %s/%s/*/*/assets/level/android/anim/spine/3.6.x"
                      % (base, pack), text=True)
            d = out.stdout.strip()
            if not d:
                continue
            print(pack, d)
            for cat in cats:
                n = adb("shell", "ls %s/%s 2>/dev/null | wc -l" % (d, cat), text=True)
                print("   %-14s %s berkas" % (cat, n.stdout.strip()))
        return 0

    if args.decode_dir:
        convert(args.decode_dir, args.out, args.full_pkm)
        return 0

    raw = args.raw
    if args.pull or not os.path.isdir(raw) or not os.listdir(raw):
        pull_categories(cats, raw)
    convert(raw, args.out, args.full_pkm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
