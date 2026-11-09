#!/usr/bin/env python3
"""Satu pembaru 欲洛降临 (EroEra — youdianse.com/game/detail/456).

Kontrak server (runUpdater / UPDATERS["eroera"] di src/server.js) &
klien (autoCheckUpdate / checkUpdate / applyUpdate di src/viewer.js):
  * Progres ke stderr ([HH:MM:SS] ...), hasil akhir ke stdout sebagai JSON
    multi-baris (indent=1).
  * --check : cepat (~0,4 dtk), baca Version.txt & GameFrameworkVersion.<hash>.dat
              dari CDN resmi res-01.eepgames.com, bandingkan signature + jumlah
              model/thumbnail di disk terhadap data/eroera-update-state.json.
  * --apply : jalankan tools/eroera/refresh.py sambil mengalirkan stderr secara
              live, hitung `new_ids` untuk badge NEW di UI, dan simpan state.

Usage:
    /srv/venv-spine/bin/python tools/eroera/update.py --check
    /srv/venv-spine/bin/python tools/eroera/update.py --apply [--force]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIEW = HERE.parents[1]
ASSETS = VIEW / "assets" / "eroera"
THUMBS = VIEW / "public" / "thumbs" / "eroera"
STATE_FILE = VIEW / "data" / "eroera-update-state.json"

sys.path.insert(0, str(HERE))
import refresh  # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def disk_inventory() -> dict:
    folders = 0
    ids: set[str] = set()
    if ASSETS.is_dir():
        for d in sorted(ASSETS.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            has_skel = any(
                f.is_file() and f.suffix.lower() in (".skel", ".json")
                for f in d.iterdir()
            )
            has_atlas = any(
                f.is_file() and f.suffix.lower() == ".atlas"
                for f in d.iterdir()
            )
            if has_skel and has_atlas:
                folders += 1
                ids.add(f"eroera/{d.name}")

    thumb_files = sum(
        1 for f in THUMBS.iterdir()
        if f.is_file() and f.suffix.lower() == ".webp"
    ) if THUMBS.is_dir() else 0

    manifest_keys = 0
    mf = THUMBS / "_manifest.json"
    if mf.is_file():
        try:
            manifest_keys = len(json.loads(mf.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass

    families = 0
    names_count = 0
    nf = ASSETS / "_names.json"
    if nf.is_file():
        try:
            nd = json.loads(nf.read_text(encoding="utf-8"))
            families = len(nd.get("families") or [])
            names_count = len(nd.get("models") or {})
        except Exception:  # noqa: BLE001
            pass

    return {
        "models": folders,
        "thumbFiles": thumb_files,
        "thumbs": manifest_keys,
        "families": families,
        "names": names_count,
        "ids": ids,
    }


def remote_spine_dir_count(gfu: dict) -> int:
    dirs: set[str] = set()
    for r in gfu["resources"]:
        if not r["name"].startswith("Spine/"):
            continue
        for a in r["assets"]:
            low = a.lower()
            if low.endswith((".skel.bytes", ".skel", ".json")):
                dirs.add(a.rsplit("/", 1)[0].lower())
    return len(dirs)


def load_state() -> dict | None:
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return None


def save_state(ver_info: dict, sig: str, inv: dict) -> dict:
    ver_label = f"{ver_info.get('LatestGameVersion')}.{ver_info.get('InternalResourceVersion')}"
    payload = {
        "source": refresh.YOUDIANSE_URL,
        "sig": sig,
        "version": ver_label,
        "gameVersion": ver_info.get("LatestGameVersion"),
        "resourceVersion": ver_info.get("InternalResourceVersion"),
        "versionListHashCode": ver_info.get("VersionListHashCode"),
        "disk": {k: v for k, v in inv.items() if k != "ids"},
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Updater 欲洛降临 (EroEra)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    do_apply = args.apply and not args.check

    t0 = time.time()
    state = load_state()
    prev_ver = (state or {}).get("version")
    prev_sig = (state or {}).get("sig")
    before = disk_inventory()

    log("Memeriksa Version.txt & GameFrameworkVersion 欲洛降临 (EroEra)…")
    try:
        ver_info, gfu, sig = refresh.fetch_catalog()
        remote_models = remote_spine_dir_count(gfu)
        ver_label = f"{ver_info.get('LatestGameVersion')}.{ver_info.get('InternalResourceVersion')}"
    except Exception as exc:  # noqa: BLE001
        err_msg = f"gagal memeriksa CDN EroEra: {exc}"
        log(f"GAGAL: {err_msg}")
        print(json.dumps({
            "ok": False,
            "mode": "apply" if do_apply else "check",
            "game": "eroera",
            "version": prev_ver,
            "previous": prev_ver,
            "changed": False,
            "have": before["models"],
            "error": err_msg,
        }, indent=1, ensure_ascii=False))
        return 1

    spine_bundles = sum(1 for r in gfu["resources"] if r["name"].startswith("Spine/"))
    log(f"CDN aktif  : v{ver_label} (sig {sig}) · {spine_bundles} bundle Spine ({remote_models} model)")
    log(f"Disk lokal : {before['models']} model Spine · {before['thumbs']} thumbnail · {before['families']} kartu root")

    missing_models = max(0, remote_models - before["models"])
    alasan: list[str] = []
    if prev_sig and sig != prev_sig:
        alasan.append(f"rilis CDN berubah ({prev_ver or prev_sig} -> {ver_label})")
    if missing_models > 0:
        alasan.append(f"{missing_models} model Spine belum terunduh")
    if before["thumbs"] < 160 or before["families"] == 0:
        alasan.append("metadata family / thumbnail belum lengkap")

    if state is None and not alasan:
        save_state(ver_info, sig, before)
        prev_ver = ver_label
        prev_sig = sig

    changed = bool(alasan)

    if not do_apply:
        if changed:
            note = f"Pembaruan tersedia (v{ver_label}): " + "; ".join(alasan) + "."
        else:
            note = (
                f"Sudah terbaru (v{ver_label}) — {before['models']} model Spine "
                f"({before['families']} kartu root, {before['thumbs']} thumbnail)."
            )
        log(f"Status     : {note}")
        print(json.dumps({
            "ok": True,
            "mode": "check",
            "game": "eroera",
            "source": refresh.YOUDIANSE_URL,
            "version": ver_label,
            "installed": prev_ver or ver_label,
            "previous": prev_ver or ver_label,
            "prevVersion": prev_ver or ver_label,
            "sig": sig,
            "changed": changed,
            "alasan": alasan,
            "new": missing_models,
            "added": missing_models,
            "have": before["models"],
            "remoteCount": remote_models,
            "thumbs": before["thumbs"],
            "families": before["families"],
            "disk": {k: v for k, v in before.items() if k != "ids"},
            "note": note,
            "seconds": round(time.time() - t0, 2),
        }, indent=1, ensure_ascii=False))
        return 0

    if not changed and not args.force:
        note = f"Sudah terbaru (v{ver_label}) — {before['models']} model Spine. Tidak ada unduhan baru."
        log(note)
        print(json.dumps({
            "ok": True,
            "mode": "apply",
            "skipped": True,
            "game": "eroera",
            "version": ver_label,
            "previous": prev_ver or ver_label,
            "changed": False,
            "new": 0,
            "added": 0,
            "downloaded": 0,
            "extracted": 0,
            "already_had": before["models"],
            "failed": 0,
            "new_ids": [],
            "have": before["models"],
            "remoteCount": remote_models,
            "thumbs": before["thumbs"],
            "families": before["families"],
            "note": note,
            "seconds": round(time.time() - t0, 2),
        }, indent=1, ensure_ascii=False))
        return 0

    cmd = [sys.executable, str(HERE / "refresh.py")]
    if args.force:
        cmd.append("--force")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stderr is not None
    assert proc.stdout is not None
    for line in proc.stderr:
        s = line.rstrip("\r\n")
        if s:
            print(s, file=sys.stderr, flush=True)
    out_text = proc.stdout.read()
    rc = proc.wait(timeout=1800)

    detail = {}
    jstart = out_text.find("{")
    if jstart >= 0:
        try:
            detail, _ = json.JSONDecoder().raw_decode(out_text[jstart:])
        except Exception:  # noqa: BLE001
            detail = {}

    if rc != 0 or not detail.get("ok", rc == 0):
        err_msg = out_text[-400:] or f"refresh.py exit {rc}"
        log(f"GAGAL: {err_msg}")
        print(json.dumps({
            "ok": False,
            "mode": "apply",
            "game": "eroera",
            "version": ver_label,
            "previous": prev_ver or ver_label,
            "changed": True,
            "have": before["models"],
            "error": err_msg,
        }, indent=1, ensure_ascii=False))
        return 1

    after = disk_inventory()
    save_state(ver_info, sig, after)
    new_ids = sorted(after["ids"] - before["ids"])
    m_stat = detail.get("models") or {}
    extracted_count = len(new_ids) or int(m_stat.get("extracted", 0) or 0)
    note = (
        f"Disinkronkan (v{ver_label}): {after['models']} model Spine "
        f"({after['families']} kartu root, {after['thumbs']} thumbnail)."
    )
    log(note)
    print(json.dumps({
        "ok": True,
        "mode": "apply",
        "game": "eroera",
        "version": ver_label,
        "previous": prev_ver or ver_label,
        "changed": True,
        "new": len(new_ids),
        "added": len(new_ids),
        "downloaded": int(detail.get("bundlesDownloaded", 0) or 0),
        "extracted": extracted_count,
        "already_had": int(m_stat.get("skip", 0) or 0),
        "failed": int(m_stat.get("fail", 0) or 0),
        "new_ids": new_ids,
        "have": after["models"],
        "remoteCount": remote_models,
        "thumbs": after["thumbs"],
        "families": after["families"],
        "disk": {k: v for k, v in after.items() if k != "ids"},
        "note": note,
        "seconds": round(time.time() - t0, 1),
    }, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
