#!/usr/bin/env python3
"""Updater UI untuk Otherworld Mercenary Corps.

Kontrak runUpdater(): --check cepat (1 HEAD), --apply boleh lama. Hanya blok
JSON hasil ke stdout; progres dari refresh.py sudah ke stderr.
"""
import argparse
import importlib.util
import json
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("merc_refresh", HERE / "refresh.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)

ap = argparse.ArgumentParser()
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--check", action="store_true")
g.add_argument("--apply", action="store_true")
# flag kompatibilitas: wrapper lama / operator manual
ap.add_argument("--force", action="store_true")
ap.add_argument("--verbose", action="store_true")
args = ap.parse_args()

try:
    result = refresh.check() if args.check else refresh.apply()
except Exception as e:  # noqa: BLE001
    traceback.print_exc(file=sys.stderr)
    result = {"ok": False, "error": str(e),
              "version": "", "changed": False, "new": 0}

# Wajib multi-baris: runUpdater() berhenti menyalin stdout ke log hanya saat
# menemui baris persis "{" / "[".
print(json.dumps(result, ensure_ascii=False, indent=1))
sys.exit(0 if result.get("ok") else 1)
