#!/usr/bin/env python3
"""Dekripsi IDOLAB2 v2 (rilis iOS 1.6.2 / 蜜桃乌托邦) — tanpa dependensi wajib.

Sumber: skrip downloader iOS (dibagikan user) + verifikasi langsung terhadap
manifest & bundle CDN `ios_cn_release` (lihat `tools/mitao/README.md`).

Struktur berkas
===============

Manifest CDN = wrapper 24 byte + container IDOLAB2 + trailer RSA-3072 384 byte::

    b"IDOLRS1\\0" + 5 u32 ; payload_len = u32@0x10 ; inner = blob[24:24+payload_len]

Container IDOLAB2 (header 0x80)::

    0x00 b"IDOLAB2\\0"  0x08 u32 2  0x0C u32 key_id(1)  0x10 u32 0x10000
    0x14 u32 0          0x18 u64 plain_len
    0x20 salt[32]       0x40 sha256(nama_berkas)[32]  0x60 HMAC header[32]
    lalu per chunk: IV[16] || ciphertext || HMAC[32]

* KDF: prk=HMAC(salt, master); enc=HMAC(prk, KDF_INFO+1);
  auth=HMAC(prk, enc+KDF_INFO+2).
* Untuk BUNDLE, master diturunkan lagi:
  ``HMAC(master, "IdolTime/BundleEncryption/v2\\n<SCOPE>\\n<key_id>")``.
  Untuk MANIFEST dipakai master langsung (``derive_bundle=False``).
* Tag chunk = HMAC(auth, header_tag || LE64(idx) || IV || ciphertext).

Backend AES (dipilih otomatis, service venv tidak punya Crypto/cryptography):
  1. pycryptodome ``Crypto.Cipher.AES``
  2. ``cryptography``
  3. CLI ``openssl enc -d -aes-256-cbc -nopad``

Jalankan ``python3 tools/mitao/idol_v2.py --self-test`` untuk uji.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import struct
import subprocess
import sys

MAGIC_RS1 = b"IDOLRS1\x00"
MAGIC_AB2 = b"IDOLAB2\x00"
HEADER_SIZE = 0x80
CHUNK_SIZE = 0x10000
FULL_RECORD_SIZE = 0x10040
KDF_INFO = b"IdolTime/AssetBundle/v2/AES256CBC-HMACSHA256"
MASTER_KEY = bytes.fromhex(
    "13db410def5575cf69e1df8309f94cf953011b2752f0680a372a1b4cb1832e6d")
SCOPE = "Release_Game18_iOS/ios_cn_release"
RESOURCE_TYPE = "ios_cn_release"


def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def derive_keys(master_key: bytes, salt: bytes) -> tuple[bytes, bytes]:
    prk = hmac_sha256(salt, master_key)
    enc = hmac_sha256(prk, KDF_INFO + b"\x01")
    auth = hmac_sha256(prk, enc + KDF_INFO + b"\x02")
    return enc, auth


def bundle_master_key(master_key: bytes, scope: str = SCOPE,
                      key_id: int = 1) -> bytes:
    label = f"IdolTime/BundleEncryption/v2\n{scope}\n{key_id}".encode()
    return hmac_sha256(master_key, label)


def unwrap_container(blob: bytes) -> bytes:
    """Lepas wrapper IDOLRS1 (manifest). Bundle langsung IDOLAB2."""
    if not blob.startswith(MAGIC_RS1):
        return blob
    payload_len = struct.unpack_from("<I", blob, 0x10)[0]
    return blob[24:24 + payload_len]


def _aes_cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
    # 1) pycryptodome
    try:
        from Crypto.Cipher import AES  # type: ignore
        return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    except ImportError:
        pass
    # 2) cryptography
    try:
        from cryptography.hazmat.primitives.ciphers import (  # type: ignore
            Cipher, algorithms, modes)
        d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return d.update(ct) + d.finalize()
    except ImportError:
        pass
    # 3) openssl CLI (selalu ada di host ini)
    p = subprocess.run(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-nopad",
         "-K", key.hex(), "-iv", iv.hex()],
        input=ct, capture_output=True, timeout=60, check=True)
    return p.stdout


def cipher_length(n: int, extra_block: bool = True) -> int:
    return ((n + 15) & ~15) + (16 if extra_block else 0)


def encrypted_length(plain_len: int, final_extra: bool = True) -> int:
    if plain_len <= 0:
        return HEADER_SIZE
    total = HEADER_SIZE
    remaining, i = plain_len, 0
    while remaining > 0:
        cur = min(CHUNK_SIZE, remaining)
        if i < plain_len // CHUNK_SIZE:
            total += FULL_RECORD_SIZE
        else:
            total += 16 + cipher_length(cur, final_extra) + 32
        remaining -= cur
        i += 1
    return total


def parse_header(blob: bytes) -> dict:
    if len(blob) < HEADER_SIZE or blob[:8] != MAGIC_AB2:
        raise ValueError(f"bukan IDOLAB2: {blob[:8]!r}")
    ver, key_id, chunk = struct.unpack_from("<III", blob, 0x08)
    if ver != 2 or key_id != 1 or chunk != CHUNK_SIZE:
        raise ValueError(f"header tidak didukung: v{ver} key={key_id} chunk={chunk:#x}")
    if struct.unpack_from("<I", blob, 0x14)[0] != 0:
        raise ValueError("reserved != 0")
    return {
        "plain_len": struct.unpack_from("<Q", blob, 0x18)[0],
        "salt": blob[0x20:0x40],
        "name_hash": blob[0x40:0x60],
        "header_tag": blob[0x60:0x80],
        "ad": blob[:0x60],
    }


def decrypt_bundle(blob: bytes, bundle_name: str,
                   master_key: bytes = MASTER_KEY,
                   check_name: bool = True,
                   derive_bundle: bool = True,
                   scope: str = SCOPE) -> bytes:
    """Dekripsi satu container IDOLAB2. Naikkan ValueError kalau ada tag yang
    tidak cocok — jangan pernah mengembalikan plaintext tanpa autentikasi."""
    blob = unwrap_container(blob)
    h = parse_header(blob)
    if check_name and not hmac.compare_digest(
            h["name_hash"], hashlib.sha256(bundle_name.encode()).digest()):
        raise ValueError("hash nama berkas tidak cocok")
    mk = bundle_master_key(master_key, scope) if derive_bundle else master_key
    enc, auth = derive_keys(mk, h["salt"])
    if not hmac.compare_digest(h["header_tag"], hmac_sha256(auth, h["ad"])):
        raise ValueError("tag header gagal (kunci master/scope salah)")
    std = encrypted_length(h["plain_len"], True)
    compat = encrypted_length(h["plain_len"], False)
    if len(blob) == std:
        final_extra = True
    elif len(blob) == compat:
        final_extra = False
    else:
        raise ValueError(f"ukuran {len(blob)} != {std}/{compat}")

    out = bytearray()
    off, idx = HEADER_SIZE, 0
    while len(out) < h["plain_len"]:
        rem = h["plain_len"] - len(out)
        pc = min(CHUNK_SIZE, rem)
        final = rem <= CHUNK_SIZE
        cl = cipher_length(pc, final_extra if final else True)
        iv = blob[off:off + 16]; off += 16
        ct = blob[off:off + cl]; off += cl
        tag = blob[off:off + 32]; off += 32
        expect = hmac_sha256(
            auth, h["header_tag"] + struct.pack("<Q", idx) + iv + ct)
        if not hmac.compare_digest(tag, expect):
            raise ValueError(f"tag chunk {idx} gagal")
        pt = _aes_cbc_decrypt(enc, iv, ct)
        pad = pt[-1]
        if not 1 <= pad <= 16 or pt[-pad:] != bytes([pad]) * pad:
            raise ValueError(f"chunk {idx} padding PKCS7 rusak")
        out.extend(pt[:-pad])
        idx += 1
    return bytes(out)


def decrypt_manifest(blob: bytes) -> bytes:
    """Khusus manifest CDN: tanpa cek nama, tanpa derivasi kunci bundle."""
    return decrypt_bundle(blob, "", check_name=False, derive_bundle=False)


def is_container(blob: bytes) -> bool:
    return len(blob) >= HEADER_SIZE and (
        blob[:8] == MAGIC_AB2 or blob[:8] == MAGIC_RS1)


def self_test() -> int:
    """Round-trip sintetis (manifest + bundle) lewat backend AES yang ada."""
    name = "assets_res_prefabs_spine_mesh_ass_30001.bundle"
    plain = bytes((i * 31 + 7) & 0xFF for i in range(CHUNK_SIZE + 517))
    salt = hashlib.sha256(b"salt").digest()
    header_tag = hashlib.sha256(b"tag").digest()
    nh = hashlib.sha256(name.encode()).digest()

    def build(mk: bytes) -> bytes:
        enc, auth = derive_keys(mk, salt)
        h = bytearray(HEADER_SIZE)
        h[0:8] = MAGIC_AB2
        struct.pack_into("<III", h, 0x08, 2, 1, CHUNK_SIZE)
        struct.pack_into("<Q", h, 0x18, len(plain))
        h[0x20:0x40] = salt
        h[0x40:0x60] = nh
        h[0x60:0x80] = hmac_sha256(auth, bytes(h[:0x60]))
        out = bytearray(h)
        for i in range((len(plain) + CHUNK_SIZE - 1) // CHUNK_SIZE):
            part = plain[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
            pad = 16 - len(part) % 16
            padded = part + bytes([pad]) * pad
            iv = hashlib.sha256(f"iv{i}".encode()).digest()[:16]
            ct = _aes_cbc_encrypt(enc, iv, padded)
            out.extend(iv + ct + hmac_sha256(
                auth, bytes(h[0x60:0x80]) + struct.pack("<Q", i) + iv + ct))
        return bytes(out)

    def _aes_cbc_encrypt(key: bytes, iv: bytes, pt: bytes) -> bytes:
        try:
            from Crypto.Cipher import AES  # type: ignore
            return AES.new(key, AES.MODE_CBC, iv).encrypt(pt)
        except ImportError:
            pass
        try:
            from cryptography.hazmat.primitives.ciphers import (  # type: ignore
                Cipher, algorithms, modes)
            e = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
            return e.update(pt) + e.finalize()
        except ImportError:
            pass
        p = subprocess.run(
            ["openssl", "enc", "-aes-256-cbc", "-nopad",
             "-K", key.hex(), "-iv", iv.hex()],
            input=pt, capture_output=True, timeout=60, check=True)
        return p.stdout

    blob = build(MASTER_KEY)
    assert is_container(blob)
    assert decrypt_bundle(blob, name, derive_bundle=False) == plain
    # bundle dengan kunci turunan scope
    bmk = bundle_master_key(MASTER_KEY)
    blob2 = build(bmk)
    assert decrypt_bundle(blob2, name, derive_bundle=True) == plain
    # manifest dibungkus IDOLRS1
    wrapped = MAGIC_RS1 + struct.pack("<IIII", 1, 1, len(blob), 384) + blob
    assert decrypt_manifest(wrapped) == plain
    # tamper harus tertolak
    bad = bytearray(blob); bad[HEADER_SIZE + 20] ^= 1
    try:
        decrypt_bundle(bytes(bad), name, derive_bundle=False)
    except ValueError:
        pass
    else:
        raise AssertionError("tamper tidak terdeteksi")
    print("oke: round-trip v2 manifest+bundle (2 chunk), kunci scope, tamper")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--self-test":
        blob = open(sys.argv[1], "rb").read()
        name = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(sys.argv[1])
        pt = decrypt_manifest(blob) if blob.startswith(MAGIC_RS1) \
            else decrypt_bundle(blob, name)
        sys.stdout.buffer.write(pt)
    else:
        sys.exit(self_test())
