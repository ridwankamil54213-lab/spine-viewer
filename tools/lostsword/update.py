#!/usr/bin/env python3
"""Satu pembaru Lost Sword dari https://lost-sword-l2d-viewer.pages.dev/.

Menggantikan pipeline XAPK/APKPure lama (tools/update-lostsword.py +
tools/extract-lostsword-video.py). Sekarang seluruh model Spine (standing,
chibi, pet), video cutscene (skill + memorial), nama/family karakter, dan
thumbnail WebP disinkronkan langsung dari situs referensi lewat
tools/lostsword/refresh.py.

Kontrak server (runUpdater / UPDATERS["lostsword"] di src/server.js) &
klien (autoCheckUpdate / checkUpdate / applyUpdate di src/viewer.js):
  * Progres ditulis ke stderr ([HH:MM:SS] ...) supaya tampil live di modal
    "Log Pembaruan".
  * Hasil akhir ditulis ke stdout sebagai JSON multi-baris (indent=1) supaya
    runUpdater berhenti mengumpulkan log pada baris "{" pertama.
  * --check : cepat, TANPA mengunduh aset. Resolve bundle Vite aktif
              (/assets/index-<hash>.js), parse katalog 143 entri, bandingkan
              signature + daftar karakter + kelengkapan 276 folder Spine,
              87 video, dan 374 thumbnail terhadap disk &
              data/lostsword-update-state.json. Menyertakan field `previous`
              agar UI tidak menyalakan titik merah palsu.
  * --apply : jalankan tools/lostsword/refresh.py sambil mengalirkan stderr
              secara live, hitung `new_ids` untuk badge NEW di UI, dan simpan
              state terbaru.

Usage:
    python3 tools/lostsword/update.py --check
    python3 tools/lostsword/update.py --apply [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIEW = HERE.parents[1]
ASSETS = VIEW / "assets" / "lostsword"
VIDEOS = VIEW / "assets" / "lostsword-video"
THUMBS = VIEW / "public" / "thumbs" / "lostsword"
STATE_FILE = VIEW / "data" / "lostsword-update-state.json"
LEGACY_STATE = Path(os.environ.get("LOSTSWORD_STATE", "/srv/spine-assets/lostsword")) / "state.json"

sys.path.insert(0, str(HERE))
import refresh  # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def disk_inventory() -> dict:
    """Inventaris lengkap aset Lost Sword yang terpasang di disk saat ini."""
    spine_folders = 0
    spine_skels = 0
    installed_ids: set[str] = set()
    for kind in ("standing", "chibi", "pet"):
        kd = ASSETS / kind
        if not kd.is_dir():
            continue
        for d in sorted(kd.iterdir()):
            if not d.is_dir():
                continue
            skels = sorted(
                f for f in d.iterdir()
                if f.is_file() and f.suffix.lower() in (".skel", ".json")
            )
            if not skels:
                continue
            spine_folders += 1
            spine_skels += len(skels)
            base_id = f"lostsword/{kind}/{d.name}"
            if len(skels) == 1:
                installed_ids.add(base_id)
            else:
                for sf in skels:
                    installed_ids.add(f"{base_id}#{sf.stem}")

    vid_count = 0
    for kd in ("skill-videos", "memorial-videos"):
        vd = VIDEOS / kd
        if not vd.is_dir():
            continue
        for f in sorted(vd.iterdir()):
            if f.is_file() and f.suffix.lower() == ".mp4" and f.stat().st_size > 1024:
                vid_count += 1
                installed_ids.add(f"lostsword-video/{kd}/{f.stem}")

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
        "folders": spine_folders,
        "skeletons": spine_skels,
        "videos": vid_count,
        "thumbFiles": thumb_files,
        "thumbs": manifest_keys,
        "families": families,
        "names": names_count,
        "ids": installed_ids,
    }


def missing_on_disk(folders: dict[tuple[str, str], list[tuple[str, str]]],
                    vpaths: list[str]) -> tuple[int, int, int]:
    """Hitung (missing_folders, missing_skeletons, missing_videos) di disk."""
    miss_folders = 0
    miss_skels = 0
    for (kind, fn), pairs in folders.items():
        dest = ASSETS / kind / refresh.san(fn)
        if not refresh.folder_complete(dest, pairs):
            miss_folders += 1
            miss_skels += len(pairs)
    miss_vids = 0
    for vp in vpaths:
        rel = vp.lstrip("./").lstrip("/")
        dest = VIDEOS / rel
        if not (dest.is_file() and dest.stat().st_size > 1024):
            miss_vids += 1
    return miss_folders, miss_skels, miss_vids


def load_state() -> dict | None:
    for p in (STATE_FILE, LEGACY_STATE):
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
    return None


def save_state(sig: str, bundle_path: str, catalog: list[dict], inv: dict) -> dict:
    payload = {
        "source": refresh.SITE,
        "sig": sig,
        "version": sig,
        "bundle": bundle_path,
        "entries": len(catalog),
        "entryIds": [str(c.get("id")) for c in catalog if c.get("id")],
        "disk": {
            "folders": inv["folders"],
            "skeletons": inv["skeletons"],
            "videos": inv["videos"],
            "thumbFiles": inv["thumbFiles"],
            "thumbs": inv["thumbs"],
            "families": inv["families"],
            "names": inv["names"],
        },
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    try:
        LEGACY_STATE.parent.mkdir(parents=True, exist_ok=True)
        LEGACY_STATE.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Updater Lost Sword (lost-sword-l2d-viewer.pages.dev)")
    ap.add_argument("--check", action="store_true", help="cek katalog daring vs disk lokal")
    ap.add_argument("--apply", action="store_true", help="unduh + sinkronkan model, video, nama & thumbnail")
    ap.add_argument("--force", action="store_true", help="jalankan refresh penuh walau versi belum berubah")
    args = ap.parse_args()
    do_apply = args.apply and not args.check

    t0 = time.time()
    state = load_state()
    prev_sig = (state or {}).get("sig")
    before = disk_inventory()

    log(f"Memeriksa katalog {refresh.SITE}/ …")
    try:
        catalog, bundle_path, sig = refresh.fetch_catalog()
        folders = refresh.collect_spine_folders(catalog)
        vpaths = refresh.collect_videos(catalog)
        remote_folders = len(folders)
        remote_skels = sum(len(v) for v in folders.values())
        remote_vids = len(vpaths)
    except Exception as exc:  # noqa: BLE001
        err_msg = f"gagal menghubungi lost-sword-l2d-viewer.pages.dev: {exc}"
        log(f"GAGAL: {err_msg}")
        print(json.dumps({
            "ok": False,
            "mode": "apply" if do_apply else "check",
            "game": "lostsword",
            "version": prev_sig,
            "previous": prev_sig,
            "prevVersion": prev_sig,
            "changed": False,
            "have": before["skeletons"],
            "error": err_msg,
        }, indent=1, ensure_ascii=False))
        return 1

    log(f"Bundle aktif : {bundle_path} (sig {sig})")
    log(f"Katalog situs: {len(catalog)} entri · {remote_folders} folder Spine ({remote_skels} skeleton) · {remote_vids} video")
    log(f"Disk lokal   : {before['folders']} folder Spine ({before['skeletons']} skeleton) · "
        f"{before['videos']} video · {before['thumbs']} thumbnail · {before['families']} family")

    miss_folders, miss_skels, miss_vids = missing_on_disk(folders, vpaths)
    expected_thumbs = remote_skels + remote_vids
    miss_thumbs = max(0, expected_thumbs - before["thumbs"])

    prev_entry_ids = set((state or {}).get("entryIds") or [])
    baru = []
    if prev_entry_ids:
        for c in catalog:
            cid = str(c.get("id") or "")
            if cid and cid not in prev_entry_ids:
                baru.append({
                    "id": cid,
                    "title": (c.get("title") or c.get("name") or cid).strip(),
                    "variant": c.get("variant"),
                })

    alasan: list[str] = []
    if prev_sig and sig != prev_sig:
        alasan.append(f"katalog berubah ({prev_sig} -> {sig})")
    if baru:
        ringkas = ", ".join(x["title"] for x in baru[:4])
        if len(baru) > 4:
            ringkas += f" (+{len(baru) - 4} lagi)"
        alasan.append(f"{len(baru)} entri karakter baru ({ringkas})")
    if miss_skels > 0:
        alasan.append(f"{miss_skels} model Spine belum terunduh")
    if miss_vids > 0:
        alasan.append(f"{miss_vids} video cutscene belum terunduh")
    if miss_thumbs > 0 or before["families"] == 0:
        alasan.append("metadata family / thumbnail belum lengkap")

    # Bootstrap state bila belum ada (atau dari format lama tanpa entryIds) dan disk sudah lengkap
    if (state is None or not state.get("entryIds")) and not alasan:
        state = save_state(sig, bundle_path, catalog, before)
        prev_sig = sig

    changed = bool(alasan)
    pending_new = miss_skels + miss_vids

    if not do_apply:
        if changed:
            note = f"Pembaruan tersedia ({sig}): " + "; ".join(alasan) + "."
        else:
            note = (
                f"Sudah terbaru ({sig}) — {before['skeletons']} model Spine + "
                f"{before['videos']} video ({before['families']} karakter, {len(catalog)} entri)."
            )
        log(f"Status       : {note}")
        disk_summary = {k: v for k, v in before.items() if k != "ids"}
        print(json.dumps({
            "ok": True,
            "mode": "check",
            "game": "lostsword",
            "source": refresh.SITE,
            "bundle": bundle_path,
            "version": sig,
            "installed": prev_sig or sig,
            "previous": prev_sig or sig,
            "prevVersion": prev_sig or sig,
            "changed": changed,
            "alasan": alasan,
            "baru": baru,
            "new": pending_new,
            "added": pending_new,
            "removed": 0,
            "have": before["skeletons"],
            "remoteCount": remote_skels,
            "videos": before["videos"],
            "remoteVideos": remote_vids,
            "thumbs": before["thumbs"],
            "families": before["families"],
            "entries": len(catalog),
            "disk": disk_summary,
            "note": note,
            "seconds": round(time.time() - t0, 2),
        }, indent=1, ensure_ascii=False))
        return 0

    if not changed and not args.force:
        note = (
            f"Sudah terbaru ({sig}) — {before['skeletons']} model Spine + "
            f"{before['videos']} video. Tidak ada unduhan baru."
        )
        log(note)
        disk_summary = {k: v for k, v in before.items() if k != "ids"}
        print(json.dumps({
            "ok": True,
            "mode": "apply",
            "skipped": True,
            "game": "lostsword",
            "source": refresh.SITE,
            "bundle": bundle_path,
            "version": sig,
            "previous": prev_sig or sig,
            "prevVersion": prev_sig or sig,
            "changed": False,
            "new": 0,
            "added": 0,
            "removed": 0,
            "downloaded": 0,
            "extracted": 0,
            "already_had": before["skeletons"],
            "failed": 0,
            "new_ids": [],
            "have": before["skeletons"],
            "remoteCount": remote_skels,
            "videos": before["videos"],
            "remoteVideos": remote_vids,
            "thumbs": before["thumbs"],
            "families": before["families"],
            "disk": disk_summary,
            "note": note,
            "seconds": round(time.time() - t0, 2),
        }, indent=1, ensure_ascii=False))
        return 0

    log("Menjalankan sinkronisasi penuh (tools/lostsword/refresh.py)…")
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "refresh.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
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
        err_msg = "; ".join(detail.get("errors") or []) or out_text[-400:] or f"refresh.py exit {rc}"
        log(f"GAGAL: {err_msg}")
        print(json.dumps({
            "ok": False,
            "mode": "apply",
            "game": "lostsword",
            "version": sig,
            "previous": prev_sig or sig,
            "prevVersion": prev_sig or sig,
            "changed": True,
            "have": before["skeletons"],
            "error": err_msg,
        }, indent=1, ensure_ascii=False))
        return 1

    after = disk_inventory()
    save_state(sig, bundle_path, catalog, after)

    new_ids = sorted(after["ids"] - before["ids"])
    m_stat = detail.get("models") or {}
    v_stat = detail.get("videos") or {}
    dl_count = (
        int(m_stat.get("downloaded", 0) or 0)
        + int(v_stat.get("downloaded", 0) or 0)
        + int(detail.get("thumbDownloaded", 0) or 0)
    )
    fail_count = int(m_stat.get("fail", 0) or 0) + int(v_stat.get("fail", 0) or 0)
    added_skels = max(0, after["skeletons"] - before["skeletons"])
    added_vids = max(0, after["videos"] - before["videos"])
    extracted_count = len(new_ids) or (added_skels + added_vids) or int(m_stat.get("downloaded", 0) or 0)

    note = (
        f"Disinkronkan dari lost-sword-l2d-viewer.pages.dev ({sig}): "
        f"{after['skeletons']} model Spine ({after['folders']} folder), "
        f"{after['videos']} video, {after['thumbs']} thumbnail, {after['families']} family."
    )
    log(note)
    disk_summary = {k: v for k, v in after.items() if k != "ids"}
    print(json.dumps({
        "ok": True,
        "mode": "apply",
        "game": "lostsword",
        "source": refresh.SITE,
        "bundle": bundle_path,
        "version": sig,
        "previous": prev_sig or sig,
        "prevVersion": prev_sig or sig,
        "changed": True,
        "new": added_skels,
        "added": added_skels,
        "removed": max(0, before["skeletons"] - after["skeletons"]),
        "downloaded": dl_count,
        "extracted": extracted_count,
        "already_had": int(m_stat.get("skip", 0) or 0) + int(m_stat.get("seeded", 0) or 0),
        "failed": fail_count,
        "new_ids": new_ids,
        "have": after["skeletons"],
        "remoteCount": remote_skels,
        "videos": after["videos"],
        "remoteVideos": remote_vids,
        "thumbs": after["thumbs"],
        "families": after["families"],
        "disk": disk_summary,
        "detail": detail,
        "errors": detail.get("errors") or [],
        "note": note,
        "seconds": round(time.time() - t0, 1),
    }, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
