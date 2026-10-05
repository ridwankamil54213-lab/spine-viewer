#!/usr/bin/env python3
"""
Angelica Aster R (当归紫苑) — Spine extractor.

Unity Addressables build. The catalog (WebGL) exposes 43k bundle keys that are
plain `<md5>.bundle` hashes, BUT the asset-group names inside the catalog are
obfuscated, so a spine bundle cannot be found from the catalog — it must be
recognised by CONTENT. Bundle URL:

  https://assets.cdnangelicaaster.net/res/v1/WebGL/1/<hash>.bundle

Every bundle is a plain UnityFS archive (Unity version stripped -> use a
fallback). A SPINE bundle holds exactly:

  TextAsset  "<name>.atlas"          (plain Spine atlas text)
  TextAsset  "<name>.skel"           (plain Spine BINARY 4.0.64)
  Texture2D  "<name>"                (page PNG)
  MonoBehaviour "<name>_SkeletonData" / "_Atlas"

Other bundles hold AudioClip / AnimationClip / Sprite / bare Texture2D — those
are skipped. No decryption anywhere.

Usage:
  extract-angelica.py --sample N          # download N random bundles, report spine ratio
  extract-angelica.py --extract [--limit N] [--workers 16] --out DIR
"""
import argparse, io, json, os, random, re, ssl, sys, threading, time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import UnityPy

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://assets.cdnangelicaaster.net/res/v1/WebGL/1/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136"
FALLBACK_UNITY = os.environ.get("UVER", "2022.3.58f1")
UnityPy.config.FALLBACK_UNITY_VERSION = FALLBACK_UNITY

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def dl(name, timeout=90, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(BASE + name, headers={"user-agent": UA})
            op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx))
            with op.open(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if i == retries - 1:
                return None
            time.sleep(1.0 * (i + 1))


def extract_bundle_bytes(data, dest, name):
    """Return status string; write <dest>/{name.atlas,name.skel|json,name.png} if spine."""
    try:
        env = UnityPy.load(io.BytesIO(data))
    except Exception as e:
        return f"load-fail:{str(e)[:40]}"
    atlas = skel = tex = None
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
                elif nm.endswith(".skel") or nm.endswith(".json"):
                    skel = raw
            except Exception:
                pass
        elif t == "Texture2D" and tex is None:
            try:
                tex = o.read().image
            except Exception:
                pass
    if atlas is None and skel is None:
        return "skip-not-spine"
    if atlas is None or skel is None or tex is None:
        return f"partial atlas={atlas is not None} skel={skel is not None} tex={tex is not None}"
    os.makedirs(dest, exist_ok=True)
    ext = ".json" if skel[:1] == b"{" else ".skel"
    open(os.path.join(dest, name + ".atlas"), "wb").write(atlas)
    open(os.path.join(dest, name + ext), "wb").write(skel)
    tex.save(os.path.join(dest, name + ".png"))
    return "ok"


def load_keys(path):
    return [l.strip() for l in open(path) if l.strip().endswith(".bundle")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="/tmp/ang_keys.txt")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default="/opt/spine-viewer/assets/angelica")
    a = ap.parse_args()

    keys = load_keys(a.keys)
    print(f"  bundles: {len(keys)}", flush=True)

    if a.sample:
        random.seed(11)
        samp = random.sample(keys, min(a.sample, len(keys)))
        st = {"ok": 0, "skip": 0, "fail": 0}
        bytes_dl = 0
        spines = []
        lock = threading.Lock()

        def w(name):
            nonlocal bytes_dl
            data = dl(name)
            if not data:
                with lock:
                    st["fail"] += 1
                return
            with lock:
                bytes_dl += len(data)
            try:
                env = UnityPy.load(io.BytesIO(data))
            except Exception:
                with lock:
                    st["fail"] += 1
                return
            is_spine = False
            for o in env.objects:
                if o.type.name == "TextAsset":
                    try:
                        nm = (getattr(o.read(), "m_Name", "") or "").lower()
                        if nm.endswith(".atlas") or nm.endswith(".skel"):
                            is_spine = True
                            break
                    except Exception:
                        pass
            with lock:
                if is_spine:
                    st["ok"] += 1
                    spines.append(name)
                else:
                    st["skip"] += 1

        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(w, samp))
        mb = bytes_dl / 1024 / 1024
        ratio = st["ok"] / max(1, len(samp))
        print(f"  sample={len(samp)} spine={st['ok']} skip={st['skip']} fail={st['fail']}")
        print(f"  downloaded {mb:.1f} MB ({mb/max(1,len(samp))*1024:.0f} KB/bundle)")
        print(f"  spine ratio ≈ {ratio*100:.1f}%  -> est. total spine ≈ {int(ratio*len(keys))}")
        print(f"  est. full download ≈ {mb/max(1,len(samp))*len(keys)/1024:.1f} GB")
        open("/tmp/ang_spine_sample.txt", "w").write("\n".join(spines))
        for s in spines[:10]:
            print("   spine:", s)
        return

    if not a.extract:
        return
    if a.limit:
        keys = keys[:a.limit]

    lock = threading.Lock()
    st = {"ok": 0, "skip": 0, "fail": 0}
    fails = []

    def work(name):
        base = name[:-len(".bundle")]
        dest = os.path.join(a.out, base)
        if os.path.exists(os.path.join(dest, base + ".atlas")):
            with lock:
                st["skip"] += 1
            return
        data = dl(name)
        if not data:
            with lock:
                st["fail"] += 1
                fails.append((name, "download"))
            return
        res = extract_bundle_bytes(data, dest, base)
        with lock:
            if res == "ok":
                st["ok"] += 1
            elif res.startswith("skip"):
                st["skip"] += 1
            else:
                st["fail"] += 1
                fails.append((name, res))

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, k) for k in keys]
        for i, _ in enumerate(as_completed(futs), 1):
            if i % 200 == 0:
                with lock:
                    print(f"  [{i}/{len(keys)}] ok={st['ok']} skip={st['skip']} fail={st['fail']} "
                          f"({time.time()-t0:.0f}s)", flush=True)
    print(f"  DONE bundles={len(keys)} ok={st['ok']} skip={st['skip']} fail={st['fail']} in {time.time()-t0:.0f}s")
    for n, r in fails[:30]:
        print("   FAIL", n, r)


if __name__ == "__main__":
    main()
