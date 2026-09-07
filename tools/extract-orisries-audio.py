#!/usr/bin/env python3
"""Ekstrak audio (AudioClip) dari bundle OrisRies yang sudah di-decrypt.

Ada dua lapis yang bikin ini tidak sekadar "tulis bytes":

1. Audio Unity TIDAK tersimpan di objek AudioClip. `m_AudioData` kosong dan
   datanya menunjuk ke `m_Resource.m_Source`, yaitu berkas
   `CAB-<hash>.resource` yang ADA DI DALAM bundle UnityFS yang sama
   (m_Offset + m_Size menunjuk posisinya). UnityPy tidak meresolve ini
   sendiri, jadi kita baca `BundleFile.files` dan potong sendiri.

2. Potongan itu bukan MP3/OGG, melainkan kontainer FSB5 (FMOD SoundBank)
   yang membungkus Vorbis. ffmpeg menolaknya ("version 5 is not
   implemented"), jadi dibongkar dengan pustaka fsb5 lalu dibangun ulang
   menjadi .ogg utuh yang bisa diputar.

Alur:
    hot_dec/*.bundle -> AudioClip -> CAB-*.resource -> FSB5 -> audio/<n>.ogg

Pemakaian:
    /srv/venv-spine/bin/python tools/extract-orisries-audio.py
    SRC=... OUT=... /srv/venv-spine/bin/python tools/extract-orisries-audio.py
"""
import collections
import os
import sys

import fsb5
import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = os.environ.get("UNITY_VERSION", "2022.3.32f1")

SRC = os.environ.get("SRC", "/srv/spine-assets/orisries/hot_dec")
CDN = os.environ.get("CDN", "/srv/spine-assets/orisries/cdn_dec")
OUT = os.environ.get("OUT", "/srv/spine-assets/orisries/audio")
AUDIO_CLIP = "83"  # Unity class id for AudioClip

MAGIC = [
    (b"ID3", ".mp3"),
    (b"\xff\xfb", ".mp3"),
    (b"\xff\xf3", ".mp3"),
    (b"\xff\xf2", ".mp3"),
    (b"OggS", ".ogg"),
    (b"RIFF", ".wav"),
    (b"fLaC", ".flac"),
]


def ext_for(data: bytes) -> str:
    for sig, ext in MAGIC:
        if data.startswith(sig):
            return ext
    return ".bin"


def safe(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name).strip("_-") or "audio"


def to_bytes(val):
    """Ubah muatan berkas UnityFS apa pun menjadi bytes.

    UnityPy mengembalikan `EndianBinaryReader_Memoryview` untuk berkas
    internal, yang tidak bisa diiris langsung — harus lewat .bytes dulu.
    """
    if isinstance(val, (bytes, bytearray, memoryview)):
        return bytes(val)
    for attr in ("bytes", "getvalue", "read"):
        fn = getattr(val, attr, None)
        if callable(fn):
            try:
                out = fn()
                if isinstance(out, (bytes, bytearray, memoryview)):
                    return bytes(out)
            except Exception:
                pass
    raw = getattr(val, "raw_data", None) or getattr(val, "data", None)
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return bytes(raw)
    return None


def resolve_resource(env, source: str):
    """Ambil bytes berkas .resource yang diminta dari dalam bundle.

    UnityPy mengekspos berkas internal UnityFS lewat `<BundleFile>.files`
    (dict nama -> muatan). Untuk bundle ber-satu berkas, di situ ada
    `CAB-<hash>` (SerializedFile) dan `CAB-<hash>.resource` (muatan audio).
    """
    want = source.rsplit("/", 1)[-1]
    for bundle in env.files.values():
        files = getattr(bundle, "files", None)
        if not isinstance(files, dict):
            continue
        # Cocokkan nama persis dulu, baru suffix.
        for key, val in files.items():
            if key == want or key.rsplit("/", 1)[-1] == want:
                return to_bytes(val)
        for key, val in files.items():
            if key.endswith(want):
                return to_bytes(val)
    return None


def rebuild_fsb5(chunk: bytes, stats: collections.Counter):
    """Bongkar FSB5 dan bangun ulang sampel pertama menjadi .ogg.

    Satu berkas FSB5 bisa berisi beberapa sampel; untuk BGM/SE OrisRies
    umumnya hanya satu.
    """
    try:
        bank = fsb5.FSB5(chunk)
    except Exception:
        stats["fsb5_parse_fail"] += 1
        return None
    if not bank.samples:
        stats["fsb5_empty"] += 1
        return None
    try:
        return bytes(bank.rebuild_sample(bank.samples[0]))
    except Exception:
        stats["fsb5_rebuild_fail"] += 1
        return None


def dump(path: str, used: set, stats: collections.Counter) -> int:
    try:
        env = UnityPy.load(path)
    except Exception:
        stats["load_fail"] += 1
        return 0

    written = 0
    for obj in env.objects:
        if str(obj.type) != AUDIO_CLIP:
            continue
        try:
            clip = obj.read()
        except Exception:
            stats["error"] += 1
            continue

        name = safe(getattr(clip, "m_Name", None) or os.path.basename(path).split("_")[0])
        res = getattr(clip, "m_Resource", None)
        offset = getattr(res, "m_Offset", None)
        size = getattr(res, "m_Size", None)
        source = getattr(res, "m_Source", "") or ""

        data = None
        # 1. Streamed FSB5 (FMOD SoundBank) — yang dipakai OrisRies.
        if source and size:
            blob = resolve_resource(env, source)
            if blob:
                off = offset or 0
                if off + size <= len(blob):
                    chunk = blob[off : off + size]
                    data = rebuild_fsb5(chunk, stats) if chunk.startswith(b"FSB5") else chunk
                else:
                    stats["offset_out_of_range"] += 1
        # 2. Audio tersimpan langsung di objek (jarang, tapi paling mudah).
        if not data:
            direct = getattr(clip, "samples_data", None) or getattr(clip, "m_AudioData", None)
            if direct:
                data = bytes(direct) if not isinstance(direct, (bytes, bytearray)) else direct

        if not data:
            stats["no_data"] += 1
            continue

        ext = ext_for(data)
        if ext == ".bin":
            stats["unknown_format"] += 1
            continue

        fname = name + ext
        i = 2
        while fname in used:
            fname = f"{name}_{i}{ext}"
            i += 1
        used.add(fname)
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, fname), "wb") as f:
            f.write(data)
        stats[ext.lstrip(".")] += 1
        written += 1
    return written


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    stats = collections.Counter()
    used = set()
    total = 0
    for src in (SRC, CDN):
        if not os.path.isdir(src):
            continue
        files = sorted(f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f)))
        cand = [f for f in files if f.startswith(("bgm_", "se"))]
        for f in cand:
            total += dump(os.path.join(src, f), used, stats)
    print(f"file audio ditulis : {total} -> {OUT}")
    for k, v in stats.most_common():
        print(f"  {k:<20}{v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
