#!/usr/bin/env python3
"""Perbarui Chaos Zero Nightmare (czn-rigs + czn-cutins-cg).

Sumbernya bukan CDN game, melainkan pustaka model komunitas
`BenNoSleep/czn-animation-viewer` (lihat tools/czn-rigs.md). Jadi "update"
 = tarik commit baru dari repo itu, konversi rig baru, salin cut-in + thumbnail
   baru, lalu tulis ulang `_names.json`/`_manifest.json`.

Repo sudah di-clone sebagai partial/sparse checkout di /opt/re-targets/czn-repo
(rigs, cutins, thumbs, index.json), sehingga `git pull --ff-only` hanya mengunduh
blob yang benar-benar baru.

Alur:
    * --check : git fetch, bandingkan commit remote vs state, hitung rig/cutin
                BARU dari index.json (remote) -> laporan cepat tanpa pull.
    * --apply : git pull, jalankan tools/czn-rigs.py (hanya rig baru) dan
                tools/czn-thumbs.py (thumbnail + nama), lalu simpan state.

Dipakai server lewat GET /api/update/czn.

    /srv/venv-spine/bin/python tools/update-czn.py --check
    /srv/venv-spine/bin/python tools/update-czn.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.environ.get("CZN_PY", "/srv/venv-spine/bin/python")
REPO = os.environ.get("CZN_REPO", "/opt/re-targets/czn-repo")
VIEW = os.environ.get("CZN_VIEW", ROOT)
OUT_RIGS = os.path.join(VIEW, "assets", "czn-rigs")
OUT_CUTINS = os.path.join(VIEW, "assets", "czn-cutins-cg")
BRANCH = os.environ.get("CZN_BRANCH", "main")
REMOTE = os.environ.get("CZN_REMOTE", "origin")
STATE_DIR = os.environ.get("CZN_STATE", "/opt/czn")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

GIT_TIMEOUT = 300


def sh(args, cwd=REPO, timeout=GIT_TIMEOUT):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_state(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    json.dump(s, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, sort_keys=True, indent=1)
    os.replace(tmp, STATE_FILE)


def local_head():
    r = sh(["git", "rev-parse", "HEAD"])
    return r.stdout.strip() if r.returncode == 0 else None


def remote_head():
    # No --depth: the repo is a shallow blob:none clone, and a --depth 1 fetch
    # grafts a new shallow root that makes git think the branches diverged
    # ("Diverging branches can't be fast-forwarded"). Deepening fetches only
    # commit/tree metadata for a partial clone, so it stays cheap.
    r = sh(["git", "fetch", REMOTE, BRANCH])
    if r.returncode != 0:
        raise RuntimeError(f"git fetch gagal: {(r.stderr or r.stdout).strip()[:200]}")
    r = sh(["git", "rev-parse", "FETCH_HEAD"])
    return r.stdout.strip() if r.returncode == 0 else None


def remote_index():
    """index.json dari remote (tanpa perlu checkout), dimuat lewat git show."""
    r = sh(["git", "show", "FETCH_HEAD:index.json"])
    if r.returncode != 0:
        raise RuntimeError(f"index.json remote tak terbaca: {(r.stderr or r.stdout).strip()[:200]}")
    return json.loads(r.stdout)


def local_index():
    try:
        return json.load(open(os.path.join(REPO, "index.json"), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"rigs": [], "cutins": []}


def slugs(idx, kind):
    key = "rigs" if kind == "rig" else "cutins"
    return {r.get("slug") or r.get("id") for r in idx.get(key, []) if (r.get("slug") or r.get("id"))}


def disk_count(path):
    try:
        return len([d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))])
    except Exception:  # noqa: BLE001
        return 0


def cutin_disk_count():
    try:
        return len([f for f in os.listdir(OUT_CUTINS) if f.lower().endswith((".webp", ".png", ".jpg"))])
    except Exception:  # noqa: BLE001
        return 0


def short(commit):
    return (commit or "")[:9]


def check():
    if not os.path.isdir(os.path.join(REPO, ".git")):
        return {"ok": False, "error": f"repo CZN belum dikloning di {REPO}"}
    rhead = remote_head()  # fetch dulu supaya origin/<branch> segar
    ridx = remote_index()
    state = load_state()

    if not state.get("commit"):
        # bootstrap: baseline = kondisi lokal sekarang (jangan lapor semua "baru")
        lidx = local_index()
        state = {
            "commit": local_head(),
            "rigs": sorted(slugs(lidx, "rig")),
            "cutins": sorted(slugs(lidx, "cutin")),
        }
        save_state(state)

    known_rigs = set(state.get("rigs", []))
    known_cutins = set(state.get("cutins", []))
    rnow, cnow = slugs(ridx, "rig"), slugs(ridx, "cutin")
    new_rigs = sorted(rnow - known_rigs) if known_rigs else []
    new_cutins = sorted(cnow - known_cutins) if known_cutins else []
    gone_rigs = sorted(known_rigs - rnow)
    gone_cutins = sorted(known_cutins - cnow)

    changed = ridx is not None and (
        bool(new_rigs) or bool(new_cutins) or short(rhead) != short(state.get("commit"))
    )
    new_ids = [f"czn-rigs/{s}" for s in new_rigs] + [f"czn-cutins-cg/{s}" for s in new_cutins]
    return {
        "ok": True,
        "mode": "check",
        "version": f"{short(rhead)} · {len(rnow)} rig / {len(cnow)} cutin",
        "commit": rhead,
        "previous": short(state.get("commit")),
        "changed": changed,
        "new": len(new_ids),
        "new_ids": new_ids,
        "new_rigs": new_rigs,
        "new_cutins": new_cutins,
        "removed_rigs": gone_rigs,
        "removed_cutins": gone_cutins,
        "rigs_repo": len(rnow),
        "cutins_repo": len(cnow),
        "rigs_disk": disk_count(OUT_RIGS),
        "cutins_disk": cutin_disk_count(),
    }


def apply_update(limit=0):
    t0 = time.time()
    if not os.path.isdir(os.path.join(REPO, ".git")):
        return {"ok": False, "error": f"repo CZN belum dikloning di {REPO}"}
    state = load_state()
    before = check()  # sekaligus menulis baseline bila belum ada
    new_rigs = before["new_rigs"]
    new_cutins = before["new_cutins"]
    print(f"repo: {before['rigs_repo']} rig / {before['cutins_repo']} cutin; "
          f"baru: {len(new_rigs)} rig + {len(new_cutins)} cutin", flush=True)

    print("  git merge --ff-only (fetch already done) …", flush=True)
    r = sh(["git", "merge", "--ff-only", "FETCH_HEAD"])
    if r.returncode != 0:
        return {"ok": False, "error": f"git pull gagal: {(r.stderr or r.stdout).strip()[:300]}"}
    for line in r.stdout.splitlines():
        if line.strip():
            print("   ", line.strip(), flush=True)

    print("  konversi rig (czn-rigs.py) …", flush=True)
    r = sh([PY, os.path.join(HERE, "czn-rigs.py"),
            os.path.join(REPO, "rigs"), OUT_RIGS, os.path.join(REPO, "index.json")],
           cwd=ROOT, timeout=3600)
    if r.returncode != 0:
        return {"ok": False, "error": f"czn-rigs.py gagal: {(r.stderr or r.stdout).strip()[:300]}"}
    for line in r.stdout.splitlines():
        if line.strip():
            print("   ", line.strip(), flush=True)

    print("  thumbnail + nama (czn-thumbs.py) …", flush=True)
    r = sh([PY, os.path.join(HERE, "czn-thumbs.py"), REPO, VIEW], cwd=ROOT, timeout=1200)
    if r.returncode != 0:
        return {"ok": False, "error": f"czn-thumbs.py gagal: {(r.stderr or r.stdout).strip()[:300]}"}
    for line in r.stdout.splitlines():
        if line.strip():
            print("   ", line.strip(), flush=True)

    idx = local_index()
    state = {
        "commit": local_head(),
        "rigs": sorted(slugs(idx, "rig")),
        "cutins": sorted(slugs(idx, "cutin")),
        "updated_at": int(time.time()),
        "rigs_disk": disk_count(OUT_RIGS),
        "cutins_disk": cutin_disk_count(),
    }
    save_state(state)
    return {
        "ok": True,
        "mode": "apply",
        "commit": state["commit"],
        "version": f"{short(state['commit'])} · {len(state['rigs'])} rig / {len(state['cutins'])} cutin",
        "rigs_before": before["rigs_disk"],
        "rigs_after": state["rigs_disk"],
        "rigs_added": max(0, state["rigs_disk"] - before["rigs_disk"]),
        "cutins_added": max(0, state["cutins_disk"] - before["cutins_disk"]),
        "new": len(new_rigs) + len(new_cutins),
        "new_ids": before["new_ids"][:limit] if limit else before["new_ids"],
        "models_written": max(0, state["rigs_disk"] - before["rigs_disk"]),
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
    except Exception as err:  # noqa: BLE001
        res = {"ok": False, "error": str(err)}
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
