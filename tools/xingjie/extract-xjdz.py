#!/usr/bin/env python3
"""Ekstrak skeleton Spine dari H5 性界大战 (xjdz) — h5.spj2web.com.

Game ini Cocos Creator 2.x web. Tidak ada APK yang perlu diunduh: seluruh aset
dilayani langsung lewat HTTP dari build H5-nya.

Rantai:
  1. GET /src/settings.<hash>.js  -> window._CCSettings: rawAssets (id -> [path,
     tipe]), uuids (id -> uuid 22-char), md5AssetsMap (uuid -> hash file),
     assetTypes. type == "sp.SkeletonData" menandai berkas spine.
  2. GET /src/assets/plugin_conf.js -> window.assets_cfg (encriptSign/encriptKey).
  3. Tiap `sp.SkeletonData` di:
       /res/import/<xx>/<uuid36>.<hash>.json          (JSON polos)
     isinya self-contained: `_skeletonJson`, `_atlasText`, `textures[].__uuid__`,
     `textureNames`.
  4. Halaman PNG-nya di:
       /res/raw-assets/<xx>/<uuid36>.<hash>.png
     **terenkripsi**: header `"assets-encrypt-2022"+encriptSign`, lalu base64 PNG
     (berakhir dgn '='), lalu encriptKey + ekor. Dekode = buang header, base64
     sampai '=' pertama.

Jalankan:
    python3 extract-xjdz.py --out /opt/spine-viewer/assets/xingjie
"""
import argparse
import base64
import json
import os
import posixpath
import re
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://h5.spj2web.com"
HEAD_FLAG = b"assets-encrypt-2022"
SIGN = "zOm6SMaxvsiBo4WcR0m5xYVEgZ5Lloq4NgB47cnW"
KEY = "u40DCSu5hsL3AVfl3QS1"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

_lock = threading.Lock()
_stat = {"ok": 0, "fail": 0, "skip": 0, "bytes": 0}
_fails = []


def log(*a):
    with _lock:
        print(*a, flush=True)


def http_get(url, tries=4):
    last = None
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(0.6 * (t + 1))
    raise last


def decode_asset(b):
    """Buang header enkripsi + base64-decode kalau perlu; kembalikan b kalau polos."""
    hdr = HEAD_FLAG + SIGN.encode()
    if not b.startswith(hdr):
        return b
    p = b[len(hdr):]
    i = p.find(b"=")          # '=' menutup base64 PNG
    body = p[: i + 1] if i >= 0 else p
    return base64.b64decode(body + b"=" * ((-len(body)) % 4))


def url_for(path, uuid, hash_, mount):
    return f"{BASE}/res/{mount}/{uuid[:2]}/{uuid}.{hash_}.{path.rsplit('.', 1)[-1]}"


def safe(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(s)).strip("._ ")
    return s or "m"


_B64 = {c: i for i, c in enumerate(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}


def decode_uuid(u):
    """uuid ter-kompres Cocos 22 char -> 36 char."""
    if not u or len(u) != 22:
        return u
    o = u[0] + u[1]
    for i in range(2, 22, 2):
        l = _B64[u[i]]
        r = _B64[u[i + 1]]
        o += "%x%x%x" % (l >> 2, ((l & 3) << 2) | (r >> 4), r & 0xF)
    return "%s-%s-%s-%s-%s" % (o[:8], o[8:12], o[12:16], o[16:20], o[20:32])


def extract_one(item, out_root, md5):
    path = item["path"]          # mis. roleSpine/H30090/body.json
    uuid = item["uuid"]
    mount, folder, name = "import", os.path.dirname(path), os.path.basename(path)
    dest = os.path.join(out_root, safe(path[:-5].replace("/", "_")))
    try:
        jurl = f"{BASE}/res/import/{uuid[:2]}/{uuid}.{md5['import'][uuid]}.json"
        raw = decode_asset(http_get(jurl))
        data = json.loads(raw)
    except Exception as e:
        with _lock:
            _stat["fail"] += 1
            _fails.append(f"{path}: import {type(e).__name__} {e}")
        return

    if "_skeletonJson" not in data:
        with _lock:
            _stat["fail"] += 1
            _fails.append(f"{path}: bukan SkeletonData (keys={list(data)[:6]})")
        return

    # sudah lengkap? (resumable)
    try:
        if os.path.isdir(dest):
            have = set(os.listdir(dest))
            need = {name[:-5] + ".json", name[:-5] + ".atlas"}
            need |= set(data.get("textureNames") or [])
            if need <= have:
                with _lock:
                    _stat["skip"] += 1
                return
    except OSError:
        pass
    os.makedirs(dest, exist_ok=True)

    stem = name[:-5]
    open(os.path.join(dest, stem + ".json"), "w", encoding="utf-8").write(
        json.dumps(data["_skeletonJson"], ensure_ascii=False))
    open(os.path.join(dest, stem + ".atlas"), "w", encoding="utf-8").write(
        data.get("_atlasText") or "")

    # halaman PNG: textures[].__uuid__ (uuid 22-char) + textureNames, urut
    pages = data.get("textureNames") or []
    tuuids = [decode_uuid(t.get("__uuid__")) for t in (data.get("textures") or [])]
    got = 0
    for i, tu in enumerate(tuuids):
        rp = pages[i] if i < len(pages) else f"{stem}.png"
        try:
            th = md5["raw-assets"].get(tu)
            if not th:
                continue
            png = decode_asset(http_get(url_for(rp, tu, th, "raw-assets")))
            if png[:4] != b"\x89PNG":
                continue
            open(os.path.join(dest, rp), "wb").write(png)
            got += 1
            with _lock:
                _stat["bytes"] += len(png)
        except Exception as e:
            with _lock:
                _fails.append(f"{path}: tex {tu} {type(e).__name__}")
    with _lock:
        _stat["ok"] += 1
        if _stat["ok"] % 25 == 0:
            print(f"  ok={_stat['ok']} skip={_stat['skip']} fail={_stat['fail']} "
                  f"{_stat['bytes']/1e6:.0f}MB", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="/opt/xingjie/map.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--filter", default="", help="substring path, mis. 'roleSpine'")
    ap.add_argument("--skip", default="skillEffect",
                    help="substring path yang dilewati (default 'skillEffect' — "
                         "efek skill, bukan model karakter; pakai --skip '' untuk ikut)")
    args = ap.parse_args()

    m = json.load(open(args.map, encoding="utf-8"))
    md5 = m["md5"]
    items = m["skeletons"]
    if args.filter:
        items = [x for x in items if args.filter in x["path"]]
    if args.skip:
        items = [x for x in items if args.skip not in x["path"]]
    if args.limit:
        items = items[: args.limit]
    print(f"skeleton: {len(items)}  ->  {args.out}", flush=True)

    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(lambda it: extract_one(it, args.out, md5), items))
    dt = time.time() - t0
    print(f"\nSELESAI ok={_stat['ok']} skip={_stat['skip']} fail={_stat['fail']} "
          f"{_stat['bytes']/1e6:.1f}MB  ({dt:.0f}s)", flush=True)
    if _fails:
        print(f"gagal ({len(_fails)}):")
        for f in _fails[:30]:
            print("  ", f)


if __name__ == "__main__":
    main()
