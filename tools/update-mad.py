#!/usr/bin/env python3
"""Perbarui Make Drama (mad-drama) dari pustaka anyabot/MAD-Viewer.

Sumbernya bukan CDN game, melainkan repo komunitas:
  * anyabot/MAD-Viewer        -> katalog (public/data/skin_list.json, cdn.json)
  * anyabot/MAD-assets-1 / -2 -> per-skin folder loose (skel/atlas/png)

Alur:
    * --check : git fetch repo katalog, bandingkan SET key skin_list.json vs
                state (/opt/mad/state.json) -> lapor skin baru.
    * --apply : git merge --ff-only, jalankan tools/extract-mad-viewer.py
                (hanya yang baru) lalu tulis ulang _names.json / manifest.

Dipakai server lewat GET /api/update/mad-drama.

    /srv/venv-spine/bin/python tools/update-mad.py --check
    /srv/venv-spine/bin/python tools/update-mad.py --apply
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
PY = os.environ.get("MAD_PY", "/srv/venv-spine/bin/python")
REPO = os.environ.get("MAD_REPO", "/opt/re-targets/mad-viewer")
VIEW = os.environ.get("MAD_VIEW", ROOT)
OUT = os.path.join(VIEW, "assets", "mad-drama")
BRANCH = os.environ.get("MAD_BRANCH", "main")
REMOTE = os.environ.get("MAD_REMOTE", "origin")
STATE_DIR = os.environ.get("MAD_STATE", "/opt/mad")
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
    # No --depth: the repo may be a shallow clone; a --depth 1 fetch grafts a new
    # shallow root and git then refuses the --ff-only merge ("diverging").
    r = sh(["git", "fetch", REMOTE, BRANCH])
    if r.returncode != 0:
        raise RuntimeError(f"git fetch gagal: {(r.stderr or r.stdout).strip()[:200]}")
    r = sh(["git", "rev-parse", "FETCH_HEAD"])
    return r.stdout.strip() if r.returncode == 0 else None


def remote_keys():
    """skin keys at the fetched revision, without checking it out."""
    r = sh(["git", "show", "FETCH_HEAD:public/data/skin_list.json"])
    if r.returncode != 0:
        raise RuntimeError(f"skin_list.json remote tak terbaca: {(r.stderr or r.stdout).strip()[:200]}")
    return [s.get("key") for s in json.loads(r.stdout).get("skins", []) if s.get("key")]


def local_keys():
    try:
        d = json.load(open(os.path.join(REPO, "public", "data", "skin_list.json"), encoding="utf-8"))
        return [s.get("key") for s in d.get("skins", []) if s.get("key")]
    except Exception:  # noqa: BLE001
        return []


def disk_units():
    try:
        return sorted(d for d in os.listdir(OUT) if os.path.isdir(os.path.join(OUT, d)))
    except Exception:  # noqa: BLE001
        return []


def short(c):
    return (c or "")[:9]


def check():
    if not os.path.isdir(os.path.join(REPO, ".git")):
        return {"ok": False, "error": f"repo MAD-Viewer belum dikloning di {REPO}"}
    rhead = remote_head()
    rkeys = remote_keys()
    state = load_state()
    if not state.get("commit"):
        state = {"commit": local_head(), "skins": local_keys()}
        save_state(state)
    known = set(state.get("skins", []))
    new = sorted(set(rkeys) - known) if known else []
    gone = sorted(known - set(rkeys))
    return {
        "ok": True,
        "mode": "check",
        "version": f"{short(rhead)} · {len(rkeys)} skin",
        "commit": rhead,
        "previous": short(state.get("commit")),
        "changed": bool(new) or short(rhead) != short(state.get("commit")),
        "new": len(new),
        "new_ids": [f"mad-drama/{k}" for k in new],
        "new_skins": new,
        "removed_skins": gone,
        "skins_repo": len(rkeys),
        "models_disk": len(disk_units()),
    }


def apply_update(limit=0):
    t0 = time.time()
    if not os.path.isdir(os.path.join(REPO, ".git")):
        return {"ok": False, "error": f"repo MAD-Viewer belum dikloning di {REPO}"}
    before = check()
    new = before["new_skins"]
    print(f"repo: {before['skins_repo']} skin; baru: {len(new)}", flush=True)

    print("  git merge --ff-only (fetch already done) …", flush=True)
    r = sh(["git", "merge", "--ff-only", "FETCH_HEAD"])
    if r.returncode != 0:
        return {"ok": False, "error": f"git merge gagal: {(r.stderr or r.stdout).strip()[:300]}"}
    for line in r.stdout.splitlines():
        if line.strip():
            print("   ", line.strip(), flush=True)

    args = [PY, os.path.join(HERE, "extract-mad-viewer.py")]
    if new and not limit:
        args += ["--only", ",".join(new)]
    elif limit:
        args += ["--limit", str(limit)]
    print("  ekstraksi skin (extract-mad-viewer.py) …", flush=True)
    r = sh(args, cwd=ROOT, timeout=7200)
    if r.returncode != 0:
        return {"ok": False, "error": f"extract-mad-viewer.py gagal: {(r.stderr or r.stdout).strip()[:300]}"}
    for line in r.stdout.splitlines():
        if line.strip():
            print("   ", line.strip(), flush=True)

    state = {"commit": local_head(), "skins": local_keys(), "updated_at": int(time.time()),
             "models_disk": len(disk_units())}
    save_state(state)
    return {
        "ok": True,
        "mode": "apply",
        "commit": state["commit"],
        "version": f"{short(state['commit'])} · {len(state['skins'])} skin",
        "new": len(new),
        "new_ids": before["new_ids"][:limit] if limit else before["new_ids"],
        "models_disk": state["models_disk"],
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
