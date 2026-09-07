#!/usr/bin/env python3
"""Decrypt OrisRies (萬源聖魔錄) Unity AssetBundles.

The game ships its Addressable bundles AES-encrypted. The scheme, published
by AXiX_Official on https://live2dhub.com/t/topic/3323:

    key          = b"wiki is transfer"        (AES-128-CBC)
    layout       = <ciphertext><iv:16><iv_len:4 bytes LE>

The IV is appended to the end of the file, followed by a little-endian u32
holding its length (always 16). Anything already starting with the UnityFS
magic is passed through untouched — the APK's own bundles are plain.

Usage:
    python3 tools/decrypt-orisries.py <encrypted_dir> <output_dir>

Run with the venv that has pycryptodome:  /srv/venv-spine/bin/python
"""
import os
import struct
import sys

from Crypto.Cipher import AES

KEY = b"wiki is transfer"
IV_LEN = 16


def decrypt_file(src: str, dst: str) -> str:
    """Decrypt one bundle. Returns 'plain', 'decrypted', or raises."""
    with open(src, "rb") as f:
        data = f.read()

    # Already a plain UnityFS bundle — copy it through unchanged.
    if data[:7] == b"UnityFS":
        with open(dst, "wb") as f:
            f.write(data)
        return "plain"

    if len(data) < IV_LEN + 4:
        raise ValueError(f"terlalu pendek ({len(data)} b) untuk memuat IV")

    iv_length = struct.unpack("<I", data[-4:])[0]
    if iv_length != IV_LEN:
        raise ValueError(f"panjang IV tak terduga: {iv_length}")

    body_end = len(data) - 4 - iv_length
    iv = data[body_end:len(data) - 4]
    ciphertext = data[:body_end]

    if len(ciphertext) % AES.block_size:
        raise ValueError(f"ciphertext bukan kelipatan blok ({len(ciphertext)} b)")

    dec = AES.new(KEY, AES.MODE_CBC, iv).decrypt(ciphertext)

    # PKCS#7 unpad, but tolerate a bundle whose tail is already clean.
    pad = dec[-1]
    if 1 <= pad <= AES.block_size and dec[-pad:] == bytes([pad]) * pad:
        dec = dec[:-pad]

    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "wb") as f:
        f.write(dec)
    return "decrypted"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src_dir, out_dir = sys.argv[1], sys.argv[2]

    tally = {"plain": 0, "decrypted": 0, "error": 0}
    errors = []
    for root, _dirs, files in os.walk(src_dir):
        for name in files:
            src = os.path.join(root, name)
            rel = os.path.relpath(src, src_dir)
            dst = os.path.join(out_dir, rel)
            try:
                tally[decrypt_file(src, dst)] += 1
            except Exception as exc:
                tally["error"] += 1
                if len(errors) < 10:
                    errors.append(f"  {rel}: {exc}")

    print(f"plain     : {tally['plain']}")
    print(f"decrypted : {tally['decrypted']}")
    print(f"error     : {tally['error']}")
    for e in errors:
        print(e)
    return 1 if tally["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
