#!/usr/bin/env python3
"""Unduh voice sentuhan (tombol tap) CherryTale dan simpan opus per model.

Sumber: kolom `touchVoice` / `touchVoice2` / `touchVoice3` di
SecretHCGClickGameScenesData.txt. Bundle-nya ada di bucket
`..._sound_charvoicetouch_<scene>_<klip>`.

Keluaran: assets/cherrytale/<model>/audio/touch/<NN>.opus + _index.json

Pemakaian
    /srv/venv-spine/bin/python tools/extract-cherrytale-touch.py --only a007_04
    /srv/venv-spine/bin/python tools/extract-cherrytale-touch.py --all
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import subprocess
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
SCENES = os.environ.get(
    "SCENES_DATA", "/opt/cherrytale/dump/textassets/SecretHCGClickGameScenesData.txt"
)
ASSETS = os.path.join(ROOT, "assets", "cherrytale")
CACHE = os.path.join(ROOT, "cache", "cherrytale", "touch")
MODELS = os.path.join(ROOT, "cache", "models-cherrytale.json")
TOUCH_COLS = (25, 26, 27)


def scene_of(model_id: str) -> tuple[str, str] | None:
    m = re.match(r"^cherrytale/img_hcg_dynamic_(.+?)_hcg(\d+)(?:_\d+)?_spine$", model_id)
    return (m.group(1), m.group(2)) if m else None


def touch_clips_by_scene() -> dict[str, list[str]]:
    rows = open(SCENES, encoding="utf-8", errors="ignore").read().splitlines()
    out: dict[str, list[str]] = {}
    for line in rows[1:]:
        parts = line.split("|")
        if len(parts) <= max(TOUCH_COLS) or not parts[2]:
            continue
        key = re.sub(r"_hcg\d+$", "", re.sub(r"_sh$", "", parts[2].lower()))
        clips = []
        for i in TOUCH_COLS:
            v = parts[i].strip()
            if v and v != "-1" and v.startswith("vic_"):
                clips.append(v)
        if clips:
            out[key] = clips
    return out


def resolve(index: dict, clip: str) -> str | None:
    hits = [k for k in index if "_sound_charvoicetouch_" in k and k.endswith("_" + clip)]
    if not hits:
        low = clip.lower()
        hits = [k for k in index if "_sound_charvoicetouch_" in k and k.lower().endswith("_" + low)]
    return sorted(hits, key=len)[0] if hits else None


def fetch(name: str, md5: str) -> bytes:
    path = os.path.join(CACHE, name)
    if os.path.exists(path) and os.path.getsize(path) > 512:
        return open(path, "rb").read()
    req = urllib.request.Request(f"{BASE_URL}{name}.{md5}", headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=120).read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
    return data


def do_model(mid: str, clips: list[str], index: dict) -> int:
    sc = scene_of(mid)
    if not sc:
        return 0
    out_dir = os.path.join(ASSETS, mid.split("/", 1)[1], "audio", "touch")
    os.makedirs(out_dir, exist_ok=True)
    tracks = []
    for n, clip in enumerate(clips, 1):
        dest = os.path.join(out_dir, f"{n:02d}.opus")
        if os.path.exists(dest):
            tracks.append({"file": f"{n:02d}.opus", "clip": clip})
            continue
        name = resolve(index, clip)
        if not name:
            continue
        raw = fetch(name, index[name][1])
        env = None
        for blob in (raw, decrypt(raw)):
            try:
                env = UnityPy.load(blob)
                break
            except Exception:
                continue
        if env is None:
            continue
        for obj in env.objects:
            if str(obj.type) != "83":
                continue
            for _k, sample in (obj.read().samples or {}).items():
                src = os.path.join(out_dir, f"{n:02d}.src")
                open(src, "wb").write(bytes(sample))
                subprocess.run(
                    ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src,
                     "-c:a", "libopus", "-b:a", "32k", "-ac", "1", "-ar", "48000", dest],
                    check=False,
                )
                os.remove(src)
                if os.path.exists(dest):
                    tracks.append({"file": f"{n:02d}.opus", "clip": clip})
    if tracks:
        json.dump({"model": mid, "lang": "JP", "tracks": tracks},
                  open(os.path.join(out_dir, "_index.json"), "w"), indent=1)
    return len(tracks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    if not args.only and not args.all:
        raise SystemExit("pakai --only <substr> atau --all")
    index = json.load(open(os.path.join(IDX, INDEX_FILE), encoding="utf-8"))
    per_scene = touch_clips_by_scene()
    models = json.load(open(MODELS))["models"]
    jobs = []
    for m in models:
        sc = scene_of(m["id"])
        if not sc:
            continue
        clips = per_scene.get(sc[0])
        if not clips:
            continue
        if args.only and args.only not in m["id"]:
            continue
        jobs.append((m["id"], clips))
    total = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(do_model, mid, clips, index) for mid, clips in jobs]
        for fut in concurrent.futures.as_completed(futs):
            total += fut.result()
    print(f"{total} voice sentuhan untuk {len(jobs)} model")


if __name__ == "__main__":
    main()
