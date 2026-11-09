#!/usr/bin/env python3
"""Sinkronkan Make Drama dari https://mad.altterisk.cc/viewer/.

Menggantikan pipeline lama yang bergantung pada clone git
/opt/re-targets/mad-viewer (git fetch + merge). Sumbernya sekarang LIVE:

  /data/skin_list.json    145 skin (key, kind, character, stores, animations)
  /data/cdn.json          unit -> bucket repo (anyabot/MAD-assets-1/2)
  /data/characters.json   202 karakter + metadata lengkap (nama, rarity,
                          elemen, peran, divisi, CV, artis, deskripsi, …)
  /data/icons.json        daftar resmi ikon skin (88) & char (180)
  /icons/skin/<name>.webp thumbnail skin
  /icons/char/<name>.webp ikon karakter (fallback)

Berkas MODEL tetap di GitHub anyabot/MAD-assets-*, diambil lewat
cdn.jsdelivr.net sesuai `cdn.json` dengan fallback raw.githubusercontent.com.

Keluaran:
  assets/mad-drama/<unit>/<unit>.skel|atlas + tekstur (nama asli)
  assets/mad-drama/_names.json        metadata karakter yang kaya
  public/thumbs/mad-drama/<unit>.webp + _manifest.json

Idempoten: model yang sudah punya .skel dilewati, thumbnail yang sudah ada
dilewati. `spine.json` sengaja DIBUANG (sidecar perilaku, bukan skeleton —
scanModels akan mengiranya model hantu kalau ikut disalin).

Usage: python3 tools/mad-drama/refresh.py [--limit N]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
OUT = VIEW / "assets" / "mad-drama"
THUMBS = VIEW / "public" / "thumbs" / "mad-drama"
SITE = "https://mad.altterisk.cc"
DATA = f"{SITE}/data"
ICONS_SKIN = f"{SITE}/icons/skin"
ICONS_CHAR = f"{SITE}/icons/char"
UA = "spine-viewer-mad-updater/1.0"
WORKERS = 6


class NotFound(Exception):
    pass


def fetch(url: str, timeout: int = 180, retries: int = 3) -> bytes:
    """curl; 404 memunculkan NotFound (bukan None) untuk fallback thumbnail."""
    curl = shutil.which("curl") or "/usr/bin/curl"
    last = None
    for attempt in range(retries):
        fd, tmp = tempfile.mkstemp(prefix="maddl-", suffix=".bin")
        os.close(fd)
        try:
            p = subprocess.run(
                [curl, "-sSL", "--max-time", str(timeout), "-A", UA,
                 "-o", tmp, "-w", "%{http_code}", url],
                capture_output=True, timeout=timeout + 20,
            )
            code = (p.stdout or b"").strip().decode("ascii", "replace")
            if p.returncode == 0 and code.startswith("2"):
                return Path(tmp).read_bytes()
            if code == "404":
                raise NotFound(url)
            last = f"HTTP {code} rc={p.returncode}"
        except NotFound:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def load_data(name: str):
    return json.loads(fetch(f"{DATA}/{name}.json").decode("utf-8", "replace"))


def unit_for(skin: dict, units: dict) -> str | None:
    """Pilih unit yang benar-benar ada: onestore (uncensored) > google > key."""
    key = skin["key"]
    stores = skin.get("stores") or []
    for store in ("onestore", "google"):
        u = f"{key}__{store}"
        if store in stores and u in units:
            return u
    return key if key in units else None


def asset_bases(unit: str, cdn: dict) -> list[str]:
    fam = cdn["families"]["skins"]
    owner = cdn["owner"]
    bucket = fam["buckets"].get(fam["units"].get(unit))
    if not bucket:
        return []
    repo, ref, folder = bucket["repo"], bucket["ref"], fam["dir"]
    js = f"{cdn['base'].rstrip('/')}/{owner}/{repo}@{ref}/{folder}/{unit}"
    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{folder}/{unit}"
    return [js, raw]


def grab_skin(skin: dict, cdn: dict) -> tuple[str, str | None, str, str]:
    """(key, unit, status, err). status = ok | skip | drama | fail."""
    units = cdn["families"]["skins"]["units"]
    unit = unit_for(skin, units)
    if not unit:
        return skin["key"], None, "fail", "unit tidak ada di cdn.json"
    dest = OUT / unit
    if any((dest / f"{unit}{ext}").is_file() for ext in (".skel", ".json")):
        return skin["key"], unit, "skip", ""
    bases = asset_bases(unit, cdn)
    last = "no source"
    for base in bases:
        try:
            listing = json.loads(fetch(f"{base}/files.json").decode("utf-8", "replace"))
            files = [f for f in listing.get("files", [])
                     if isinstance(f, str) and "/" not in f]
            skel = next((f for f in files
                         if f.lower().endswith((".skel", ".json")) and f != "spine.json"), None)
            atlas = next((f for f in files if f.lower().endswith(".atlas")), None)
            if not skel or not atlas:
                # dm_ma0001 / dm_ma0002 memang cuma berisi PNG (texture-only).
                return skin["key"], None, "drama", "tanpa skeleton (drama)"
            blobs = {}
            for f in files:
                if f == "spine.json":
                    continue
                blobs[f] = fetch(f"{base}/{urllib.parse.quote(f)}")
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f"{unit}{os.path.splitext(skel)[1]}").write_bytes(blobs[skel])
            (dest / f"{unit}.atlas").write_bytes(blobs[atlas])
            for f, data in blobs.items():
                if f in (skel, atlas):
                    continue
                (dest / f).write_bytes(data)
            return skin["key"], unit, "ok", ""
        except NotFound as e:
            last = str(e)[:110]
        except Exception as e:  # noqa: BLE001
            last = str(e)[:110]
    return skin["key"], None, "fail", last


def label(types: dict, group: str, value) -> str | None:
    if value is None:
        return None
    rec = (types.get(group) or {}).get(str(value))
    return (rec or {}).get("en") or (rec or {}).get("name") or None


def build_names(skins: list, chars: dict, types: dict, units: dict) -> dict:
    out = {}
    for s in skins:
        unit = unit_for(s, units)
        if not unit:
            continue
        c = chars.get(s.get("character") or "", {}) or {}
        name = c.get("nameEn") or c.get("name") or s["key"]
        star = c.get("defaultStar")
        out[unit] = {
            "name": name,
            "nameKo": c.get("name") or None,
            "kind": s.get("kind"),
            "store": unit.split("__")[1] if "__" in unit else None,
            "character": s.get("character"),
            "animations": s.get("animations"),
            "rarity": "★" * int(star) if isinstance(star, int) and star > 0 else None,
            "element": label(types, "attribute", c.get("attributeType")),
            "class": label(types, "role", c.get("roleType")),
            "position": label(types, "position", c.get("positionType")),
            "division": label(types, "division", c.get("divisionType")),
            "faction": label(types, "faction", c.get("factionType")),
            "artist": c.get("artistEn") or c.get("artist") or None,
            "cv": c.get("cvEn") or c.get("cv") or None,
            "desc": c.get("descEn") or c.get("desc") or None,
            "source": "mad.altterisk.cc",
        }
    return out


def thumb_candidates(skin: dict, skin_icons: set, char_icons: set) -> list[str]:
    """Urutan: ikon skin eksak -> varian Icon_ -> ikon karakter."""
    key = skin["key"].upper()
    out = []
    for stem in (f"Thumbnail_{key}", f"Thumbnail_Icon_{key}",
                 f"Thumbnail_{key.split('__')[0]}"):
        if stem in skin_icons:
            out.append(f"{ICONS_SKIN}/{stem}.webp")
            break
    code = skin.get("character") or ""
    if f"Icon_{code}" in char_icons:
        out.append(f"{ICONS_CHAR}/Icon_{code}.webp")
    return out


def download_thumbs(skins: list, units: dict, skin_icons: set, char_icons: set):
    THUMBS.mkdir(parents=True, exist_ok=True)
    jobs = []
    for s in skins:
        # Skin "drama" cuma PNG tanpa skeleton -> tidak pernah jadi model,
        # jadi jangan buat kunci manifest yatim untuknya.
        if s.get("kind") == "drama":
            continue
        unit = unit_for(s, units)
        if not unit:
            continue
        urls = thumb_candidates(s, skin_icons, char_icons)
        if urls:
            jobs.append((unit, urls))

    def one(job) -> tuple[str, bool]:
        unit, urls = job
        dest = THUMBS / f"{unit}.webp"
        if dest.is_file() and dest.stat().st_size > 512:
            return unit, True
        for url in urls:
            try:
                data = fetch(url, timeout=90)
            except NotFound:
                continue
            except Exception:  # noqa: BLE001
                continue
            if data and data.startswith(b"RIFF"):
                dest.write_bytes(data)
                return unit, True
        return unit, False

    manifest = {}
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for unit, good in pool.map(one, jobs):
            if good:
                ok += 1
                manifest[f"mad-drama/{unit}"] = f"{unit}.webp"
    (THUMBS / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return ok, len(jobs), manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah skin (uji)")
    a = ap.parse_args()

    print("mengambil katalog MAD Viewer…", file=sys.stderr, flush=True)
    skin_list = load_data("skin_list")["skins"]
    cdn = load_data("cdn")
    characters = load_data("characters")
    icon_groups = load_data("icons")["groups"]
    chars = characters.get("characters") or {}
    types = characters.get("types") or {}
    skin_icons = set(icon_groups.get("skin") or [])
    char_icons = set(icon_groups.get("char") or [])
    units = cdn["families"]["skins"]["units"]
    if a.limit:
        skin_list = skin_list[: a.limit]
    print(f"skin {len(skin_list)} · karakter {len(chars)} · ikon skin {len(skin_icons)}",
          file=sys.stderr, flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, r in enumerate(pool.map(lambda s: grab_skin(s, cdn), skin_list), 1):
            results.append(r)
            if i % 25 == 0 or i == len(skin_list):
                print(f"  model {i}/{len(skin_list)}", file=sys.stderr, flush=True)
    counts = {}
    errors = []
    for key, unit, status, err in results:
        counts[status] = counts.get(status, 0) + 1
        if status == "fail":
            errors.append(f"{key}: {err}")

    # Mode uji jangan menimpa katalog nama/manifest yang sudah lengkap.
    if a.limit:
        print(json.dumps({"skins": len(skin_list), "models": counts,
                          "note": "mode uji — metadata tidak ditulis"}, indent=1))
        return

    names = build_names(skin_list, chars, types, units)
    (OUT / "_names.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    thumb_ok, thumb_jobs, manifest = download_thumbs(
        skin_list, units, skin_icons, char_icons)

    res = {
        "skins": len(skin_list),
        "characters": len(chars),
        "models": counts,
        "names": len(names),
        "thumbOk": thumb_ok,
        "thumbMapped": thumb_jobs,
        "manifestEntries": len(manifest),
        "errors": errors[:12],
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
