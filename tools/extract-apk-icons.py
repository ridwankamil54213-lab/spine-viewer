#!/usr/bin/env python3
"""Ambil icon launcher (128x128) langsung dari APK lokal/redroid.

Dipakai untuk mengisi `public/thumbs/_game/<key>.png` bagi game yang APK-nya
sudah ada di disk (lebih andal daripada menebak URL toko: ikon di dalam APK
selalu resmi dan sudah ada apa adanya).

Heuristik:
  1. kalau `get_app_icon()` menunjuk berkas .png/.webp -> pakai itu;
  2. kalau adaptif (.xml) / gagal -> pindai res/**, kumpulkan .png/.webp yang
     namanya mengandung launcher/icon/logo, pilih yang paling besar & bujur;
  3. simpan 128x128 ke public/thumbs/_game/<key>.png.

Pakai:  /srv/venv-spine/bin/python tools/extract-apk-icons.py [key ...]
"""
import io
import os
import re
import sys
import zipfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "thumbs", "_game")
SIZE = 128

# key game -> APK (base) yang di disk. Split APK: pakai base saja, ikon ada di base.
APK = {
    "blissful": "/opt/blissful/BlissfulAbyss.apk",
    "wuhua": "/opt/wh/pack/com.cipaishe.wuhua.google.apk",
    "dragontravelers": "/opt/dt/apk/base.apk",
    "juezhan": "/opt/juezhan/game.apk",
    "mitao-utopia": "/opt/mitao/game.apk",
    "throne": "/opt/throne/apk/base.apk",
    "ysjh": "/opt/ysjh/ysjh.apk",
    "stellar": "/opt/games/stellar/stellar.apk",
    "shenlan": "/opt/games/shenlan.apk",
    "xingjie": "/opt/xingjie/apk/xjdz.apk",
}

WANT = re.compile(r"(launcher|app_?icon|ic_?icon|game_?icon|logo)", re.I)
IMG = re.compile(r"\.(png|webp)$", re.I)


def score(name):
    s = 0
    if "launcher" in name.lower():
        s += 4
    if re.search(r"ic_launcher|app_icon", name, re.I):
        s += 3
    if "logo" in name.lower():
        s += 1
    if "foreground" in name.lower():
        s += 2          # adaptive foreground = the actual art
    if "round" in name.lower():
        s -= 1
    return s


def best_from_zip(zf):
    cands = []
    for n in zf.namelist():
        if not IMG.search(n) or not n.startswith("res/"):
            continue
        if not WANT.search(os.path.basename(n)):
            continue
        try:
            data = zf.read(n)
            im = Image.open(io.BytesIO(data))
            w, h = im.size
        except Exception:
            continue
        # bujur & besar lebih baik; hindari 1x1 / strip
        if w < 48 or h < 48:
            continue
        ratio = min(w, h) / max(w, h)
        cands.append((score(n) + int(min(w, h) >= 192) + round(ratio, 2), w * h, n, data))
    if not cands:
        return None, None
    cands.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return cands[0][2], cands[0][3]


def square(im, size=SIZE):
    im = im.convert("RGBA")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    return im.resize((size, size), Image.LANCZOS)


def do(key, path):
    if not os.path.exists(path):
        print(f"  MISS {key:16} {path}")
        return False
    os.makedirs(OUT, exist_ok=True)
    name = data = None
    # 1) coba ikon resmi dari manifest
    try:
        from pyaxmlparser import APK
        ic = APK(path).get_app_icon()
    except Exception:
        ic = None
    with zipfile.ZipFile(path) as zf:
        if ic and IMG.search(ic):
            try:
                data = zf.read(ic); name = ic
            except KeyError:
                data = None
        if data is None:
            name, data = best_from_zip(zf)
    if data is None:
        print(f"  FAIL {key:16} (tak ada kandidat ikon)")
        return False
    try:
        im = Image.open(io.BytesIO(data))
        square(im).save(os.path.join(OUT, key + ".png"), "PNG")
        print(f"  OK   {key:16} {im.size[0]}x{im.size[1]} <- {name}")
        return True
    except Exception as e:
        print(f"  FAIL {key:16} {e}")
        return False


def main():
    keys = sys.argv[1:] or list(APK)
    ok = 0
    for k in keys:
        if k in APK:
            ok += do(k, APK[k])
    print(f"\n  {ok}/{len(keys)} icon dari APK")


if __name__ == "__main__":
    main()
