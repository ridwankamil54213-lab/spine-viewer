#!/usr/bin/env python3
"""魔竞革命 (euwv.0577ai.com) — ekstrak model Spine dari bundle hot-update.

Sumber: CDN game TERBUKA
    https://euwv.0577ai.com/ob/update/android/filelist          (daftar berkas)
    https://euwv.0577ai.com/ob/update/android/<filename>       (bundle, UnityFS)
Ditemukan dari daftar CDN hasil bongkar '二游资源工具.exe' (tools/game-cdn-list.md),
alias di tool: 魔竞革命.

Tiap bundle = UnityFS berisi N model Spine, satu model = 3 objek berbagi nama:
    TextAsset "<id>"        -> skeleton JSON (Spine 3.8.99)
    TextAsset "<id>.atlas"  -> atlas
    Texture2D "<id>"        -> halaman tekstur
Keluaran: <out>/<id>/{<id>.json,<id>.atlas,<id>.png}

Pakai: /srv/venv-spine/bin/python tools/mojinggeming/extract-mojinggeming.py
"""
import json
import os
import subprocess
import sys
import time
from collections import defaultdict

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "6000.0.58f2"

BASE = "https://euwv.0577ai.com/ob/update/android"
OUT = "/opt/spine-viewer/assets/mojinggeming"
CACHE = "/opt/mojinggeming/bundles"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def http(url, dest=None, timeout=300):
    cmd = ["curl", "-s", "--max-time", str(timeout), "-A", UA]
    if dest:
        r = subprocess.run(cmd + ["-o", dest, "-w", "%{http_code}", url], capture_output=True, text=True)
        return r.stdout.strip()
    return subprocess.run(cmd + [url], capture_output=True).stdout


def list_bundles():
    raw = http(BASE + "/filelist", timeout=120)
    data = json.loads(raw)
    return [e for e in data if "spine" in e["filename"].lower() or "memorycardspine" in e["filename"].lower()]


def parse_text_asset(raw):
    """TextAsset mentah: int32 name_len / name (align4) / int32 size / data."""
    import struct
    try:
        n = struct.unpack("<i", raw[0:4])[0]
        if not (0 < n < 512):
            return None, None
        name = raw[4:4 + n].decode("utf-8", "replace")
        q = 4 + n
        q += (4 - (q % 4)) % 4
        size = struct.unpack("<i", raw[q:q + 4])[0]
        return name, raw[q + 4:q + 4 + size]
    except Exception:
        return None, None


def extract_bundle(path, out_root):
    name = os.path.basename(path)
    data = open(path, "rb").read()
    o = data.rfind(b"UnityFS")
    if o < 0:
        return 0
    env = UnityPy.load(data[o:])

    skels, atlases, texs = {}, {}, {}
    for ob in env.objects:
        t = ob.type.name
        try:
            if t == "TextAsset":
                nm, body = parse_text_asset(ob.get_raw_data())
                if not nm or body is None:
                    continue
                if nm.lower().endswith(".atlas"):
                    atlases[nm[:-6]] = body
                else:
                    skels[nm] = body
            elif t == "Texture2D":
                r = ob.read()
                # keep raw image lazily; PIL save later
                texs[r.m_Name] = r
        except Exception:
            pass

    n = 0
    for stem, skel in skels.items():
        at = atlases.get(stem)
        if not at:
            continue
        dest = os.path.join(out_root, stem)
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, stem + ".json"), "wb") as f:
            f.write(skel)
        with open(os.path.join(dest, stem + ".atlas"), "wb") as f:
            f.write(at)
        # Satu model bisa memakai >1 halaman tekstur: objek Texture2D bernama
        # <stem>, <stem>2, <stem>3, ... Atlas merujuknya lewat nama berkas
        # ("1101.png", "11012.png", "11013.png").
        for tname, r in texs.items():
            rest = tname[len(stem):] if tname.startswith(stem) else None
            if tname == stem or (rest and rest.isdigit()):
                try:
                    img = r.image
                    if img is not None:
                        img.convert("RGBA").save(os.path.join(dest, tname + ".png"), "PNG")
                except Exception:
                    pass
        n += 1
    return n


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    entries = list_bundles()
    print(f"bundle spine: {len(entries)}", flush=True)
    total = 0
    t0 = time.time()
    for i, e in enumerate(entries, 1):
        fn = e["filename"]
        fp = os.path.join(CACHE, fn.replace("/", "_"))
        if not os.path.exists(fp) or os.path.getsize(fp) < 100:
            code = http(f"{BASE}/{fn}", dest=fp)
            if code != "200":
                print(f"  [{i}] GAGAL unduh {fn}: http {code}", flush=True)
                continue
        try:
            n = extract_bundle(fp, OUT)
        except Exception as ex:
            print(f"  [{i}] GAGAL ekstrak {fn}: {ex}", flush=True)
            continue
        total += n
        print(f"  [{i}/{len(entries)}] {fn:22} {n:3} model  (total {total}, {time.time()-t0:.0f}s)", flush=True)
    print(f"SELESAI {total} model -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
