#!/usr/bin/env python3
"""Unduh BGM adegan CherryTale, simpan opus global.

BGM dipakai lintas scene, jadi disimpan sekali di assets/cherrytale/__bgm
(bukan per model) dan dirujuk lewat /cherrytale-audio/__bgm/<klip>.opus.
Klip dibaca dari kolom `music` di dump StoryHData.txt.

Pemakaian
    /srv/venv-spine/bin/python tools/extract-cherrytale-bgm.py
    /srv/venv-spine/bin/python tools/extract-cherrytale-bgm.py --only sex
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("ex", os.path.join(HERE, "extract-cherrytale.py"))
_ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ex)
BASE_URL, UA, decrypt = _ex.BASE_URL, _ex.UA, _ex.decrypt

import UnityPy  # noqa: E402

IDX = os.path.join(ROOT, "cache", "cherrytale", "idx")
INDEX_FILE = "index.txt.da878ac4b4769f289fed678c3fe8d3a2"
STORY = os.environ.get(
    "STORY_DATA", "/opt/cherrytale/dump/textassets/StoryHData.txt"
)
ASSETS = os.path.join(ROOT, "assets", "cherrytale")
CACHE = os.path.join(ROOT, "cache", "cherrytale", "story-audio")
BITRATE = "48k"


def sh(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def collect_clips() -> set[str]:
    """Klip BGM yang benar-benar dipakai skrip adegan."""
    rows = open(STORY, encoding="utf-8", errors="ignore").read().splitlines()
    head = [h.strip().rstrip("┤") for h in rows[0].split("|")]
    bgm_i = head.index("music")
    bgm: set[str] = set()
    for line in rows[1:]:
        parts = line.split("|")
        if len(parts) <= bgm_i:
            continue
        music = parts[bgm_i].strip()
        if music and music != "-1":
            bgm.add(music)
    return bgm


def resolve(index: dict, clip: str) -> str | None:
    """Klip BGM -> nama bundle, lewat pencocokan sufiks yang ketat."""
    t1 = clip.split("_")[0]
    t2 = "_".join(clip.split("_")[:2])
    for suffix in (f"_sound_bgm_{t2}_{clip}", f"_sound_bgm_{t1}_{clip}", f"_sound_bgm_{clip}"):
        hits = [k for k in index if k.endswith(suffix)]
        if hits:
            return sorted(hits, key=len)[0]
    return None


def fetch(name: str, md5: str) -> bytes:
    path = os.path.join(CACHE, name)
    if os.path.exists(path) and os.path.getsize(path) > 512:
        return open(path, "rb").read()
    req = urllib.request.Request(f"{BASE_URL}{name}.{md5}", headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=120).read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
    return data


def extract_one(clip: str, index: dict) -> tuple[str, float]:
    name = resolve(index, clip)
    if not name:
        return clip, 0.0
    out_dir = os.path.join(ASSETS, "__bgm")
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r"[^\w.\-]", "_", clip)
    dest = os.path.join(out_dir, safe + ".opus")
    if os.path.exists(dest):
        return clip, 0.0
    raw = fetch(name, index[name][1])
    env = None
    for blob in (raw, decrypt(raw)):
        try:
            env = UnityPy.load(blob)
            break
        except Exception:
            continue
    if env is None:
        return clip, 0.0
    seconds = 0.0
    for obj in env.objects:
        if str(obj.type) != "83":
            continue
        for _key, sample in (obj.read().samples or {}).items():
            src = os.path.join(out_dir, safe + ".src")
            open(src, "wb").write(bytes(sample))
            sh(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src,
                "-c:a", "libopus", "-b:a", BITRATE, "-ac", "1", "-ar", "48000", dest])
            os.remove(src)
            if os.path.exists(dest):
                try:
                    out = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", dest],
                        capture_output=True, text=True, check=False,
                    ).stdout.strip()
                    seconds = round(float(out), 3)
                except Exception:
                    seconds = 0.0
    return clip, seconds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring klip")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    index = json.load(open(os.path.join(IDX, INDEX_FILE), encoding="utf-8"))
    bgm = collect_clips()
    if args.only:
        bgm = {c for c in bgm if args.only in c}
    meta: dict[str, dict] = {"bgm": {}}
    miss = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(extract_one, c, index) for c in sorted(bgm)]
        for fut in concurrent.futures.as_completed(futs):
            clip, seconds = fut.result()
            if os.path.exists(os.path.join(ASSETS, "__bgm", re.sub(r"[^\w.\-]", "_", clip) + ".opus")):
                meta["bgm"][clip] = seconds
            else:
                miss += 1
    json.dump(meta, open(os.path.join(ASSETS, "__audio-meta.json"), "w"), indent=1)
    print(f"bgm={len(meta['bgm'])} gagal={miss}")


if __name__ == "__main__":
    main()
