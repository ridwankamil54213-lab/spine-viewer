#!/usr/bin/env python3
"""Unduh voice H-scene Ark Re:Code (Hxxx_SexStory_*.ogg) dari catalog
Addressables ke opus per model.

Sumber internal id di catalog_116310.json:
    Assets/Game/Hero/H001/Sound/H001_SexStory_01.ogg   (aset logis)
    http://PatchDomain/Android/...h001_sexstory_01.prefab_<hash>.bundle

AudioClip di bundle polos (tanpa dekripsi) -> WAV 48 kHz mono -> opus 32k.
Keluaran: assets/arkrecode/<MODEL>_S/audio/story/<NN>.opus + _index.json

Pemakaian
    /srv/venv-spine/bin/python tools/extract-arkrecode-story-voices.py --only H001_S
    /srv/venv-spine/bin/python tools/extract-arkrecode-story-voices.py --all
    /srv/venv-spine/bin/python tools/extract-arkrecode-story-voices.py --all --limit 5
"""
from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import os
import re
import ssl
import subprocess
import urllib.request

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f2"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOG = os.path.join(ROOT, "cache", "arkrecode", "catalog_116310.json")
ASSETS = os.path.join(ROOT, "assets", "arkrecode")
CACHE = os.path.join(ROOT, "cache", "arkrecode", "voice")
CDN = "https://erdpu.gzxhcjz.com/GamePatch/Android/"
UA = {"User-Agent": "UnityPlayer/2022.3.28f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"}
CTX = ssl._create_unverified_context()
AUDIO = re.compile(r"Assets/Game/Hero/(H\d{3})/Sound/\1_(SexStory|Sex|Story)_(\d+)\.ogg$", re.I)


def fetch(url: str, dest: str) -> bytes:
    if os.path.exists(dest) and os.path.getsize(dest) > 512:
        return open(dest, "rb").read()
    req = urllib.request.Request(url, headers=UA)
    data = urllib.request.urlopen(req, timeout=120, context=CTX).read()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "wb").write(data)
    return data


_HERO_CACHE: dict[str, str] = {}


def resolve(ids: list[str], hero: str, group: str, number: str) -> str | None:
    """Bundle hero gabungan memuat SEMUA audio hero itu; individual bundle
   SexStory hanya ada untuk sebagian kecil hero. Ambil gabungan bila ada."""
    if hero in _HERO_CACHE:
        return _HERO_CACHE[hero]
    stem = f"/game/hero/{hero.lower()}_"
    hits = [
        i for i in ids
        if i.startswith("http") and i.endswith(".bundle") and stem in i.lower()
        and ("/game/hero/" in i.lower())
    ]
    # Bundle gabungan biasanya yang tidak punya sufiks全称 `.prefab_*`.
    hits = [i for i in hits if "/sound/" not in i.lower() and "/img" not in i.lower()]
    if not hits:
        hits = [i for i in ids if i.startswith("http") and i.endswith(".bundle")
                and f"{hero.lower()}_{group.lower()}_{number}" in i.lower()]
    if not hits:
        return None
    url = sorted(hits, key=len)[0].replace("http://PatchDomain/Android/", CDN)
    _HERO_CACHE[hero] = url
    return url


def do_model(model: str, clips: list[tuple[str, str, str]], ids: list[str], index: dict) -> int:
    hero = model.split("_")[0]
    out_dir = os.path.join(ASSETS, model, "audio", "story")
    os.makedirs(out_dir, exist_ok=True)
    tracks = []
    for group, num, clip in clips:
        stem = f"{group}_{int(num):02d}"
        dest = os.path.join(out_dir, stem + ".opus")
        if not os.path.exists(dest):
            url = resolve(ids, hero, group, num)
            if not url:
                continue
            raw = fetch(url, os.path.join(CACHE, os.path.basename(url)))
            try:
                env = UnityPy.load(io.BytesIO(raw))
            except Exception:
                continue
            want = f"{hero}_{group}_{num}"
            blob = None
            for o in env.objects:
                if str(o.type) != "83":
                    continue
                r = o.read()
                if str(r.m_Name).lower() != want.lower():
                    continue
                for _k, v in (r.samples or {}).items():
                    blob = bytes(v)
                    break
                if blob:
                    break
            if not blob:
                continue
            src = os.path.join(out_dir, stem + ".src")
            open(src, "wb").write(blob)
            subprocess.run(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src,
                 "-c:a", "libopus", "-b:a", "32k", "-ac", "1", "-ar", "48000", dest],
                check=False,
            )
            os.remove(src)
        if os.path.exists(dest):
            tracks.append({"file": stem + ".opus", "clip": clip, "group": group})
    if tracks:
        json.dump({"model": model, "lang": "KO", "tracks": tracks},
                  open(os.path.join(out_dir, "_index.json"), "w"), indent=1)
    return len(tracks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    if not args.only and not args.all:
        raise SystemExit("pakai --only <model> atau --all")
    cat = json.load(open(CATALOG, encoding="utf-8"))
    ids = [str(x) for x in cat["m_InternalIds"]]
    by_hero: dict[str, list[tuple[str, str, str]]] = {}
    for i in ids:
        m = AUDIO.match(i)
        if not m:
            continue
        hero, group, num = m.group(1), m.group(2), m.group(3)
        by_hero.setdefault(hero, []).append((group, num, i.split("/")[-1]))
    models = sorted({h + "_S" for h in by_hero})
    if args.only:
        models = [m for m in models if args.only.lower() in m.lower()]
    if args.limit:
        models = models[: args.limit]
    print(f"model: {len(models)}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {}
        for model in models:
            futs[pool.submit(do_model, model, sorted(by_hero[model.split("_")[0]]), ids, {})] = model
        total = 0
        for fut in concurrent.futures.as_completed(futs):
            model = futs[fut]
            n = fut.result()
            total += n
            if n:
                print(f"  {model}: {n}", flush=True)
    print(f"selesai: {total} klip")


if __name__ == "__main__":
    main()
