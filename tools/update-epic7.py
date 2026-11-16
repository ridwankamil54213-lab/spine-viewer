#!/usr/bin/env python3
"""Satu pembaru untuk seluruh aset Epic Seven dari e7codex.com.

Empat sumber, semuanya dari host yang sama dan harus tetap sinkron:

  1. lobby      assets/epic7/<id>/           units.json -> spine[]
  2. combat     assets/epic7-combat/<id>/    assets.e7codex.com/<id>/combat/
  3. skill      assets/epic7-skill/<id>_skill<n>/  units.json -> skills[]
  4. wallpaper  assets/epic7-wallpaper/<id>/ lobby_anims.json

Selain berkas model, katalog nama (assets/epic7/_names.json) dan thumbnail
(public/thumbs/epic7) ikut diperbarui — tanpa itu model baru muncul sebagai
kode mentah tanpa nama dan tanpa potret.

Kontrak server (lihat runUpdater / UPDATERS.epic7 di src/server.js):
  --check : cepat, TANPA mengunduh aset. Bandingkan tanda tangan katalog
            daring + isi disk terhadap data/epic7-update-state.json. Cetak
            JSON ke stdout, progres ke stderr.
  --apply : unduh yang belum lengkap, bangun ulang _names.json + thumbnail,
            lalu simpan state baru. cfg.rescan:true membuat /api/models
            dipindai ulang otomatis tanpa perlu refresh manual.

Thumbnail dari e7codex berukuran 2075x3120 / ~4,4 MB per potret. Untuk 855
model itu ~3,4 GB yang harus dikirim ke galeri, jadi dinormalisasi ffmpeg ke
lebar 300 px (proporsi dipertahankan). Sengaja TANPA Pillow: interpreter
systemd (/usr/bin/python3) tidak memilikinya; ffmpeg sudah ada dan dipakai
server untuk export. Kalau ffmpeg gagal, berkas asli tetap disimpan.

Kelengkapan model dicek dari tiga berkas (json + atlas + halaman tekstur),
bukan cuma .json: dulu kalau unduhan halaman atlas gagal, model dianggap
sudah ada selamanya dan tidak pernah dicoba ulang.

Usage:
    python3 tools/update-epic7.py --check
    python3 tools/update-epic7.py --apply [--workers 6] [--limit 20]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://e7codex.com"
ASSET_HOST = "https://assets.e7codex.com"
UNITS_URL = f"{BASE}/data/units.json"
LOBBY_ANIMS_URL = f"{BASE}/data/lobby_anims.json"
THUMB_WIDTH = 300

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A_LOBBY = os.environ.get("E7_LOBBY", os.path.join(ROOT, "assets", "epic7"))
A_COMBAT = os.environ.get("E7_COMBAT", os.path.join(ROOT, "assets", "epic7-combat"))
A_SKILL = os.environ.get("E7_SKILL", os.path.join(ROOT, "assets", "epic7-skill"))
A_WALL = os.environ.get("E7_WALL", os.path.join(ROOT, "assets", "epic7-wallpaper"))
THUMBS = os.environ.get("E7_THUMBS", os.path.join(ROOT, "public", "thumbs", "epic7"))
STATE = os.environ.get("E7_STATE", os.path.join(ROOT, "data", "epic7-update-state.json"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": f"{BASE}/",
    "Accept": "*/*",
}

EBML = b"\x1a\x45\xdf\xa3"
IMG_EXT = (".png", ".webp", ".jpg")


class NotFound(Exception):
    """Sumber memang tidak punya berkas ini (404), jangan diulang."""


def fetch(url: str, timeout: int = 120, retries: int = 3) -> bytes:
    """Ambil URL lewat curl, bukan urllib.

    curl menangani tantangan Cloudflare e7codex jauh lebih konsisten
    (0,1 dtk vs 5–33 dtk stall pada urllib). Kode status diambil dari
    -w '%{http_code}' sementara body ditulis ke berkas sementara, supaya
    404 bisa dibedakan dari 403/429 yang memang perlu diulang.
    """
    curl = shutil.which("curl") or "/usr/bin/curl"
    last = None
    for attempt in range(retries):
        fd, tmp = tempfile.mkstemp(prefix="e7dl-", suffix=".bin")
        os.close(fd)
        try:
            p = subprocess.run(
                [curl, "-sSL", "--max-time", str(timeout),
                 "-A", HEADERS["User-Agent"],
                 "-H", f"Referer: {HEADERS['Referer']}",
                 "-o", tmp, "-w", "%{http_code}", url],
                capture_output=True, timeout=timeout + 20,
            )
            code = (p.stdout or b"").strip().decode("ascii", "replace")
            if p.returncode == 0 and code.startswith("2"):
                with open(tmp, "rb") as f:
                    return f.read()
            if code == "404":
                raise NotFound(url)
            last = f"HTTP {code} rc={p.returncode} {(p.stderr or b'')[:120]!r}"
        except NotFound:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        # 403/429 = rate limit Cloudflare: beri jeda lebih panjang.
        time.sleep(1.5 * (attempt + 1) if ("403" in str(last) or "429" in str(last))
                   else 0.8 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def atlas_page(atlas_text: str) -> str | None:
    for line in atlas_text.replace("\r", "").split("\n"):
        s = line.strip()
        if s and s.lower().endswith(IMG_EXT):
            return s
    return None


# --------------------------------------------------------------------------
# State: deteksi katalog baru/berubah, bukan cuma berkas yang hilang
# --------------------------------------------------------------------------

def signature(units_raw: bytes, anims_raw: bytes) -> dict:
    return {
        "units": hashlib.sha256(units_raw).hexdigest()[:16],
        "anims": hashlib.sha256(anims_raw).hexdigest()[:16],
    }


def disk_counts() -> dict:
    def n(p: str, suffixes: tuple[str, ...]) -> int:
        if not os.path.isdir(p):
            return 0
        c = 0
        for _, _, files in os.walk(p):
            c += sum(1 for f in files if f.lower().endswith(suffixes))
        return c

    return {
        "lobby": n(A_LOBBY, (".json", ".atlas") + IMG_EXT),
        "combat": n(A_COMBAT, (".json", ".atlas") + IMG_EXT),
        "skill": n(A_SKILL, (".webp",)),
        "wall": n(A_WALL, (".webm",)),
        "thumbs": n(THUMBS, (".png",)),
    }


def load_state() -> dict | None:
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def save_state(sig: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    payload = {
        "sig": sig,
        "disk": disk_counts(),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(STATE, "w") as f:
        json.dump(payload, f, indent=1)


def spine_complete(d: str, uid: str) -> bool:
    """Model Spine lengkap = skeleton + atlas + minimal satu halaman tekstur."""
    if not (os.path.isfile(os.path.join(d, f"{uid}.json"))
            and os.path.isfile(os.path.join(d, f"{uid}.atlas"))):
        return False
    try:
        return any(f.lower().endswith(IMG_EXT) for f in os.listdir(d))
    except OSError:
        return False


# --------------------------------------------------------------------------
# Perencanaan: tentukan apa yang belum lengkap di disk (tanpa mengunduh isi)
# --------------------------------------------------------------------------

def plan(units: list[dict], anims: list[dict]) -> dict:
    lobby, combat, skill, wall = [], [], [], []

    for u in units:
        uid = u.get("id")
        if not uid:
            continue
        if u.get("spine") and not spine_complete(os.path.join(A_LOBBY, uid), uid):
            lobby.append(u)
        if u.get("has_combat") and not spine_complete(os.path.join(A_COMBAT, uid), uid):
            combat.append(u)
        for path in u.get("skills") or []:
            base = os.path.basename(path)
            num = os.path.splitext(base)[0].rsplit("_", 1)[-1]
            d = os.path.join(A_SKILL, f"{uid}_skill{num}")
            if not os.path.isfile(os.path.join(d, base)):
                skill.append({"id": uid, "url": f"{BASE}/{path}",
                              "folder": f"{uid}_skill{num}", "file": base})

    for a in anims:
        aid = a.get("id")
        if aid and not os.path.isfile(os.path.join(A_WALL, aid, f"{aid}.webm")):
            wall.append(a)

    return {"lobby": lobby, "combat": combat, "skill": skill, "wallpaper": wall}


# --------------------------------------------------------------------------
# Pengunduhan
# --------------------------------------------------------------------------

def _dl_spine(uid: str, urls: tuple[str, str, str | None], d: str, src: str) -> dict:
    """Unduh atlas + skeleton + halaman tekstur, lalu validasi kelengkapan."""
    os.makedirs(d, exist_ok=True)
    atlas_url, skel_url, page_url = urls
    try:
        atlas = fetch(atlas_url)
        skel = fetch(skel_url)
        with open(os.path.join(d, f"{uid}.atlas"), "wb") as f:
            f.write(atlas)
        with open(os.path.join(d, f"{uid}.json"), "wb") as f:
            f.write(skel)
        page = atlas_page(atlas.decode("utf8", "replace"))
        if page:
            if not page_url:
                raise RuntimeError("halaman atlas tanpa URL dasar")
            data = fetch(f"{page_url}/{page}")
            with open(os.path.join(d, page), "wb") as f:
                f.write(data)
        ok = spine_complete(d, uid)
        return {"id": uid, "ok": ok, "src": src,
                "err": "" if ok else "berkas tidak lengkap"}
    except Exception as e:  # noqa: BLE001
        return {"id": uid, "ok": False, "src": src, "err": str(e)[:120]}


def dl_lobby(u: dict) -> dict:
    uid = u["id"]
    sp = (u.get("spine") or [{}])[0]
    return _dl_spine(
        uid,
        (f"{BASE}/{sp['atlas']}", f"{BASE}/{sp['json']}", f"{BASE}/assets/{uid}"),
        os.path.join(A_LOBBY, uid), "lobby",
    )


def dl_combat(u: dict) -> dict:
    uid = u["id"]
    return _dl_spine(
        uid,
        (f"{ASSET_HOST}/{uid}/combat/{uid}.atlas",
         f"{ASSET_HOST}/{uid}/combat/{uid}.json",
         f"{ASSET_HOST}/{uid}/combat"),
        os.path.join(A_COMBAT, uid), "combat",
    )


def dl_skill(j: dict) -> dict:
    d = os.path.join(A_SKILL, j["folder"])
    os.makedirs(d, exist_ok=True)
    try:
        data = fetch(j["url"])
        if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            return {"id": j["folder"], "ok": False, "src": "skill", "err": "bukan WEBP"}
        with open(os.path.join(d, j["file"]), "wb") as f:
            f.write(data)
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
        with open(os.path.join(d, f"{aid}.webm"), "wb") as f:
            f.write(data)
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
            if done % 25 == 0 or done == len(jobs):
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
    """Unduh thumb.png, perkecil ke 300 px, lalu perbarui _manifest.json."""
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
        dest = os.path.join(THUMBS, f"{uid}.png")
        fd, tmp = tempfile.mkstemp(suffix=".png", dir=THUMBS)
        os.close(fd)
        try:
            data = fetch(f"{BASE}/{u['thumb']}", timeout=180)
            if data[:8] != b"\x89PNG\r\n\x1a\n":
                return False
            with open(tmp, "wb") as f:
                f.write(data)
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                     "-vf", f"scale={THUMB_WIDTH}:-2", "-frames:v", "1",
                     "-update", "1", dest],
                    check=True, capture_output=True, timeout=120,
                )
            except Exception:  # noqa: BLE001 - ffmpeg gagal: simpan apa adanya
                with open(dest, "wb") as f:
                    f.write(data)
            # Jangan sampai berkas 0 byte bikin unduhan berikutnya dilewati.
            if not os.path.isfile(dest) or os.path.getsize(dest) < 512:
                with open(dest, "wb") as f:
                    f.write(data)
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    ok = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(one, todo):
            ok += 1 if r else 0
    # Manifest dibaca server; tanpa ini thumbnail baru tidak akan tampil.
    manifest_path = os.path.join(THUMBS, "_manifest.json")
    man = {}
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path) as f:
                man = json.load(f)
        except Exception:  # noqa: BLE001
            man = {}
    for f in os.listdir(THUMBS):
        if f.endswith(".png") and f != "_manifest.json":
            man[f"epic7/{f[:-4]}"] = f
    with open(manifest_path, "w") as f:
        json.dump(man, f, indent=1)
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
        units_raw = fetch(UNITS_URL, timeout=30)
        anims_raw = fetch(LOBBY_ANIMS_URL, timeout=30)
        units = json.loads(units_raw)
        anims = json.loads(anims_raw)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"gagal mengambil katalog: {e}"}, indent=1))
        return 1

    sig = signature(units_raw, anims_raw)
    p = plan(units, anims)
    total_new = sum(len(v) for v in p.values())
    state = load_state()

    if not a.apply:
        alasan = []
        if state is None:
            if total_new:
                alasan.append("data E7 belum ada di disk")
            # Bootstrap: catat kondisi sekarang sebagai baseline.
            save_state(sig)
        else:
            if state.get("sig") != sig:
                alasan.append("katalog e7codex berubah")
            if state.get("disk") != disk_counts():
                alasan.append("isi disk berubah")
        if total_new:
            alasan.append(f"{total_new} berkas belum lengkap")
        res = {
            "ok": True,
            "mode": "check",
            "changed": bool(alasan),
            "alasan": alasan,
            "katalog": {"unit": len(units), "wallpaper": len(anims)},
            "new": total_new,
            "detail": {k: len(v) for k, v in p.items()},
            "contoh": {k: [x.get("id") or x.get("folder") for x in v[:5]]
                       for k, v in p.items() if v},
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

    good = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    # Rig lobby adalah inti pustaka; sisanya (combat/skill/wallpaper) bersifat
    # pelengkap/varian. Kegagalan pelengkap jangan menghalangi rescan model.
    critical = [r for r in bad if r["src"] == "lobby"]

    # Katalog nama + thumbnail selalu dibangun ulang: murah, dan model baru
    # tanpa nama/potret akan terlihat seperti data mentah.
    print("membangun ulang katalog nama…", file=sys.stderr, flush=True)
    named = rebuild_names(units)
    print("memeriksa thumbnail…", file=sys.stderr, flush=True)
    thumbs = fetch_thumbs(units, a.workers)
    save_state(sig)

    res = {
        "ok": not critical,
        "mode": "apply",
        "new": len(good),
        "gagal": len(bad),
        "katalog": {"unit": len(units), "wallpaper": len(anims)},
        "detail": {k: len(v) for k, v in p.items()},
        "names": named,
        "thumbs": thumbs,
        "errors": [f"{r['src']}/{r['id']}: {r.get('err','')}" for r in critical[:15]],
        "warnings": [f"{r['src']}/{r['id']}: {r.get('err','')}"
                     for r in bad if r["src"] != "lobby"][:15],
        "seconds": round(time.time() - t0, 1),
        "catatan": "server memindai ulang /api/models otomatis (cfg.rescan)",
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if not critical else 1


if __name__ == "__main__":
    sys.exit(main())
