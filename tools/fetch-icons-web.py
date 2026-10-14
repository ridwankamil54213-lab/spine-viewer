#!/usr/bin/env python3
"""Ambil icon game dari halaman web (Play Store / QooApp / Nutaku / unavatar /
situs resmi), plus salinan icon game induk untuk game turunan.

Strategi:
  - mode "og"     : unduh HTML halaman, ambil og:image / twitter:image.
                    Naikkan resolusi googleusercontent ke =s512.
  - mode "direct" : unduh URL gambar langsung.
Semua lalu di-crop kotak tengah + simpan 128x128 ke public/thumbs/_game/<key>.png.

Ikon dari APK lokal ditangani tools/extract-apk-icons.py (game yang APK-nya ada
di disk); game turunan (‑cg/‑l2d/‑video) memakai icon game induknya.

Pakai:  /srv/venv-spine/bin/python tools/fetch-icons-web.py [key ...]
"""
import io
import os
import re
import sys
import time

import requests
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "thumbs", "_game")
SIZE = 128
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

# key -> ("og", <halaman>) | ("direct", <url gambar>)
SOURCES = {
    # ---- Google Play (og:image = ikon 512x512) ----
    "angelica":        ("og", "https://play.google.com/store/apps/details?id=com.dmm.games.angelica&hl=en"),
    "bluearchive":     ("og", "https://play.google.com/store/apps/details?id=com.nexon.bluearchive&hl=en"),
    "chaoszero":       ("og", "https://play.google.com/store/apps/details?id=com.smilegate.chaoszero.stove.google&hl=en"),
    "dotabyss":        ("og", "https://play.google.com/store/apps/details?id=com.exnoa.abyss&hl=en"),
    "goddessparadise": ("og", "https://play.google.com/store/apps/details?id=com.asikagames.paradise.googleplay&hl=en"),
    "idleangels":      ("og", "https://play.google.com/store/apps/details?id=com.mujoysg.hxbb&hl=en"),
    "isekaislowlife":  ("og", "https://play.google.com/store/apps/details?id=com.iskslowtest.mislen&hl=en"),
    "mecharashi":      ("og", "https://play.google.com/store/apps/details?id=com.tentree.gp.mecharashi&hl=en"),
    "orisries":        ("og", "https://play.google.com/store/apps/details?id=com.megagames.orisries&hl=en"),
    "riichicity":      ("og", "https://play.google.com/store/apps/details?id=com.riichicity.happywoods&hl=en"),
    "talesofangels":   ("og", "https://play.google.com/store/apps/details?id=com.wickedgirl.hw&hl=en"),
    # ---- QooApp (og:image = ikon/cover) ----
    "alcherystars":    ("og", "https://apps.qoo-app.com/en/app/16352"),
    "epic7":           ("og", "https://apps.qoo-app.com/en/app/6830"),
    "crosscore":       ("og", "https://apps.qoo-app.com/en/app/132149"),
    "peachhan":        ("og", "https://apps.qoo-app.com/en/app/70247"),
    "girlwars":        ("og", "https://apps.qoo-app.com/en/app/22359"),
    "kink":            ("og", "https://apps.qoo-app.com/ko/app/132721"),
    # ---- Situs resmi ----
    "muvluv":          ("og", "https://muvluv-girls-garden.com/x/"),
    "tenkei":          ("og", "https://tenkei-paradox.com/x/"),
    # ---- Nutaku (thumbnail_s.jpg = kotak 150x150) ----
    "everlusting":     ("direct", "https://cdn1-images.nutaku.net/images/manage/games/everlusting-life/thumbnail_s.jpg"),
    "mengqi":          ("direct", "https://cdn1-images.nutaku.net/images/manage/games/presidents-ambition/thumbnail_s.jpg"),
    "starlust":        ("direct", "https://cdn1-images.nutaku.net/images/manage/games/star-lusts/thumbnail_s.jpg"),
    # ---- Avatar Twitter resmi (situs FANZA ter-gate umur) ----
    "ivntight":        ("direct", "https://unavatar.io/twitter/project_iv_n"),
}

# Game turunan memakai icon game induknya (salin file).
DERIVED = {
    "azurlane-l2d": "azurlane",
    "lostsword-video": "lostsword",
    "dotabyss-l2d": "dotabyss",
    "girlwars-l2d": "girlwars",
    "muvluv-cg": "muvluv",
    "shenlan-cg": "shenlan",
}


def og_image(html):
    for pat in (r'<meta property="og:image" content="([^"]+)"',
                r'<meta name="twitter:image" content="([^"]+)"'):
        m = re.search(pat, html)
        if m:
            return m.group(1).replace("&amp;", "&")
    return None


def upscale(url):
    return re.sub(r"=.*$", "=s512", url) if "googleusercontent.com" in url else url


def square(im, size=SIZE):
    im = im.convert("RGBA")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    return im.resize((size, size), Image.LANCZOS)


def do(key, mode, src):
    try:
        if mode == "og":
            r = requests.get(src, headers=H, timeout=45)
            url = og_image(r.text)
            if not url:
                print(f"  FAIL {key:16} og:image tak ada (http {r.status_code})")
                return False
            url = upscale(url)
        else:
            url = src
        content = requests.get(url, headers=H, timeout=45).content
        im = Image.open(io.BytesIO(content))
        os.makedirs(OUT, exist_ok=True)
        square(im).save(os.path.join(OUT, key + ".png"), "PNG")
        print(f"  OK   {key:16} {im.size[0]}x{im.size[1]} <- {url.split('/')[2]}")
        return True
    except Exception as e:
        print(f"  FAIL {key:16} {str(e)[:80]}")
        return False


def main():
    keys = sys.argv[1:] or list(SOURCES)
    ok = 0
    for k in keys:
        if k in SOURCES:
            ok += do(k, *SOURCES[k])
            time.sleep(0.4)
    # salinan ikon induk
    copies = 0
    for k, parent in DERIVED.items():
        p = os.path.join(OUT, parent + ".png")
        if os.path.exists(p):
            with open(p, "rb") as f:
                data = f.read()
            with open(os.path.join(OUT, k + ".png"), "wb") as f:
                f.write(data)
            copies += 1
    print(f"\n  {ok}/{len(keys)} dari web, {copies} salinan turunan")


if __name__ == "__main__":
    main()
