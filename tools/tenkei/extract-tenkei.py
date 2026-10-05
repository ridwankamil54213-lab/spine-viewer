#!/usr/bin/env python3
"""
天啓パラドクスX / Tenkei Paradox X (KMS / EXNOA) — Spine extractor.

The game is a Unity Addressables build. Two catalogs list every bundle:

  https://cdne-paripari-prod.tenkei-paradox.com/production/
      production<N>-864dc0b0-6f1a-4aaa-bb36-703600ea7966/Assets/<Platform>/
      (base_catalog.json | assets_catalog.json | vfx_catalog.json)

`<N>` changes with game updates (seen: 3, 7, 8, 9 — try 1..12). Android and
WebGL trees hold the same assets (`Assets/Android/...`).

Each spine is ONE plain UnityFS bundle:

  PariPariPublicRemote/spines_assets_spines/<id>_<hash>.bundle
    -> TextAsset  "<id>.atlas"   (plain Spine atlas text)
       TextAsset  "<id>.skel"    (plain Spine binary, no decryption)
       Texture2D  "<id>"         (page PNG)

URL mapping: strip the leading "PariPariPublicRemote/" and append to
  <base>/production/production<N>-<uuid>/Assets/<Platform>/

Output: <out>/<id>/{<id>.json-or-skel,<id>.atlas,<id>.png}

Usage:
  extract-tenkei.py --probe                      # find the live production<N>
  extract-tenkei.py --list                       # count bundles per category
  extract-tenkei.py --extract [--cat spines] [--limit N] [--filter RX] --out DIR
"""
import argparse, io, json, os, re, ssl, threading, time
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import UnityPy

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = "https://cdne-paripari-prod.tenkei-paradox.com"
UUID = "864dc0b0-6f1a-4aaa-bb36-703600ea7966"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136"

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def get(url, timeout=120, retries=4, binary=True):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"user-agent": UA})
            op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx))
            with op.open(req, timeout=timeout) as r:
                data = r.read()
            if not data:
                raise IOError("empty")
            return data if binary else data.decode("utf-8")
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def base_for(prod, platform):
    return f"{HOST}/production/production{prod}-{UUID}/Assets/{platform}"


def probe_production(platform="Android", start=1, end=12):
    """Return the highest production<N> whose assets_catalog.json exists."""
    found = []
    for n in range(start, end + 1):
        u = f"{base_for(n, platform)}/assets_catalog.json"
        try:
            req = urllib.request.Request(u, headers={"user-agent": UA})
            op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx))
            with op.open(req, timeout=15) as r:
                if r.status == 200:
                    found.append(n)
        except Exception:
            pass
    return found


def load_catalog(prod, platform, name="assets_catalog.json"):
    url = f"{base_for(prod, platform)}/{name}"
    return json.loads(get(url, binary=False))


def list_spines(cat, cat_name="assets_catalog.json", platform="Android"):
    d = load_catalog(cat, platform, cat_name)
    ids = d.get("m_InternalIds") or []
    out = []
    for i in ids:
        if i.startswith("PariPariPublicRemote/") and i.endswith(".bundle"):
            up = i[len("PariPariPublicRemote/"):]
            cat_dir = up.split("/")[0]
            out.append({"raw": i, "url": f"{base_for(cat, platform)}/{up}", "cat": cat_dir})
    return out


def extract_bundle(data, dest, name):
    env = UnityPy.load(io.BytesIO(data))
    atlas = None
    skel = None
    tex = None
    for o in env.objects:
        t = o.type.name
        if t == "TextAsset":
            try:
                d = o.read()
                nm = (getattr(d, "m_Name", "") or "").lower()
                raw = d.m_Script
                raw = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else bytes(raw)
                if nm.endswith(".atlas"):
                    atlas = raw
                elif nm.endswith(".skel"):
                    skel = raw
                elif nm.endswith(".json"):
                    skel = raw
            except Exception:
                pass
        elif t == "Texture2D":
            try:
                tex = o.read().image
            except Exception:
                pass
    if atlas is None and skel is None:
        return "skip-not-spine"
    if atlas is None or skel is None or tex is None:
        return f"missing atlas={atlas is not None} skel={skel is not None} tex={tex is not None}"
    os.makedirs(dest, exist_ok=True)
    ext = ".json" if skel[:1] == b"{" else ".skel"
    open(os.path.join(dest, name + ".atlas"), "wb").write(atlas)
    open(os.path.join(dest, name + ext), "wb").write(skel)
    tex.save(os.path.join(dest, name + ".png"))
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", type=int, default=0)
    ap.add_argument("--platform", default="Android")
    ap.add_argument("--catalog", default="assets_catalog.json")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--cat", default="spines_assets_spines")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--filter", default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="/opt/spine-viewer/assets/tenkei")
    a = ap.parse_args()

    prod = a.prod
    if not prod or a.probe:
        found = probe_production(a.platform)
        print(f"  live production<N>: {found}")
        if not found:
            raise SystemExit("no live production tree")
        prod = max(found)
    print(f"  using production{prod} / {a.platform}")

    items = list_spines(prod, a.catalog, a.platform)
    import collections
    cats = collections.Counter(x["cat"] for x in items)
    print(f"  bundles: {len(items)}")
    if a.list:
        for k, v in cats.most_common():
            print(f"    {k:44} {v}")
        return
    if a.cat and a.cat != "*":
        items = [x for x in items if x["cat"] == a.cat]
    if a.filter:
        rx = re.compile(a.filter)
        items = [x for x in items if rx.search(x["raw"])]
    if a.limit:
        items = items[:a.limit]
    if not a.extract:
        print(f"  selected: {len(items)}  (use --extract)")
        return

    lock = threading.Lock()
    stats = {"ok": 0, "skip": 0, "fail": 0}
    fails = []

    def work(x):
        name = os.path.basename(x["raw"]).split("_")[0]
        dest = os.path.join(a.out, x["cat"], name)
        if os.path.exists(os.path.join(dest, name + ".atlas")):
            with lock:
                stats["skip"] += 1
            return
        try:
            data = get(x["url"])
        except Exception as e:
            with lock:
                stats["fail"] += 1
                fails.append((x["raw"], f"download:{e}"))
            return
        try:
            res = extract_bundle(data, dest, name)
        except Exception as e:
            res = f"extract:{e}"
        with lock:
            if res == "ok":
                stats["ok"] += 1
            elif res.startswith("skip"):
                stats["skip"] += 1
            else:
                stats["fail"] += 1
                fails.append((x["raw"], res))

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, x) for x in items]
        for i, _ in enumerate(as_completed(futs), 1):
            if i % 50 == 0:
                with lock:
                    print(f"  [{i}/{len(items)}] ok={stats['ok']} skip={stats['skip']} fail={stats['fail']}", flush=True)

    print(f"  DONE bundles={len(items)} ok={stats['ok']} skip={stats['skip']} fail={stats['fail']}")
    for n, r in fails[:30]:
        print("   FAIL", n, r)


if __name__ == "__main__":
    main()
