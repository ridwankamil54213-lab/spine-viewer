#!/usr/bin/env python3
"""Unduh voice H-scene CherryTale dan simpan sebagai opus per model.

Sumber nama: index.txt (cache) — aset berakhiran
`_hcg<NN>_sh_vic_hstory_<base>_hcg<N>_<NNN>` (001..0NN, urut).

Keluaran: assets/cherrytale/<model>/audio/<NNN>.opus + _index.json
  Track disimpan 32 kbps mono opus: 28 baris ~0,65 MB per model (WAV
  mentahnya 14 MB), cukup untuk diputar <audio> tanpa ffmpeg di browser.

Pemakaian
    /srv/venv-spine/bin/python tools/extract-cherrytale-voices.py --only a007_04
    /srv/venv-spine/bin/python tools/extract-cherrytale-voices.py --all
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
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ex", os.path.join(HERE, "extract-cherrytale.py"))
_ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ex)
BASE_URL, UA, decrypt = _ex.BASE_URL, _ex.UA, _ex.decrypt

import UnityPy  # noqa: E402

ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets", "cherrytale")
IDX = os.path.join(ROOT, "cache", "cherrytale", "idx")
INDEX_FILE = "index.txt.da878ac4b4769f289fed678c3fe8d3a2"
BUNDLE_CACHE = os.path.join(ROOT, "cache", "cherrytale", "voice")
BITRATE = "32k"


def scene_of(model_id: str) -> tuple[str, str, str] | None:
    """id model -> (base, hcg, varian). img_hcg_dynamic_a007_04_hcg1_1_spine."""
    m = re.match(
        r"^cherrytale/img_hcg_dynamic_(.+?)(?:_hcg(\d+)(?:_(\d+))?)?_spine$", model_id
    )
    if not m:
        return None
    return m.group(1), m.group(2) or "", m.group(3) or ""


def fetch(url: str, dest: str) -> bytes:
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return open(dest, "rb").read()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=120).read()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "wb").write(data)
    return data


def load_bundle(name: str, md5: str) -> "UnityPy.environment.Environment | None":
    path = os.path.join(BUNDLE_CACHE, name)
    raw = fetch(f"{BASE_URL}{name}.{md5}", path)
    for blob in (raw, decrypt(raw)):
        try:
            return UnityPy.load(blob)
        except Exception:
            continue
    return None


def _src_ext(blob: bytes) -> str:
    """Suara datang dalam beberapa wadah: WAV PCM, AAC/MP4, atau FSB5."""
    if blob[:4] == b"RIFF":
        return ".wav"
    if blob[4:8] == b"ftyp":
        return ".m4a"
    if blob[:4] == b"FSB5":
        return ".fsb"
    return ".bin"


def encode(samples: dict, out_dir: str) -> list[dict]:
    """Tulis tiap samples AudioClip -> opus, kembalikan daftar track."""
    tracks = []
    for key in sorted(samples):
        blob = bytes(samples[key])
        n = re.search(r"(\d+)\.", key)
        stem = f"{int(n.group(1)):03d}" if n else re.sub(r"\W", "_", key)
        src = os.path.join(out_dir, f"{stem}{_src_ext(blob)}")
        dest = os.path.join(out_dir, stem + ".opus")
        open(src, "wb").write(blob)
        seconds = 0.0
        if src.endswith(".wav"):
            with wave.open(src) as w:
                seconds = round(w.getnframes() / w.getframerate(), 3)
        if not os.path.exists(dest):
            subprocess.run(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src,
                 "-c:a", "libopus", "-b:a", BITRATE, "-ac", "1", "-ar", "48000", dest],
                check=False,
            )
        if os.path.exists(dest):
            if seconds == 0.0:
                try:
                    out = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", dest],
                        capture_output=True, text=True, check=False,
                    ).stdout.strip()
                    seconds = round(float(out), 3)
                except Exception:
                    seconds = 0.0
            os.remove(src)
            tracks.append({"file": stem + ".opus", "seconds": seconds,
                           "voice": stem})
        else:
            # ffmpeg tak bisa men-decode wadahnya: simpan apa adanya.
            tracks.append({"file": os.path.basename(src), "seconds": seconds,
                           "voice": stem})
    return tracks


def do_model(model_id: str, index: dict) -> tuple[str, int]:
    sc = scene_of(model_id)
    if not sc:
        return model_id, 0
    base, hcg, _var = sc
    if not hcg:
        return model_id, 0
    prefix = f"hstory_{base}_hcg{hcg}_"
    names = sorted((k for k in index if prefix in k), key=lambda k: k)
    if not names:
        return model_id, 0
    out_dir = os.path.join(ASSETS, model_id.split("/", 1)[1], "audio")
    os.makedirs(out_dir, exist_ok=True)
    samples: dict = {}
    for name in names:
        entry = index.get(name)
        if not entry:
            continue
        env = load_bundle(name, entry[1])
        if env is None:
            continue
        for obj in env.objects:
            if str(obj.type) != "83":
                continue
            r = obj.read()
            samples.update(r.samples or {})
    tracks = encode(samples, out_dir)
    if tracks:
        meta_path = os.path.join(out_dir, "_index.json")
        old = {}
        if os.path.exists(meta_path):
            try:
                old = json.load(open(meta_path))
            except Exception:
                old = {}
        old.update({"model": model_id, "lang": "JP", "tracks": tracks})
        old["total_seconds"] = round(sum(t["seconds"] for t in tracks), 2)
        json.dump(old, open(meta_path, "w"), indent=1)
    return model_id, len(tracks)



def invalidate_model_cache() -> None:
    """Hapus cache pindai supaya data baru ikut ter-attach saat server start.

    Signature cache hanya melihat mtime di assets/, sedangkan lampiran scene +
    voice dibaca dari data/ dan folder audio — keduanya tidak mengubah
    signature itu, jadi tanpa ini server menyajikan cache lama.
    """
    for name in ("models-cache.json", "models-cache.json.tmp"):
        try:
            os.remove(os.path.join(ROOT, "data", name))
        except OSError:
            pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring id model")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    index = json.load(open(os.path.join(IDX, INDEX_FILE), encoding="utf-8"))
    models = json.load(open(os.path.join(ROOT, "cache", "models-cherrytale.json")))["models"]
    targets = [m["id"] for m in models if "_hcg" in m["id"]]
    if args.only:
        targets = [t for t in targets if args.only in t]
    elif not args.all:
        raise SystemExit("pakai --only <substr> atau --all")

    total = 0
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(do_model, t, index): t for t in targets}
        for fut in concurrent.futures.as_completed(futs):
            mid, n = fut.result()
            total += n
            done += 1
            if n:
                print(f"[{done}/{len(targets)}] {mid}: {n} track")
            else:
                print(f"[{done}/{len(targets)}] {mid}: -")
    invalidate_model_cache()
    print(f"selesai: {total} track untuk {done} model")


if __name__ == "__main__":
    main()
