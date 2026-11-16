#!/usr/bin/env python3
"""Satu pembaru untuk SELURUH aset CrossCore dari https://crosscore.art/.

Menggantikan pipeline lama berbasis ArtHub / GitHub Talors1225 dan pohon
`crosscore-interaction` (keduanya sudah diarsipkan ke /srv/spine-assets/).

Sumber:
  /                       -> app.<hash>.js -> catalog-all.<hash>.js
  catalog-all.<hash>.js   -> 486 scene / 134 karakter / 421 kostum
  /api/art/<sha256>/...   -> skeleton .json, .atlas, halaman .png, ilustrasi .webp

Kontrak server (lihat runUpdater di src/server.js / UPDATERS.crosscore):
  --check : cepat, TANPA mengunduh aset. Ambil katalog, bandingkan signature
            serta himpunan scene dengan data/crosscore-art-state.json dan isi
            disk. Check pertama melakukan bootstrap supaya tidak melapor
            "semua baru". Cetak JSON ke stdout, progres ke stderr.
  --apply : jalankan tools/crosscore/import-art.py (idempoten; hanya mengunduh
            berkas yang belum ada), lalu tulis _names.json, thumbnail, manifest,
            dan state. cfg.rescan:true membuat /api/models dipindai ulang.

Usage:
    python3 tools/crosscore/update.py --check
    python3 tools/crosscore/update.py --apply
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
HERE = VIEW / "tools" / "crosscore"
STATE = VIEW / "data" / "crosscore-art-state.json"
CROSS = VIEW / "assets" / "crosscore"
CG = VIEW / "assets" / "crosscore-cg"

# import-art.py memakai tanda hubung pada namanya, jadi dimuat lewat importlib.
spec = importlib.util.spec_from_file_location("cc_import", HERE / "import-art.py")
assert spec is not None and spec.loader is not None, "import-art.py tidak bisa dimuat"
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def scene_ready(x: dict) -> bool:
    slug = cc.slug_of(x)
    if x.get("static"):
        f = CG / slug / f"{slug}.webp"
    else:
        f = CROSS / slug / f"{slug}.json"
    return f.exists() and f.stat().st_size > 100


def version(cat: dict) -> str:
    c = cat.get("coverage") or {}
    return (f"v{c.get('gameResourceVersion', '?')} · "
            f"{c.get('characters', 0)} karakter / {c.get('outfits', 0)} kostum / "
            f"{c.get('scenes', 0)} scene")


def check() -> dict:
    cat = cc.catalog()
    scenes = cat["characters"]
    slugs = {cc.slug_of(x) for x in scenes}
    have = sum(1 for x in scenes if scene_ready(x))
    state = load_state()
    known = set(state.get("scenes") or [])
    missing = sorted(slugs - known)
    if not state.get("sig"):
        # Bootstrap: kondisi sekarang jadi baseline.
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "sig": cat["sig"], "catalogUrl": cat["catalogUrl"],
            "coverage": cat["coverage"], "scenes": sorted(slugs),
            "updated_at": int(time.time()),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return {
            "ok": True, "mode": "check", "changed": False, "new": 0,
            "new_ids": [], "previous": None, "version": version(cat),
            "expected": len(scenes), "have": have, "bootstrap": True,
            "detail": {"scenes": len(scenes), "disk": have},
        }
    changed = (cat["sig"] != state.get("sig") or bool(missing)
               or have < len(scenes))
    return {
        "ok": True,
        "mode": "check",
        "version": version(cat),
        "previous": (state.get("catalogUrl") or "")[:24],
        "changed": changed,
        "new": len(missing) + max(0, len(scenes) - have),
        "new_ids": missing[:20],
        "expected": len(scenes),
        "have": have,
        "detail": {"scenes": len(scenes), "disk": have,
                   "new_scenes": len(missing), "coverage": cat["coverage"]},
        "sources": {"crosscore.art": cat["sig"]},
    }


def apply_update() -> dict:
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, str(HERE / "import-art.py"), "--workers", "8"],
        cwd=str(VIEW), stdout=subprocess.PIPE, stderr=sys.stderr,
        text=True, timeout=3600,
    )
    try:
        res = json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "import-art.py tidak mengembalikan JSON",
                "rc": r.returncode, "stdout": (r.stdout or "")[-500:]}
    out = {
        "ok": bool(res.get("ok")) and r.returncode == 0,
        "mode": "apply",
        "version": version({"coverage": res.get("coverage") or {}}),
        "new": res.get("downloaded", 0),
        "new_ids": [],
        "new_models": [],
        "downloaded": res.get("downloaded", 0),
        "failed": res.get("failed", 0),
        "errors": res.get("errors", []),
        "bytes": res.get("bytes", 0),
        "detail": res.get("coverage"),
        # Selalu true: metadata (_names.json / thumbnail) ditulis ulang walau
        # tidak ada berkas model baru, jadi klien harus memanggil refresh().
        "extracted": True,
        "seconds": round(time.time() - t0, 1),
    }
    if not out["ok"]:
        out["error"] = f"{res.get('failed')} scene gagal diunduh (lihat log)"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    try:
        res = apply_update() if a.apply else check()
    except Exception as err:  # noqa: BLE001
        res = {"ok": False, "error": str(err)}
    # SATU-SATUNYA yang boleh ke stdout: blok JSON hasil.
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
