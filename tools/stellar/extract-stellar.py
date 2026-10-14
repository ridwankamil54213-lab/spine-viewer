#!/usr/bin/env python3
"""Ekstrak Spine マブラヴ... bukan: Stellar Valkyries (Cocos2d-x Lua) dari APK.

Sumber: assets/res/spine/<id>[/<scene>]/<name>.{skel,atlas,png}
  - .skel  = Spine BINARY, TIDAK terenkripsi (langsung dipakai)
  - .atlas = teks biasa, TIDAK terenkripsi
  - .png   = TERENKRIPSI: header "abcgame" (7 byte) + XXTEA
             (kunci di-set lewat LuaStack::setXXTEAKeyAndSign)

Skema dekripsi (diverifikasi: hasil PNG berawalan \\x89PNG):
    key = b"wX34UsTVXt4RezWe"        # sama utk game berheader "abcgame"
    data = XXTEA_decrypt(raw[7:], key, padding=False)

Kunci ditemukan dari forum live2dhub (header "abcgame" + kunci dibagikan
anggota untuk game sejenis). Tanpa dekripsi ini, browser menolak PNG
("InvalidStateError: The source image could not be decoded").

Pakai:  /srv/venv-spine/bin/python tools/stellar/extract-stellar.py
"""
import os
import zipfile

import xxtea

APK = "/opt/games/stellar/stellar.apk"
OUT = "/opt/spine-viewer/assets/stellar"
PREFIX = "assets/res/spine/"
KEY = b"wX34UsTVXt4RezWe"
HDR = b"abcgame"          # 7 byte


def decrypt_png(raw: bytes) -> bytes:
    body = raw[len(HDR):] if raw[:len(HDR)] == HDR else raw
    pad = (-len(body)) % 4
    return xxtea.decrypt(body + b"\x00" * pad, KEY, padding=False)


def main():
    z = zipfile.ZipFile(APK)
    ents = [n for n in z.namelist() if n.startswith(PREFIX)]
    print(f"entry: {len(ents)}")
    n_png = n_plain = 0
    for n in ents:
        rel = n[len(PREFIX):]
        if not rel:
            continue
        dst = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        raw = z.read(n)
        if rel.lower().endswith(".png"):
            data = decrypt_png(raw)
            n_png += 1
        else:
            data = raw
            n_plain += 1
        with open(dst, "wb") as f:
            f.write(data)
    print(f"SELESAI png(decrypt)={n_png} plain={n_plain} -> {OUT}")


if __name__ == "__main__":
    main()
