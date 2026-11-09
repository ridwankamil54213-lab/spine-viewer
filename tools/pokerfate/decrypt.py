#!/usr/bin/env python3
"""Dekripsi bundle PokerFate yang terbungkus header XENC.

Sumber algoritma: tutorial komunitas di live2dhub.com/t/topic/6530
("PokerFate 解包"), yang menurunkan konstanta dari GameAssembly.dll versi
2026-10 (Unity 2022.3.62f3, IL2CPP).

Format berkas:
    XENC (4 byte) | nonce (16 byte) | ciphertext

Ciphertext adalah XOR dengan keystream yang DIDERIVASI ULANG tiap 64 byte:

    n64   = LE64(nonce[0:8]) ^ LE64(nonce[8:16])
    m     = mix(n64)                       # splitmix64 dua langkah
    seed  = m ^ (m >> 31) ^ S
    state = seed - index_blok * C          # pengurangan, bukan penjumlahan
    lalu xorshift(13, 7, 17); tiap byte diambil dari state & 0xFF

Catatan penting dari tutorial: konstanta S dan C terikat pada versi game.
Kalau versi APK berbeda, hasilnya bukan "UnityFS" dan dekripsi dianggap
gagal — jangan dipakai, konstanta harus diturunkan ulang.

Verifikasi yang dipakai skrip ini: hasil dekripsi harus dimulai dengan
"UnityFS" ATAU "UnityWeb" ATAU "UnityRaw". Hanya memeriksa 8 byte pertama
tidak cukup untuk memastikan konstanta benar (xorshift bersifat afin atas
seed, sehingga ratusan konstanta bisa lolos uji 8 byte), jadi skrip ini
juga memeriksa bahwa field ukuran di header masuk akal terhadap panjang
payload sebenarnya.
"""

import glob
import json
import os
import struct
import sys

MASK = (1 << 64) - 1
S = 0xAF3E40196CB07413
C = 0x61C8864680B583EB

HEADER_MAGIC = (b"UnityFS", b"UnityWeb", b"UnityRaw", b"UnityArchive")


def mix(z: int) -> int:
    z &= MASK
    z ^= z >> 30
    z = (z * 0xBF58476D1CE4E5B9) & MASK
    z ^= z >> 27
    z = (z * 0x94D049BB133111EB) & MASK
    return z


def keystream(nonce: bytes, length: int) -> bytes:
    n64 = struct.unpack_from("<Q", nonce, 0)[0] ^ struct.unpack_from("<Q", nonce, 8)[0]
    m = mix(n64)
    seed = (m ^ (m >> 31) ^ S) & MASK
    out = bytearray()
    block = 0
    while len(out) < length:
        state = (seed - block * C) & MASK
        for _ in range(64):
            state ^= (state << 13) & MASK
            state ^= state >> 7
            state ^= (state << 17) & MASK
            out.append(state & 0xFF)
        block += 1
    return bytes(out[:length])


def looks_valid(plain: bytes) -> bool:
    """Cek struktur, bukan cuma magic.

    UnityFS header: magic, lalu versi (u32 BE), lalu tiga string
    nul-terminated (unityVersion, unityRevision) dan ukuran (i64 BE).
    Kalau magic cocok tapi ukuran yang dideklarasikan jauh dari panjang
    berkas, kemungkinan besar ini "dekripsi palsu".
    """
    if not plain.startswith(HEADER_MAGIC):
        return False
    if not plain.startswith(b"UnityFS"):
        return True
    try:
        p = 8  # magic
        p += 4  # version
        for _ in range(2):  # unityVersion, unityRevision
            end = plain.index(b"\x00", p)
            if end < p or end - p > 64:
                return False
            p = end + 1
        if p + 8 > len(plain):
            return False
        declared = struct.unpack_from(">q", plain, p)[0]
        # Ukuran yang dideklarasikan harus sebanding dengan berkas nyata.
        return 0 < declared <= len(plain) + 1024 * 1024
    except (ValueError, struct.error):
        return False


def decrypt_bytes(data: bytes) -> tuple[bytes, bool]:
    if data[:4] != b"XENC":
        return data, False
    if len(data) < 20:
        return data, False
    nonce = data[4:20]
    body = data[20:]
    ks = keystream(nonce, len(body))
    # XOR big-int berjalan di C, jauh lebih cepat daripada generator Python
    # per byte untuk total ~1,4 GB bundle (penting karena --apply dibatasi
    # UPDATE_TIMEOUT_MS 30 menit di server).
    plain = (int.from_bytes(body, "little") ^ int.from_bytes(ks, "little")) \
        .to_bytes(len(body), "little")
    return plain, True


def self_test() -> dict:
    """Round-trip XENC sintetis: buktikan keystream + XOR konsisten."""
    import os as _os
    nonce = _os.urandom(16)
    body = b"UnityFS\x00" + _os.urandom(4096)
    ks = keystream(nonce, len(body))
    ct = (int.from_bytes(body, "little") ^ int.from_bytes(ks, "little")) \
        .to_bytes(len(body), "little")
    plain, enc = decrypt_bytes(b"XENC" + nonce + ct)
    return {"ok": bool(enc and plain == body), "magic": plain[:8].decode("latin1"),
            "bytes": len(body)}


def decrypt_file(src: str, dst: str) -> str:
    """Kembalikan status: 'ok' | 'plain' | 'gagal'."""
    with open(src, "rb") as fh:
        data = fh.read()
    plain, was_encrypted = decrypt_bytes(data)
    if not was_encrypted:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        return "plain"
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(plain)
    return "ok" if looks_valid(plain) else "gagal"


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        result = self_test()
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    if len(sys.argv) < 3:
        print("pakai: decrypt.py <bundle-atau-direktori> <keluaran> | --self-test",
              file=sys.stderr)
        return 2
    src, dst = sys.argv[1], sys.argv[2]

    if os.path.isfile(src):
        files = [src]
    else:
        files = sorted(
            glob.glob(os.path.join(src, "**", "*.bundle"), recursive=True)
            + glob.glob(os.path.join(src, "**", "*.ab"), recursive=True)
        )
    if not files:
        print("tidak ada berkas .bundle/.ab ditemukan", file=sys.stderr)
        return 1

    tally = {"ok": 0, "plain": 0, "gagal": 0}
    for path in files:
        name = os.path.basename(path)
        status = decrypt_file(path, os.path.join(dst, name))
        tally[status] += 1

    print(f"terdekripsi {tally['ok']}, tidak terenkripsi {tally['plain']}, gagal {tally['gagal']}")
    if tally["gagal"]:
        print(
            "PERINGATAN: ada berkas yang gagal. Konstanta S/C kemungkinan tidak "
            "cocok dengan versi APK ini; dekripsi jangan dilanjutkan.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
