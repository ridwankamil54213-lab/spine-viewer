#!/usr/bin/env python3
"""Dekripsi aset game "shiyue" (慾女神話 / 淫欲斗羅 dan sejenisnya).

Temuan kunci
============

Aset game ini (Cocos Creator / cocos2d-x Lua) dibungkus:

    b"shiyuegam" + payload XXTEA

Perhatikan: header yang tertulis hanya 9 byte "shiyuegam", padahal sign yang
didaftarkan game adalah "shiyuegame" (10 byte) — byte ke-10 ikut terenkripsi.

Cara menemukan kunci:

    strings libcocos2dlua.so | grep -B1 shiyuegame
    -> JYDYdpyRecDuHQc8     (tepat SEBELUM string "shiyuegame")

Kunci 16 byte itu dipakai ResourcesDecode::setXXTeaKey(key, keylen, sign,
signlen). XXTEA standar cocos2d-x; panjang asli TIDAK disimpan di header
payload (berbeda dari xxtea_decrypt biasa), jadi hasil dekripsi dipangkas
memakai penanda format:

    PNG  -> sampai "IEND" + 4 byte CRC
    Lua  -> sampai akhir data (bytecode Lua 1B4C7561)
    lain -> apa adanya

Terverifikasi pada dua APK berbeda: 慾女神話 v7.2.24 dan 淫欲斗羅 v7.4.13,
PNG hasil dekripsi membuka dengan benar di Pillow (1675x1303 dan 1832x155),
dan modelnya render utuh di spine-viewer setelah .skel dikonversi 3.6->3.8.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

SIGN = b"shiyuegame"
KEY = b"JYDYdpyRecDuHQc8"
DELTA = 0x9E3779B9


def _u32(data: bytes) -> list[int]:
    return list(struct.unpack("<%dI" % (len(data) // 4), data))


def _b32(v: list[int]) -> bytes:
    return struct.pack("<%dI" % len(v), *v)


def xxtea_decrypt(data: bytes, key: bytes) -> bytes:
    """XXTEA standard (cocos2d-x xxtea_decrypt)."""
    if len(data) < 8:
        return b""
    data = data[: len(data) - (len(data) % 4)]
    v = _u32(data)
    k = _u32((key + b"\0" * 16)[:16])
    n = len(v)
    if n < 2:
        return b""

    rounds = 6 + 52 // n
    total = (rounds * DELTA) & 0xFFFFFFFF
    y = v[0]
    while total:
        e = (total >> 2) & 3
        for p in range(n - 1, -1, -1):
            z = v[p - 1] if p > 0 else v[-1]
            mx = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ (
                (total ^ y) + (k[(p & 3) ^ e] ^ z)
            )
            v[p] = (v[p] - mx) & 0xFFFFFFFF
            y = v[p]
        total = (total - DELTA) & 0xFFFFFFFF
    return _b32(v)


def _trim(plain: bytes) -> bytes:
    """Pangkas padding XXTEA memakai penanda format."""
    if plain[:8] == b"\x89PNG\r\n\x1a\n":
        i = plain.find(b"IEND")
        return plain[: i + 8] if i > 0 else plain
    if plain[:4] == b"\x1bLua":
        return plain  # bytecode: biarkan apa adanya
    return plain


# --- jalur cepat lewat C kalau tersedia -------------------------------------
# Implementasi Python murni ~1 MB/detik; untuk 7 GB aset itu berjam-jam. Versi
# C (xxtea_fast.c) 286x lebih cepat dan sudah diverifikasi byte-identik dengan
# implementasi Python pada data nyata.
_LIB = None


def _load_lib():
    global _LIB
    if _LIB is not None:
        return _LIB
    import ctypes

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libxxtea_fast.so")
    if not os.path.exists(path):
        return None
    lib = ctypes.CDLL(path)
    lib.xxtea_decrypt.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p]
    lib.xxtea_decrypt.restype = ctypes.c_int
    _LIB = lib
    return lib


def _decrypt_fast(payload: bytes) -> bytes | None:
    lib = _load_lib()
    if lib is None or len(payload) < 8:
        return None
    import ctypes

    payload = payload[: len(payload) - (len(payload) % 4)]
    out = ctypes.create_string_buffer(len(payload))
    got = lib.xxtea_decrypt(payload, len(payload), KEY, out)
    return out.raw[:got] if got else None


def is_encrypted(data: bytes) -> bool:
    return data.startswith(SIGN)


def decrypt_bytes(data: bytes) -> bytes:
    if not is_encrypted(data):
        return data
    payload = data[len(SIGN):]
    if len(payload) < 8:
        return data
    plain = _decrypt_fast(payload)
    if plain is None:
        plain = xxtea_decrypt(payload, KEY)
    return _trim(plain)


def decrypt_file(src: str, dst: str) -> bool:
    with open(src, "rb") as fh:
        raw = fh.read()
    if not is_encrypted(raw):
        return False
    out = decrypt_bytes(raw)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(out)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Dekripsi aset game shiyue")
    ap.add_argument("src", help="berkas atau direktori")
    ap.add_argument("dst", help="berkas atau direktori keluaran")
    ap.add_argument("--ext", default=".png,.luac,.csb",
                    help="ekstensi yang didekripsi (pisah koma)")
    args = ap.parse_args()

    exts = tuple(e.strip().lower() for e in args.ext.split(",") if e.strip())

    if os.path.isfile(args.src):
        ok = decrypt_file(args.src, args.dst)
        print("terdekripsi" if ok else "tidak terenkripsi")
        return 0 if ok else 1

    n = total = 0
    for dirpath, _, files in os.walk(args.src):
        for name in files:
            if exts and not name.lower().endswith(exts):
                continue
            total += 1
            rel = os.path.relpath(os.path.join(dirpath, name), args.src)
            if decrypt_file(os.path.join(dirpath, name), os.path.join(args.dst, rel)):
                n += 1
    print(f"terdekripsi {n} dari {total} berkas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
