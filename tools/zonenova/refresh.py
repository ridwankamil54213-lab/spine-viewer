#!/usr/bin/env python3
"""Refresh deterministik Zone Nova dari cache lokal (tanpa jaringan).

  /srv/venv-spine/bin/python tools/zonenova/refresh.py

Sama dengan `update.py --apply --offline`: config, katalog, master-data, dan
semua .ab diambil dari /srv/spine-assets/zonenova/. Berguna saat CDN sedang
down atau setelah mengubah logika nama/ekstraksi. Untuk sinkron rilis terbaru
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
