#!/usr/bin/env python3
"""Refresh deterministik Arknights dari cache lokal (tanpa jaringan).

Dipakai setelah mengubah logika nama/thumbnail, atau saat CDN sedang down:
  /srv/venv-spine/bin/python tools/arknights/refresh.py

Sama dengan `update.py --apply --offline` — zip, metadata, dan pohon ilustrasi
diambil dari /srv/spine-assets/arknights/, jadi hasilnya identik dengan apply
terakhir. Untuk sinkron rilis terbaru, jalankan update.py biasa.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import update  # noqa: E402

if __name__ == "__main__":
	sys.argv = [sys.argv[0], "--apply", "--offline"]
	sys.exit(update.main())
