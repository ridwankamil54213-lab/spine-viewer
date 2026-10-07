#!/usr/bin/env python3
"""Pembaru Brown Dust 2 (bd2) — tarik model Spine baru dari repo aset komunitas.

Sumber  : github.com/Zormolo/Brown-Dust-2-Assets (branch main, ~5 GB, pakai
          Git-LFS untuk biner — tapi raw.githubusercontent.com mengembalikan
          ISI ASLI, bukan pointer LFS, jadi tak butuh git-lfs).
Layout  : repo menyimpan  assets/spine/<kategori>/<Karakter>/<Kostum>/<id>.skel
          (+ .atlas + .png). Updater ini menaruh model baru ke TATA LETAK YANG
          SUDAH DIBACA VIEWER:

            karakter      -> assets/bd2-char/<Karakter>/<Kostum>/<id>.skel
            varian lain   -> assets/bd2-char/<Karakter>/<Kostum>/<Jenis>/<id>.skel
                             (Jenis = "Skill-Cutscene", "Interaction", ...)
            tanpa karakter (misc/special_animation) -> assets/bd2/<id>/<id>.skel

          Jadi model baru otomatis membentuk "family" (model utama + dropdown
          varian) seperti hasil tools/relayout-bd2.py.

Integritas: tiap berkas diverifikasi terhadap sha git-blob dari GitHub Trees
          API (sha1("blob <len>\\0" + isi)). Unduhan terpotong langsung ditolak.

Pemakaian:
    /srv/venv-spine/bin/python tools/update-browndust.py --check
    /srv/venv-spine/bin/python tools/update-browndust.py --apply
    BD2_GH_TOKEN=... python tools/update-browndust.py --apply   # naikkan rate limit

Progres -> stderr; hasil JSON -> stdout (kontrak /api/update/:game).
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
DEST_CHAR = os.path.join(ASSETS, "bd2-char")
DEST_FLAT = os.path.join(ASSETS, "bd2")
STATE_DIR = os.environ.get("BD2_STATE_DIR", "/srv/spine-assets/bd2-update")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
SLUG = "Zormolo/Brown-Dust-2-Assets"
BRANCH = os.environ.get("BD2_BRANCH", "main")
GH_API = f"https://api.github.com/repos/{SLUG}"
GH_RAW = f"https://raw.githubusercontent.com/{SLUG}/{BRANCH}/"
UA = "spine-viewer-bd2-updater/1.0"
WORKERS = 8
MAX_MB = 60  # batas satu berkas (tiap berkas > ini dilewati kecuali .png)
ASSET_EXT = (".skel", ".atlas", ".png", ".jpg", ".jpeg", ".webp")

# Kategori repo, paling spesifik dulu (id boleh muncul di >1; yang pertama menang),
# sama seperti tools/relayout-bd2.py.
CATEGORIES = [
    "character",
    "skill_cutscene",
    "interaction",
    "light_novel_talk",
    "npc",
    "miscellaneous",
    "special_animation",
]
JENIS = {
    "character": "Karakter",
    "skill_cutscene": "Skill Cutscene",
    "interaction": "Interaction",
    "light_novel_talk": "Light Novel Talk",
    "npc": "NPC",
    "miscellaneous": "Lainnya",
    "special_animation": "Special Animation",
    "censored": "Tersensor",
}


def _log(msg):
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_state(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, STATE_FILE)


def _token():
    """Token GitHub (read-only API) tanpa pernah dicetak.

    Urutan: BD2_GH_TOKEN, GH_TOKEN, lalu berkas token yang sudah ada di mesin
    (dipakai juga untuk push repo ini). Kuota anonim hanya 60/jam — 7 panggilan
    per check cepat habis; dengan token jadi 5000/jam.
    """
    for var in ("BD2_GH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        v = os.environ.get(var)
        if v:
            return v.strip()
    for path in (os.path.expanduser("~/.config/github/token"),
                 "/root/.config/github/token"):
        try:
            with open(path, encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            continue
    return None


GH_TOKEN = _token()


def gh_get(url, raw=False, tries=4):
    """GET dengan retry; kembalikan bytes (raw) atau objek JSON.

    Rate limit (HTTP 403/429) TIDAK diulang — mengulanginya hanya mengubah satu
    kegagalan cepat menjadi hang bermenit-menit (banyak endpoint × backoff).
    """
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        headers["Authorization"] = "Bearer " + GH_TOKEN
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                hint = " (set BD2_GH_TOKEN untuk kuota lebih besar)" if not GH_TOKEN else ""
                raise RuntimeError(f"GitHub menolak ({e.code}) {url}{hint}") from e
            last = e
            time.sleep(1.5 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET gagal {url}: {last}")


def fetch_tree(saved):
    """({path: {size, sha}}, version) — dengan cache.

    GitHub menolak (HTTP 500) `git/trees/main?recursive=1` untuk repo sebesar
    ini, jadi pohon diambil PER KATEGORI lewat sintaks `main:<path>`.

    Agar `--check` rutin tak menghabiskan rate limit anonim (60/jam, tiap
    panggilan kategori satu hit), pohon + commit sha di-cache di state: kalau
    commit sha belum berubah, pohon lama dipakai lagi. Jadi check normal cuma
    SATU panggilan API (ambil sha HEAD); 7 panggilan kategori hanya saat repo
    benar-benar berubah.
    """
    blobs = {}
    version = ""
    try:
        version = gh_get(f"{GH_API}/commits/{BRANCH}").get("sha", "")
    except Exception as e:  # noqa: BLE001
        _log("tak bisa baca commit sha: " + str(e)[:80])

    cached = saved.get("tree") or {}
    if version and saved.get("version") == version and cached:
        _log(f"pohon dari cache (commit {version[:10]} tak berubah)")
        return {p: {"size": v[0], "sha": v[1]} for p, v in cached.items()}, version

    for cat in CATEGORIES:
        url = f"{GH_API}/git/trees/{BRANCH}:assets/spine/{cat}?recursive=1"
        try:
            t = gh_get(url)
        except Exception as e:  # noqa: BLE001
            _log(f"kategori dilewati ({cat}): {str(e)[:80]}")
            continue
        n = 0
        for x in t.get("tree", []):
            if x.get("type") != "blob":
                continue
            blobs[f"assets/spine/{cat}/{x['path']}"] = {
                "size": x.get("size", 0), "sha": x.get("sha", ""),
            }
            n += 1
        _log(f"  pohon {cat}: {n} berkas")
    if not blobs:
        raise RuntimeError("tak ada berkas yang terbaca dari repo")
    return blobs, version


def build_ref(blobs):
    """stem -> (kategori, karakter, kostum) dari pohon repo."""
    ref = {}
    for cat in CATEGORIES:
        pre = f"assets/spine/{cat}/"
        for path in blobs:
            if not path.startswith(pre) or not path.endswith(".skel"):
                continue
            parts = path[len(pre):].split("/")          # <Kar>/<Kost>/x.skel atau x.skel
            ch = parts[0] if len(parts) >= 2 else None
            co = parts[1] if len(parts) >= 3 else None
            ref.setdefault(parts[-1][:-5], (cat, ch, co))
    return ref


def slug(s):
    return re.sub(r"[^\w.\-]+", "-", str(s)).strip("-")


def dest_dir_for(stem, cat, ch, co):
    """Folder tujuan model (mengikuti tata letak viewer saat ini)."""
    if not ch:
        return os.path.join(DEST_FLAT, slug(stem))
    parts = [DEST_CHAR, slug(ch)]
    if co:
        parts.append(slug(co))
    if cat != "character":
        parts.append(slug(JENIS.get(cat, cat)))
    return os.path.join(*parts)


def model_dirs(blobs):
    """{dir: {'stems': set, 'files': [path,...]}} untuk tiap folder ber-skel."""
    out = {}
    for path in blobs:
        if not path.startswith("assets/spine/"):
            continue
        if not path.endswith(ASSET_EXT):
            continue
        d = path.rsplit("/", 1)[0]
        e = out.setdefault(d, {"stems": set(), "files": []})
        e["files"].append(path)
        if path.endswith(".skel"):
            e["stems"].add(os.path.basename(path)[:-5])
    # buang folder tanpa .skel (mis. hanya .atlas)
    return {d: v for d, v in out.items() if v["stems"]}


def local_stems():
    got = set()
    for root in (DEST_CHAR, DEST_FLAT):
        for dp, _, fs in os.walk(root):
            for f in fs:
                if f.endswith(".skel"):
                    got.add(f[:-5])
    return got


def plan(blobs, ref):
    """Daftar model BARU: folder yang belum punya satupun skel-nya terpasang."""
    installed = local_stems()
    new = []
    for d, info in sorted(model_dirs(blobs).items()):
        if info["stems"] & installed:
            continue
        stem = sorted(info["stems"])[0]
        cat, ch, co = ref.get(stem, (None, None, None))
        if cat is None:
            _log(f"lewati (tak terpetakan): {stem}  {d}")
            continue
        new.append({
            "stem": stem,
            "cat": cat,
            "char": ch,
            "costume": co,
            "dir": d,
            "files": sorted(info["files"]),
            "dest": dest_dir_for(stem, cat, ch, co),
        })
    return new


def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch_file(item):
    """Unduh satu blob; kembalikan (path, data|None, err)."""
    path, meta = item
    url = GH_RAW + urllib.parse.quote(path)
    try:
        data = gh_get(url, raw=True, tries=5)
    except Exception as e:  # noqa: BLE001
        return path, None, str(e)[:120]
    if meta.get("sha") and blob_sha(data) != meta["sha"]:
        return path, None, "sha tidak cocok (unduhan rusak)"
    return path, data, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah model (uji)")
    a = ap.parse_args()
    if not (a.check or a.apply):
        a.check = True

    saved = load_state()
    blobs, version = fetch_tree(saved)
    ref = build_ref(blobs)
    new = plan(blobs, ref)
    if a.limit:
        new = new[: a.limit]
    installed = len(local_stems())
    try:
        prev_files = int(saved.get("fileCount") or 0)
    except Exception:  # noqa: BLE001
        prev_files = 0
    changed = version != saved.get("version") or len(blobs) != prev_files

    _log(f"repo: {len(blobs)} berkas, {version[:10] or '?'}")
    _log(f"kamus referensi: {len(ref)} id | terpasang: {installed} skel")
    _log(f"model baru: {len(new)}")
    for m in new[:40]:
        _log(f"  BARU  {m['stem']:26s} -> {os.path.relpath(m['dest'], ROOT)}")

    result = {
        "ok": True,
        "version": version[:12] or None,
        "previous": saved.get("version", "")[:12] or None,
        "changed": changed,
        "fileCount": len(blobs),
        "total": len(ref),
        "installed": installed,
        "new": len(new),
        "ids": [m["stem"] for m in new],
    }

    if a.check or not new:
        # Simpan baseline (version + jumlah berkas) walau tak ada yang diunduh,
        # supaya `changed` pada --check berikutnya jadi false dan titik merah
        # tak menyala terus setelah model benar-benar sudah terpasang.
        if version:
            st = load_state()
            st.update({"version": version, "fileCount": len(blobs),
                       "checkedAt": int(time.time()),
                       "tree": {p: [b["size"], b["sha"]] for p, b in blobs.items()}})
            save_state(st)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    # ---- unduh + pasang -------------------------------------------------
    jobs = []  # (path, meta)
    for m in new:
        for p in m["files"]:
            size = blobs.get(p, {}).get("size", 0)
            if size > MAX_MB * 1024 * 1024 and not p.lower().endswith(".png"):
                _log(f"  lewati berkas besar ({size//1048576} MB): {p}")
                continue
            jobs.append((p, blobs[p]))

    _log(f"mengunduh {len(jobs)} berkas untuk {len(new)} model ...")
    fetched = {}
    failed = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_file, j): j for j in jobs}
        for fut in cf.as_completed(futs):
            path, data, err = fut.result()
            if data is not None:
                fetched[path] = data
            else:
                failed.append(f"{path}: {err}")
            done += 1
            if done % 25 == 0:
                _log(f"  unduh {done}/{len(jobs)} (gagal={len(failed)})")

    _log(f"unduhan selesai: ok={len(fetched)} gagal={len(failed)}")
    for f in failed[:12]:
        _log("   GAGAL " + f)

    added, skipped = 0, 0
    for m in new:
        files = [p for p in m["files"] if p in fetched]
        if not any(p.endswith(".skel") for p in files):
            skipped += 1
            continue
        os.makedirs(m["dest"], exist_ok=True)
        for p in files:
            out = os.path.join(m["dest"], os.path.basename(p))
            if os.path.exists(out) and os.path.getsize(out) == len(fetched[p]):
                continue
            tmp = out + ".part"
            with open(tmp, "wb") as f:
                f.write(fetched[p])
            os.replace(tmp, out)
        added += 1

    result.update({
        "added": added,
        "skipped": skipped,
        "failedFiles": len(failed),
        "new": 0,          # sudah dipasang -> check berikutnya bersih
        "extracted": added,
        # Id LENGKAP relatif ke assets/ — BD2 tersebar di dua root (bd2/ dan
        # bd2-char/), jadi viewer tak bisa menebak prefix-nya dari nama game.
        "new_ids": [os.path.relpath(m["dest"], ASSETS).replace(os.sep, "/")
                    for m in new if any(p.endswith(".skel") and p in fetched for p in m["files"])],
        "new_models": [m["stem"] for m in new],
    })
    os.makedirs(STATE_DIR, exist_ok=True)
    new_ids = [os.path.relpath(m["dest"], ASSETS).replace(os.sep, "/")
               for m in new if any(p.endswith(".skel") and p in fetched for p in m["files"])]
    save_state({
        "version": version,
        "fileCount": len(blobs),
        "appliedAt": int(time.time()),
        "added": added,
        "new_ids": new_ids,
        "new_models": [m["stem"] for m in new],
    })

    _log(f"=== selesai: +{added} model, lewat={skipped}, berkas gagal={len(failed)}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
