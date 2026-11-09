#!/usr/bin/env python3
"""Satu pembaru Make Drama dari https://mad.altterisk.cc/viewer/.

Menggantikan tools/update-mad.py lama (git fetch + merge clone
/opt/re-targets/mad-viewer). Sekarang katalog dibaca LIVE dari situs, dan
tools/mad-drama/refresh.py yang mengunduh model, metadata, dan thumbnail.

Kontrak server (lihat runUpdater / UPDATERS["mad-drama"] di src/server.js):
  --check : cepat, TANPA mengunduh aset. Bandingkan hash 4 katalog live +
            jumlah berkas disk terhadap data/mad-drama-update-state.json,
            plus jumlah unit yang belum ada di disk. Cetak JSON ke stdout.
  --apply : jalankan refresh.py, simpan state. cfg.rescan:true membuat
            /api/models dipindai ulang otomatis.

Usage:
    python3 tools/mad-drama/update.py --check
    python3 tools/mad-drama/update.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
HERE = VIEW / "tools" / "mad-drama"
STATE = VIEW / "data" / "mad-drama-update-state.json"
REFRESH = HERE / "refresh.py"
ASSETS = VIEW / "assets" / "mad-drama"
THUMBS = VIEW / "public" / "thumbs" / "mad-drama"
CATALOGS = ("skin_list", "cdn", "characters", "icons")

sys.path.insert(0, str(HERE))
import refresh  # noqa: E402


def signature() -> dict:
    return {name: hashlib.sha256(
        refresh.fetch(f"{refresh.DATA}/{name}.json", timeout=120)).hexdigest()[:16]
        for name in CATALOGS}


def disk_state() -> dict:
    def dirs_with_skel() -> int:
        if not ASSETS.is_dir():
            return 0
        n = 0
        for d in ASSETS.iterdir():
            if d.is_dir() and any(f.name.startswith(d.name + ".")
                                  and f.suffix.lower() in (".skel", ".json")
                                  for f in d.iterdir() if f.is_file()):
                n += 1
        return n

    def thumbs() -> int:
        return sum(1 for f in THUMBS.iterdir()
                   if f.is_file() and f.name.endswith(".webp")) if THUMBS.is_dir() else 0

    def names() -> int:
        try:
            return len(json.loads((ASSETS / "_names.json").read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return 0

    return {"models": dirs_with_skel(), "thumbs": thumbs(), "names": names()}


def missing_models() -> tuple[int, int]:
    """Unit yang seharusnya jadi model tapi belum ada di disk.

    Skin ber-kind "drama" (dm_ma0001 / dm_ma0002) cuma berisi PNG tanpa
    skeleton — refresh.py memang melewatkannya, dan tidak akan pernah
    menghasilkan folder model. Kalau ikut dihitung, --check akan selalu
    melapor "2 model belum ada" selamanya (titik merah palsu).
    """
    try:
        skins = refresh.load_data("skin_list")["skins"]
        cdn = refresh.load_data("cdn")
        units = cdn["families"]["skins"]["units"]
        missing = drama = 0
        for s in skins:
            if s.get("kind") == "drama":
                drama += 1
                continue
            u = refresh.unit_for(s, units)
            if u and not (ASSETS / u).is_dir():
                missing += 1
        return missing, drama
    except Exception:  # noqa: BLE001
        return 0, 0


def load_state() -> dict | None:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def save_state(sig: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "sig": sig,
        "disk": disk_state(),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    try:
        sig = signature()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"gagal membaca katalog MAD: {e}"}, indent=1))
        return 1

    state = load_state()
    disk = disk_state()

    if not a.apply:
        alasan = []
        if state is None:
            save_state(sig)
        else:
            if state.get("sig") != sig:
                alasan.append("katalog MAD Viewer berubah")
            if state.get("disk") != disk:
                alasan.append("isi disk berubah")
        new, drama = missing_models()
        if new:
            alasan.append(f"{new} model belum ada")
        res = {
            "ok": True,
            "mode": "check",
            "changed": bool(alasan),
            "alasan": alasan,
            "new": new,
            "drama": drama,
            "disk": disk,
            "seconds": round(time.time() - t0, 1),
        }
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0

    # --- apply ---
    p = subprocess.run([sys.executable, str(REFRESH)], capture_output=True,
                       text=True, timeout=3600)
    for line in p.stderr.splitlines():
        print(f"  {line}", file=sys.stderr, flush=True)
    out = p.stdout
    start = out.find("{")
    detail = {}
    if start >= 0:
        try:
            detail, _ = json.JSONDecoder().raw_decode(out[start:])
        except Exception:  # noqa: BLE001
            detail = {}
    save_state(sig)
    models = detail.get("models") or {}
    res = {
        "ok": p.returncode == 0,
        "mode": "apply",
        "new": int(models.get("ok", 0) or 0),
        "gagal": len(detail.get("errors") or []),
        "detail": {
            "model": int(models.get("ok", 0) or 0),
            "drama": int(models.get("drama", 0) or 0),
            "thumbnail": int(detail.get("thumbOk", 0) or 0),
            "nama": int(detail.get("names", 0) or 0),
            "karakter": int(detail.get("characters", 0) or 0),
        },
        "disk": disk_state(),
        "errors": (detail.get("errors") or [])[:10],
        "seconds": round(time.time() - t0, 1),
        "catatan": "server memindai ulang /api/models otomatis (cfg.rescan)",
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
