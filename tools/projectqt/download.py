#!/usr/bin/env python3
"""Download Project QT Spine bundles listed in the asset manifest.

Reads the manifest the game's own API returns (assets.json), picks the
.unity3d entries whose name mentions "spine", and fetches them from the CDN
with the X-QOOKIA-DEVICE-TYPE header the web client sends (without it the
CDN hands back an error page instead of the bundle).

Resumable: an existing file with the declared size is skipped.
"""
import json
import os
import sys
import urllib.request

BASE = "https://d2mfyxc2xcodjl.cloudfront.net"
HEADERS = {"X-QOOKIA-DEVICE-TYPE": "web", "User-Agent": "Mozilla/5.0"}


def main():
    manifest, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)

    doc = json.load(open(manifest, encoding="utf-8"))
    patches = []
    for a in doc["response"]["asset"]:
        patches += json.loads(a)["asset_patchs"] if isinstance(a, str) else a["asset_patchs"]

    cands = [p for p in patches if p[0].lower().endswith(".unity3d") and "spine" in p[0].lower()]
    print(f"spine bundles: {len(cands)}", flush=True)

    ok = skip = fail = 0
    for i, p in enumerate(cands, 1):
        name, url, size = p[0], p[1], int(p[3])
        dest = os.path.join(out, name)
        if os.path.exists(dest) and os.path.getsize(dest) == size:
            skip += 1
            continue
        try:
            req = urllib.request.Request(f"{BASE}/{url}", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) != size:
                fail += 1
                print(f"  SIZE MISMATCH {name}: {len(data)} != {size}")
                continue
            with open(dest, "wb") as f:
                f.write(data)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  FAIL {name}: {e}")
        if i % 10 == 0 or i == len(cands):
            print(f"  {i}/{len(cands)} ok={ok} skip={skip} fail={fail}", flush=True)

    print(f"\nDONE ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    main()
