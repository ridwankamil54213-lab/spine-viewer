#!/usr/bin/env python3
"""Satu pembaru Brown Dust 2 dari github.com/Zormolo/Brown-Dust-2-Assets.

Menyatukan dua langkah yang sebelumnya harus dijalankan terpisah:

  1. tools/update-browndust.py          -> model Spine ke assets/bd2-char/
                                            dan assets/bd2/ (tata letak family)
  2. tools/browndust/refresh-thumbs.py -> thumbnail dari assets/ui/ repo
                                            (costume_face / costume_icon)

`update-browndust.py` sudah punya state sendiri di
`/srv/spine-assets/bd2-update/state.json` (cache pohon GitHub per commit SHA).
Wrapper ini menambah state ringan di data/bd2-update-state.json untuk
mendeteksi perubahan metadata/thumbnail, plus kontrak --check/--apply yang
sama dengan updater CZN / E7 / CrossCore.

Kontrak server (lihat runUpdater / UPDATERS.bd2 di src/server.js):
  --check : cepat, TANPA mengunduh aset. Bandingkan commit SHA + jumlah
            berkas disk terhadap state, lalu tanya updater model berapa yang
            belum ada. Cetak JSON ke stdout, progres ke stderr.
  --apply : unduh model baru, bangun ulang thumbnail, simpan state.
            cfg.rescan:true membuat /api/models dipindai ulang otomatis.

Kegagalan thumbnail bersifat kosmetik; yang menggagalkan apply (dan rescan)
cuma kegagalan berkas model.

Usage:
    python3 tools/browndust/update.py --check
    python3 tools/browndust/update.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
HERE = VIEW / "tools" / "browndust"
MODEL_SCRIPT = VIEW / "tools" / "update-browndust.py"
THUMB_SCRIPT = HERE / "refresh-thumbs.py"
STATE = VIEW / "data" / "bd2-update-state.json"
A_CHAR = VIEW / "assets" / "bd2-char"
A_FLAT = VIEW / "assets" / "bd2"
T_DIR = VIEW / "public" / "thumbs" / "bd2"


def disk_state() -> dict:
    def skels(p: Path) -> int:
        if not p.is_dir():
            return 0
        return sum(1 for _, _, fs in os.walk(p)
                   for f in fs if f.lower().endswith(".skel"))

    thumbs = sum(1 for f in T_DIR.iterdir()
                 if f.is_file() and f.name.endswith(".png")) if T_DIR.is_dir() else 0
    man = 0
    if (T_DIR / "_manifest.json").is_file():
        try:
            man = len(json.loads((T_DIR / "_manifest.json").read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            man = 0
    return {"char": skels(A_CHAR), "flat": skels(A_FLAT),
            "thumbs": thumbs, "manifest": man}


def load_state() -> dict | None:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def save_state(version: str) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "version": version,
        "disk": disk_state(),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=1), encoding="utf-8")


def run(script: Path, args: list[str], label: str) -> dict:
    print(f"menjalankan {label}…", file=sys.stderr, flush=True)
    p = subprocess.run([sys.executable, str(script), *args],
                       capture_output=True, text=True, timeout=3600)
    if p.stdout.strip():
        for line in p.stdout.splitlines():
            print(f"  {line}", file=sys.stderr, flush=True)
    out = p.stdout
    start = out.find("{")
    result = {}
    if start >= 0:
        try:
            result, _ = json.JSONDecoder().raw_decode(out[start:])
        except Exception:  # noqa: BLE001
            result = {}
    return {"ok": p.returncode == 0, "result": result,
            "err": (p.stderr or "").strip()[-300:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    state = load_state()
    disk = disk_state()

    if not a.apply:
        r = run(MODEL_SCRIPT, ["--check"], "cek model BD2")
        d = r["result"]
        version = str(d.get("version") or "")
        new = int(d.get("new", 0) or 0)
        alasan = []
        if state is None:
            save_state(version)
        else:
            # SHA kosong berarti GitHub sedang rate-limit / tidak terjangkau.
            # Itu BUKAN perubahan repo, jangan nyalakan titik merah palsu.
            if version and state.get("version") != version:
                alasan.append("commit repo aset berubah")
            if state.get("disk") != disk:
                alasan.append("isi disk berubah")
        if new:
            alasan.append(f"{new} model belum ada")
        res = {
            "ok": True,
            "mode": "check",
            "changed": bool(alasan),
            "alasan": alasan,
            "new": new,
            "installed": int(d.get("installed", 0) or 0),
            "total": int(d.get("total", 0) or 0),
            "version": version or None,
            "offline": not version,
            "disk": disk,
            "seconds": round(time.time() - t0, 1),
        }
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0

    # --- apply ---
    m = run(MODEL_SCRIPT, ["--apply"], "unduh model BD2")
    md = m["result"]
    version = str(md.get("version") or "")
    failed_files = int(md.get("failedFiles", 0) or 0)
    t = run(THUMB_SCRIPT, ["--version", version], "bangun thumbnail BD2")
    td = t["result"]

    save_state(version)
    res = {
        "ok": m["ok"] and failed_files == 0,
        "mode": "apply",
        "new": int(md.get("added", 0) or 0),
        "gagal": failed_files,
        "detail": {
            "model": int(md.get("added", 0) or 0),
            "thumbnail": int(td.get("thumbOk", 0) or 0),
            "manifest": int(td.get("manifestEntries", 0) or 0),
        },
        "version": version or None,
        "disk": disk_state(),
        "warnings": [] if t["ok"] else ["sebagian thumbnail gagal diunduh"],
        "seconds": round(time.time() - t0, 1),
        "catatan": "server memindai ulang /api/models otomatis (cfg.rescan)",
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
