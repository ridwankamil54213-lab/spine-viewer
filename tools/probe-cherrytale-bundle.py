#!/usr/bin/env python3
"""Probe satu bundle CherryTale: unduh, dekripsi, lalu daftar isinya."""
from __future__ import annotations

import json
import os
import struct
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util

import UnityPy

_spec = importlib.util.spec_from_file_location(
    "extract_cherrytale",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract-cherrytale.py"),
)
_ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ex)
BASE_URL, UA, decrypt = _ex.BASE_URL, _ex.UA, _ex.decrypt

IDX = "cache/cherrytale/idx"
CACHE = "cache/cherrytale/probe"
INDEX_FILE = "index.txt.da878ac4b4769f289fed678c3fe8d3a2"


def fetch(name: str) -> bytes:
    dest = os.path.join(CACHE, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return open(dest, "rb").read()
    with open(os.path.join(IDX, INDEX_FILE), encoding="utf-8") as f:
        entry = json.load(f).get(name)
    if not entry:
        raise SystemExit(f"tidak ada di index: {name}")
    url = f"{BASE_URL}{name}.{entry[1]}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=120).read()
    os.makedirs(CACHE, exist_ok=True)
    open(dest, "wb").write(data)
    return data


def bundle_names(prefix: str) -> list[str]:
    with open(os.path.join(IDX, "index.txt.da878ac4b4769f289fed678c3fe8d3a2"), encoding="utf-8") as f:
        return sorted(k for k in json.load(f) if prefix in k)


def fsb5_info(fsb: bytes) -> dict:
    """Baca header FSB5 secukupnya: codec, kanal, sample rate, durasi."""
    if fsb[:4] != b"FSB5":
        return {"magic": fsb[:4].decode("latin-1")}
    ver = struct.unpack_from("<I", fsb, 4)[0]
    num = struct.unpack_from("<I", fsb, 8)[0]
    size = struct.unpack_from("<I", fsb, 12)[0]
    rate = struct.unpack_from("<I", fsb, 16)[0]
    mode = struct.unpack_from("<I", fsb, 20)[0]
    codec = mode & 0x3
    chans = 1 if mode & 0x4 else 2
    mode_name = {0: "PCM", 1: "PCM_B", 2: "VORBIS", 3: "MPEG"}.get(codec, str(codec))
    return {
        "magic": "FSB5",
        "version": ver,
        "header_bytes": num,
        "sample_count": size,
        "sample_rate": rate,
        "mode": hex(mode),
        "codec": mode_name,
        "channels": chans,
        "seconds": round(size / rate, 2) if rate else None,
    }


def probe(name: str) -> None:
    print("=" * 70)
    print(name)
    raw = fetch(name)
    print("  ukuran unduh:", len(raw))
    env = None
    # Berkas versionshare kadang sudah ber-versi 2020 (tidak teracak); yang
    # baseassets masih 2018 dan wajib didekripsi. Coba apa adanya dulu.
    for label, blob in (("apa adanya", raw), ("didekripsi", decrypt(raw))):
        try:
            env = UnityPy.load(blob)
            print("  parse:", label)
            break
        except Exception as e:
            print("  parse", label, "gagal:", str(e)[:120])
    if env is None:
        return
    for obj in env.objects:
        try:
            t = str(obj.type)
            r = obj.read()
        except Exception as e:
            print("  obj", obj.path_id, "error:", e)
            continue
        nm = getattr(r, "m_Name", "?")
        print(f"  obj {obj.path_id} tipe={t} nama={nm!r}")
        if t == "AudioClip":
            for k, v in (r.samples or {}).items():
                info = fsb5_info(bytes(v))
                print("    audio:", k, info)
            print("    channels:", getattr(r, "m_Channels", None),
                  "freq:", getattr(r, "m_Frequency", None),
                  "samples:", getattr(r, "m_Samples", None))
        elif t == "MonoBehaviour":
            try:
                tree = obj.read_typetree()
                print("    typetree:", json.dumps(tree, default=str)[:1500])
            except Exception as e:
                print("    typetree gagal:", str(e)[:120])
        elif t == "AnimationClip":
            print("    sample_rate:", getattr(r, "m_SampleRate", None),
                  "legacy:", getattr(r, "m_Legacy", None))
            for c in (getattr(r, "m_FloatCurves", None) or [])[:12]:
                print(f"    kurva: {getattr(c, 'path', '?')} .{getattr(c, 'attribute', '?')}"
                      f" keys={len(getattr(c, 'curve', {}).get('m_Curve', []) or [])}")


if __name__ == "__main__":
    prefix = sys.argv[1]
    names = bundle_names(prefix)
    print(f"{len(names)} bundle untuk prefiks {prefix!r}")
    for n in names:
        if n.endswith("index.txt") or n == "AssetRowResources.txt":
            continue
        probe(n)
