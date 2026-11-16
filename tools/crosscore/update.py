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
EXTRAS_FILE = VIEW / "assets" / "crosscore" / "_extras.json"
EXTRAS_STATE = VIEW / "data" / "crosscore-extras-state.json"
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
    # Efek / touch / suara ditulis import-extras.py; kalau belum pernah
    # dijalankan, apply harus ditawarkan walaupun katalog utama tidak berubah.
    extras_ok = EXTRAS_FILE.is_file() and EXTRAS_STATE.is_file()
    changed = (cat["sig"] != state.get("sig") or bool(missing)
               or have < len(scenes) or not extras_ok)
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


def run_json(script: Path, args: list[str]) -> tuple[dict, int]:
    """Jalankan satu importer; stdout = SATU blok JSON, stderr = progres."""
    print(f"menjalankan {script.name} …", file=sys.stderr, flush=True)
    r = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(VIEW), stdout=subprocess.PIPE, stderr=sys.stderr,
        text=True, timeout=3600,
    )
    try:
        return json.loads(r.stdout), r.returncode
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": f"{script.name} tidak mengembalikan JSON",
                "stdout": (r.stdout or "")[-400:]}, r.returncode


def apply_update() -> dict:
    t0 = time.time()
    art, rc1 = run_json(HERE / "import-art.py", ["--workers", "8"])
    extras, rc2 = run_json(HERE / "import-extras.py", ["--workers", "8"])
    ok = (bool(art.get("ok")) and bool(extras.get("ok"))
          and rc1 == 0 and rc2 == 0)
    eff = extras.get("effects") or {}
    snd = extras.get("sound") or {}
    tch = extras.get("touch") or {}
    out = {
        "ok": ok,
        "mode": "apply",
        "version": version({"coverage": art.get("coverage") or {}}),
        "new": (art.get("downloaded", 0) + eff.get("models", 0)
                + snd.get("clips", 0)),
        "new_ids": [],
        "new_models": [],
        "downloaded": art.get("downloaded", 0),
        "failed": (art.get("failed", 0) + (eff.get("failed") or 0)
                   + (snd.get("failed") or 0)),
        "errors": (art.get("errors") or []) + (extras.get("errors") or []),
        "detail": {
            "coverage": art.get("coverage"),
            "effects": eff.get("models", 0),
            "touchModels": tch.get("models", 0),
            "touchActions": tch.get("actions", 0),
            "audioClips": snd.get("clips", 0),
            "audioScenes": snd.get("scenes", 0),
        },
        # Selalu true: metadata (_names/_extras/touch/thumbnail) ditulis ulang
        # walau tidak ada berkas baru, jadi klien harus memanggil refresh().
        "extracted": True,
        "seconds": round(time.time() - t0, 1),
    }
    if not ok:
        out["error"] = " Sebagian impor gagal (lihat log)".strip()
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
