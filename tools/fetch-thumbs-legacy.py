#!/usr/bin/env python3
"""Download Nikke character thumbnails from nkas.pages.dev.

Pattern: nikke/c101 -> si_c101_00_s.png ; a variant c101_01 -> si_c101_01_s.png.

IMPORTANT: the host returns HTTP 200 with an HTML error page for unknown
characters, so status codes are useless. Every response is validated as a real
PNG (magic bytes + plausible dimensions) before being kept.
"""
import json
import os
import re
import struct
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

API = "http://127.0.0.1:3000/api/models"
BASE = "https://nkas.pages.dev/characters/"
DEST = "/srv/spine-viewer/public/thumbs/nikke"
MANIFEST = os.path.join(DEST, "_manifest.json")
WORKERS = 12

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def is_png(buf):
    """Real PNG? The host serves HTML error pages with a 200 status."""
    if not buf or len(buf) < 24 or not buf.startswith(PNG_MAGIC):
        return False
    try:
        w, h = struct.unpack(">II", buf[16:24])
    except struct.error:
        return False
    # thumbnails are square-ish and small; an HTML page parses as garbage
    return 16 <= w <= 4096 and 16 <= h <= 4096


def char_slugs(model_id):
    """Candidate thumbnail slugs for a model id, best guess first.

    c101          -> si_c101_00_s
    c101_01       -> si_c101_01_s
    c010          -> si_c010_00_s
    azxservicetime_1 -> si_azxservicetime_1_00_s, then si_azxservicetime_00_s
    """
    leaf = model_id.split("/")[-1]
    out = []
    # a trailing _NN on the folder is the costume/variant index the site uses
    m = re.match(r"^(.*?)_(\d{1,2})$", leaf)
    if m:
        stem, num = m.group(1), m.group(2)
        out.append("si_%s_%02d_s" % (stem, int(num)))
        out.append("si_%s_%s_s" % (stem, num))
        out.append("si_%s_00_s" % stem)
    out.append("si_%s_00_s" % leaf)
    seen = set()
    return [s for s in out if not (s in seen or seen.add(s))]


def fetch(slug):
    url = BASE + slug + ".png"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            buf = r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return slug, None
    return slug, buf if is_png(buf) else None


def main():
    data = json.load(urllib.request.urlopen(API, timeout=120))
    models = data["models"]
    nikke = [m for m in models if (m.get("game") or "") == "nikke"]
    # thumbnails are per character; variants share their root's image
    roots = [m for m in nikke if not m.get("family") or m["family"]["root"] == m["id"]]
    print("model nikke : %d" % len(nikke))
    print("root (karakter): %d" % len(roots))

    os.makedirs(DEST, exist_ok=True)

    # slug -> first model id that wants it
    wanted = {}
    for m in roots:
        wanted.setdefault(char_slugs(m["id"])[0], m["id"])

    print("slug dicoba : %d" % len(wanted))
    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for slug, buf in ex.map(fetch, sorted(wanted)):
            done += 1
            if done % 100 == 0:
                print("  ...%d/%d" % (done, len(wanted)), flush=True)
            if buf:
                path = os.path.join(DEST, slug + ".png")
                with open(path, "wb") as fh:
                    fh.write(buf)
                results[slug] = os.path.getsize(path)

    print("\nberhasil : %d" % len(results))
    print("gagal    : %d" % (len(wanted) - len(results)))

    # map every model (roots AND variants) to its thumbnail file
    manifest = {}
    missing = []
    for m in nikke:
        root = (m.get("family") or {}).get("root") or m["id"]
        got = None
        for slug in char_slugs(root):
            if slug in results:
                got = slug + ".png"
                break
        if got:
            manifest[m["id"]] = got
        else:
            missing.append(m["id"])

    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh)
    print("\nmanifest : %d model" % len(manifest))
    print("tanpa thumbnail : %d" % len(missing))
    if missing:
        print("\ncontoh yang tidak ketemu:")
        for i in missing[:20]:
            print("   ", i, "-> dicoba", char_slugs((next(m for m in nikke if m["id"] == i).get("family") or {}).get("root") or i))
    print("\ntotal ukuran: %.1f MB" % (sum(results.values()) / 1024 / 1024))

    with open("/root/thumb-missing.txt", "w") as fh:
        fh.write("\n".join(missing))
    print("daftar miss -> /root/thumb-missing.txt")


if __name__ == "__main__":
    sys.exit(main())
