#!/usr/bin/env python3
"""Sinkronkan model Spine, video, nama, family, dan thumbnail Lost Sword.

Menggantikan ekstraktor bundle XAPK lama (UnityPy). Sekarang seluruh aset
diambil langsung dari https://lost-sword-l2d-viewer.pages.dev/ lewat
tools/lostsword/refresh.py.

Usage:
    python3 tools/extract-lostsword.py [--limit N] [--replace]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "lostsword" / "refresh.py"
os.execv(sys.executable, [sys.executable, str(TARGET), *sys.argv[1:]])
