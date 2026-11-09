#!/usr/bin/env python3
"""Satu pembaru untuk seluruh aset CrossCore dari ArtHub.

Sumber: github.com/Talors1225/arthub-viewer-web (dan bucket R2 yang dipakai
repo itu untuk aset besar). Menggantikan tools/update-crosscore.py lama yang
masih bergantung pada mirror komunitas `kmou424/...` / `R2iCecho/...`.

Tiga langkah, dijalankan berurutan:

  1. tools/update-crosscore-arthub.py        -> assets/crosscore/ (502 entri
     indeks, 495 folder unik) dari crosscore/crosscore_chars.json
  2. tools/update-crosscore-interaction.py  -> assets/crosscore-interaction/
     (325 model/layer) dari katalog interaksi R2
  3. tools/crosscore/refresh-meta.py        -> _names.json + 761 thumbnail
     WebP + dua _manifest.json dari thumbs/index.json

Kontrak server (lihat runUpdater / UPDATERS.crosscore di src/server.js):
  --check : cepat, TANPA mengunduh aset. Bandingkan tanda tangan tiga katalog
            + isi disk terhadap data/crosscore-update-state.json, lalu tanya
            kedua skrip unduh berapa model yang belum ada. Cetak JSON ke
            stdout, progres ke stderr.
  --apply : jalankan tiga langkah di atas, simpan state. cfg.rescan:true
            membuat /api/models dipindai ulang otomatis.

Kegagalan thumbnail bersifat kosmetik: model yang sudah terunduh tetap sah.
Yang menggagalkan apply (dan rescan) cuma kegagalan pada langkah 1/2.

Usage:
    python3 tools/crosscore/update.py --check
    python3 tools/crosscore/update.py --apply [--workers 8]
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
HERE = VIEW / "tools" / "crosscore"
STATE = VIEW / "data" / "crosscore-update-state.json"
A_CROSS = VIEW / "assets" / "crosscore"
A_INTER = VIEW / "assets" / "crosscore-interaction"
T_CROSS = VIEW / "public" / "thumbs" / "crosscore"
T_INTER = VIEW / "public" / "thumbs" / "crosscore-interaction"

GH_RAW = "https://raw.githubusercontent.com/Talors1225/arthub-viewer-web/main"
CHARS_URL = f"{GH_RAW}/crosscore/crosscore_chars.json"
THUMB_INDEX_URL = f"{GH_RAW}/thumbs/index.json"
CATALOG_URL = ("https://pub-3be583976a374ca9aacd740e9d14ad96.r2.dev"
               "/crosscore-interaction/catalog/catalog.json")

STEPS = [
    ("model Spine", VIEW / "tools" / "update-crosscore-arthub.py"),
    ("model interaksi", VIEW / "tools" / "update-crosscore-interaction.py"),
    ("nama + thumbnail", HERE / "refresh-meta.py"),
]


def fetch(url: str, timeout: int = 60) -> bytes:
    import shutil
    import tempfile

    curl = shutil.which("curl") or "/usr/bin/curl"
    fd, tmp = tempfile.mkstemp(prefix="ccsig-", suffix=".bin")
    os.close(fd)
    try:
        p = subprocess.run(
            [curl, "-sSL", "--max-time", str(timeout), "-o", tmp,
             "-w", "%{http_code}", url],
            capture_output=True, timeout=timeout + 20,
        )
        code = (p.stdout or b"").strip().decode("ascii", "replace")
        if p.returncode == 0 and code.startswith("2"):
            return Path(tmp).read_bytes()
        raise RuntimeError(f"HTTP {code} untuk {url}")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def signature() -> dict:
    return {k: hashlib.sha256(fetch(u)).hexdigest()[:16] for k, u in {
        "chars": CHARS_URL,
        "thumbIndex": THUMB_INDEX_URL,
        "catalog": CATALOG_URL,
    }.items()}


def disk_state() -> dict:
    def dirs(p: Path) -> int:
        return sum(1 for f in p.iterdir() if f.is_dir()) if p.is_dir() else 0

    def files(p: Path, suffix: str) -> int:
        return sum(1 for f in p.iterdir() if f.is_file() and f.name.endswith(suffix)) if p.is_dir() else 0

    return {
        "cross": dirs(A_CROSS),
        "inter": dirs(A_INTER),
        "thumbCross": files(T_CROSS, ".webp"),
        "thumbInter": files(T_INTER, ".webp"),
        "names": len(json.loads((A_CROSS / "_names.json").read_text(encoding="utf-8")))
        if (A_CROSS / "_names.json").is_file() else 0,
    }


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


def run_step(script: Path, args: list[str], label: str) -> dict:
    """Jalankan satu sub-skrip, ambil objek JSON pertama dari stdout."""
    print(f"menjalankan {label}…", file=sys.stderr, flush=True)
    p = subprocess.run([sys.executable, str(script), *args],
                       capture_output=True, text=True, timeout=1800)
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


def check_counts() -> dict:
    """Tanya kedua skrip unduh berapa model yang belum ada (tanpa mengunduh)."""
    out = {}
    for label, script in STEPS[:2]:
        r = run_step(script, ["--check"], f"cek {label}")
        d = r["result"]
        out[label] = int(d.get("new", 0) or 0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    t0 = time.time()
    try:
        sig = signature()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"gagal membaca katalog: {e}"}, indent=1))
        return 1

    state = load_state()
    disk = disk_state()

    if not a.apply:
        alasan = []
        if state is None:
            save_state(sig)
        else:
            if state.get("sig") != sig:
                alasan.append("katalog ArtHub berubah")
            if state.get("disk") != disk:
                alasan.append("isi disk berubah")
        counts = check_counts()
        total_new = sum(counts.values())
        if total_new:
            alasan.append(f"{total_new} model belum ada")
        res = {
            "ok": True,
            "mode": "check",
            "changed": bool(alasan),
            "alasan": alasan,
            "new": total_new,
            "detail": counts,
            "katalog": sig,
            "disk": disk,
            "seconds": round(time.time() - t0, 1),
        }
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0

    # --- apply ---
    results = {}
    critical = []
    for i, (label, script) in enumerate(STEPS):
        args = ["--apply"]
        if i < 2:
            args += ["--workers", str(a.workers if i == 0 else max(4, a.workers - 2))]
        r = run_step(script, args, label)
        results[label] = r["result"]
        if not r["ok"] and i < 2:
            critical.append(f"{label}: rc={r['err']}")
        elif not r["ok"]:
            results.setdefault("warnings", []).append(f"{label}: thumbnail gagal sebagian")

    save_state(sig)
    meta = results.get("nama + thumbnail", {}) or {}
    spine = results.get("model Spine", {}) or {}
    inter = results.get("model interaksi", {}) or {}
    res = {
        "ok": not critical,
        "mode": "apply",
        "new": int(spine.get("ok", 0) or 0) + int(inter.get("ok", 0) or 0),
        "gagal": int(spine.get("gagal", 0) or 0) + int(inter.get("gagal", 0) or 0),
        "detail": {
            "spine": int(spine.get("ok", 0) or 0),
            "interaksi": int(inter.get("ok", 0) or 0),
            "thumbnail": int(meta.get("thumbOk", 0) or 0),
            "nama": int(meta.get("names", 0) or 0),
        },
        "disk": disk_state(),
        "errors": critical,
        "warnings": results.get("warnings", []),
        "seconds": round(time.time() - t0, 1),
        "catatan": "server memindai ulang /api/models otomatis (cfg.rescan)",
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if not critical else 1


if __name__ == "__main__":
    sys.exit(main())
