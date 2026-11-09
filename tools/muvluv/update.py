#!/usr/bin/env python3
"""Satu pembaru thumbnail untuk game マブラヴ ガールズガーデンX.

Sumbernya LOKAL: 1243 rig di assets/muvluv/ + 1170 CG di assets/muvluv-cg/.
tools/muvluv/refresh-thumbs.py yang memasangkan keduanya dan menulis
public/thumbs/muvluv/*.webp + _manifest.json. Tidak ada unduhan jaringan.

Kontrak server (UPDATERS["muvluv"] di src/server.js):
  --check : cepat, tanpa konversi. Bandingkan tanda tangan himpunan model/CG +
            jumlah berkas disk terhadap data/muvluv-update-state.json.
  --apply : jalankan refresh-thumbs.py, simpan state. cfg.rescan:true membuat
            klien memuat ulang /api/thumbnails setelah selesai.

Usage:
    python3 tools/muvluv/update.py --check
    python3 tools/muvluv/update.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STATE = VIEW / "data" / "muvluv-update-state.json"
REFRESH = HERE / "refresh-thumbs.py"
MODELS = VIEW / "assets" / "muvluv"
CG = VIEW / "assets" / "muvluv-cg"
OUT = VIEW / "public" / "thumbs" / "muvluv"
MANIFEST = OUT / "_manifest.json"


def signature() -> str:
    h = hashlib.sha256()
    for label, folder, pattern in (("m", MODELS, None), ("c", CG, "*.png")):
        names = sorted(
            p.name for p in folder.iterdir()
            if (p.is_dir() if pattern is None else p.is_file() and p.suffix == ".png")
        ) if folder.is_dir() else []
        h.update(label.encode())
        for n in names:
            h.update(n.encode("utf-8", "replace"))
            h.update(b"\0")
    return h.hexdigest()[:16]


def disk_state() -> dict:
    def manifest_count() -> int:
        try:
            return len(json.loads(MANIFEST.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return 0

    def webp_count() -> int:
        return len(list(OUT.glob("*.webp"))) if OUT.is_dir() else 0

    def model_count() -> int:
        return sum(1 for p in MODELS.iterdir() if p.is_dir()) if MODELS.is_dir() else 0

    return {"models": model_count(), "thumbs": webp_count(), "manifest": manifest_count()}


def load_state() -> dict | None:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def save_state(sig: str) -> None:
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
    sig = signature()
    state = load_state()
    disk = disk_state()

    if not a.apply:
        alasan = []
        if state is None:
            save_state(sig)  # bootstrap: jangan langsung nyala merah
        else:
            if state.get("sig") != sig:
                alasan.append("himpunan model/CG MuvLuv berubah")
            if state.get("disk") != disk:
                alasan.append("isi thumbnail berubah")
        # Berkas .webp yang hilang padahal kunci manifest masih ada.
        missing = max(0, disk["manifest"] - disk["thumbs"])
        if missing:
            alasan.append(f"{missing} berkas thumbnail hilang")
        print(json.dumps({
            "ok": True,
            "mode": "check",
            "changed": bool(alasan),
            "alasan": alasan,
            "new": missing,
            "disk": disk,
            "seconds": round(time.time() - t0, 2),
        }, indent=1, ensure_ascii=False))
        return 0

    # --- apply ---
    p = subprocess.run([sys.executable, str(REFRESH)], capture_output=True,
                       text=True, timeout=1800)
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
    save_state(signature())
    res = {
        "ok": p.returncode == 0,
        "mode": "apply",
        "new": int(detail.get("created", 0) or 0),
        "gagal": len(detail.get("gagal") or []),
        "detail": {
            "thumbnail": int(detail.get("thumbOk", 0) or 0),
            "terpetakan": int(detail.get("matched", 0) or 0),
            "tanpaCG": int(detail.get("unmatched", 0) or 0),
            "model": int(detail.get("models", 0) or 0),
        },
        "disk": disk_state(),
        "seconds": round(time.time() - t0, 1),
        "catatan": "sumber lokal; server memuat ulang /api/thumbnails (cfg.rescan)",
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
