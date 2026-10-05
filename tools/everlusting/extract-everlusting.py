#!/usr/bin/env python3
"""
Everlusting Life (adult-chess.com) — Spine extractor.

Source: community downloader script, live2dhub topic 4603 post #40 / #124.
The game's asset service lists every downloadable bundle:

  POST https://assetservice.adult-chess.com/ac/get_assets_with_als
       headers: x-country: JP, content-type: application/json
       body:    {"state": "ac-release-v<VER>", "static_type": "webgl_bundles"}
  -> {"result": {"assets": { "<category>": [ {uid,name,url,size,hash,...}, ... ] }}}

Every entry is a **plain UnityFS AssetBundle** (Unity 2022.3.20f1) that holds
exactly one Spine model:
    TextAsset  "<Name>.atlas"   (Spine atlas, plain text)
    TextAsset  "<Name>"         (Spine skeleton, plain JSON, Spine 4.2.40)
    Texture2D  "<Name>"         (page PNG)

No decryption anywhere. Output layout:
    <out>/<category>/<name>/{<name>.json,<name>.atlas,<name>.png}

Usage:
  extract-everlusting.py --list
  extract-everlusting.py --extract [--filter REGEX] [--limit N] --out DIR
  extract-everlusting.py --version 3.0.0
"""
import argparse, io, json, os, re, ssl, sys, threading, time
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import UnityPy

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://assetservice.adult-chess.com/ac/get_assets_with_als"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0")

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def http_post(url, payload, timeout=40):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={
        "user-agent": UA, "x-country": "JP", "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9", "content-type": "application/json",
    })
    op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx))
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_get(url, timeout=120, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"user-agent": UA})
            op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx))
            with op.open(req, timeout=timeout) as r:
                data = r.read()
            if data:
                return data
            raise IOError("empty")
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def fetch_index(version):
    d = http_post(API, {"state": f"ac-release-v{version}", "static_type": "webgl_bundles"})
    assets = d.get("result", {}).get("assets", {})
    out = []
    for cat, items in assets.items():
        for it in items:
            out.append({
                "category": cat,
                "name": it["name"],
                "url": it.get("cloudfront_url") or it["url"],
                "backup": it.get("backup_url"),
                "size": it.get("size", 0),
            })
    return out


def extract_bundle(data, name, dest):
    """UnityFS bundle bytes -> <dest>/{name.json,.atlas,.png}. Returns status."""
    env = UnityPy.load(io.BytesIO(data))
    atlas = skel = tex = None
    for o in env.objects:
        t = o.type.name
        if t == "TextAsset":
            try:
                d = o.read()
                nm = getattr(d, "m_Name", "") or ""
                raw = d.m_Script
                raw = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else bytes(raw)
                if nm.lower().endswith(".atlas"):
                    atlas = raw
                else:
                    skel = (nm, raw)
            except Exception:
                pass
        elif t == "Texture2D":
            try:
                tex = o.read().image  # PIL image
            except Exception:
                pass
    if not (atlas and skel and tex is not None):
        # Some entries are plain preview images (Texture2D only) — not spine.
        if not atlas and not skel:
            return "skip-not-spine"
        return f"missing atlas={bool(atlas)} skel={bool(skel)} tex={tex is not None}"
    os.makedirs(dest, exist_ok=True)
    base = skel[0] or name
    open(os.path.join(dest, name + ".atlas"), "wb").write(atlas)
    open(os.path.join(dest, name + ".json"), "wb").write(skel[1])
    tex.save(os.path.join(dest, name + ".png"))
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="3.0.0")
    ap.add_argument("--cache", default=os.path.join(HERE, "index.json"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--filter", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="/opt/spine-viewer/assets/everlusting")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    if not os.path.exists(a.cache) or a.list:
        idx = fetch_index(a.version)
        json.dump(idx, open(a.cache, "w"), ensure_ascii=False)
        print(f"  index -> {a.cache} ({len(idx)} bundles)", flush=True)
    idx = json.load(open(a.cache))
    print(f"  bundles: {len(idx)}")
    if a.list:
        import collections
        c = collections.Counter(x["category"] for x in idx)
        for k, v in c.most_common():
            print(f"    {k:24} {v}")
        return
    if not a.extract:
        return

    if a.filter:
        rx = re.compile(a.filter)
        idx = [x for x in idx if rx.search(x["name"]) or rx.search(x["category"])]
        print(f"  after filter: {len(idx)}")
    if a.limit:
        idx = idx[:a.limit]

    lock = threading.Lock()
    stats = {"ok": 0, "skip": 0, "fail": 0}
    fails = []

    def work(it):
        dest = os.path.join(a.out, it["category"], it["name"])
        if os.path.exists(os.path.join(dest, it["name"] + ".json")) and \
           os.path.exists(os.path.join(dest, it["name"] + ".png")):
            with lock:
                stats["skip"] += 1
            return
        try:
            data = http_get(it["url"])
        except Exception:
            try:
                data = http_get(it["backup"])
            except Exception as e:
                with lock:
                    stats["fail"] += 1
                    fails.append((it["name"], f"download:{e}"))
                return
        try:
            res = extract_bundle(data, it["name"], dest)
        except Exception as e:
            res = f"extract:{e}"
        with lock:
            if res == "ok":
                stats["ok"] += 1
            elif res.startswith("skip"):
                stats["skip"] += 1
            else:
                stats["fail"] += 1
                fails.append((it["name"], res))

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, it) for it in idx]
        for i, _ in enumerate(as_completed(futs), 1):
            if i % 100 == 0:
                with lock:
                    print(f"  [{i}/{len(idx)}] ok={stats['ok']} skip={stats['skip']} fail={stats['fail']}", flush=True)

    print(f"  DONE bundles={len(idx)} ok={stats['ok']} skip={stats['skip']} fail={stats['fail']}")
    for n, r in fails[:30]:
        print("   FAIL", n, r)


if __name__ == "__main__":
    main()
