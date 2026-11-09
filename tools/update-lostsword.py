#!/usr/bin/env python3
"""Updater Lost Sword (berbasis https://lost-sword-l2d-viewer.pages.dev/).

Menggantikan pipeline ekstraksi XAPK APKPure lama. Seluruh implementasi
berada di tools/lostsword/update.py & tools/lostsword/refresh.py.

Usage:
    python3 tools/update-lostsword.py --check
    python3 tools/update-lostsword.py --apply [--force]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "lostsword" / "update.py"
os.execv(sys.executable, [sys.executable, str(TARGET), *sys.argv[1:]])
