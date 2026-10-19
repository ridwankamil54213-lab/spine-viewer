#!/usr/bin/env python3
"""
Sailor Girl (DMM) Spine extractor.

Source (from 二游资源工具.exe hardcoded URLs):
  https://sailor-dev-dmm-sp.oss-ap-southeast-1.aliyuncs.com/sailorgirl_unity/android_ex/v7.0/
    PackageManifest_PackageEx_2026-06-11-890.bytes   <- YooAsset manifest
    {md5}.bundle                                     <- one bundle per spine model

YooAsset naming rule: bundle files are fetched as ``<hash>.bundle`` where hash
is the 32-hex md5 recorded in the manifest. Bundle names themselves 404.

Output: assets/sailorgirl/<model>/<model>.atlas, .json, *.png
"""
import argparse, hashlib, json, os, re, sys, time
import urllib.request, ssl
import UnityPy

BASE = "https://sailor-dev-dmm-sp.oss-ap-southeast-1.aliyuncs.com/sailorgirl_unity/android_ex/v7.0/"
MANIFEST = "PackageManifest_PackageEx_2026-06-11-890.bytes"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UnityPy.config.FALLBACK_UNITY_VERSION = "2021.3.45f2"


def fetch(url, dest=None, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
                data = r.read()
            if dest:
                tmp = dest + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, dest)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise last


def parse_manifest(raw):
    """Extract (bundle_name, md5) pairs from the YooAsset binary manifest.

    The manifest is a compact protobuf-ish blob: the 32-hex md5 of a bundle is
    written immediately before its bundle name. Pairing by proximity like this
    is what the tool itself does, and it survives manifest version changes far
    better than a hardcoded protobuf schema.
    """
    text = raw.decode("latin-1")
    bundles = re.findall(r"[a-z0-9_]+\.bundle", text)
    hashes = re.findall(r"[0-9a-f]{32}", text)
    pairs = []
    seen = set()
    for name in bundles:
        if name in seen:
            continue
        seen.add(name)
        idx = raw.find(name.encode())
        # md5 closest *before* the bundle name
        best = None
        for h in hashes:
            hb = h.encode()
            pos = raw.rfind(hb, max(0, idx - 220), idx)
            if pos != -1:
                best = h
        if best:
            pairs.append((name, best))
    return pairs


def extract_bundle(path, outdir, model):
    env = UnityPy.load(path)
    os.makedirs(outdir, exist_ok=True)
    got = {"json": None, "atlas": None, "png": []}
    for obj in env.objects:
        t = obj.type.name
        if t == "TextAsset":
            d = obj.read()
            nm = getattr(d, "m_Name", None) or getattr(d, "name", "") or ""
            data = getattr(d, "m_Script", None) or getattr(d, "script", b"")
            if isinstance(data, str):
                data = data.encode("utf8")
            if nm.endswith(".atlas") or nm.endswith(".atlas.txt"):
                open(os.path.join(outdir, f"{model}.atlas"), "wb").write(data)
                got["atlas"] = len(data)
            else:
                open(os.path.join(outdir, f"{model}.json"), "wb").write(data)
                got["json"] = len(data)
        elif t == "Texture2D":
            d = obj.read()
            nm = getattr(d, "m_Name", None) or "tex"
            try:
                img = d.image
                fn = os.path.join(outdir, f"{nm}.png")
                img.save(fn)
                got["png"].append(fn)
            except Exception:
                pass
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="/opt/spine-viewer/assets")
    ap.add_argument("--cache", default="/opt/sailorgirl/bundles")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    os.makedirs(args.cache, exist_ok=True)
    mpath = os.path.join(args.cache, MANIFEST)
    if not os.path.exists(mpath):
        print("fetching manifest…", flush=True)
        fetch(BASE + MANIFEST, mpath)
    raw = open(mpath, "rb").read()
    pairs = parse_manifest(raw)
    print(f"bundle ditemukan: {len(pairs)}", flush=True)
    if args.limit:
        pairs = pairs[: args.limit]

    root = os.path.join(args.assets, "sailorgirl")
    os.makedirs(root, exist_ok=True)
    report = []
    for i, (name, md5) in enumerate(pairs, 1):
        # model name: r001_tryst  (from packageex_assets_resex_spine_role_r001_tryst.bundle)
        m = re.search(r"spine_role_(.+?)\.bundle", name)
        model = (m.group(1) if m else name.replace(".bundle", "")).upper()
        outdir = os.path.join(root, model)
        if os.path.exists(os.path.join(outdir, f"{model}.json")):
            print(f"[{i}/{len(pairs)}] skip {model} (sudah ada)", flush=True)
            continue
        bpath = os.path.join(args.cache, f"{md5}.bundle")
        if not os.path.exists(bpath):
            try:
                fetch(BASE + f"{md5}.bundle", bpath)
            except Exception as e:  # noqa: BLE001
                print(f"[{i}/{len(pairs)}] GAGAL unduh {model}: {e}", flush=True)
                report.append({"model": model, "ok": False, "err": str(e)[:80]})
                continue
        try:
            got = extract_bundle(bpath, outdir, model)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(pairs)}] GAGAL ekstrak {model}: {e}", flush=True)
            report.append({"model": model, "ok": False, "err": str(e)[:80]})
            continue
        ok = bool(got["json"] and got["atlas"] and got["png"])
        print(
            f"[{i}/{len(pairs)}] {model} json={got['json']} atlas={got['atlas']} "
            f"png={len(got['png'])} {'OK' if ok else 'SEBAGIAN'}",
            flush=True,
        )
        report.append({"model": model, "ok": ok, **{k: (v if k != "png" else len(v)) for k, v in got.items()}})

    json.dump(report, open("/opt/sailorgirl/report.json", "w"), indent=1)
    good = sum(1 for r in report if r["ok"])
    print(f"\nSELESAI: {good}/{len(report)} model lengkap", flush=True)


if __name__ == "__main__":
    sys.exit(main())
