#!/usr/bin/env python3
"""Impor EFEK, zona SENTUH, dan SUARA CrossCore dari crosscore.art.

Dijalankan SETELAH tools/crosscore/import-art.py (butuh katalog hasil unduh
di data/crosscore-art-catalog.json dan pohon assets/crosscore/).

Sumber:
  katalog `characters[].effects`     -> 225 rig overlay (front/back)
  /official-zones.js                 -> export default {prefab: [rows]}
  /touch-zones.js                    -> export const zonesByPrefab = {...}
  /audio/catalog.json                -> {sceneId: {touchIndex: [clip.webm]}}
  /audio/entrances.json              -> {sceneId: {animation, clip}}
  /audio/subtitles.json              -> {clip: teks}
  /audio/clips/<clip>.webm           -> berkas suara

Hasil:
  assets/crosscore/<slug>_effF|effB/  rig efek (atlas + halaman disalin dari
                                      scene induk, namanya ditulis ulang)
  assets/crosscore/_extras.json       nama model efek + peta audio + subtitle
  data/cc-interaction.json            zona sentuh untuk mesin CCI viewer
  public/audio/crosscore/clips/       klip suara (diserve statis)

Semua langkah idempoten: berkas yang sudah ada dilewati.

Usage:
    python3 tools/crosscore/import-extras.py [--workers 8] [--limit N]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
ASSETS = VIEW / "assets"
CROSS = ASSETS / "crosscore"
CATALOG = VIEW / "data" / "crosscore-art-catalog.json"
NAMES = CROSS / "_names.json"
EXTRAS = CROSS / "_extras.json"
INTERACTION = VIEW / "data" / "cc-interaction.json"
AUDIO_DIR = VIEW / "public" / "audio" / "crosscore" / "clips"
STATE = VIEW / "data" / "crosscore-extras-state.json"

BASE = "https://crosscore.art"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": BASE + "/",
    "Accept": "*/*",
}
PAGE_RE = re.compile(r"\.(png|webp|jpg|jpeg)$", re.I)


def get(url: str, tries: int = 5, timeout: int = 120) -> bytes:
    parts = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit((
        parts.scheme, parts.netloc,
        urllib.parse.quote(parts.path, safe="/%"),
        parts.query, parts.fragment,
    ))
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(min(20, 1.5 * (2 ** i)))
    raise RuntimeError(f"gagal mengambil {url}: {last}")


def slug_of(x: dict) -> str:
    raw = "_".join(str(x.get(k) or "") for k in ("characterId", "skinId", "id"))
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")[:110]


def json_module(path: str, marker: str) -> dict:
    s = get(f"{BASE}/{path}", tries=3).decode("utf-8", "replace")
    i = s.index(marker) + len(marker)
    body = s[i:].strip()
    return json.loads(body.rstrip(";"))


def atlas_pages(atlas: str) -> list[str]:
    return [l.strip() for l in atlas.splitlines()
            if l and not l.startswith(" ") and PAGE_RE.search(l.strip())]


def copy_or_link(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    try:
        os.link(src, dst)  # hemat disk: halaman tekstur identik
    except OSError:
        shutil.copyfile(src, dst)


# ---------------------------------------------------------------- efek ----
def import_effects(cat: dict, workers: int, limit: int) -> dict:
    scenes = [x for x in cat["characters"] if x.get("effects")]
    if limit:
        scenes = scenes[:limit]
    jobs = []
    for x in scenes:
        slug = slug_of(x)
        for side, url in (x.get("effects") or {}).items():
            if not isinstance(url, str):
                continue
            suffix = "effF" if side == "front" else "effB"
            jobs.append((x, slug, f"{slug}_{suffix}", side, url))
    roster = {r["id"]: r for r in cat["roster"]}
    names: dict[str, dict] = {}
    failed: list[str] = []
    done = 0
    nbytes = 0

    def one(job) -> int:
        x, parent_slug, stem, side, url = job
        parent = CROSS / parent_slug
        src_atlas = parent / f"{parent_slug}.atlas"
        out = CROSS / stem
        skel = out / f"{stem}.json"
        atlas = out / f"{stem}.atlas"
        if (skel.exists() and skel.stat().st_size > 100
                and atlas.exists() and atlas.stat().st_size > 10):
            pages = atlas_pages(atlas.read_text(encoding="utf-8", errors="replace"))
            if pages and all((out / p).exists() for p in pages):
                return 0
        if not src_atlas.exists():
            raise RuntimeError(f"atlas induk tidak ada: {parent_slug}")
        out.mkdir(parents=True, exist_ok=True)
        effect_json = get(BASE + url)
        atlas_text = src_atlas.read_text(encoding="utf-8", errors="replace")
        pages = atlas_pages(atlas_text)
        total = len(effect_json) + len(atlas_text)
        for i, page in enumerate(pages):
            suffix = Path(page).suffix
            local = f"{stem}{'' if i == 0 else '_' + str(i + 1)}{suffix}"
            copy_or_link(parent / page, out / local)
            atlas_text = atlas_text.replace(page, local)
            total += (out / local).stat().st_size
        skel.write_bytes(effect_json)
        atlas.write_text(atlas_text, encoding="utf-8")
        return total

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, j): j for j in jobs}
        for fut in concurrent.futures.as_completed(futs):
            x, parent_slug, stem, side, url = futs[fut]
            try:
                nbytes += fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append(f"{stem}: {e}")
            done += 1
            if done % 40 == 0 or done == len(jobs):
                print(f"  efek {done}/{len(jobs)} | gagal {len(failed)}",
                      file=sys.stderr, flush=True)

    for x, parent_slug, stem, side, url in jobs:
        cid = str(x.get("characterId") or "")
        r = roster.get(cid, {})
        outfit = x.get("outfit") or ""
        side_label = "Efek Depan" if side == "front" else "Efek Belakang"
        names[f"crosscore/{stem}"] = {
            "name": x.get("name") or r.get("name") or cid,
            "title": outfit,
            "label": " · ".join(p for p in (outfit, side_label) if p),
            "category": f"{x.get('rarity', '')}★" if x.get("rarity") else None,
            "group": x.get("englishName") or r.get("englishName"),
            "game": "crosscore",
            "characterId": cid,
            "skinId": str(x.get("skinId") or ""),
            "outfit": outfit,
            "sceneLabel": side_label,
            "englishName": x.get("englishName") or r.get("englishName"),
            "rarity": x.get("rarity"),
            "spineVersion": x.get("skeletonVersion"),
            "pma": x.get("premultipliedAlpha"),
            "static": False,
            "effect": True,
            "rank": 1,          # root tetap rig utama (rank 0)
            "source": "crosscore.art",
        }
    return {"jobs": jobs, "names": names, "failed": failed, "bytes": nbytes}


# ------------------------------------------------------------- sentuh ----
def import_touch(cat: dict, audio_catalog: dict) -> dict:
    official = json_module("official-zones.js", "export default")
    fallback = json_module("touch-zones.js", "export const zonesByPrefab =")
    roster = {r["id"]: r for r in cat["roster"]}
    models = []
    for x in cat["characters"]:
        if x.get("static"):
            continue
        skeleton = str(x.get("skeleton") or "")
        folder = str(x.get("touchPrefab") or
                     (skeleton.split("/")[-2].lower() if "/" in skeleton else ""))
        rows = official.get(folder) or fallback.get(folder)
        if not rows:
            continue
        scene_id = str(x.get("id") or "")
        cues = audio_catalog.get(scene_id) or {}
        actions = []
        for row in rows:
            idx = row.get("index")
            if idx is None:
                continue
            cues_at = cues.get(str(idx)) or []
            if not isinstance(cues_at, list):
                cues_at = [cues_at]
            actions.append({
                "index": idx,
                "sName": row.get("action") or f"click{idx}",
                "sType": row.get("role") or row.get("track") or 1,
                "areas": row.get("boxes") or [],
                "audioId": cues_at,
                "content": {"isHide": not row.get("enabled", True)},
            })
        if not actions:
            continue
        cid = str(x.get("characterId") or "")
        models.append({
            "id": str(x.get("modelId") or slug_of(x)),
            "name": x.get("name") or roster.get(cid, {}).get("name") or cid,
            "title": x.get("outfit") or "",
            # Kunci pencocokan CCI = nama folder model (slug), lower-case.
            "prefab": slug_of(x).lower(),
            "group": "角色皮肤",
            "actions": actions,
        })
    payload = {"schema": 1, "models": models}
    INTERACTION.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"official": len(official), "fallback": len(fallback),
            "models": len(models), "actions": sum(len(m["actions"]) for m in models)}


# -------------------------------------------------------------- suara ----
def import_sound(cat: dict, audio_catalog: dict, entrances: dict,
                 subtitles: dict, workers: int) -> dict:
    clips = set()
    for cues in audio_catalog.values():
        for arr in cues.values():
            clips.update(arr if isinstance(arr, list) else [arr])
    for v in entrances.values():
        if v.get("clip"):
            clips.add(v["clip"])
    clips = {c for c in clips if isinstance(c, str) and c}
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    failed = []
    done = 0
    nbytes = 0

    def one(name: str) -> int:
        dest = AUDIO_DIR / name
        if dest.exists() and dest.stat().st_size > 100:
            return 0
        data = get(f"{BASE}/audio/clips/{name}", tries=4, timeout=60)
        if not data:
            raise RuntimeError("berkas kosong")
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return len(data)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, c): c for c in sorted(clips)}
        for fut in concurrent.futures.as_completed(futs):
            c = futs[fut]
            try:
                nbytes += fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append(f"{c}: {e}")
            done += 1
            if done % 500 == 0 or done == len(clips):
                print(f"  audio {done}/{len(clips)} | {nbytes / 1e6:.0f} MB | gagal {len(failed)}",
                      file=sys.stderr, flush=True)

    prefix = "/audio/crosscore/clips/"
    audio_map = {}
    for x in cat["characters"]:
        if x.get("static"):
            continue
        scene_id = str(x.get("id") or "")
        cues = audio_catalog.get(scene_id) or {}
        by_index = {}
        tracks = []
        for idx, arr in cues.items():
            arr = arr if isinstance(arr, list) else [arr]
            urls = [prefix + urllib.parse.quote(n) for n in arr if isinstance(n, str)]
            by_index[str(idx)] = urls
            for u in urls:
                if u not in tracks:
                    tracks.append(u)
        ent = entrances.get(scene_id) or {}
        entrance = prefix + urllib.parse.quote(ent["clip"]) if ent.get("clip") else None
        if entrance and entrance not in tracks:
            tracks.insert(0, entrance)
        if tracks:
            audio_map[f"crosscore/{slug_of(x)}"] = {
                "lang": "CN",
                "tracks": tracks,
                "byIndex": by_index,
                "entrance": entrance,
            }
    return {"clips": len(clips), "scenes": len(audio_map),
            "failed": failed, "bytes": nbytes, "audio": audio_map,
            "subtitles": subtitles}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    audio_catalog = json.loads(get(f"{BASE}/audio/catalog.json", tries=3)
                               .decode("utf-8", "replace"))
    entrances = json.loads(get(f"{BASE}/audio/entrances.json", tries=3)
                           .decode("utf-8", "replace"))
    subtitles = json.loads(get(f"{BASE}/audio/subtitles.json", tries=3)
                           .decode("utf-8", "replace"))

    eff = import_effects(cat, a.workers, a.limit)
    touch = import_touch(cat, audio_catalog)
    snd = import_sound(cat, audio_catalog, entrances, subtitles, a.workers)

    EXTRAS.write_text(json.dumps({
        "source": "crosscore.art",
        "names": eff["names"],
        "audio": snd["audio"],
        "subtitles": snd["subtitles"],
        "touch": {"models": touch["models"], "actions": touch["actions"]},
    }, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    STATE.write_text(json.dumps({
        "at": int(time.time()),
        "effects": len(eff["jobs"]),
        "clips": snd["clips"],
        "touchModels": touch["models"],
    }, indent=1), encoding="utf-8")

    failed = len(eff["failed"]) + len(snd["failed"])
    res = {
        "ok": failed == 0,
        "source": "crosscore.art",
        "effects": {"models": len(eff["jobs"]), "bytes": eff["bytes"],
                    "failed": len(eff["failed"])},
        "touch": touch,
        "sound": {"clips": snd["clips"], "scenes": snd["scenes"],
                  "bytes": snd["bytes"], "failed": len(snd["failed"])},
        "errors": (eff["failed"] + snd["failed"])[:8],
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
