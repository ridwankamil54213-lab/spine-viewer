#!/usr/bin/env python3
"""Replace penuh pustaka Epic Seven dari e7codex.com.

Massalah yang dibersihkan: `assets/epic7/` berisi 2.018 folder padahal
katalog live cuma 856 unit — lebih dari 1.000 folder sisa pipeline lama
(nama lowercase `abigail`, `achates_m`, ...) bercampur dengan id kanonik.

Script ini tidak pernah menghapus dulu:
  1. unduh katalog ke staging (E7_* env) lewat update-epic7.py --apply;
  2. validasi semua unit/combat/skill/wallpaper + nama + thumbnail;
  3. stop service, pindahkan 4 root lama ke arsip bertimestamp;
  4. swap staging ke lokasi final;
  5. restart + rescan + updater --apply (state bersih).

Usage:
  python3 tools/replace-epic7.py --dry-run
  python3 tools/replace-epic7.py --apply --workers 8
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

VIEW = Path(__file__).resolve().parents[1]
UPDATER = VIEW / "tools" / "update-epic7.py"
STAGE_ROOT = Path(os.environ.get("E7_STAGE_ROOT", "/srv/spine-assets"))
ARCHIVE_ROOT = Path(os.environ.get("E7_ARCHIVE_ROOT", "/srv/spine-assets"))
BASE = os.environ.get("SPINE_URL", "http://127.0.0.1:3000")
LEGACY = ["epic7-v3"]
PAIRS = [
    ("epic7", "LOBBY"),
    ("epic7-combat", "COMBAT"),
    ("epic7-skill", "SKILL"),
    ("epic7-wallpaper", "WALL"),
]
IMG_EXT = (".png", ".webp", ".jpg")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def service(action: str) -> None:
    subprocess.run(["systemctl", action, "spine-viewer"], check=False,
                   capture_output=True, timeout=180)


def rescan() -> dict:
    last = None
    for attempt in range(20):
        try:
            with urllib.request.urlopen(
                    f"{BASE}/api/models?lean=1&refresh=1", timeout=900) as r:
                d = json.load(r)
            models = d.get("models", d if isinstance(d, list) else [])
            counts = {}
            for m in models:
                g = m.get("game") or ""
                if g.startswith("epic7"):
                    counts[g] = counts.get(g, 0) + 1
            return counts
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3)
    raise RuntimeError(f"rescan gagal: {last}")


def validate(stage: Path, catalog: dict) -> dict:
    errors = []
    counts = {}
    for name, _ in PAIRS:
        root = stage / name
        folders = [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
        counts[name] = len(folders)
    expected = catalog["lobby"] | catalog["combat"]
    lobby = stage / "epic7"
    for uid in sorted(catalog["lobby"]):
        d = lobby / uid
        if not (d.is_dir() and (d / f"{uid}.json").is_file() and
                (d / f"{uid}.atlas").is_file() and
                any(f.name.lower().endswith(IMG_EXT) for f in d.iterdir() if f.is_file())):
            errors.append(f"lobby/{uid}")
    combat = stage / "epic7-combat"
    for uid in sorted(catalog["combat"]):
        d = combat / uid
        if not (d.is_dir() and (d / f"{uid}.json").is_file() and
                (d / f"{uid}.atlas").is_file() and
                any(f.name.lower().endswith(IMG_EXT) for f in d.iterdir() if f.is_file())):
            errors.append(f"combat/{uid}")
    for folder, fname in catalog["skill"]:
        if not (stage / "epic7-skill" / folder / fname).is_file():
            errors.append(f"skill/{folder}/{fname}")
    for uid in catalog["wall"]:
        if not (stage / "epic7-wallpaper" / uid / f"{uid}.webm").is_file():
            errors.append("wall/" + uid)
    names = stage / "epic7" / "_names.json"
    n_names = len(json.loads(names.read_text(encoding="utf-8"))) if names.is_file() else 0
    thumbs = stage / "thumbs" / "_manifest.json"
    n_thumbs = len(json.loads(thumbs.read_text(encoding="utf-8"))) if thumbs.is_file() else 0
    res = {"folder": counts, "names": n_names, "thumbs": n_thumbs,
           "errors": errors[:15], "errorCount": len(errors)}
    if errors or n_names < len(catalog["lobby"]) or n_thumbs < 100:
        raise RuntimeError("validasi staging gagal: " + json.dumps(res, ensure_ascii=False))
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--stage", default="", help="lanjutkan staging yang sudah ada")
    a = ap.parse_args()
    if not a.apply and not a.dry_run:
        print("wajib --apply atau --dry-run", file=sys.stderr)
        return 2

    t0 = time.time()
    spec = importlib.util.spec_from_file_location("update_epic7", UPDATER)
    if not spec or not spec.loader:
        raise RuntimeError("tidak bisa memuat " + str(UPDATER))
    up = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(up)
    units_raw = up.fetch(up.UNITS_URL, timeout=60)
    anims_raw = up.fetch(up.LOBBY_ANIMS_URL, timeout=60)
    units, anims = json.loads(units_raw), json.loads(anims_raw)
    catalog = {
        "lobby": {u["id"] for u in units if u.get("spine") and u.get("id")},
        "combat": {u["id"] for u in units if u.get("has_combat") and u.get("id")},
        "skill": {(f"{u['id']}_skill{os.path.splitext(os.path.basename(p))[0].rsplit('_', 1)[-1]}",
                   os.path.basename(p))
                  for u in units if u.get("id") for p in (u.get("skills") or [])},
        "wall": {a.get("id") for a in anims if a.get("id")},
    }
    log("katalog: " + json.dumps({k: len(v) for k, v in catalog.items()}, ensure_ascii=False))

    tag = time.strftime("%Y%m%d-%H%M%S")
    stage = Path(a.stage).resolve() if a.stage else STAGE_ROOT / f"epic7-stage-{tag}"
    archive = ARCHIVE_ROOT / f"epic7-before-replace-{tag}"
    if (not a.stage and stage.exists()) or archive.exists():
        print("staging/arsip sudah ada", file=sys.stderr)
        return 2
    (stage / "thumbs").mkdir(parents=True, exist_ok=True)
    log(f"staging: {stage}")

    env = dict(os.environ,
               E7_LOBBY=str(stage / "epic7"),
               E7_COMBAT=str(stage / "epic7-combat"),
               E7_SKILL=str(stage / "epic7-skill"),
               E7_WALL=str(stage / "epic7-wallpaper"),
               E7_THUMBS=str(stage / "thumbs"),
               E7_STATE=str(stage / "state.json"))
    p = subprocess.run([sys.executable, str(UPDATER), "--apply",
                        "--workers", str(a.workers)], env=env,
                       capture_output=True, text=True, timeout=14400)
    for line in p.stderr.splitlines()[-10:]:
        log(line)
    if p.returncode != 0:
        print(p.stdout[-3000:], file=sys.stderr)
        return 1
    checked = validate(stage, catalog)
    log("validasi: " + json.dumps(checked, ensure_ascii=False))
    if a.dry_run:
        print(json.dumps({"ok": True, "mode": "dry-run", "stage": str(stage),
                          "validasi": checked}, indent=1, ensure_ascii=False))
        return 0

    swapped = False
    try:
        service("stop")
        for name in LEGACY:
            src = VIEW / "assets" / name
            if src.exists():
                dst = archive / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        for name, _ in PAIRS:
            src = VIEW / "assets" / name
            dst = archive / name
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        src_thumbs = VIEW / "public" / "thumbs" / "epic7"
        if src_thumbs.exists():
            shutil.move(str(src_thumbs), str(archive / "thumbs"))
        for name, _ in PAIRS:
            shutil.move(str(stage / name), str(VIEW / "assets" / name))
        shutil.move(str(stage / "thumbs"), str(src_thumbs))
        swapped = True
        log(f"swap selesai — arsip: {archive}")
    except Exception as e:  # noqa: BLE001
        if not swapped:
            for name, _ in PAIRS:
                src = VIEW / "assets" / name
                old = archive / name
                if old.exists() and not src.exists():
                    shutil.move(str(old), str(src))
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    finally:
        service("start")

    counts = rescan()
    log("rescan: " + json.dumps(counts, ensure_ascii=False))
    # State final sesuai pohon baru.
    p2 = subprocess.run([sys.executable, str(UPDATER), "--apply",
                         "--workers", str(a.workers)],
                        capture_output=True, text=True, timeout=3600)
    log("updater: " + (p2.stdout.strip().splitlines()[-1] if p2.stdout.strip()
                       else p2.stderr[-300:]))
    expected = {
        "epic7": len(catalog["lobby"]),
        "epic7-combat": len(catalog["combat"]),
        "epic7-skill": len(catalog["skill"]),
        "epic7-wallpaper": len(catalog["wall"]),
    }
    stale = {k: v for k, v in counts.items() if k not in expected}
    result = {
        "ok": (p2.returncode == 0 and not stale and
               all(counts.get(k) == v for k, v in expected.items())),
        "mode": "replace", "counts": counts,        "katalog": {k: len(v) for k, v in catalog.items()},
        "stale": stale,
        "validasi": checked, "arsip": str(archive), "updateRc": p2.returncode,
        "seconds": round(time.time() - t0, 1),
    }
    logfile = Path("/var/log") / f"epic7-replace-{tag}.json"
    logfile.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
