#!/usr/bin/env python3
"""Pembaru Nikke: Goddess of Victory (nikke) — model spine karakter/skin.

Sumber  : repo GitHub Nikke-db/Nikke-db.github.io — mirror lengkap aset spine
          NIKKE, disusun persis seperti layout viewer:
              l2d/<folder>/<folder>_00.skel    (+ .atlas + halaman .png)
          <folder> = karakter utama (c010) atau varian/skin (c010_01), persis
          nama folder di assets/nikke/, jadi tinggal disalin apa adanya.
          Unduhan lewat raw.githubusercontent.com — 1 request per berkas, tanpa
          GitHub API untuk berkas (API hanya untuk daftar pohon sekali).

Deteksi : pohon repo (recursive tree, sekali) -> daftar folder <nama>. Sebuah
          folder dianggap HADIR kalau assets/nikke/<folder>/ sudah memuat
          sekurangnya satu .skel. Yang belum ada = "baru".

`--check` = 1 request (tree) + diff; `--apply` = unduh folder baru + pasang.
Progres -> stderr; hasil JSON -> stdout (kontrak /api/update/:game).
"""
import argparse
import concurrent.futures as cf
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "assets", "nikke")
STATE_DIR = os.environ.get("NIKKE_STATE_DIR", "/srv/spine-assets/nikke-update")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

REPO = "Nikke-db/Nikke-db.github.io"
BRANCH = os.environ.get("NIKKE_BRANCH", "main")
TREE_URL = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
UA = "spine-viewer-nikke-updater/1.0"
WORKERS = 8


def _log(msg):
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def _gh_token():
    tok = os.environ.get("GITHUB_TOKEN", "")
    if tok:
        return tok.strip()
    try:
        with open("/root/.config/github/token") as f:
            return f.read().strip()
    except Exception:
        return ""


def http_get(url, tries=4, timeout=90):
    headers = {"User-Agent": UA}
    if "api.github.com" in url:
        tok = _gh_token()
        if tok:
            headers["Authorization"] = "token " + tok
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"gagal GET {url}: {last}")


def remote_index():
    """{folder: [relpath...]} untuk setiap folder model di l2d/ repo.

    Relatif DI DALAM folder: berkas utama flat (c404_00.skel) maupun di
    subfolder varian (aim/c404_aim_00.skel, cover/c404_cover_00.skel) — viewer
    sudah memperlakukan <folder>/aim & <folder>/cover sebagai varian.
    """
    data = json.loads(http_get(TREE_URL))
    if data.get("truncated"):
        _log("peringatan: tree repo terpotong (truncated)")
    files = {}
    for it in data.get("tree", []):
        p = it.get("path", "")
        if not p.startswith("l2d/") or it.get("type") != "blob":
            continue
        parts = p.split("/")
        if len(parts) < 3:
            continue
        folder = parts[1]
        rel = "/".join(parts[2:])
        files.setdefault(folder, []).append(rel)
    return files


def installed_files():
    """Set path relatif ('<folder>/<rel>') yang SUDAH ada di disk."""
    out = set()
    if not os.path.isdir(DEST):
        return out
    for d in os.listdir(DEST):
        fdir = os.path.join(DEST, d)
        if d.startswith(".") or not os.path.isdir(fdir):
            continue
        for root, _dirs, fs in os.walk(fdir):
            for f in fs:
                full = os.path.join(root, f)
                out.add(os.path.relpath(full, DEST).replace(os.sep, "/"))
    return out


def installed():
    """Folder model yang sudah punya sekurangnya satu skeleton (.skel)."""
    have = installed_files()
    return {p.split("/")[0] for p in have if p.endswith(".skel")}


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=1)


def check():
    idx = remote_index()
    have = installed()
    new = sorted(f for f in idx if f not in have)
    st = load_state()
    _log(f"repo: {len(idx)} folder, {len(have)} ada, {len(new)} baru")
    return {
        "ok": True,
        "changed": bool(new),
        "previous": st.get("last_update"),
        "total": len(idx),
        "installed": len(have),
        "new": len(new),
        "samples": new[:10],
        "new_models": new[:10],
        "repo": REPO,
    }


def download_folder(folder, rels):
    """Unduh berkas yang belum ada di satu folder (termasuk subfolder varian).

    Hanya mengunduh berkas yang BELUM ada, jadi folder yang sudah sebagian
    terpasang (mis. main ada, aim/cover belum) dilengkapi tanpa unduh ulang.
    """
    dst_root = os.path.join(DEST, folder)
    have = installed_files()
    done = 0
    for rel in rels:
        full = folder + "/" + rel
        if full in have:
            continue
        dst = os.path.join(dst_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            blob = http_get(RAW + "l2d/" + full)
        except Exception as e:  # noqa: BLE001
            return folder, False, f"{rel}: {str(e)[:100]}"
        with open(dst, "wb") as f:
            f.write(blob)
        done += 1
    return folder, True, None


def apply_update(limit=0):
    idx = remote_index()
    have = installed_files()
    # Folder yang punya berkas belum lengkap (model baru ATAU varian aim/cover baru).
    todo = []
    for f in sorted(idx):
        if not (f + "/" + f + "_00.skel" in have):
            todo.append(f)  # model baru
            continue
        miss = [rel for rel in idx[f] if f + "/" + rel not in have]
        if miss:
            todo.append(f)  # model lama tapi berkas/varian baru
    if limit:
        todo = todo[:limit]
    _log(f"{len(todo)} folder akan diperiksa/diunduh")
    done = 0
    failed = 0
    new_models = []
    errors = []
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(download_folder, f, sorted(idx[f])): f for f in todo}
        for i, fu in enumerate(cf.as_completed(futs), 1):
            folder, ok, err = fu.result()
            if ok:
                done += 1
                if len(new_models) < 50:
                    new_models.append(folder)
            else:
                failed += 1
                errors.append(f"{folder}: {err}")
            if i % 25 == 0 or i == len(todo):
                _log(f"  {i}/{len(todo)} ok={done} gagal={failed}")

    st = load_state()
    st["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    st["total"] = len(idx)
    save_state(st)

    return {
        "repo": REPO,
        "total": len(idx),
        "installed": len(installed()),
        "new": len(todo),
        "downloaded": done,
        "failed": failed,
        "extracted": done,
        "new_models": new_models,
        "asset_dir": DEST,
        "errors": errors[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="hanya hitung folder baru")
    ap.add_argument("--apply", action="store_true", help="unduh folder baru")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.apply:
        print(json.dumps(apply_update(limit=args.limit), indent=1, ensure_ascii=False))
    elif args.check:
        print(json.dumps(check(), indent=1, ensure_ascii=False))
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
