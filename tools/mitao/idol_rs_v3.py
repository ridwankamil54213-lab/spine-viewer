#!/usr/bin/env python3
"""Dekripsi container IDOLRS1 / IDOLAB3 (IdolTime NativeResource v3).

Latar belakang
==============

Versi 2.48.3 memakai container `IDOLAB2` dengan AES-256-CBC + HMAC-SHA256
dan KDF HKDF berlabel `IdolTime/AssetBundle/v2/AES256CBC-HMACSHA256`.
Versi 2.50.1 mengganti seluruh skema: manifest sekarang dibungkus

    IDOLRS1\\0  <u32> <u32> <u32 plain_len> <u32>  IDOLAB3 <u32 3> ...

dan payload dienkripsi ChaCha20 dengan kunci turunan BLAKE2b.
Parser manifest lama gagal karena membaca `AssetCount` dari header yang kini
berisi magic + angka, sehingga keluar nilai acak (2086347518).

Hasil analisis libidol_resource_guard.so (REA/Ghidra)
=====================================================

  ir3_01(byte out[32])   -> menulis kunci material 32 byte:
                            ae8a925f02ff7c39 4e3c4a6a37cc3d61  (little-endian)

  derive(out32, state)   (FUN_00103608):
      k32 = DAT_1005d8 ^ DAT_1005b8        -> 32 byte material
      S   = blake2b_init(key=k32)          (FUN_001048c0)
      update(S, "IdolTime/NativeResource/v3", 26)
      update(S, state, 0x50)               (80 byte header blok)
      final(S, out32)                      (FUN_001064a4)

  nonce untuk ChaCha20 (ir3_03) dibentuk dari
      header[0x28..0x50] (40 byte) + u64(offset chunk) + u32(len chunk)
  sehingga tiap chunk memakai nonce berbeda; tidak ada counter block.

Catatan penting: `expand 32-byte k` dan pola konstanta `ih8Mih8`, `Jli(8`,
`*ij(8` di .rodata menunjukkan implementasi ChaCha20/Salsa20 (kemungkinan
monocypher). Salt/header 80 byte per berkas berasal dari blok IDOLAB3, jadi
dekripsi butuh header berkas itu utuh.
"""

from __future__ import annotations

import struct

# Material kunci dari ir3_01 (dua qword little-endian)
KEY_QWORD0 = 0x397CFF025F928AAE
KEY_QWORD1 = 0x613DCC376A4A3C4E

# Konstanta di .rodata yang di-XOR pada derive() untuk membentuk kunci BLAKE2b
DAT_1005B8 = bytes.fromhex("65eed96ead3392ed55c3665032380f0c887380e793b26af4e48ab23d987a49d1")
DAT_1005D8 = bytes.fromhex("2157f48866370ad2392a71cb8285a8a33644ed533ffa87c5158ab4755ed927aa")

KDF_PERSONAL = b"IdolTime/NativeResource/v3"

MAGIC_RS = b"IDOLRS1\x00"
MAGIC_AB = b"IDOLAB3"


def key_material() -> bytes:
    """32 byte material kunci seperti yang ditulis ir3_01."""
    return struct.pack("<QQ", KEY_QWORD0, KEY_QWORD1)


def kdf_seed() -> bytes:
    """Kunci BLAKE2b = DAT_1005d8 XOR DAT_1005b8."""
    return bytes(a ^ b for a, b in zip(DAT_1005D8, DAT_1005B8))


def parse_header(blob: bytes) -> dict:
    """Baca header IDOLRS1 + awal blok IDOLAB3."""
    if not blob.startswith(MAGIC_RS):
        raise ValueError(f"bukan container IDOLRS1 (magic={blob[:8]!r})")
    u32 = lambda o: struct.unpack_from("<I", blob, o)[0]
    hdr = {
        "magic": MAGIC_RS,
        "u32_8": u32(8),
        "u32_12": u32(12),
        "plain_len": u32(16),
        "u32_20": u32(20),
    }
    off = blob.find(MAGIC_AB)
    if off < 0:
        raise ValueError("blok IDOLAB3 tidak ditemukan")
    hdr["ab_offset"] = off
    hdr["ab_version"] = u32(off + 8)
    hdr["ab_u32_12"] = u32(off + 12)
    hdr["chunk_size"] = u32(off + 16)
    hdr["ab_reserved"] = u32(off + 20)
    hdr["ab_len"] = u32(off + 24)
    return hdr


def derive_key(header_block: bytes) -> bytes:
    """Kunci ChaCha20/BLAKE2b dari blok header 0x50 byte (lihat FUN_00103608)."""
    import hashlib

    seed = kdf_seed()
    h = hashlib.blake2b(digest_size=32, key=seed)
    h.update(KDF_PERSONAL)
    h.update(header_block[:0x50])
    return h.digest()


if __name__ == "__main__":
    import sys

    blob = open(sys.argv[1], "rb").read()
    hdr = parse_header(blob)
    for k, v in hdr.items():
        print(f"  {k}: {v if not isinstance(v, bytes) else v!r}")
    print()
    print("key material :", key_material().hex())
    print("kdf seed     :", kdf_seed().hex())
    blk = blob[hdr["ab_offset"] : hdr["ab_offset"] + 0x50]
    print("header block :", blk.hex())
    print("derived key  :", derive_key(blk).hex())
