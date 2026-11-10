#!/usr/bin/env python3
"""Regenerasi metadata model 3D dari aset yang sudah ada, TANPA jaringan.

    /srv/venv-spine/bin/python tools/model3d/refresh.py

Menjalankan ``update.py --apply --offline``: _meta.json yang sudah ada dipakai
ulang, names/family/thumbnail/icon dihitung ulang secara deterministik.
Berguna setelah menambah folder .glb manual atau mengganti pemetaan ilustrasi.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
cmd = [sys.executable, os.path.join(ROOT, "tools", "model3d", "update.py"),
       "--apply", "--offline"]
print("+", " ".join(cmd), file=sys.stderr, flush=True)
subprocess.run(cmd, cwd=ROOT, check=True)
print("refresh model 3D selesai", file=sys.stderr, flush=True)
