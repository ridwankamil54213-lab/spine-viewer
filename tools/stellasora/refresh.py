#!/usr/bin/env python3
"""Refresh deterministik Stella Sora dari cache lokal (tanpa jaringan).

  /srv/venv-spine/bin/python tools/stellasora/refresh.py

Sama dengan `update.py --apply --offline`. Untuk sinkron rilis terbaru
jalankan `update.py --apply` biasa.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import update  # noqa: E402

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--apply", "--offline"]
    sys.exit(update.main())
