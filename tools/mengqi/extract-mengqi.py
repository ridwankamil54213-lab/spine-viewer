#!/usr/bin/env python3
"""
梦琪领导 / President's Ambition - Project Beauty R  (cgg4game Cocos Creator 2.x)

Reproduces the community resource-script flow documented on live2dhub topic
4603 (posts by whomepack):

  1. GET https://city2ntk.cgg4game.com/webfyen/nutakupc.php   (nutaku channel)
     -> 302 Location: https://cdnen.cgg4game.com/games/richman2Release/nutaku.html?...&resVer=<hash>
     (dmm channel: city2dmm.cgg4game.com/webdmm/h5Index_dmmPC.php)
  2. GET https://h.cgg4game.com/games/richman2Release/resource/default.res.<resVer>.json
     -> {'groups':..., 'files': {'assets':..., 'animation': {...}}}  (a nested tree)
  3. Every spine model is a leaf dict { "<Name>.atlas":hash, "<Name>.json":hash, "<Name>":texhash }
     served from https://cdnen.cgg4game.com/games/richman2Release/resource/animation/<path>/
        <Name>_<atlasHash>.atlas
        <Name>_<jsonHash>.json
        <Name>_<texHash>.png
     Spine JSON is plain (e.g. 3.7.94) — no decryption.

Usage:
  extract-mengqi.py --fetch-config                 # refresh default.res.<resVer>.json
  extract-mengqi.py --list                         # show model count
  extract-mengqi.py --extract [--limit N] [--filter REGEX] --out DIR
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.error, ssl, collections

HERE = os.path.dirname(os.path.abspath(__file__))
CDN = "https://cdnen.cgg4game.com"
RES_BASE = "https://h.cgg4game.com/games/richman2Release/resource"
ANIM_DIR = "games/richman2Release/resource/animation"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0")
REF = "https://cdnen.cgg4game.com/"

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def http_get(url, ref=None, timeout=40, redirect=True):
    hdrs = {"User-Agent": UA}
    if ref:
        hdrs["Referer"] = ref
    req = urllib.request.Request(url, headers=hdrs)
    if redirect:
        op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx))
    else:
        class NR(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx), NR())
    return op.open(req, timeout=timeout)


def fetch_resver():
    """Query the nutaku channel landing page and pull ?resVer= out of its Location."""
    url = "https://city2ntk.cgg4game.com/webfyen/nutakupc.php"
    try:
        http_get(url, ref=CDN + "/", redirect=False)
        return None
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            from urllib.parse import urlparse, parse_qs
            loc = e.headers.get("Location", "")
            return parse_qs(urlparse(loc).query).get("resVer", [None])[0]
        raise


def fetch_config(cache):
    rv = fetch_resver()
    if not rv:
        raise SystemExit("could not resolve resVer")
    url = f"{RES_BASE}/default.res.{rv}.json"
    print(f"  resVer={rv}")
    with http_get(url, ref="https://h.cgg4game.com/") as r:
        data = json.loads(r.read().decode("utf-8"))
    json.dump(data, open(cache, "w"), ensure_ascii=False)
    print(f"  config -> {cache}")
    return data


def walk_models(node, path, out):
    """Yield (name, dir_path, atlas_hash, json_hash, tex_hash)."""
    if not isinstance(node, dict):
        return
    atlas_key = next((k for k in node if k.endswith(".atlas")), None)
    if atlas_key and isinstance(node.get(atlas_key), str):
        name = atlas_key[:-len(".atlas")]
        jkey = name + ".json"
        if isinstance(node.get(jkey), str):
            out.append((name, path, node[atlas_key], node[jkey], node.get(name)))
        return
    for k, v in node.items():
        if isinstance(v, dict):
            walk_models(v, (path + "/" + k) if path else k, out)


def load_models(cache):
    d = json.load(open(cache))
    out = []
    walk_models(d["files"]["animation"], "", out)
    return out


def url_for(item_path, base_name, hash_, ext):
    from urllib.parse import quote
    p = item_path.strip("/")
    seg = f"{ANIM_DIR}/{p}/{base_name}_{hash_}{ext}"
    # Some models embed a literal space in the file name; percent-encode it.
    return CDN + "/" + quote(seg, safe="/")


def download(url, dest, retries=5):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return "skip"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for i in range(retries):
        try:
            with http_get(url, ref=REF, timeout=60) as r:
                data = r.read()
            if not data:
                raise IOError("empty")
            tmp = dest + ".part"
            open(tmp, "wb").write(data)
            os.replace(tmp, dest)
            return "ok"
        except Exception as e:
            if i == retries - 1:
                return f"fail:{e}"
            time.sleep(1.5 * (i + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "default.res.json"))
    ap.add_argument("--fetch-config", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--filter", default=None)
    ap.add_argument("--out", default="/opt/spine-viewer/assets/mengqi/resources")
    a = ap.parse_args()

    if a.fetch_config or not os.path.exists(a.config):
        fetch_config(a.config)

    models = load_models(a.config)
    print(f"  models found: {len(models)}")
    if a.filter:
        rx = re.compile(a.filter)
        models = [m for m in models if rx.search(m[0]) or rx.search(m[1])]
        print(f"  after filter: {len(models)}")
    if a.list:
        c = collections.Counter(m[1].split("/")[0] or "<root>" for m in models)
        for k, v in c.most_common(30):
            print(f"    {v:5}  {k}")
        return
    if not a.extract:
        for m in models[:20]:
            print("   ", m)
        return

    if a.limit:
        models = models[:a.limit]
    ok = skip = fail = 0
    fails = []
    for i, (name, path, ah, jh, th) in enumerate(models, 1):
        # Nested layout (no flattening): <out>/<sub/dir>/<Name>/<files>, so the
        # viewer sidebar shows "dmR › role_fishion › <Name>" directly.
        d = os.path.join(a.out, path.strip("/"), name)
        r1 = download(url_for(path, name, ah, ".atlas"), os.path.join(d, name + ".atlas"))
        r2 = download(url_for(path, name, jh, ".json"), os.path.join(d, name + ".json"))
        r3 = download(url_for(path, name, th, ".png"), os.path.join(d, name + ".png")) if th else "skip"
        res = [r1, r2, r3]
        if any(x.startswith("fail") for x in res):
            fail += 1
            fails.append((d, res))
        elif all(x == "skip" for x in res):
            skip += 1
        else:
            ok += 1
        if i % 100 == 0:
            print(f"  [{i}/{len(models)}] ok={ok} skip={skip} fail={fail}", flush=True)
    print(f"  DONE models={len(models)} ok={ok} skip={skip} fail={fail}")
    for d, res in fails[:20]:
        print("   FAIL", d, res)


if __name__ == "__main__":
    main()
