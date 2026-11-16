#!/usr/bin/env python3
"""Ganti seluruh pohon model NIKKE dengan unduhan bersih dari ArtHub.

Akar masalah: `assets/nikke/` tercampur sisa pipeline lama — 553 folder yang
tidak ada di katalog kanonik (nama polos `777`, `absolute`, dan folder
`__catalog-...` dobel), 6 folder katalog belum terunduh, dan 430 model `#`
dari beberapa skel dalam satu folder. `refresh.py` sengaja idempoten dan
melewati folder yang sudah ada, jadi tidak bisa membersihkan sisa itu.

Script ini TIDAK pernah menghapus pohon lama lebih dulu:

  1. unduh katalog kanonik ke staging (`NIKKE_OUT` di `/srv/spine-assets`);
  2. validasi staging: jumlah folder = katalog, tiap folder tepat satu
     `<id>.skel` + `<id>.atlas`, semua halaman atlas ada, tidak ada folder
     asing, dan `_names.json` lengkap;
  3. baru setelah valid, stop service, **pindahkan** (bukan rm -rf) pohon lama
     ke arsip bertimestamp, swap staging ke `assets/nikke`;
  4. restart, rescan `/api/models`, regenerasi potret Prydwen, lalu jalankan
     updater (`--apply`) supaya state tidak memicu "perubahan" palsu.

Flag `--apply` wajib supaya script tidak bisa jalan tidak sengaja.

Usage:
  python3 tools/nikke/replace.py --dry-run
  python3 tools/nikke/replace.py --apply --workers 12
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
OUT = VIEW / "assets" / "nikke"
STAGING_ROOT = Path(os.environ.get("NIKKE_STAGING_ROOT", "/srv/spine-assets"))
REFRESH = Path(__file__).with_name("refresh.py")
PRYDwen = Path(__file__).with_name("import-prydwen.py")
UPDATE = Path(__file__).with_name("update.py")
STATE_ROOT = Path(os.environ.get("NIKKE_STATE", "/srv/spine-assets"))
BASE = os.environ.get("SPINE_URL", "http://127.0.0.1:3000")
PAGE_EXT = (".png", ".webp", ".jpg", ".jpeg")

sys.path.insert(0, str(Path(__file__).parent))
from refresh import CATALOG, load_json, atlas_pages  # noqa: E402


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def http_json(url: str, timeout: int = 120) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def folder_ok(d: Path, cid: str) -> bool:
    """Satu model kanonik = tepat satu skel + atlas + semua halaman atlas."""
    if not d.is_dir():
        return False
    skels = [p for p in d.glob("*.skel") if p.is_file()]
    atlases = [p for p in d.glob("*.atlas") if p.is_file()]
    if len(skels) != 1 or skels[0].name != f"{cid}.skel":
        return False
    if len(atlases) != 1 or atlases[0].name != f"{cid}.atlas":
        return False
    for page in atlas_pages(atlases[0].read_bytes()):
        if not (d / page).is_file():
            return False
    return True


def seed_missing(stage: Path, ids: set[str], source: Path) -> list[str]:
    """Ambil HANYA model kanonik yang 403 di R2 dari pohon lama yang valid.

    Dipakai untuk 12 `*_skillcut` yang tidak lagi tersedia di bucket R2.
    Tidak pernah menyalin folder asing/`#`, dan tidak menimpa folder yang
    sudah lengkap dari hasil unduhan.
    """
    seeded = []
    for cid in sorted(ids):
        if folder_ok(stage / cid, cid) or not folder_ok(source / cid, cid):
            continue
        dest = stage / cid
        dest.mkdir(parents=True, exist_ok=True)
        for f in (source / cid).iterdir():
            if f.is_file():
                shutil.copy2(f, dest / f.name)
        if not folder_ok(dest, cid):
            raise RuntimeError(f"seed gagal untuk {cid}")
        seeded.append(cid)
    return seeded


def validate(stage: Path, ids: set[str]) -> dict:
    """Gagal kalau staging belum layak dipasang."""
    folders = {p.name for p in stage.iterdir() if p.is_dir()}
    extra = sorted(folders - ids)
    missing = sorted(ids - folders)
    broken = []
    for cid in sorted(ids):
        d = stage / cid
        skels = [p for p in d.glob("*.skel") if p.is_file()]
        atlases = [p for p in d.glob("*.atlas") if p.is_file()]
        if len(skels) != 1 or skels[0].name != f"{cid}.skel":
            broken.append(f"{cid}: skel={[p.name for p in skels]}")
            continue
        if len(atlases) != 1 or atlases[0].name != f"{cid}.atlas":
            broken.append(f"{cid}: atlas={[p.name for p in atlases]}")
            continue
        for page in atlas_pages(atlases[0].read_bytes()):
            if not (d / page).is_file():
                broken.append(f"{cid}: halaman {page}")
                break
    names = stage / "_names.json"
    n_names = len(json.loads(names.read_text(encoding="utf-8"))) if names.is_file() else 0
    res = {
        "folder": len(folders),
        "katalog": len(ids),
        "ekstra": extra[:12],
        "ekstraJumlah": len(extra),
        "belumAda": missing[:12],
        "belumAdaJumlah": len(missing),
        "rusak": broken[:12],
        "rusakJumlah": len(broken),
        "nama": n_names,
    }
    if extra or missing or broken or n_names != len(ids):
        raise RuntimeError("validasi staging gagal: " + json.dumps(res, ensure_ascii=False))
    return res


def service(action: str) -> None:
    subprocess.run(["systemctl", action, "spine-viewer"], check=False,
                   capture_output=True, timeout=180)


def rescan() -> int:
    # systemctl start kembali sebelum socket HTTP siap; tunggu sampai listener
    # benar-benar hidup supaya swap yang sudah sukses tidak dilaporkan gagal.
    last = None
    for attempt in range(20):
        try:
            with urllib.request.urlopen(
                    f"{BASE}/api/models?lean=1&refresh=1", timeout=900) as r:
                d = json.load(r)
            models = d.get("models", d if isinstance(d, list) else [])
            return len([m for m in models if (m.get("game") or "") == "nikke"])
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"rescan belum siap ({attempt + 1}/20): {str(e)[:80]}")
            time.sleep(3)
    raise RuntimeError(f"rescan gagal setelah 20 percobaan: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--stage", default="",
                    help="pakai/lanjutkan staging yang sudah ada (bukan buat baru)")
    a = ap.parse_args()
    if not a.apply and not a.dry_run:
        print("wajib --apply atau --dry-run", file=sys.stderr)
        return 2

    t0 = time.time()
    catalog = load_json(CATALOG)
    chars = catalog["characters"]
    ids = {str(c["id"]) for c in chars}
    tag = stamp()
    stage = Path(a.stage).resolve() if a.stage else STAGING_ROOT / f"nikke-stage-{tag}"
    archive = STATE_ROOT / f"nikke-before-replace-{tag}"
    if (not a.stage and stage.exists()) or archive.exists():
        print("path staging/arsip sudah ada; hentikan", file=sys.stderr)
        return 2
    log(f"katalog kanonik: {len(chars)} karakter / {len(ids)} id unik")
    log(f"staging: {stage}")

    env = dict(os.environ, NIKKE_OUT=str(stage))
    p = subprocess.run([sys.executable, str(REFRESH), "--workers", str(a.workers)],
                       env=env, capture_output=True, text=True, timeout=5400)
    for line in p.stderr.splitlines()[-8:]:
        log(line)
    out = p.stdout
    start = out.find("{")
    detail = {}
    if start >= 0:
        try:
            detail, _ = json.JSONDecoder().raw_decode(out[start:])
        except json.JSONDecodeError:
            pass
    if p.returncode != 0:
        print(json.dumps({"ok": False, "error": "refresh.py gagal",
                          "stderr": p.stderr[-1500:]}, ensure_ascii=False, indent=1))
        return 1
    errors = detail.get("errors") or []
    counts = detail.get("models") or {}
    log(f"unduhan: {counts} error={len(errors)}")
    if errors:
        log(f"error R2: {len(errors)} — coba seed dari salinan kanonik lokal")
    seeded = seed_missing(stage, ids, OUT)
    if seeded:
        log(f"seed kanonik lokal: {len(seeded)} — " + ", ".join(seeded[:12]))
    if int(counts.get("ok", 0)) + int(counts.get("skip", 0)) + len(seeded) != len(ids):
        print(json.dumps({"ok": False, "error": "unduhan tidak lengkap",
                          "detail": detail, "seed": seeded}, ensure_ascii=False, indent=1))
        return 1

    checked = validate(stage, ids)
    log("validasi staging: " + json.dumps(checked, ensure_ascii=False))
    log(f"pohon lama: {sum(1 for _ in OUT.iterdir()) if OUT.exists() else 0} entri")
    if a.dry_run:
        print(json.dumps({"ok": True, "mode": "dry-run", "unduh": counts,
                          "validasi": checked, "staging": str(stage),
                          "seconds": round(time.time() - t0, 1)},
                         indent=1, ensure_ascii=False))
        return 0

    swapped = False
    try:
        service("stop")
        STAGING_ROOT.mkdir(parents=True, exist_ok=True)
        if OUT.exists():
            shutil.move(str(OUT), str(archive))
        shutil.move(str(stage), str(OUT))
        swapped = True
        log(f"swap selesai — arsip lama: {archive}")
    except Exception as e:  # noqa: BLE001
        if not swapped and archive.exists() and not OUT.exists():
            shutil.move(str(archive), str(OUT))
            log("rollback: pohon lama dipulihkan")
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    finally:
        service("start")

    # Indeks model, potret Prydwen, dan state updater ikut diselaraskan.
    n_models = rescan()
    log(f"rescan: {n_models} model NIKKE")
    p2 = subprocess.run([sys.executable, str(PRYDwen)], capture_output=True,
                        text=True, timeout=900)
    log("prydwen: " + (p2.stdout.strip().splitlines()[-1] if p2.stdout.strip()
                       else p2.stderr[-300:]))
    p3 = subprocess.run([sys.executable, str(UPDATE), "--apply"],
                        capture_output=True, text=True, timeout=5400)
    log("updater: " + (p3.stdout.strip().splitlines()[-1] if p3.stdout.strip()
                       else p3.stderr[-300:]))

    result = {
        "ok": p3.returncode == 0 and n_models == len(ids),
        "mode": "replace",
        "model": n_models,
        "katalog": len(ids),
        "validasi": checked,
        "seedLokal": len(seeded),
        "arsip": str(archive),
        "potretPrydwen": p2.returncode == 0,
        "updateRc": p3.returncode,
        "seconds": round(time.time() - t0, 1),
    }
    logfile = Path("/var/log") / f"nikke-replace-{tag}.json"
    logfile.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
