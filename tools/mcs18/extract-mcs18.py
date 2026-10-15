#!/usr/bin/env python3
"""禁果便利店 (mcs18) — ekstrak model Spine dari bundle Addressables.

Game: 禁果便利店 / 群交避難所 / 我的便利店竟成了美少女的避难所
      (My Convenience Store Became a Shelter for Beautiful Girls), EROLABS.
CDN terbuka (dari bongkaran 二游资源工具.exe, alias 群交避难所):
    https://mcs18-client-resource-tw.1uhg.com/Android/catalog_1.2.0.json
    https://mcs18-client-resource-tw.1uhg.com/Android/<path>.bundle

Catalog = Addressables; bundle karakter ada di
    Android/arts_assets_assets/arts/animation/characterNN_MM_normal_<hash>.bundle
Tiap bundle = UnityFS berisi TextAsset "<name>.skel" (Spine biner/JSON),
"<name>.atlas" + Texture2D. Keluaran: <out>/<name>/{skel,atlas,png}.

Pakai: /srv/venv-spine/bin/python tools/mcs18/extract-mcs18.py
"""
import json
import os
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

BASE = "https://mcs18-client-resource-tw.1uhg.com"
CATALOG = BASE + "/Android/catalog_1.2.0.json"
OUT = "/opt/spine-viewer/assets/mcs18"
CACHE = "/opt/mcs18/bundles"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
WORKERS = 8


def http(url, dest=None, timeout=180):
    cmd = ["curl", "-s", "--max-time", str(timeout), "-A", UA]
    if dest:
        r = subprocess.run(cmd + ["-o", dest, "-w", "%{http_code}", url], capture_output=True, text=True)
        return r.stdout.strip()
    return subprocess.run(cmd + [url], capture_output=True).stdout


def parse_text_asset(raw):
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


def bundle_rel_paths():
    """Bundel karakter spine: arts/.../animation/character* dan
    spine_assets/character*."""
    raw = http(CATALOG, timeout=120)
    d = json.loads(raw)
    out = []
    for i in d.get("m_InternalIds", []):
        if not i.endswith(".bundle"):
            continue
        rel = i.split("}/", 1)[-1] if "}" in i else i
        low = rel.lower()
        if "plugin" in low or "shaders" in low:
            continue
        if "character" in low or "spine_assets" in low:
            out.append(rel)
    return out


def extract_bundle(path, out_root):
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
                elif nm.lower().endswith(".skel"):
                    skels[nm[:-5]] = body
                else:
                    # beberapa game menaruh skeleton JSON tanpa ekstensi
                    if body[:1] == b"{":
                        skels[nm] = body
            elif t == "Texture2D":
                r = ob.read()
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
        with open(os.path.join(dest, stem + (".json" if skel[:1] == b"{" else ".skel")), "wb") as f:
            f.write(skel)
        with open(os.path.join(dest, stem + ".atlas"), "wb") as f:
            f.write(at)
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


def one(rel):
    fp = os.path.join(CACHE, rel.replace("/", "_"))
    if not os.path.exists(fp) or os.path.getsize(fp) < 100:
        code = http(f"{BASE}/{rel}", dest=fp)
        if code != "200":
            return rel, -1
    try:
        return rel, extract_bundle(fp, OUT)
    except Exception:
        return rel, -2


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    rels = bundle_rel_paths()
    print(f"bundle karakter: {len(rels)}", flush=True)
    total = 0
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(one, r): r for r in rels}
        for f in as_completed(futs):
            rel, n = f.result()
            done += 1
            if n > 0:
                total += n
            print(f"  [{done}/{len(rels)}] {rel.split('/')[-1][:46]:46} {n:3}  (total {total}, {time.time()-t0:.0f}s)",
                  flush=True)
    print(f"SELESAI {total} model -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
