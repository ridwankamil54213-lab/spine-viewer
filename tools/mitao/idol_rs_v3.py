#!/usr/bin/env python3
"""Dekripsi container IDOLNAB3 v3 (蜜桃乌托邦 2.50.1) — Python murni.

Latar belakang / sumber
=======================

Ekstrak `lib/arm64-v8a/libidol_resource_guard.so` dari APK 2.50.1 lewat HTTP
Range (tanpa unduh 198 MB), lalu dekompilasi Ghidra. Image base 0x100000, jadi
alamat Ghidra = offset berkas + 0x100000. Ekspor: ir3_01/ir3_02/ir3_03.

  ir3_01 (0x1033e8) : tulis 16 byte material kunci.
  ir3_02 (0x103410) : validasi header + hitung ukuran plain.
  ir3_03 (0x103710) : dekripsi satu chunk 64 KiB.
  FUN_001034d0      : validator header (magic, versi, chunk, hash nama berkas).
  FUN_00103608      : KDF BLAKE2b + verifikasi tag header.
  FUN_001039f8      : HChaCha20.
  FUN_00103d9c      : ChaCha20 (counter 64-bit + nonce 8 byte, monocypher).
  FUN_00110d4c      : Poly1305 RFC 8439 (pad16 AD/CT + LE64 panjang).
  FUN_0010654c      : BLAKE2b-128 untuk hash nama berkas.

Skema (XChaCha20-Poly1305 per chunk)
====================================

Header 0x60 = 96 byte::

    0x00  b"IDOLNAB3"           magic
    0x08  u32 3                 versi
    0x0C  u32 0x10000           ukuran chunk
    0x10  u64 plain_len         panjang plaintext
    0x18  16 byte               KEY_MATERIAL (ir3_01 / DAT_001005a0)
    0x28  24 byte               nonce XChaCha20
    0x40  16 byte               BLAKE2b-128(nama_berkas)
    0x50  16 byte               tag header (Poly1305, AD = header[0:0x50])

Lalu per chunk i = 0..ceil(plain_len/0x10000)-1::

    ciphertext[chunk_len] || tag[16]

* Kunci: ``BLAKE2b(key=KDF_SEED, data=PERSONAL + header[0:0x50],
  digest_size=32)``. KDF_SEED = DAT_001005d8 XOR DAT_001005b8.
* Subkey = HChaCha20(kunci, nonce[0:16]); nonce ChaCha20 = nonce[16:24].
* nonce chunk = header[0x28:0x38] + LE64(u64(header[0x38:0x40]) ^ (i+1)).
* AD chunk = header[0:0x60] + LE64(i) + LE32(chunk_len).
* otk = blok ChaCha20 counter 0 [0:32]; tag = Poly1305(otk, AD, ciphertext).
* plaintext = ChaCha20 counter 1 XOR ciphertext (verifikasi tag dulu).

CATATAN PENTING — MANIFEST MASIH BLOKIR
======================================

Ini menyelesaikan dekripsi **bundle** (`IDOLNAB3`). Berkas
`PackageManifest_DefaultPackage_2.50.1.bytes` memakai container BERBEDA:

    0x00  b"IDOLRS1\\0" + 4 u32   (24 byte wrapper)
    0x18  container IDOLAB2 v2    (magic/versi 2/key_id 1/chunk 0x10000/
                                   plain_len/salt 32/name_hash 32/tag 32)
    ...   384 byte trailer high-entropy (kemungkinan tanda tangan RSA-3072)

`mitao_api.decrypt_bundle()` (v2) TIDAK bisa dipakai: HMAC header gagal dengan
MASTER_KEY_HEX 2.48.3 -> kunci master v2 dirotasi. Kunci baru tidak ada di
`libidol_resource_guard.so` maupun string `libil2cpp.so`. Selama kunci itu
belum ketemu, manifest tidak bisa dibaca -> daftar BundleName/FileHash tidak
tersedia -> `--apply` tetap diblokir oleh `tools/update-mitao.py`.

Jalankan ``python3 tools/mitao/idol_rs_v3.py --self-test`` untuk uji round-trip.
"""
from __future__ import annotations

import hashlib
import hmac
import struct
import sys

# --- konstanta dari .rodata libidol_resource_guard.so ------------------------
MAGIC = b"IDOLNAB3"
HEADER_SIZE = 0x60
CHUNK_SIZE = 0x10000
TAG_SIZE = 16
PERSONAL = b"IdolTime/NativeResource/v3"
KEY_MATERIAL = struct.pack("<QQ", 0x397CFF025F928AAE, 0x613DCC376A4A3C4E)
DAT_1005B8 = bytes.fromhex(
    "65eed96ead3392ed55c3665032380f0c887380e793b26af4e48ab23d987a49d1")
DAT_1005D8 = bytes.fromhex(
    "2157f48866370ad2392a71cb8285a8a33644ed533ffa87c5158ab4755ed927aa")
KDF_SEED = bytes(a ^ b for a, b in zip(DAT_1005D8, DAT_1005B8))
SIGMA = b"expand 32-byte k"
MASK32 = 0xFFFFFFFF

# Kompatibilitas dengan catatan RE lama (nama simbol dipertahankan).
MAGIC_RS = b"IDOLRS1\x00"      # wrapper manifest, bukan container ini
MAGIC_AB = MAGIC               # dulu keliru disebut IDOLAB3
KEY_QWORD0 = 0x397CFF025F928AAE
KEY_QWORD1 = 0x613DCC376A4A3C4E
KDF_PERSONAL = PERSONAL


def _rotl(v: int, n: int) -> int:
    return ((v << n) & MASK32) | (v >> (32 - n))


def _qr(s: list, a: int, b: int, c: int, d: int) -> None:
    s[a] = (s[a] + s[b]) & MASK32
    s[d] ^= s[a]
    s[d] = _rotl(s[d], 16)
    s[c] = (s[c] + s[d]) & MASK32
    s[b] ^= s[c]
    s[b] = _rotl(s[b], 12)
    s[a] = (s[a] + s[b]) & MASK32
    s[d] ^= s[a]
    s[d] = _rotl(s[d], 8)
    s[c] = (s[c] + s[d]) & MASK32
    s[b] ^= s[c]
    s[b] = _rotl(s[b], 7)


def _rounds(state: list) -> None:
    for _ in range(10):
        _qr(state, 0, 4, 8, 12)
        _qr(state, 1, 5, 9, 13)
        _qr(state, 2, 6, 10, 14)
        _qr(state, 3, 7, 11, 15)
        _qr(state, 0, 5, 10, 15)
        _qr(state, 1, 6, 11, 12)
        _qr(state, 2, 7, 8, 13)
        _qr(state, 3, 4, 9, 14)


def key_material() -> bytes:
    """16 byte material kunci dari ir3_01 (dulu keliru disebut 32 byte)."""
    return KEY_MATERIAL


def kdf_seed() -> bytes:
    return KDF_SEED


def hchacha20(key: bytes, nonce16: bytes) -> bytes:
    """HChaCha20: 20 putaran, TANPA menjumlahkan state awal, keluar 8 word."""
    if len(key) != 32 or len(nonce16) != 16:
        raise ValueError("kunci harus 32 byte, nonce HChaCha 16 byte")
    s = list(struct.unpack("<4I", SIGMA)) + list(struct.unpack("<8I", key)) \
        + list(struct.unpack("<4I", nonce16))
    _rounds(s)
    return struct.pack("<8I", s[0], s[1], s[2], s[3], s[12], s[13], s[14], s[15])


def chacha20_block(subkey: bytes, counter: int, nonce8: bytes) -> bytes:
    """Satu blok 64 byte ChaCha20 monocypher (counter 64-bit, nonce 8 byte)."""
    s = list(struct.unpack("<4I", SIGMA)) + list(struct.unpack("<8I", subkey))
    s += [counter & MASK32, (counter >> 32) & MASK32]
    s += list(struct.unpack("<2I", nonce8))
    orig = list(s)
    _rounds(s)
    return struct.pack("<16I", *[(s[i] + orig[i]) & MASK32 for i in range(16)])


def chacha20_xor(subkey: bytes, counter: int, nonce8: bytes, data: bytes) -> bytes:
    """Aliran ChaCha20 mulai dari `counter` (increment per blok 64 byte)."""
    out = bytearray()
    for off in range(0, len(data), 64):
        ks = chacha20_block(subkey, counter + off // 64, nonce8)
        part = data[off:off + 64]
        out.extend(bytes(a ^ b for a, b in zip(part, ks)))
    return bytes(out)


def poly1305_tag(otk: bytes, ad: bytes, ct: bytes) -> bytes:
    """Poly1305 RFC 8439: pad16(AD) || pad16(CT) || LE64(len AD) || LE64(len CT)."""
    r = int.from_bytes(otk[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(otk[16:32], "little")
    p = (1 << 130) - 5
    buf = ad + b"\0" * (-len(ad) % 16) + ct + b"\0" * (-len(ct) % 16)
    buf += struct.pack("<QQ", len(ad), len(ct))
    acc = 0
    for off in range(0, len(buf), 16):
        n = int.from_bytes(buf[off:off + 16] + b"\x01", "little")
        acc = ((acc + n) * r) % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def derive_key(header: bytes) -> bytes:
    """BLAKE2b keyed: FUN_00103608."""
    return hashlib.blake2b(PERSONAL + header[:0x50], key=KDF_SEED,
                           digest_size=32).digest()


# Alias untuk catatan lama: `header_block` = header[0:0x50].
def derive_key_from_block(header_block: bytes) -> bytes:
    return hashlib.blake2b(PERSONAL + header_block[:0x50], key=KDF_SEED,
                           digest_size=32).digest()


def name_hash(filename: str) -> bytes:
    """BLAKE2b-128 dari nama berkas: FUN_0010654c / FUN_001067c4."""
    return hashlib.blake2b(filename.encode(), digest_size=16).digest()


def _nonce_for(nonce24: bytes, index: int) -> bytes:
    tail = struct.unpack("<Q", nonce24[16:24])[0] ^ (index + 1)
    return nonce24[:16] + struct.pack("<Q", tail)


def _ad_for(header: bytes, index: int, chunk_len: int) -> bytes:
    return header[:HEADER_SIZE] + struct.pack("<QI", index, chunk_len)


def _header_tag(key: bytes, nonce24: bytes, header: bytes) -> bytes:
    sub = hchacha20(key, nonce24[:16])
    otk = chacha20_block(sub, 0, nonce24[16:24])[:32]
    return poly1305_tag(otk, header[:0x50], b"")


def _chunk_tag(key: bytes, nonce24: bytes, header: bytes, index: int,
               ct: bytes) -> bytes:
    sub = hchacha20(key, nonce24[:16])
    otk = chacha20_block(sub, 0, nonce24[16:24])[:32]
    return poly1305_tag(otk, _ad_for(header, index, len(ct)), ct)


def parse_header(blob: bytes) -> dict:
    """Baca + validasi header IDOLNAB3 (setara FUN_001034d0 + ir3_02)."""
    if len(blob) < HEADER_SIZE or blob[:8] != MAGIC:
        raise ValueError(f"bukan container {MAGIC.decode()} (magic={blob[:8]!r})")
    ver, chunk = struct.unpack_from("<II", blob, 0x08)
    if ver != 3 or chunk != CHUNK_SIZE:
        raise ValueError(f"versi/chunk tidak didukung: {ver}/{chunk:#x}")
    plain_len = struct.unpack_from("<Q", blob, 0x10)[0]
    if plain_len >= 0x200000001:
        raise ValueError("plain_len tidak wajar")
    if blob[0x18:0x28] != KEY_MATERIAL:
        raise ValueError("material kunci header tidak cocok (bukan rilis ini?)")
    nonce = blob[0x28:0x40]
    chunks = (plain_len + CHUNK_SIZE - 1) // CHUNK_SIZE
    expected = HEADER_SIZE + plain_len + chunks * TAG_SIZE
    if len(blob) != expected:
        raise ValueError(f"ukuran berkas {len(blob)} != {expected}")
    return {
        "magic": MAGIC, "version": ver, "chunk_size": chunk,
        "plain_len": plain_len, "nonce": nonce, "chunks": chunks,
        "name_hash": blob[0x40:0x50], "header_tag": blob[0x50:0x60],
        "key": derive_key(blob[:HEADER_SIZE]),
    }


def decrypt(blob: bytes, filename: str) -> bytes:
    """Dekripsi seluruh container IDOLNAB3. Naikkan ValueError kalau ada
    header/tag yang tidak cocok — jangan pernah mengembalikan plaintext yang
    belum terautentikasi."""
    hdr = parse_header(blob)
    if not hmac.compare_digest(hdr["name_hash"], name_hash(filename)):
        raise ValueError("hash nama berkas tidak cocok")
    if not hmac.compare_digest(
            hdr["header_tag"], _header_tag(hdr["key"], hdr["nonce"], blob)):
        raise ValueError("tag header gagal (kunci/skema salah)")

    out = bytearray()
    off = HEADER_SIZE
    for i in range(hdr["chunks"]):
        remaining = hdr["plain_len"] - len(out)
        clen = min(CHUNK_SIZE, remaining)
        ct = blob[off:off + clen]
        tag = blob[off + clen:off + clen + TAG_SIZE]
        off += clen + TAG_SIZE
        nonce = _nonce_for(hdr["nonce"], i)
        if not hmac.compare_digest(
                tag, _chunk_tag(hdr["key"], nonce, blob, i, ct)):
            raise ValueError(f"tag chunk {i} gagal")
        sub = hchacha20(hdr["key"], nonce[:16])
        out.extend(chacha20_xor(sub, 1, nonce[16:24], ct))
    return bytes(out)


def encrypt(plain: bytes, filename: str, nonce24: bytes | None = None) -> bytes:
    """Kebalikan dari decrypt(); dipakai untuk fixture/self-test."""
    if nonce24 is None:
        nonce24 = hashlib.sha256(filename.encode()).digest()[:24]
    if len(nonce24) != 24:
        raise ValueError("nonce harus 24 byte")
    h = bytearray(HEADER_SIZE)
    h[0:8] = MAGIC
    struct.pack_into("<II", h, 0x08, 3, CHUNK_SIZE)
    struct.pack_into("<Q", h, 0x10, len(plain))
    h[0x18:0x28] = KEY_MATERIAL
    h[0x28:0x40] = nonce24
    h[0x40:0x50] = name_hash(filename)
    key = derive_key(bytes(h))
    h[0x50:0x60] = _header_tag(key, nonce24, bytes(h))
    out = bytearray(h)
    for i in range((len(plain) + CHUNK_SIZE - 1) // CHUNK_SIZE):
        part = plain[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        nonce = _nonce_for(nonce24, i)
        sub = hchacha20(key, nonce[:16])
        ct = chacha20_xor(sub, 1, nonce[16:24], part)
        out.extend(ct)
        out.extend(_chunk_tag(key, nonce, bytes(h), i, ct))
    return bytes(out)


def is_v3_container(blob: bytes) -> bool:
    return len(blob) >= HEADER_SIZE and blob[:8] == MAGIC


def self_test() -> int:
    """Round-trip multi-chunk + deteksi rusak + bandingkan primitif."""
    name = "share_assets_res_rawdata_spine_c010_00.bundle"
    plain = bytes((i * 37 + 11) & 0xFF for i in range(CHUNK_SIZE * 2 + 1234))
    blob = encrypt(plain, name)
    assert is_v3_container(blob)
    assert decrypt(blob, name) == plain, "round-trip gagal"
    assert len(blob) == HEADER_SIZE + len(plain) + 3 * TAG_SIZE

    bad = bytearray(blob)
    bad[HEADER_SIZE + 5] ^= 1
    try:
        decrypt(bytes(bad), name)
    except ValueError as e:
        assert "tag chunk" in str(e)
    else:
        raise AssertionError("perubahan ciphertext tidak terdeteksi")
    try:
        decrypt(blob, name + "x")
    except ValueError as e:
        assert "nama berkas" in str(e)
    else:
        raise AssertionError("nama berkas salah tidak terdeteksi")

    # Verifikasi independen: aliran ChaCha20 vs cryptography (OpenSSL),
    # dan Poly1305 vs cryptography, untuk (key, nonce, counter) yang sama.
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        from cryptography.hazmat.primitives.poly1305 import Poly1305
    except ImportError:
        print("oke: round-trip + tamper (cryptography tidak tersedia, lewati silang)")
        return 0
    key = bytes(range(32))
    n8 = bytes(range(8))
    mine = chacha20_xor(key, 7, n8, b"\0" * 128)
    theirs = Cipher(algorithms.ChaCha20(
        key, struct.pack("<I", 7) + b"\0" * 4 + n8), mode=None).encryptor().update(b"\0" * 128)
    assert mine == theirs, "ChaCha20 tidak cocok dengan OpenSSL"
    otk = bytes(range(32))
    ad, ct = b"header-data", b"cipher-text"
    buf = ad + b"\0" * (-len(ad) % 16) + ct + b"\0" * (-len(ct) % 16)
    buf += struct.pack("<QQ", len(ad), len(ct))
    ref = Poly1305(otk)
    ref.update(buf)
    assert poly1305_tag(otk, ad, ct) == ref.finalize(), \
        "Poly1305 tidak cocok dengan OpenSSL"
    print("oke: round-trip 3 chunk, tamper, nama salah, ChaCha20 & Poly1305 = OpenSSL")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--self-test":
        blob = open(sys.argv[1], "rb").read()
        if not is_v3_container(blob):
            print(f"bukan {MAGIC.decode()}: {blob[:8]!r}")
            sys.exit(2)
        h = parse_header(blob)
        for k, v in h.items():
            print(f"  {k}: {v.hex() if isinstance(v, bytes) else v}")
        sys.exit(0)
    sys.exit(self_test())
