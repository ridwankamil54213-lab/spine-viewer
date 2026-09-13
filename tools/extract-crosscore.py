#!/usr/bin/env python3
"""Assemble CrossCore (交错战线) Spine models for the viewer.

Source: an official resource CDN, no APK needed.
  https://cdn.megagamelog.com/cross/release/android/curr_1/ver.bytes
    -> .NET BinaryFormatter manifest listing every AssetBundle (name/size/md5)
  https://cdn.megagamelog.com/cross/release/android/curr_1/Custom/<AB name>

Bundles are FakeHeader/UnityCN-encrypted, so UnityPy cannot read them. They are
extracted with AssetStudioModCLI (aelurum fork, net8 portable, which ships the
Linux libTexture2DDecoderNative.so the RazTools build lacks — textures are ASTC).

Each `prefabs_spine_*` bundle is self-contained: exporting it with NO type
filter yields the skeleton (a TextAsset whose payload is JSON, shipped as
`.prefab`), the atlas text, and the page texture as a real PNG. So one bundle
per model, no cross-bundle texture matching needed.

Output layout per model — exactly what the viewer's scanner expects:
    assets/crosscore/<Name>/<Name>.json    (skeleton; JSON, so the .json
                                            extension makes the viewer parse it
                                            as text, not binary)
    assets/crosscore/<Name>/<Name>.atlas
    assets/crosscore/<Name>/<Name>.png

Usage:
    python3 tools/extract-crosscore.py --work /root/cross --out assets/crosscore
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

CDN = "https://cdn.megagamelog.com/cross/release/android/curr_1"
MANIFEST_URL = f"{CDN}/ver.bytes"

# AssetStudioModCLI (aelurum fork). The RazTools build has no Linux
# Texture2DDecoderNative, so ASTC textures fail to decode there — use:
#   https://github.com/aelurum/AssetStudio/releases  ->  AssetStudioModCLI_net8_portable.zip
# (needs the .NET 8 runtime; run with `dotnet AssetStudioModCLI.dll`).
STUDIO = os.environ.get(
    "ASSETSTUDIO",
    "/opt/studio3/AssetStudioModCLI_net8_portable/AssetStudioModCLI.dll",
)
AB_RE = re.compile(r"^prefabs_spine_")


def read_7bit(data, i):
    val, shift = 0, 0
    for k in range(4):
        if i + k >= len(data):
            return None, None
        b = data[i + k]
        val |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            return val, i + k + 1
    return None, None


def parse_manifest(path):
    """BinaryFormatter strings are 7-bit-length-prefixed; pair each AB name
    with the FileMD5/size that follow it. (A plain regex over the file
    over-matches: the byte after a name can itself be a letter.)"""
    data = open(path, "rb").read()
    names = []
    i = 0
    while i < len(data):
        ln, after = read_7bit(data, i)
        if ln is None or after is None or not (8 <= ln <= 120) or after + ln > len(data):
            i += 1
            continue
        s = data[after:after + ln]
        if not re.match(rb"(prefabs|textures)_[A-Za-z0-9_]+$", s):
            i += 1
            continue
        tail = data[after + ln: after + ln + 90]
        m = re.search(rb"[0-9A-F]{32}", tail)
        if not m:
            i += 1
            continue
        p = after + ln + m.start() + 32
        size = int.from_bytes(data[p:p + 8], "little", signed=True) if p + 8 <= len(data) else 0
        names.append({"name": s.decode(), "md5": m.group().decode(), "size": size})
        i = after + ln
    return names


def download(entries, raw):
    os.makedirs(raw, exist_ok=True)
    todo = [e for e in entries if not (os.path.exists(os.path.join(raw, e["name"]))
                                       and os.path.getsize(os.path.join(raw, e["name"])) == e["size"])]
    if not todo:
        print(f"[2/4] all {len(entries)} bundles present")
        return
    print(f"[2/4] downloading {len(todo)}/{len(entries)} bundles "
          f"({sum(e['size'] for e in todo)/1024**2:.0f} MB)")
    cfg = os.path.join(raw, "_curl.cfg")
    lines = ["--create-dirs", "--fail", "--location", "--silent", "--show-error"]
    for e in todo:
        lines += [f'url = "{CDN}/Custom/{e["name"]}"', f'output = "{raw}/{e["name"]}"']
    open(cfg, "w").write("\n".join(lines) + "\n")
    subprocess.run(["curl", "-K", cfg, "--parallel", "--parallel-max", "16",
                    "--retry", "4", "--retry-delay", "2", "--retry-all-errors", "--max-time", "600"],
                   check=True)


def extract(raw, extracted, batch=30):
    """Extract with AssetStudioModCLI in small batches.

    Feeding all 521 bundles at once OOM-kills the process (~6.5 GB RSS): it
    keeps every decoded texture in memory. Batches of ~30 bundle the peak by
    an order of magnitude and each run appends to the same output tree.
    """
    print(f"[3/4] extracting with AssetStudioModCLI (batches of {batch}) -> {extracted}")
    if os.path.isdir(extracted):
        shutil.rmtree(extracted)
    os.makedirs(extracted, exist_ok=True)

    bundles = sorted(f for f in os.listdir(raw) if f.startswith("prefabs_spine"))
    tmpdir = os.path.join(raw, "_batch")
    for i in range(0, len(bundles), batch):
        chunk = bundles[i:i + batch]
        shutil.rmtree(tmpdir, ignore_errors=True)
        os.makedirs(tmpdir)
        for f in chunk:
            os.symlink(os.path.join(raw, f), os.path.join(tmpdir, f))
        r = subprocess.run(["dotnet", STUDIO, tmpdir, "-o", extracted, "--log-level", "error"],
                           capture_output=True, text=True)
        print(f"    batch {i // batch + 1}/{(len(bundles) + batch - 1) // batch}: "
              f"{len(chunk)} bundles rc={r.returncode}")
    shutil.rmtree(tmpdir, ignore_errors=True)


def assemble(extracted, out):
    root = os.path.join(extracted, "assets", "res", "prefabs", "spine")
    if not os.path.isdir(root):
        # older/newer builds may nest differently; find "prefabs/spine"
        for dp, _, _ in os.walk(extracted):
            if dp.endswith(os.path.join("prefabs", "spine")):
                root = dp
                break
    made = 0
    os.makedirs(out, exist_ok=True)
    for stem in sorted(os.listdir(root)):
        d = os.path.join(root, stem)
        if not os.path.isdir(d):
            continue
        files = os.listdir(d)
        skel = [f for f in files if f.endswith(".prefab")]
        atlas = [f for f in files if f.endswith(".atlas")]
        pngs = [f for f in files if f.lower().endswith(".png")]
        if not (skel and atlas and pngs):
            continue
        base = skel[0][: -len(".prefab")]
        dest = os.path.join(out, base)
        os.makedirs(dest, exist_ok=True)
        # skeleton: JSON payload, so ship it as .json
        shutil.copyfile(os.path.join(d, skel[0]), os.path.join(dest, base + ".json"))
        shutil.copyfile(os.path.join(d, atlas[0]), os.path.join(dest, base + ".atlas"))
        for png in pngs:
            shutil.copyfile(os.path.join(d, png), os.path.join(dest, png))
        made += 1
    print(f"[4/4] assembled {made} models -> {out}")
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/root/cross")
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = args.out or os.path.join(repo, "assets", "crosscore")

    os.makedirs(args.work, exist_ok=True)
    man_path = os.path.join(args.work, "ver.bytes")
    if not os.path.exists(man_path):
        print("[1/4] fetching ver.bytes")
        subprocess.run(["curl", "-fsSL", "--max-time", "120", "-o", man_path, MANIFEST_URL], check=True)
    entries = [e for e in parse_manifest(man_path) if AB_RE.match(e["name"])]
    print(f"[1/4] manifest: {len(entries)} Spine bundles")

    raw = os.path.join(args.work, "ab")
    if not args.skip_download:
        download(entries, raw)
    extracted = os.path.join(args.work, "extracted")
    extract(raw, extracted)
    assemble(extracted, out)


if __name__ == "__main__":
    sys.exit(main())
