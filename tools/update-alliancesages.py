#!/usr/bin/env python3
"""Perbarui model Spine 贤者同盟 / Alliance Sages (CDN euwv.0577ai.com).

Game ini memakai hot-update polos: satu berkas `filelist` JSON di CDN
menyebut SETIAP paket aset beserta ukuran + crc, mis.

    https://euwv.0577ai.com/ob/update/android/filelist
    [{"filename": "2026/0922/spinechar", "size": 3003778, "crc": ...}, ...]

Bundle `spine*` (spinechar, spinecharb, spinecharm, spineskin, spinecharNN,
memorycardspineNN) adalah UnityFS berisi beberapa model Spine 3.8.99 (JSON).

Alur:
    * --check : unduh `filelist`, saring bundle spine, bandingkan UKURAN tiap
                bundle dengan state terakhir. Laporkan bundle baru/berubah +
                perkiraan unduhan. Tidak mengunduh bundle. Murah (1 request).
    * --apply : seperti --check, lalu unduh HANYA bundle yang baru/berubah,
                ekstrak ulang isinya ke assets/alliancesages (timpa model yang
                berubah), simpan state. Model lama yang tidak tersentuh tetap.

Dipakai server lewat GET /api/update/alliancesages (tombol "Perbarui aset").

Pemakaian langsung:
    /srv/venv-spine/bin/python tools/update-alliancesages.py --check
    /srv/venv-spine/bin/python tools/update-alliancesages.py --apply
"""
import argparse
import importlib.util
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# Muat ekstraktor (nama berkasnya bertanda hubung, jadi lewat importlib).
MJG_STATE_DEFAULT = "/opt/alliancesages"

_spec = importlib.util.spec_from_file_location(
    "extract_alliancesages",
    os.path.join(HERE, "alliancesages", "extract-alliancesages.py"),
)
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

STATE_DIR = os.environ.get("ALLIANCESAGES_STATE", MJG_STATE_DEFAULT)
STATE_FILE = os.path.join(STATE_DIR, "state.json")
OUT = ex.OUT
CACHE = ex.CACHE


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"bundles": {}}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, sort_keys=True, indent=1)
    os.replace(tmp, STATE_FILE)


def spine_entries():
    """Ambil `filelist` sekali, kembalikan entri bundle yang berisi spine."""
    return ex.list_bundles()


def diff(entries, state):
    """Bandingkan entri CDN dengan state -> (baru, berubah, tak berubah)."""
    old = state.get("bundles", {})
    new, changed, same = [], [], 0
    for e in entries:
        fn = e["filename"]
        sz = int(e.get("size", 0))
        prev = old.get(fn)
        if prev is None:
            new.append(e)
        elif int(prev.get("size", -1)) != sz:
            changed.append(e)
        else:
            same += 1
    return new, changed, same


def model_count():
    try:
        return len([d for d in os.listdir(OUT) if os.path.isdir(os.path.join(OUT, d))])
    except Exception:
        return 0


def check():
    entries = spine_entries()
    state = load_state()
    new, changed, same = diff(entries, state)
    dl = sum(int(e.get("size", 0)) for e in new + changed)
    return {
        "ok": True,
        "mode": "check",
        "total_bundles": len(entries),
        "new": [
            {"filename": e["filename"], "size": e.get("size")}
            for e in sorted(new, key=lambda x: x["filename"])
        ],
        "changed": [
            {"filename": e["filename"], "size": e.get("size")}
            for e in sorted(changed, key=lambda x: x["filename"])
        ],
        "unchanged": same,
        "download_bytes": dl,
        "download_mb": round(dl / 1e6, 1),
        "models_on_disk": model_count(),
    }


def apply_update(limit=0):
    t0 = time.time()
    entries = spine_entries()
    state = load_state()
    todo = diff(entries, state)
    new, changed, same = todo
    targets = sorted(new + changed, key=lambda x: x["filename"])
    if limit:
        targets = targets[:limit]

    before = model_count()
    print(f"bundle spine: {len(entries)}; berubah/baru: {len(new)+len(changed)}; "
          f"akan diunduh: {len(targets)}", flush=True)

    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    ok = skipped = models = 0
    for i, e in enumerate(targets, 1):
        fn = e["filename"]
        fp = os.path.join(CACHE, fn.replace("/", "_"))
        want = int(e.get("size", 0))
        have = os.path.getsize(fp) if os.path.exists(fp) else -1
        if have != want:
            code = ex.http(f"{ex.BASE}/{fn}", dest=fp)
            if code != "200":
                print(f"  [{i}] GAGAL unduh {fn}: http {code}", flush=True)
                skipped += 1
                continue
        try:
            n = ex.extract_bundle(fp, OUT)
        except Exception as err:
            print(f"  [{i}] GAGAL ekstrak {fn}: {err}", flush=True)
            skipped += 1
            continue
        ok += 1
        models += n
        # State per-bundle disimpan begitu berhasil supaya jalankan ulang setelah
        # putus tidak mengunduh lagi yang sudah selesai.
        st = state.setdefault("bundles", {})
        st[fn] = {
            "size": int(e.get("size", 0)),
            "crc": e.get("crc"),
            "models": n,
            "at": int(time.time()),
        }
        save_state(state)
        print(f"  [{i}/{len(targets)}] {fn:20} {n:3} model "
              f"({time.time()-t0:.0f}s)", flush=True)

    # Bundle yang lama tapi sudah tidak ada di CDN: buang catatannya.
    live = {e["filename"] for e in entries}
    for fn in list(state.get("bundles", {})):
        if fn not in live:
            state["bundles"].pop(fn, None)
    state["updated_at"] = int(time.time())
    state["total_bundles"] = len(entries)
    save_state(state)

    after = model_count()
    return {
        "ok": True,
        "mode": "apply",
        "bundles_total": len(entries),
        "bundles_new": len(new),
        "bundles_changed": len(changed),
        "bundles_unchanged": same,
        "bundles_downloaded": ok,
        "bundles_skipped": skipped,
        "models_written": models,
        "models_before": before,
        "models_after": after,
        "models_added": max(0, after - before),
        "seconds": round(time.time() - t0, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah bundle (uji)")
    a = ap.parse_args()
    try:
        res = apply_update(limit=a.limit) if a.apply else check()
    except Exception as err:
        res = {"ok": False, "error": str(err)}
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
