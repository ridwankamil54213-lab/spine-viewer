#!/usr/bin/env python3
"""Sinkronkan video cutscene Lost Sword dari https://lost-sword-l2d-viewer.pages.dev/.

Menggantikan ekstraktor VideoClip XAPK lama. Sekarang 87 video
(skill-videos/*.mp4 dan memorial-videos/*.mp4) disinkronkan bersama model
Spine, family karakter, dan thumbnail lewat tools/lostsword/update.py.

Usage:
    python3 tools/extract-lostsword-video.py [--check | --apply]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "lostsword" / "update.py"
args = sys.argv[1:] or ["--apply"]
os.execv(sys.executable, [sys.executable, str(TARGET), *args])
