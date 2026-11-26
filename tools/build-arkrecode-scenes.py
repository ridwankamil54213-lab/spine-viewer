#!/usr/bin/env python3
"""Susun data adegan H-scene Ark Re:Code untuk viewer.

Sumber data yang tersedia:
  * animasi Spine Hxxx_S (urutan asli di file .skel) sebagai fase,
  * AudioClip SexStory_## / Sex_## dari bundle hero (lihat
    tools/extract-arkrecode-story-voices.py) sebagai baris voice.

Tidak ada tabel dialog/urutan cerita di katalog APK maupun CDN, jadi voice
dipetakan berurutan ke fase yang ada; tiap tap memajukan satu baris voice.
Fitur viewer yang dipakai ulang: dock timeline, tap, sensor, lensa, dan
subtitle (tanpa teks) — persis jalur model tanpa skrip di CherryTale.

Keluaran: data/arkrecode-scenes.json { "<model id>": {...} }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "arkrecode-scenes.json")
ASSETS = os.path.join(ROOT, "assets", "arkrecode")
MODELS = os.path.join(ROOT, "cache", "models-arkrecode.json")
VOICE_PREFIX = "/arkrecode-audio"
DEFAULT_SECONDS = 2.2
MAX_SECONDS = 8.0


def run(cmd):
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def collect_models() -> list[dict]:
    """Ambil daftar model dari cache lokal bila ada,否则 dari API."""
    if os.path.exists(MODELS):
        d = json.load(open(MODELS))
        return d.get("models", d) if isinstance(d, dict) else d
    import urllib.request
    d = json.load(urllib.request.urlopen("http://127.0.0.1:3000/api/models?game=arkrecode"))
    json.dump(d, open(MODELS, "w"))
    return d["models"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    models = collect_models()
    targets = [
        m for m in models
        if re.match(r"^arkrecode/H\d{3}_S$", m["id"])
        and os.path.exists(os.path.join(ASSETS, m["id"].split("/", 1)[1], "audio", "story", "_index.json"))
    ]
    if args.only:
        targets = [m for m in targets if args.only.lower() in m["id"].lower()]
    if args.limit:
        targets = targets[: args.limit]

    out: dict = {}
    for m in targets:
        slug = m["id"].split("/", 1)[1]
        anims = [a for a in (m.get("animations") or []) if a]
        if not anims:
            continue
        voice_path = os.path.join(ASSETS, slug, "audio", "story", "_index.json")
        meta = json.load(open(voice_path))
        tracks = [t for t in meta.get("tracks", []) if t.get("file")]
        if not tracks:
            continue
        # Fase: 00_Idle, 01_Touch, 02_CutIn, ... (urutan milik skeleton).
        phases = []
        for i, anim in enumerate(anims):
            phases.append({
                "label": anim.replace("_", " "),
                "anim": anim,
                "skins": [],
                "mix": [],
                "lines": [],
                "seconds": DEFAULT_SECONDS,
            })
        # Voice dibagi merata ke fase, diprioritaskan SexStory.
        story = [t for t in tracks if t.get("group") == "SexStory"]
        sex = [t for t in tracks if t.get("group") == "Sex"]
        queue = story + sex
        # Voice yang lebih banyak dari fase -> beberapa baris per fase.
        for i, track in enumerate(queue):
            idx = min(len(phases) - 1, int(i * len(phases) / len(queue)))
            url = f"{VOICE_PREFIX}/{slug}/audio/story/{track['file']}"
            phases[idx]["lines"].append({
                "text": "", "textZh": "", "speaker": "",
                "voice": url, "seconds": DEFAULT_SECONDS,
            })
        for p in phases:
            if not p["lines"]:
                p["lines"].append({"text": "", "textZh": "", "speaker": "",
                                   "voice": None, "seconds": DEFAULT_SECONDS})
            p["seconds"] = round(min(MAX_SECONDS, DEFAULT_SECONDS * len(p["lines"])), 3)
        out[m["id"]] = {
            "phases": phases,
            "audio": {"lang": "KO", "tracks": [f"{VOICE_PREFIX}/{slug}/audio/story/{t['file']}" for t in tracks]},
            "touch": [],
            "bgm": None,
            "source": "voices",
        }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
    # Cache server tidak dipakai untuk arkrecode (tidak melalui attachCherrytaleScenes).
    print(f"{len(out)} scene, {sum(len(v['phases']) for v in out.values())} fase, "
          f"{sum(len(p['lines']) for v in out.values() for p in v['phases'])} voice -> {OUT}")


if __name__ == "__main__":
    main()
