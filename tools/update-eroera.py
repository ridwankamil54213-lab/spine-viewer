#!/usr/bin/env python3
"""Wrapper untuk tools/eroera/update.py (欲洛降临 — youdianse.com/game/detail/456)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "eroera" / "update.py"
os.execv(sys.executable, [sys.executable, str(TARGET), *sys.argv[1:]])
