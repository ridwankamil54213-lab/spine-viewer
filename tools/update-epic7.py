#!/usr/bin/env python3
"""Pembaru aset Epic Seven dari e7codex.

Satu skrip menangani EMPAT sumber, karena semuanya berasal dari e7codex dan
harus tetap sinkron satu sama lain:

  1. lobby      assets/epic7/<id>/            units.json -> spine[]
  2. combat     assets/epic7-combat/<id>/     assets.e7codex.com/<id>/combat/
  3. skill      assets/epic7-skill/<id>_skill<n>/  units.json -> skills[]
  4. wallpaper  assets/epic7-wallpaper/<id>/  lobby_anims.json

Selain berkas model, katalog nama (assets/epic7/_names.json) dan thumbnail
(public/thumbs/epic7) ikut diperbarui — tanpa itu model baru muncul sebagai
kode mentah tanpa nama dan tanpa potret.

Mode:
  --check  bandingkan katalog daring dengan yang ada di disk, laporkan
           berapa model/berkas baru. Tidak mengunduh apa pun.
  --apply  unduh yang baru/berubah, lalu bangun ulang katalog nama +
           thumbnail untuk model yang belum punya.

Keduanya mencetak satu objek JSON ke stdout (server mem-parse-nya).

Catatan penting: /api/models memakai cache di data/models-cache.json.
Setelah --apply, jalankan /api/models?refresh=1 (atau restart layanan)
supaya model baru muncul — nama dan family dihitung saat scan, bukan saat
permintaan.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://e7codex.com"
ASSET_HOST = "https://assets.e7codex.com"
UNITS_URL = f"{BASE}/data/units.json"
LOBBY_ANIMS_URL = f"{BASE}/data/lobby_anims.json"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A_LOBBY = os.path.join(ROOT, "assets", "epic7")
A_COMBAT = os.path.join(ROOT, "assets", "epic7-combat")
A_SKILL = os.path.join(ROOT, "assets", "epic7-skill")
A_WALL = os.path.join(ROOT, "assets", "epic7-wallpaper")
THUMBS = os.path.join(ROOT, "public", "thumbs", "epic7")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": f"{BASE}/",
    "Accept": "*/*",
}

EBML = b"\x1a\x45\xdf\xa3"


def fetch(url: str, timeout: int = 120, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            time.sleep(1.5 * (attempt + 1) if e.code == 403 else 0.8 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def atlas_page(atlas_text: str) -> str | None:
    for line in atlas_text.replace("\r", "").split("\n"):
        s = line.strip()
        if s and s.lower().endswith((".png", ".webp", ".jpg")):
            return s
    return None


# --------------------------------------------------------------------------
# Perencanaan: tentukan apa yang belum ada di disk (tanpa mengunduh isi)
# --------------------------------------------------------------------------

def plan(units: list[dict], anims: list[dict]) -> dict:
    lobby, combat, skill, wall = [], [], [], []

    for u in units:
        uid = u.get("id")
        if not uid:
            continue
        # Lobby: satu berkas .json per model.
        if u.get("spine") and not os.path.isfile(os.path.join(A_LOBBY, uid, f"{uid}.json")):
            lobby.append(u)
        # Combat: hanya yang ditandai has_combat.
        if u.get("has_combat") and not os.path.isfile(os.path.join(A_COMBAT, uid, f"{uid}.json")):
            combat.append(u)
        # Skill: satu berkas per entri skills[].
        for path in u.get("skills") or []:
            base = os.path.basename(path)
            num = os.path.splitext(base)[0].rsplit("_", 1)[-1]
            d = os.path.join(A_SKILL, f"{uid}_skill{num}")
            if not os.path.isfile(os.path.join(d, base)):
                skill.append({"id": uid, "url": f"{BASE}/{path}", "folder": f"{uid}_skill{num}", "file": base})

    for a in anims:
        aid = a.get("id")
        if aid and not os.path.isfile(os.path.join(A_WALL, aid, f"{aid}.webm")):
            wall.append(a)

    return {"lobby": lobby, "combat": combat, "skill": skill, "wallpaper": wall}


# --------------------------------------------------------------------------
# Pengunduhan
# --------------------------------------------------------------------------

def dl_lobby(u: dict) -> dict:
    uid = u["id"]
    sp = (u.get("spine") or [{}])[0]
    d = os.path.join(A_LOBBY, uid)
    os.makedirs(d, exist_ok=True)
    try:
        atlas = fetch(f"{BASE}/{sp['atlas']}")
        skel = fetch(f"{BASE}/{sp['json']}")
        open(os.path.join(d, f"{uid}.atlas"), "wb").write(atlas)
        open(os.path.join(d, f"{uid}.json"), "wb").write(skel)
        page = atlas_page(atlas.decode("utf8", "replace"))
        if page:
            open(os.path.join(d, page), "wb").write(fetch(f"{BASE}/assets/{uid}/{page}"))
        return {"id": uid, "ok": True, "src": "lobby"}
    except Exception as e:  # noqa: BLE001
        return {"id": uid, "ok": False, "src": "lobby", "err": str(e)[:100]}


def dl_combat(u: dict) -> dict:
    uid = u["id"]
    d = os.path.join(A_COMBAT, uid)
    os.makedirs(d, exist_ok=True)
    try:
        atlas = fetch(f"{ASSET_HOST}/{uid}/combat/{uid}.atlas")
        skel = fetch(f"{ASSET_HOST}/{uid}/combat/{uid}.json")
        open(os.path.join(d, f"{uid}.atlas"), "wb").write(atlas)
        open(os.path.join(d, f"{uid}.json"), "wb").write(skel)
        page = atlas_page(atlas.decode("utf8", "replace"))
        if page:
            open(os.path.join(d, page), "wb").write(fetch(f"{ASSET_HOST}/{uid}/combat/{page}"))
        return {"id": uid, "ok": True, "src": "combat"}
    except Exception as e:  # noqa: BLE001
        return {"id": uid, "ok": False, "src": "combat", "err": str(e)[:100]}


def dl_skill(j: dict) -> dict:
    d = os.path.join(A_SKILL, j["folder"])
    os.makedirs(d, exist_ok=True)
    try:
        data = fetch(j["url"])
        if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            return {"id": j["folder"], "ok": False, "src": "skill", "err": "bukan WEBP"}
        open(os.path.join(d, j["file"]), "wb").write(data)
        return {"id": j["folder"], "ok": True, "src": "skill"}
    except Exception as e:  # noqa: BLE001
        return {"id": j["folder"], "ok": False, "src": "skill", "err": str(e)[:100]}


def dl_wall(a: dict) -> dict:
    aid = a["id"]
    d = os.path.join(A_WALL, aid)
    os.makedirs(d, exist_ok=True)
    try:
        data = fetch(f"{ASSET_HOST}/{a['video']}", timeout=600)
        if data[:4] != EBML:
            return {"id": aid, "ok": False, "src": "wallpaper", "err": "bukan WebM"}
        open(os.path.join(d, f"{aid}.webm"), "wb").write(data)
        return {"id": aid, "ok": True, "src": "wallpaper"}
    except Exception as e:  # noqa: BLE001
        return {"id": aid, "ok": False, "src": "wallpaper", "err": str(e)[:100]}


def run_jobs(jobs: list, fn, workers: int, label: str) -> list[dict]:
    out: list[dict] = []
    if not jobs:
        return out
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(fn, j) for j in jobs]
        for f in as_completed(futs):
            out.append(f.result())
            done += 1
            if done % 5 == 0 or done == len(jobs):
                # stderr: itulah yang dialirkan server ke panel log.
                print(f"  {label}: {done}/{len(jobs)}", file=sys.stderr, flush=True)
    return out


# --------------------------------------------------------------------------
# Katalog nama + thumbnail
# --------------------------------------------------------------------------

ROLE_LABEL = {
    "knight": "Knight", "ranger": "Ranger", "mage": "Mage",
    "assassin": "Assassin", "warrior": "Warrior", "manauser": "Manauser",
}
ATTR_LABEL = {"fire": "Fire", "ice": "Ice", "wind": "Wind", "light": "Light", "dark": "Dark"}


def rebuild_names(units: list[dict]) -> int:
    """Tulis ulang _names.json — sama bentuknya dengan fetch-e7codex-meta.py."""
    catalog = {}
    for x in units:
        uid = x.get("id")
        if not uid:
            continue
        name = (x.get("hero_name") or x.get("name") or uid).strip()
        rec: dict = {"kind": x.get("kind") or "unit", "name": name}
        hero = (x.get("hero_name") or "").strip()
        if hero and hero != name:
            rec["hero"] = hero
        rar = x.get("rarity")
        if isinstance(rar, int) and rar > 0:
            rec["rarity"] = "★" * min(rar, 6)
            rec["rarityNum"] = rar
        if x.get("attribute"):
            rec["element"] = ATTR_LABEL.get(x["attribute"], x["attribute"].title())
        if x.get("role"):
            rec["class"] = ROLE_LABEL.get(x["role"], x["role"].title())
        if x.get("slug"):
            rec["slug"] = x["slug"]
        if x.get("released"):
            rec["released"] = x["released"]
        if x.get("has_combat"):
            rec["combat"] = True
        catalog[uid] = rec
    os.makedirs(A_LOBBY, exist_ok=True)
    with open(os.path.join(A_LOBBY, "_names.json"), "w") as f:
        json.dump(catalog, f, indent=1, ensure_ascii=False, sort_keys=True)
    return len(catalog)


def fetch_thumbs(units: list[dict], workers: int) -> int:
    """Unduh thumb.png untuk model yang foldernya ada tapi potretnya belum."""
    os.makedirs(THUMBS, exist_ok=True)
    todo = []
    for u in units:
        uid = u.get("id")
        if not uid or not u.get("thumb"):
            continue
        if not os.path.isdir(os.path.join(A_LOBBY, uid)):
            continue
        if os.path.isfile(os.path.join(THUMBS, f"{uid}.png")):
            continue
        todo.append(u)
    if not todo:
        return 0

    def one(u: dict) -> bool:
        uid = u["id"]
        try:
            data = fetch(f"{BASE}/{u['thumb']}", timeout=120)
            if data[:4] != b"\x89PNG":
                return False
            open(os.path.join(THUMBS, f"{uid}.png"), "wb").write(data)
            return True
        except Exception:  # noqa: BLE001
            return False

    ok = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(one, todo):
            ok += 1 if r else 0
    # Manifest dibaca server; tanpa ini thumbnail baru tidak akan tampil.
    manifest_path = os.path.join(THUMBS, "_manifest.json")
    man = {}
    if os.path.isfile(manifest_path):
        try:
            man = json.load(open(manifest_path))
        except Exception:  # noqa: BLE001
            man = {}
    for f in os.listdir(THUMBS):
        if f.endswith(".png") and f != "_manifest.json":
            man[f"epic7/{f[:-4]}"] = f
    json.dump(man, open(manifest_path, "w"), indent=1)
    return ok


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah unduhan (uji)")
    a = ap.parse_args()

    t0 = time.time()
    print("mengambil katalog e7codex…", file=sys.stderr, flush=True)
    try:
        units = json.loads(fetch(UNITS_URL))
        anims = json.loads(fetch(LOBBY_ANIMS_URL))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"gagal mengambil katalog: {e}"}, indent=1))
        return 1

    p = plan(units, anims)
    total_new = sum(len(v) for v in p.values())

    if not a.apply:
        res = {
            "ok": True,
            "mode": "check",
            "katalog": {"unit": len(units), "wallpaper": len(anims)},
            "new": total_new,
            "detail": {k: len(v) for k, v in p.items()},
            "contoh": {k: [x.get("id") or x.get("folder") for x in v[:5]] for k, v in p.items() if v},
            "seconds": round(time.time() - t0, 1),
        }
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0

    # --- apply ---
    jobs = []
    for u in p["lobby"]:
        jobs.append((dl_lobby, u))
    for u in p["combat"]:
        jobs.append((dl_combat, u))
    for j in p["skill"]:
        jobs.append((dl_skill, j))
    for w in p["wallpaper"]:
        jobs.append((dl_wall, w))
    if a.limit:
        jobs = jobs[: a.limit]

    results: list[dict] = []
    for fn, label in ((dl_lobby, "lobby"), (dl_combat, "combat"), (dl_skill, "skill")):
        subset = [j for f, j in jobs if f is fn]
        results += run_jobs(subset, fn, a.workers, label)
    # Wallpaper dijalankan sendiri: berkasnya besar (sampai 186 MB), jadi
    # paralelisme kecil supaya tidak menghabiskan bandwidth.
    subset = [j for f, j in jobs if f is dl_wall]
    results += run_jobs(subset, dl_wall, max(2, a.workers // 3), "wallpaper")

    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]

    # Katalog nama + thumbnail selalu dibangun ulang: murah, dan model baru
    # tanpa nama/potret akan terlihat seperti data mentah.
    print("membangun ulang katalog nama…", file=sys.stderr, flush=True)
    named = rebuild_names(units)
    print("memeriksa thumbnail…", file=sys.stderr, flush=True)
    thumbs = fetch_thumbs(units, a.workers)

    res = {
        "ok": not bad,
        "mode": "apply",
        "new": len(ok),
        "gagal": len(bad),
        "detail": {k: len(v) for k, v in p.items()},
        "names": named,
        "thumbs": thumbs,
        "errors": [f"{r['src']}/{r['id']}: {r.get('err','')}" for r in bad[:15]],
        "seconds": round(time.time() - t0, 1),
        "catatan": "jalankan /api/models?refresh=1 agar model baru muncul di pustaka",
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
