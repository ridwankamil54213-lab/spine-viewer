#!/usr/bin/env python3
"""Perbarui model Spine 禁果便利店 (mcs18, CDN mcs18-client-resource-tw.1uhg.com).

Addressables terbuka: `catalog_<version>.json` berisi m_InternalIds semua
bundle. Bundle karakter spine ada di beberapa grup:
    .../arts/animation/character*_<hash>.bundle
    .../spine_assets_character*_<hash>.bundle
    .../storyanimation_assets_character*_<hash>.bundle
Tiap bundle = UnityFS berisi .skel + .atlas + Texture2D.

Alur:
    * --check : unduh catalog, bandingkan SET nama bundle + hash dengan state.
                Laporkan bundle baru/hilang + jumlah model yang ada di disk.
    * --apply : unduh + ekstrak HANYA bundle yang baru/berubah (hash baru).

Catatan: versi catalog diambil dari state `catalog_url`; kenaikan versi
dilaporkan sebagai perubahan (bundle hash biasanya ikut berubah).
Dipakai server lewat GET /api/update/mcs18.

    /srv/venv-spine/bin/python tools/update-mcs18.py --check
    /srv/venv-spine/bin/python tools/update-mcs18.py --apply
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "extract_mcs18", os.path.join(HERE, "mcs18", "extract-mcs18.py")
)
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

STATE_DIR = os.environ.get("MCS18_STATE", "/opt/mcs18")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
OUT = ex.OUT


def load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        return {"bundles": {}}


def save_state(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    json.dump(s, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, sort_keys=True, indent=1)
    os.replace(tmp, STATE_FILE)


def model_count():
    try:
        return len([d for d in os.listdir(OUT) if os.path.isdir(os.path.join(OUT, d))])
    except Exception:
        return 0


def diff(rels, state):
    old = state.get("bundles", {})
    new = [r for r in rels if r not in old]
    same = len(rels) - len(new)
    gone = [r for r in old if r not in set(rels)]
    return new, same, gone


def check():
    rels = ex.bundle_rel_paths()
    state = load_state()
    new, same, gone = diff(rels, state)
    return {
        "ok": True,
        "mode": "check",
        "bundles_total": len(rels),
        "new": new,
        "new_count": len(new),
        "unchanged": same,
        "removed": gone,
        "models_on_disk": model_count(),
    }


def apply_update(limit=0):
    t0 = time.time()
    rels = ex.bundle_rel_paths()
    state = load_state()
    new, same, gone = diff(rels, state)
    targets = new[:limit] if limit else new
    before = model_count()
    print(f"bundle: {len(rels)}; baru: {len(new)}; diproses: {len(targets)}", flush=True)

    ok = skipped = models = 0
    for i, rel in enumerate(targets, 1):
        _, n = ex.one(rel)
        if n == -1:
            print(f"  [{i}] GAGAL unduh {rel}", flush=True)
            skipped += 1
            continue
        if n < 0:
            print(f"  [{i}] GAGAL ekstrak {rel}", flush=True)
            skipped += 1
            continue
        ok += 1
        models += n
        st = state.setdefault("bundles", {})
        st[rel] = {"models": n, "at": int(time.time())}
        save_state(state)
        print(f"  [{i}/{len(targets)}] {rel.split('/')[-1][:48]:48} {n:3} ({time.time()-t0:.0f}s)", flush=True)

    live = set(rels)
    for r in list(state.get("bundles", {})):
        if r not in live:
            state["bundles"].pop(r, None)
    state["updated_at"] = int(time.time())
    state["bundles_total"] = len(rels)
    save_state(state)

    after = model_count()
    return {
        "ok": True,
        "mode": "apply",
        "bundles_total": len(rels),
        "bundles_new": len(new),
        "bundles_removed": len(gone),
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
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    try:
        res = apply_update(limit=a.limit) if a.apply else check()
    except Exception as err:
        res = {"ok": False, "error": str(err)}
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
