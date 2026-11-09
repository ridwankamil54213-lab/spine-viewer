#!/usr/bin/env python3
"""Bangun thumbnail Brown Dust 2 dari repo Zormolo/Brown-Dust-2-Assets.

Sumber (repo yang sama dengan model):
  assets/ui/costume_face/illust_inven_<stem>.png   216 potret (prioritas)
  assets/ui/costume_icon/icon_costume<id>.png      208 ikon (fallback)

Pemetaan:
  tiap folder model yang punya .skel -> stem berkas skeleton
    -> illust_inven_<stem>.png kalau ada
    -> kalau tidak, data/bd2-names.json[stem].costumeId -> icon_costume<id>.png
  data/bd2-names.json juga mengindeks kunci "cutscene_*", jadi varian skill
  cutscene ikut dapat thumbnail lewat costumeId-nya.

Keluaran: public/thumbs/bd2/<id>.png + _manifest.json. Kunci manifest adalah
id model LENGKAP ("bd2/..." dan "bd2-char/..."), karena kedua root jatuh ke
satu game "bd2" (resolveGame mencocokkan awalan).

Daftar berkas UI di-cache per commit SHA repo di data/bd2-ui-thumbs-state.json
(diabaikan git) supaya --check/--apply rutin tidak menghabiskan kuota GitHub
API anonim (60/jam).

Folder dengan beberapa skeleton diberi id "<folder>#<stem>" oleh scanModels();
semuanya berbagi satu berkas thumbnail.

Idempoten: berkas yang sudah ada dilewati. Tidak menghapus apa pun.

Usage:
    python3 tools/browndust/refresh-thumbs.py [--version <commit-sha>]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
A_ROOT = VIEW / "assets"
OUT = VIEW / "public" / "thumbs" / "bd2"
NAMES_FILE = VIEW / "data" / "bd2-names.json"
STATE = VIEW / "data" / "bd2-ui-thumbs-state.json"
BD2_STATE = Path("/srv/spine-assets/bd2-update/state.json")

SLUG = "Zormolo/Brown-Dust-2-Assets"
BRANCH = "main"
GH_API = f"https://api.github.com/repos/{SLUG}"
GH_RAW = f"https://raw.githubusercontent.com/{SLUG}/{BRANCH}/"
UA = "spine-viewer-bd2-thumbs/1.0"
WORKERS = 8
UI_DIRS = ("costume_face", "costume_icon")


def fetch(url: str, timeout: int = 90, retries: int = 3) -> bytes:
    """curl: konsisten untuk GitHub API maupun raw, dengan deteksi 404."""
    curl = shutil.which("curl") or "/usr/bin/curl"
    last = None
    for attempt in range(retries):
        fd, tmp = tempfile.mkstemp(prefix="bd2ui-", suffix=".bin")
        os.close(fd)
        try:
            p = subprocess.run(
                [curl, "-sSL", "--max-time", str(timeout), "-A", UA,
                 "-H", "Accept: application/vnd.github+json",
                 "-o", tmp, "-w", "%{http_code}", url],
                capture_output=True, timeout=timeout + 20,
            )
            code = (p.stdout or b"").strip().decode("ascii", "replace")
            if p.returncode == 0 and code.startswith("2"):
                return Path(tmp).read_bytes()
            last = f"HTTP {code} rc={p.returncode}"
        except Exception as e:  # noqa: BLE001
            last = e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def repo_version() -> str:
    """Commit SHA: argumen --version dulu, lalu state updater model."""
    try:
        return json.loads(BD2_STATE.read_text(encoding="utf-8")).get("version", "")
    except Exception:  # noqa: BLE001
        return ""


def ui_lists(version: str) -> dict[str, set[str]]:
    """{nama dir: set(nama berkas)} — cache per commit SHA."""
    cached = {}
    try:
        cached = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cached = {}
    if version and cached.get("version") == version and all(
            cached.get(d) for d in UI_DIRS):
        return {d: set(cached[d]) for d in UI_DIRS}

    out = {}
    for d in UI_DIRS:
        url = f"{GH_API}/git/trees/{BRANCH}:assets/ui/{d}?recursive=1"
        tree = json.loads(fetch(url))
        out[d] = {x["path"].split("/")[-1] for x in tree.get("tree", [])
                  if x.get("type") == "blob" and
                  x.get("path", "").lower().endswith(".png")}
    if version:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "version": version,
            **{d: sorted(out[d]) for d in UI_DIRS},
        }, indent=1), encoding="utf-8")
    return out


def safe_name(model_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", model_id) + ".png"


def model_dirs() -> list[tuple[str, list[str], str]]:
    """(id model / daftar id saat multi-skeleton, stem utama)."""
    out = []
    for game in ("bd2-char", "bd2"):
        root = A_ROOT / game
        if not root.is_dir():
            continue
        for dirpath, _, files in os.walk(root):
            skels = sorted(f for f in files if f.lower().endswith(".skel"))
            if not skels:
                continue
            rel = Path(dirpath).relative_to(A_ROOT).as_posix()
            ids = ([f"{rel}#{Path(s).stem}" for s in skels]
                   if len(skels) > 1 else [rel])
            out.append((rel, ids, Path(skels[0]).stem))
    return out


def thumb_for(stem: str, names: dict, face: set[str], icon: set[str]) -> str | None:
    cand = f"illust_inven_{stem}.png"
    if cand in face:
        return f"assets/ui/costume_face/{cand}"
    rec = names.get(stem) or {}
    cid = rec.get("costumeId")
    if cid:
        cand = f"icon_costume{cid}.png"
        if cand in icon:
            return f"assets/ui/costume_icon/{cand}"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="", help="commit SHA repo (dari updater)")
    a = ap.parse_args()
    version = a.version or repo_version()

    names = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
    lists = ui_lists(version)
    face, icon = lists["costume_face"], lists["costume_icon"]
    OUT.mkdir(parents=True, exist_ok=True)

    dirs = model_dirs()
    jobs = []  # (id-ids, filename, rel-path)
    for _rel, ids, stem in dirs:
        rel = thumb_for(stem, names, face, icon)
        if not rel:
            continue
        jobs.append((ids, safe_name(ids[0].split("#")[0]), rel))

    def one(job) -> tuple[list[str], str, bool, str]:
        ids, filename, rel = job
        dest = OUT / filename
        if dest.exists() and dest.stat().st_size > 512:
            return ids, filename, True, ""
        try:
            data = fetch(GH_RAW + rel, timeout=120)
            if not data.startswith(b"\x89PNG"):
                return ids, filename, False, "bukan PNG"
            dest.write_bytes(data)
            return ids, filename, True, ""
        except Exception as e:  # noqa: BLE001
            return ids, filename, False, str(e)[:100]

    manifest = {}
    ok, bad = 0, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for ids, filename, good, err in pool.map(one, jobs):
            if good:
                ok += 1
                for mid in ids:
                    manifest[mid] = filename
            else:
                bad.append(f"{ids[0]}: {err}")
    (OUT / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")

    res = {
        "modelDirs": len(dirs),
        "mapped": len(jobs),
        "thumbOk": ok,
        "thumbFailed": len(bad),
        "manifestEntries": len(manifest),
        "faceFiles": len(face),
        "iconFiles": len(icon),
        "version": version[:12] or None,
        "errors": bad[:10],
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    if bad:
        print("GAGAL: sebagian thumbnail tidak terunduh", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
