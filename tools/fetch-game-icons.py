"""Fetch official game icons for the Spine Stage game cards.

Each game gets one representative icon (app-store art / official index icon)
saved to public/thumbs/_game/<key>.png. The viewer falls back to the letter
badge whenever a game has no icon, so this is purely cosmetic.
"""
import io
import os

import requests
from PIL import Image

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA}

# Repo-relative: dulu hardcoded "/srv/spine-viewer/..." — path itu TIDAK ada,
# jadi skrip ini tak pernah menulis icon ke tempat yang dibaca server
# (THUMBS = <root>/public/thumbs). Server hanya menangkap LOKASI BARU karena
# cache-nya memakai mtime; jangan andalkan itu, tulis ke root repo.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "thumbs", "_game")
SIZE = 128

GAMES = [
    ("azurlane",        "https://play-lh.googleusercontent.com/xm_fZgRuFC6npGnzKgBbw1V2VuZo4Pc67LLcrecmihkaDK-LFa_yKi6x4zmg-Nb-tvqy1ppLgjEdmgZMV00vg9E=w240-h480-rw"),
    ("nikke",           "https://play-lh.googleusercontent.com/JK5mejs0bVT_9613gCxNfCjRw_m3JiQ4wC8B8Kt471yu7ThFQazVkCLTfPZ81hnenft7ilaE-qSwVGpQT6sEFcY=s512-rw"),
    ("arkrecode",       "https://res-r.hrbksd.com/image/index_icon/1787120162025.webp"),
    ("bd2",             "https://play-lh.googleusercontent.com/frPGVrz_hwSOyNm3y9RoVkfxD5I5ibKv0C5RD9Ub1188PJtv3BXa7KkfSyzr_-9SeNk50AVt3P2XvS_jtzTa=w240-h480-rw"),
    ("alliancesages",   "https://res-r.hrbksd.com/image/index_icon/1771930071921.webp"),
    ("lostsword",       "https://play-lh.googleusercontent.com/_OS6EQ01n93vfCiMRVgOb6RSsYiyacTI-2z_ebCzHNlLHdQX4Ln12dC1qGLjb_nrLc2L7Yr62osZDvFdIIv0JA=w240-h480-rw"),
    # Depose Girls (放置少女) isn't on Google Play. This is the official
    # favicon served from the game's own CDN (https://snh5-cdn1.ttagj.com).
    ("deposegirls",     "https://snh5-cdn1.ttagj.com/platform/dmm-release/favicon.ico"),
    # Project QT's Nutaku CDN isn't reachable from here, so this is a banner
    # served from the game's own asset CDN (cloudfront, see tools/projectqt).
    ("projectqt",       "https://d2mfyxc2xcodjl.cloudfront.net/share/bab6fc2c35fbb080514fc48cae681727beb68dc6.png"),
    # Shoujou Kaisen's icon comes out of the APK instead of the web:
    # res/drawable-xxhdpi-v11/licon.png in com.onemt.and.shoujokaisen.apk
    # (see tools/shoujoukaisen/README.md). Left out of GAMES on purpose.
    #
    # Stellar Affinity, Haze Reverb and DotAbyss are also APK-only, and none
    # has a plain res/ icon at all — all are Unity/IL2CPP builds that keep the
    # launcher art inside resources.arsc under an obfuscated name
    # (res/oj.png, res/dK.png and res/oj.png respectively). Find it with:
    #     from pyaxmlparser import APK; APK(path).get_app_icon()
    # then unzip that entry. Left out of GAMES on purpose.
    #
    # Note for DotAbyss: the manifest name is only a starting point. res/ also
    # holds bigger, transparent/not-quite-square art (res/as.png at 432px is a
    # character cut-out on black, res/Gx.png is a bare gradient with no logo).
    # res/oj.png is the real 192x192 fully-opaque launcher tile — always eyeball
    # the candidates before picking, size alone picks the wrong one.
]

# Game yang PUNYA model tapi BELUM punya icon (2026-10-14). Isi URL-nya ke GAMES
# di atas, lalu jalankan ulang. Rincian + kandidat sumber: tools/game-icons-pending.md
PENDING_GAMES = [
    "alcherystars", "angelica", "blissful", "bluearchive",
    "chaoszero", "crosscore", "demo", "dotabyss", "dotabyss-l2d",
    "dragontravelers",
    "epic7", "everlusting", "girlwars", "girlwars-l2d", "goddessparadise",
    "idleangels", "isekaislowlife", "ivntight", "juezhan", "kink",
    "mecharashi", "mengqi", "mitao-utopia", "muvluv",
    "muvluv-cg", "orisries", "peachhan", "riichicity", "shenlan", "shenlan-cg",
    "starlust", "stellar", "talesofangels", "tenkei", "throne", "wuhua",
    "xingjie", "ysjh",
]


def main():
    os.makedirs(OUT, exist_ok=True)
    for key, url in GAMES:
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content))
            img = img.convert("RGBA")
            # trim to a square first so app-store banners don't crop oddly
            w, h = img.size
            s = min(w, h)
            img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
            img = img.resize((SIZE, SIZE), Image.LANCZOS)
            dest = os.path.join(OUT, key + ".png")
            img.save(dest, "PNG")
            print(f"  OK  {key:16} {w}x{h} -> {SIZE}x{SIZE}  ({os.path.getsize(dest)//1024} KB)")
        except Exception as e:
            print(f"  FAIL {key:16} {str(e)[:70]}")

    have = {f[:-4] for f in os.listdir(OUT) if f.endswith(".png")}
    todo = [k for k in PENDING_GAMES if k not in have]
    print(f"\n  icon ada: {len(have)} | game tanpa icon: {len(todo)}")
    if todo:
        print("  belum ada icon: " + ", ".join(todo))


if __name__ == "__main__":
    main()
