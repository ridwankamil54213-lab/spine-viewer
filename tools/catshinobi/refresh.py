#!/usr/bin/env python3
"""Regenerasi SEMUA metadata Cat Shinobi tanpa jaringan.

    /srv/venv-spine/bin/python tools/catshinobi/refresh.py

Urutan:
  1. tools/catshinobi-names.py  -> data/catshinobi-names.json
     (tabel Unity Localization dari bundle APK yang sudah ada di disk)
  2. tools/catshinobi/enrich.py --offline -> thumbnail + family
     (pakai cache sprite, tidak menyentuh bundle 648 MB)

Kalau APK baru sudah diekstrak dan sprite-nya belum di-cache, jalankan
``enrich.py`` sekali TANPA --offline dulu.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable

STEPS = [
    [PY, os.path.join(ROOT, "tools", "catshinobi-names.py")],
    [PY, os.path.join(ROOT, "tools", "catshinobi", "enrich.py"), "--offline"],
]

for step in STEPS:
    print("+", " ".join(os.path.basename(x) if x.startswith(ROOT) else x
                        for x in step), flush=True)
    subprocess.run(step, cwd=ROOT, check=True)
print("refresh Cat Shinobi selesai", flush=True)
