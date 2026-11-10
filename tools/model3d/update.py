#!/usr/bin/env python3
"""Ambil model 3D Stella Sora (.glb) dan bangun metadata viewer.

Sumber: StellaSoraWiki/StellaSoraModels (GitHub, public). Per karakter:

    <Nama>/<Nama>.glb                  mesh + skin + tekstur, TANPA clip
    <Nama>/<Nama>.anims.json           daftar clip (nama, file, duration, loop)
    <Nama>/<Nama>_anims/<Clip>.glb     AnimationClip terpisah (tanpa mesh)

Keluaran (semua deterministik, tanpa login / API key):

    assets/stellasora-3d/<id>/model.glb
    assets/stellasora-3d/<id>/anims/<Clip>.glb   (maks 3 per model)
    assets/stellasora-3d/<id>/_meta.json
    data/stellasora-3d-names.json               nama karakter + variant
    data/stellasora-3d-family.json              varian kostum per karakter
    public/thumbs/stellasora-3d/_manifest.json  + WebP ilustrasi (bukan atlas)
    public/thumbs/_game/stellasora-3d.png

Thumbnail sengaja memakai **ilustrasi 2D karakter** yang sudah ada di
public/thumbs/stellasora/ (hasil portrait AVG), dipetakan lewat
data/stellasora-l2d-names.json — bukan potongan atlas, bukan render 3D.

Mode:
    --check              bandingkan tree remote dengan state lokal
    --apply              unduh yang belum ada + regenerasi metadata
    --apply --offline    regenerasi metadata dari aset yang sudah ada
    --limit N            batasi jumlah model (untuk percobaan)
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.environ.get("M3D_ASSETS", os.path.join(ROOT, "assets", "stellasora-3d"))
THUMBS = os.environ.get("M3D_THUMBS", os.path.join(ROOT, "public", "thumbs", "stellasora-3d"))
GAME_ICON = os.path.join(ROOT, "public", "thumbs", "_game", "stellasora-3d.png")
L2D_THUMBS = os.path.join(ROOT, "public", "thumbs", "stellasora")
NAMES_OUT = os.path.join(ROOT, "data", "stellasora-3d-names.json")
FAMILY_OUT = os.path.join(ROOT, "data", "stellasora-3d-family.json")
L2D_NAMES = os.path.join(ROOT, "data", "stellasora-l2d-names.json")
CACHE = os.environ.get("M3D_CACHE", "/srv/spine-assets/stellasora-3d")
STATE = os.path.join(CACHE, "state.json")
TREE_CACHE = os.path.join(CACHE, "tree.json")

REPO = "StellaSoraWiki/StellaSoraModels"
TREE_API = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
UA = {"User-Agent": "spine-viewer/1.0 (+self-hosted asset mirror)"}
WORKERS = 10
MAX_CLIPS = 3
SAFE = re.compile(r"[^a-z0-9_.-]+")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def http_get(url, tries=3, timeout=90):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            last = exc
            time.sleep(1 + i)
    raise RuntimeError(f"{url}: {last}")


def tree(offline=False):
    if offline and os.path.exists(TREE_CACHE):
        return json.load(open(TREE_CACHE, encoding="utf-8"))["tree"]
    raw = http_get(TREE_API)
    data = json.loads(raw)
    if not isinstance(data.get("tree"), list):
        raise RuntimeError(f"tree GitHub tidak valid: {str(data)[:160]}")
    os.makedirs(CACHE, exist_ok=True)
    with open(TREE_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data["tree"]


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(d):
    os.makedirs(CACHE, exist_ok=True)
    tmp = STATE + ".part"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, STATE)


def safe(s):
    return SAFE.sub("_", s.lower()).strip("_") or "model"


def model_id(folder, stem):
    """Id ASCII: karakter + '__' + nama skin kalau ada."""
    tail = stem[len(folder) + 1:] if stem.startswith(folder + "_") else ""
    return safe(folder + ("__" + tail if tail else ""))


def parse_variant(folder, stem):
    tail = stem[len(folder) + 1:] if stem.startswith(folder + "_") else ""
    # Empat nama kostum ber-prefix: Firstlight_Noya -> Noya / "Firstlight".
    for pref in ("Firstlight_", "Snowish_", "Springseek_", "Suntide_"):
        if folder.startswith(pref):
            char = folder[len(pref):]
            return char, (pref[:-1] + (" — " + tail.replace("_", " ") if tail else "")), tail
    char = folder
    variant = tail.replace("_", " ").strip() if tail else "Default"
    return char, variant, tail


def clip_score(c):
    n = str(c.get("name", "")).lower()
    pts = 0
    if any(k in n for k in ("idle", "stand", "wait", "breath", "lobby", "relax")):
        pts += 100
    elif n.startswith("attack"):
        pts += 60
    elif any(k in n for k in ("skill", "win", "run", "move", "walk")):
        pts += 40
    if c.get("loop"):
        pts += 20
    if c.get("face"):
        pts -= 10
    return -pts  # urut menaik = prioritas tertinggi lebih dulu


def local_folders():
    if not os.path.isdir(ASSETS):
        return []
    return sorted(d for d in os.listdir(ASSETS)
                  if os.path.isfile(os.path.join(ASSETS, d, "model.glb")))


def check(offline=False):
    t = tree(offline)
    main = sorted(x["path"] for x in t
                  if x["path"].endswith(".glb") and x["path"].count("/") == 1)
    by_size = {x["path"]: x.get("size") for x in t}
    sig = hashlib.sha1("|".join(
        f"{p}:{by_size.get(p)}" for p in main).encode()).hexdigest()[:12]
    st = load_state()
    have = len(local_folders())
    new = max(0, len(main) - have)
    return {
        "ok": True,
        "version": sig,
        "previous": st.get("version"),
        "changed": bool(new) or st.get("version") != sig,
        "expected": len(main),
        "have": have,
        "new": new,
        "source": REPO,
        "animLimit": MAX_CLIPS,
    }


def illustration_map():
    """character (lowercase) -> nama berkas WebP ilustrasi 2D."""
    out = {}
    try:
        names = json.load(open(L2D_NAMES, encoding="utf-8"))
        manifest = json.load(open(os.path.join(L2D_THUMBS, "_manifest.json"),
                                 encoding="utf-8"))
    except Exception:
        return out
    for folder, rec in names.items():
        char = (rec.get("character") or "").strip()
        f = manifest.get("stellasora-l2d/" + folder)
        if char and f:
            out.setdefault(char.lower(), f)
    return out


def build_metadata(entries, illus):
    """Tulis names/family/thumbnail dari folder aset yang sudah ada."""
    os.makedirs(THUMBS, exist_ok=True)
    names = {}
    families_by_char = {}
    manifest = {}
    for e in entries:
        mid = "stellasora-3d/" + e["id"]
        char = e["character"]
        variant = e["variant"]
        names[e["id"]] = {
            "name": f"{char} — {variant}" if variant != "Default" else char,
            "character": char,
            "variant": variant,
            "source": f"{REPO} · ilustrasi Stella Sora AVG",
            "charId": e.get("charId"),
        }
        families_by_char.setdefault(char, []).append({"id": mid, "label": variant})
        f = illus.get(char.lower())
        if f and os.path.isfile(os.path.join(L2D_THUMBS, f)):
            src = os.path.join(L2D_THUMBS, f)
            dst = os.path.join(THUMBS, f)
            if not os.path.exists(dst):
                shutil.copyfile(src, dst)
            manifest[mid] = f
    families = []
    for char, members in sorted(families_by_char.items()):
        if len(members) < 2:
            continue
        members.sort(key=lambda m: (m["label"] != "Default", m["label"]))
        root = next((m["id"] for m in members if m["label"] == "Default"), members[0]["id"])
        families.append({"root": root, "name": char, "members": members})

    with open(NAMES_OUT, "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(FAMILY_OUT, "w", encoding="utf-8") as f:
        json.dump({"families": families}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(THUMBS, "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)

    # Ikon game dari ilustrasi pertama yang tersedia (bukan tangkapan 3D).
    try:
        from PIL import Image, ImageDraw
        src = next((os.path.join(THUMBS, v) for v in manifest.values()
                    if os.path.isfile(os.path.join(THUMBS, v))), None)
        if src:
            im = Image.open(src).convert("RGBA")
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w - s) // 2, 0, (w + s) // 2, s)).resize((128, 128), Image.Resampling.LANCZOS)
            mask = Image.new("L", (128, 128), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, 127, 127), radius=20, fill=255)
            im.putalpha(mask)
            os.makedirs(os.path.dirname(GAME_ICON), exist_ok=True)
            im.save(GAME_ICON)
    except Exception as exc:
        log(f"ikon game dilewati: {exc}")
    return names, families, manifest


def apply_update(offline=False, limit=0):
    t = tree(offline)
    sizes = {x["path"]: x.get("size", 0) for x in t}
    main = sorted(x["path"] for x in t
                  if x["path"].endswith(".glb") and x["path"].count("/") == 1)
    all_main = main[:]
    anims_json = {x["path"]: True for x in t if x["path"].endswith(".anims.json")}
    if limit:
        main = main[:limit]

    illus = illustration_map()
    entries = []
    downloads = []

    def want(dest, url, expected):
        if os.path.isfile(dest) and (not expected or os.path.getsize(dest) == expected):
            return False
        downloads.append((dest, url, expected))
        return True

    for p in main:
        folder, fname = p.split("/", 1)
        stem = fname[:-4]
        mid = model_id(folder, stem)
        model_dest = os.path.join(ASSETS, mid, "model.glb")
        want(model_dest, RAW + p, sizes.get(p, 0))

        # Mode offline tidak bisa mengambil .anims.json; pakai _meta.json
        # lama supaya charId / daftar clip tidak hilang saat regenerasi.
        meta = {}
        try:
            meta = json.load(open(os.path.join(ASSETS, mid, "_meta.json"), encoding="utf-8"))
        except Exception:
            meta = {}
        meta.update({"id": mid, "source": REPO})
        meta.setdefault("character", folder.replace("_", " "))
        meta.setdefault("variant", "Default")
        meta.setdefault("charId", None)
        meta.setdefault("clips", [])
        char, variant, tail = parse_variant(folder, stem)
        meta["character"], meta["variant"] = char, variant
        meta["name"] = f"{char} — {variant}" if variant != "Default" else char

        aj = f"{folder}/{stem}.anims.json"
        if aj in anims_json and not offline:
            try:
                doc = json.loads(http_get(RAW + aj, timeout=30))
                meta["charId"] = str(doc.get("id") or "") or None
                clips = sorted(doc.get("clips") or [], key=clip_score)[:MAX_CLIPS]
                for c in clips:
                    cf = c.get("file") or ""
                    cn = c.get("name") or os.path.basename(cf)[:-4]
                    if not cf:
                        continue
                    dest = os.path.join(ASSETS, mid, "anims", safe(cn) + ".glb")
                    want(dest, RAW + cf, sizes.get(cf, 0))
                    meta["clips"].append({"name": cn, "file": safe(cn) + ".glb",
                                          "duration": c.get("duration")})
            except Exception as exc:
                log(f"clip {mid}: {str(exc)[:70]} (dilewati)")
        entries.append(meta)

    log(f"{len(downloads)} berkas perlu diunduh dari {len(main)} model")
    done = skipped = failed = 0

    def fetch(item):
        dest, url, expected = item
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            raw = http_get(url)
            if expected and len(raw) != expected:
                raise RuntimeError(f"ukuran {len(raw)} != {expected}")
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, dest)
            return "ok"
        except Exception as exc:
            log(f"GAGAL {url}: {str(exc)[:90]}")
            return "fail"

    if not offline and downloads:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for state_ in ex.map(fetch, downloads):
                done += state_ == "ok"
                failed += state_ == "fail"
    else:
        skipped = len(downloads)

    # _meta.json hanya untuk folder yang benar-benar punya model.glb.
    installed = []
    for e in entries:
        d = os.path.join(ASSETS, e["id"])
        if not os.path.isfile(os.path.join(d, "model.glb")):
            continue
        with open(os.path.join(d, "_meta.json"), "w", encoding="utf-8") as f:
            json.dump(e, f, ensure_ascii=False, indent=1)
        installed.append(e)

    names, families, manifest = build_metadata(installed, illus)
    sig = hashlib.sha1("|".join(
        f"{p}:{sizes.get(p)}" for p in all_main).encode()).hexdigest()[:12]
    save_state({"version": sig, "models": [e["id"] for e in installed],
                "appliedAt": int(time.time())})
    return {
        "ok": True, "version": sig,
        "expected": len(main), "installed": len(installed),
        "downloaded": done, "skipped": skipped, "failed": failed,
        "names": len(names), "families": len(families),
        "thumbs": len(set(manifest.values())), "thumbKeys": len(manifest),
        "new_ids": ["stellasora-3d/" + e["id"] for e in installed],
        "source": REPO, "animLimit": MAX_CLIPS,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.apply:
        print(json.dumps(apply_update(offline=a.offline, limit=a.limit), indent=1))
    elif a.check:
        print(json.dumps(check(offline=a.offline), indent=1))
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
