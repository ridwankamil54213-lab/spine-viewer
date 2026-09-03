#!/usr/bin/env python3
"""Download every Project QT .unity3d bundle so they can be inspected.

The first pass only fetched bundles whose NAME contained "spine" (86 of 1930)
and found 86 models. Most character bundles don't say "spine" in the name, so
this pulls all of them and tools/projectqt/scan_bundles.py checks each one for
a skeleton + atlas instead of trusting the filename.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = "https://d2mfyxc2xcodjl.cloudfront.net"
HEADERS = {"X-QOOKIA-DEVICE-TYPE": "web", "User-Agent": "Mozilla/5.0"}


def main():
    manifest, out = sys.argv[1], sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    os.makedirs(out, exist_ok=True)

    doc = json.load(open(manifest, encoding="utf-8"))
    patches = []
    for a in doc["response"]["asset"]:
        patches += json.loads(a)["asset_patchs"] if isinstance(a, str) else a["asset_patchs"]

    cands = [p for p in patches if p[0].lower().endswith(".unity3d")]
    if limit:
        cands = cands[:limit]
    print(f"bundles: {len(cands)}", flush=True)

    ok = skip = fail = 0
    errors = []
    for i, p in enumerate(cands, 1):
        name, url, size = p[0], p[1], int(p[3])
        dest = os.path.join(out, name)
        if os.path.exists(dest) and os.path.getsize(dest) == size:
            skip += 1
            continue
        try:
            # Some paths contain spaces, which urllib rejects outright —
            # quote them (leaving '/' intact) so those bundles still fetch.
            safe_url = urllib.parse.quote(f"{BASE}/{url}", safe="/:%")
            req = urllib.request.Request(safe_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) != size:
                fail += 1
                errors.append(f"{name}: size {len(data)} != {size}")
                continue
            with open(dest, "wb") as f:
                f.write(data)
            ok += 1
        except Exception as e:
            fail += 1
            errors.append(f"{name}: {e}")
        if i % 100 == 0 or i == len(cands):
            print(f"  {i}/{len(cands)} ok={ok} skip={skip} fail={fail}", flush=True)

    print(f"\nDONE ok={ok} skip={skip} fail={fail}")
    if errors:
        with open(os.path.join(out, "_errors.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(str(e) for e in errors))
        for e in errors[:10]:
            print("  " + e)


if __name__ == "__main__":
    main()
