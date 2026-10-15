#!/usr/bin/env python3
"""Perbarui model Spine 贤者同盟 / Alliance Sages (CDN euwv.0577ai.com).

Game ini memakai hot-update polos: satu berkas `filelist` JSON di CDN
menyebut SETIAP paket aset beserta ukuran + crc, mis.

    https://euwv.0577ai.com/ob/update/android/filelist
    [{"filename": "spinechar", "size": 3003778, "crc": ...}, ...]

Ada DUA kelompok bundle spine, masing-masing punya pohon aset sendiri:
    * karakter (spinechar[NN], spinecharb/m, spineskinNN) -> assets/alliancesages
    * CG / h-scene (hscene[NN], cgNN, memorycardspineNN)   -> assets/alliancesages-cg

Alur:
    * --check : unduh `filelist`, bandingkan UKURAN tiap bundle dengan state.
                Laporkan bundle baru/berubah + perkiraan unduhan. Tanpa unduh
                bundle. Murah (1 request).
    * --apply : seperti --check, lalu unduh HANYA bundle yang baru/berubah,
                ekstrak ulang isinya (timpa model yang berubah), simpan state.
    * --target char|cg|both (default both) memilih kelompok yang diproses.

Dipakai server lewat GET /api/update/alliancesages (tombol "Perbarui aset").

Pemakaian langsung:
    /srv/venv-spine/bin/python tools/update-alliancesages.py --check
    /srv/venv-spine/bin/python tools/update-alliancesages.py --apply
    /srv/venv-spine/bin/python tools/update-alliancesages.py --apply --target cg
"""
import argparse
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# Muat ekstraktor (nama berkasnya bertanda hubung, jadi lewat importlib).
STATE_DEFAULT = "/opt/alliancesages"

_spec = importlib.util.spec_from_file_location(
    "extract_alliancesages",
    os.path.join(HERE, "alliancesages", "extract-alliancesages.py"),
)
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

STATE_DIR = os.environ.get("ALLIANCESAGES_STATE", STATE_DEFAULT)
STATE_FILE = os.path.join(STATE_DIR, "state.json")

# kelompok -> direktori keluaran
TARGETS = {
    "char": ex.OUT,
    "cg": ex.OUT_CG,
}
# kelompok -> prefix id model di library viewer
KIND_DIR = {"char": "alliancesages", "cg": "alliancesages-cg"}


def kind_dir(kind):
    return KIND_DIR[kind]


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


def diff(entries, state, kind):
    """Bandingkan entri CDN dengan state -> (baru, berubah, tak berubah)."""
    old = state.get("bundles", {})
    new, changed, same = [], [], 0
    for e in entries:
        fn = e["filename"]
        sz = int(e.get("size", 0))
        prev = old.get(fn)
        if prev is None or prev.get("kind") != kind:
            new.append(e)
        elif int(prev.get("size", -1)) != sz:
            changed.append(e)
        else:
            same += 1
    return new, changed, same


def model_count(out):
    try:
        return len([d for d in os.listdir(out) if os.path.isdir(os.path.join(out, d))])
    except Exception:
        return 0


def check(kinds):
    state = load_state()
    res = {"ok": True, "mode": "check", "targets": {}}
    for kind in kinds:
        entries = ex.list_bundles(kind)
        new, changed, same = diff(entries, state, kind)
        dl = sum(int(e.get("size", 0)) for e in new + changed)
        res["targets"][kind] = {
            "dir": TARGETS[kind],
            "total_bundles": len(entries),
            "new": [{"filename": e["filename"], "size": e.get("size")} for e in sorted(new, key=lambda x: x["filename"])],
            "changed": [{"filename": e["filename"], "size": e.get("size")} for e in sorted(changed, key=lambda x: x["filename"])],
            "unchanged": same,
            "download_bytes": dl,
            "download_mb": round(dl / 1e6, 1),
            "models_on_disk": model_count(TARGETS[kind]),
        }
    return res


def apply_update(kinds, limit=0):
    t0 = time.time()
    state = load_state()
    report = {"ok": True, "mode": "apply", "targets": {}}
    new_ids = []
    os.makedirs(ex.CACHE, exist_ok=True)

    for kind in kinds:
        out = TARGETS[kind]
        entries = ex.list_bundles(kind)
        new, changed, same = diff(entries, state, kind)
        targets = sorted(new + changed, key=lambda x: x["filename"])
        if limit:
            targets = targets[:limit]
        os.makedirs(out, exist_ok=True)
        before_set = set(os.listdir(out))
        before = len(before_set)
        print(f"[{kind}] bundle: {len(entries)}; berubah/baru: {len(new)+len(changed)}; "
              f"akan diunduh: {len(targets)}", flush=True)
        os.makedirs(out, exist_ok=True)

        ok = skipped = models = 0
        for i, e in enumerate(targets, 1):
            fn = e["filename"]
            fp = os.path.join(ex.CACHE, fn.replace("/", "_"))
            want = int(e.get("size", 0))
            have = os.path.getsize(fp) if os.path.exists(fp) else -1
            if have != want:
                code = ex.http(f"{ex.BASE}/{fn}", dest=fp)
                if code != "200":
                    print(f"  [{kind} {i}] GAGAL unduh {fn}: http {code}", flush=True)
                    skipped += 1
                    continue
            try:
                n = ex.extract_bundle(fp, out)
            except Exception as err:
                print(f"  [{kind} {i}] GAGAL ekstrak {fn}: {err}", flush=True)
                skipped += 1
                continue
            ok += 1
            models += n
            st = state.setdefault("bundles", {})
            st[fn] = {"kind": kind, "size": want, "crc": e.get("crc"), "models": n, "at": int(time.time())}
            save_state(state)
            print(f"  [{kind} {i}/{len(targets)}] {fn:20} {n:3} model ({time.time()-t0:.0f}s)", flush=True)

        # Bundle yang sudah tidak ada di CDN: buang catatannya (hanya kind ini).
        live = {e["filename"] for e in entries}
        for fn in list(state.get("bundles", {})):
            b = state["bundles"][fn]
            if b.get("kind") == kind and fn not in live:
                state["bundles"].pop(fn, None)
        save_state(state)

        after = model_count(out)
        # Model yang baru muncul = folder yang tadinya belum ada. Dikirim sebagai
        # id lengkap ("alliancesages/<nama>" / "alliancesages-cg/<nama>") supaya
        # viewer bisa menandainya sebagai "baru".
        now = set(os.listdir(out)) if os.path.isdir(out) else set()
        added_ids = [f"{kind_dir(kind)}/{n}" for n in sorted(now - before_set)]
        new_ids.extend(added_ids)
        report["targets"][kind] = {
            "dir": out,
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
            "new_ids": added_ids,
        }

    state["updated_at"] = int(time.time())
    save_state(state)
    report["new_ids"] = new_ids
    report["seconds"] = round(time.time() - t0, 1)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", choices=["char", "cg", "both"], default="both")
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah bundle per target (uji)")
    a = ap.parse_args()
    kinds = ["char", "cg"] if a.target == "both" else [a.target]
    try:
        res = apply_update(kinds, limit=a.limit) if a.apply else check(kinds)
    except Exception as err:
        res = {"ok": False, "error": str(err)}
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
