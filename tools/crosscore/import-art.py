#!/usr/bin/env python3
"""Impor SELURUH katalog https://crosscore.art/ ke pustaka spine-viewer.

Sumbernya bukan repo/git, melainkan situs "Cross Core L2D Viewer":

  /                                  -> app.<hash>.js
  app.<hash>.js                      -> catalog-all.<hash>.js
  catalog-all.<hash>.js              -> export const characters/skins/roster/coverage
  /api/art/<sha256>/<file>           -> skeleton .json, .atlas, halaman .png,
                                        dan illustration.webp

Katalog `characters` berisi 486 SCENE (134 karakter / 421 kostum):
  - 408 scene punya skeleton + atlas (Spine 4.2.20 / 4.2.38 / 3.8.99, PMA)
  - 78 scene `static:true` cuma punya illustration.webp
Efek front/back di katalog adalah LAPISAN overlay yang dipakai situs untuk
dikomposisikan di atas rig utama; viewer kita merender satu rig sekali, jadi
mereka sengaja tidak dijadikan model berdiri sendiri.

Struktur hasil:
  assets/crosscore/<slug>/<slug>.json|atlas|<halaman>.png
  assets/crosscore-cg/<slug>/<slug>.webp          (galeri gambar statis)
  assets/crosscore/_names.json                    (nama + metadata per id)
  public/thumbs/crosscore/<slug>.webp             (dari ilustrasi statis)
  public/thumbs/crosscore/_manifest.json          (id model -> berkas thumb)
  data/crosscore-art-catalog.json                 (katalog mentah, buat update.py)

Baris nama halaman di .atlas ditulis ulang ke <slug>.png agar mengikuti
konvensi scanner (folder = stem). Semua berkas yang sudah ada dilewati, jadi
aman dijalankan ulang / dilanjut setelah putus.

Usage:
    python3 tools/crosscore/import-art.py [--workers 8] [--limit N]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
ASSETS = VIEW / "assets"
CROSS = ASSETS / "crosscore"
CG = ASSETS / "crosscore-cg"
THUMBS = VIEW / "public" / "thumbs" / "crosscore"
NAMES = CROSS / "_names.json"
MANIFEST = THUMBS / "_manifest.json"
CATALOG_CACHE = VIEW / "data" / "crosscore-art-catalog.json"
STATE = VIEW / "data" / "crosscore-art-state.json"

BASE = "https://crosscore.art"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": BASE + "/",
    "Accept": "*/*",
}
PAGE_RE = re.compile(r"\.(png|webp|jpg|jpeg)$", re.I)


def get(url: str, tries: int = 5, timeout: int = 120) -> bytes:
    # Beberapa nama berkas di katalog mengandung spasi ("Gondul _character.json").
    # urllib menolak kontrol/spasi mentah, jadi path-nya di-encode dulu.
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


def catalog() -> dict:
    """Ambil katalog terkini; URL bundle-nya di-parse dari HTML tiap kali."""
    html = get(BASE + "/", tries=3).decode("utf-8", "replace")
    m = re.search(r'src="\./(app\.[0-9a-f]+\.js)"', html)
    if not m:
        raise RuntimeError("app.<hash>.js tidak ketemu di HTML crosscore.art")
    app = get(f"{BASE}/{m.group(1)}", tries=3).decode("utf-8", "replace")
    c = re.search(r"from '\./(catalog-all\.[0-9a-f]+\.js)'", app)
    if not c:
        raise RuntimeError("catalog-all.<hash>.js tidak ketemu di app bundle")
    js = get(f"{BASE}/{c.group(1)}", tries=3).decode("utf-8", "replace")

    def grab(name: str):
        mm = re.search(r"export const " + name + r"\s*=\s*", js)
        if not mm:
            raise RuntimeError(f"export {name} tidak ada di katalog")
        i = mm.end()
        if js[i] == "[":
            e = js.find("];", i) + 1
        else:
            depth = 0
            for j in range(i, len(js)):
                if js[j] == "{":
                    depth += 1
                elif js[j] == "}":
                    depth -= 1
                    if depth == 0:
                        e = j + 1
                        break
        return json.loads(js[i:e])

    out = {
        "characters": grab("characters"),
        "skins": grab("skins"),
        "roster": grab("roster"),
        "coverage": grab("coverage"),
        "catalogUrl": c.group(1),
        "sig": hashlib.sha256(js.encode("utf-8")).hexdigest()[:16],
    }
    CATALOG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def slug_of(x: dict) -> str:
    raw = "_".join(str(x.get(k) or "") for k in ("characterId", "skinId", "id"))
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")[:110]


def atlas_pages(atlas: str) -> list[str]:
    return [l.strip() for l in atlas.splitlines()
            if l and not l.startswith(" ") and PAGE_RE.search(l.strip())]


def fetch_scene(x: dict, workers_lock=None) -> dict:
    """Unduh satu scene. Mengembalikan {id, files, thumb, static}."""
    slug = slug_of(x)
    static = bool(x.get("static"))
    result = {"slug": slug, "static": static, "files": 0, "bytes": 0}

    if static:
        out = CG / slug
        dest = out / f"{slug}.webp"
        if dest.exists() and dest.stat().st_size > 100:
            return result
        out.mkdir(parents=True, exist_ok=True)
        data = get(BASE + str(x["image"]))
        dest.write_bytes(data)
        result.update(files=1, bytes=len(data))
        return result

    out = CROSS / slug
    skel = out / f"{slug}.json"
    atlas = out / f"{slug}.atlas"
    if (skel.exists() and skel.stat().st_size > 100
            and atlas.exists() and atlas.stat().st_size > 10):
        # Pastikan semua halaman tekstur juga ada.
        pages = atlas_pages(atlas.read_text(encoding="utf-8", errors="replace"))
        if pages and all((out / p).exists() for p in pages):
            return result

    out.mkdir(parents=True, exist_ok=True)
    # Halaman tekstur selalu hidup di DIREKTORI YANG SAMA dengan .atlas.
    # Katalog punya tiga bentuk URL, jadi jangan pernah menebak prefix:
    #   /api/art/<sha256>/<file>.atlas            (373 scene)
    #   /api/legacy-art/<sha1>/<subdir>/<file>    (12 scene)
    #   /game-clips/<sha256>/<file>.atlas         (23 scene)
    atlas_dir = str(x["atlas"]).rsplit("/", 1)[0]
    skel_bytes = get(BASE + str(x["skeleton"]))
    atlas_text = get(BASE + str(x["atlas"])).decode("utf-8", "replace")
    pages = atlas_pages(atlas_text)
    total = len(skel_bytes) + len(atlas_text)
    for i, page in enumerate(pages):
        suffix = Path(page).suffix
        local = f"{slug}{'' if i == 0 else '_' + str(i + 1)}{suffix}"
        data = get(f"{BASE}{atlas_dir}/{page}")
        (out / local).write_bytes(data)
        atlas_text = atlas_text.replace(page, local)
        total += len(data)
    skel.write_bytes(skel_bytes)
    atlas.write_text(atlas_text, encoding="utf-8")
    result.update(files=2 + len(pages), bytes=total)
    return result


def build_metadata(cat: dict) -> None:
    """Tulis _names.json, thumbnail, dan _manifest.json."""
    roster = {r["id"]: r for r in cat["roster"]}
    skin_label = {s["id"]: s.get("label") for s in cat["skins"]}
    names: dict[str, dict] = {}
    manifest: dict[str, str] = {}
    THUMBS.mkdir(parents=True, exist_ok=True)

    # Ilustrasi statis dipakai sebagai thumbnail untuk SEMUA scene skin itu.
    thumb_by_skin: dict[str, str] = {}
    for x in cat["characters"]:
        if not x.get("static") or not x.get("image"):
            continue
        slug = slug_of(x)
        src = CG / slug / f"{slug}.webp"
        if not src.exists():
            continue
        dst = THUMBS / f"{slug}.webp"
        if not dst.exists():
            dst.write_bytes(src.read_bytes())
        thumb_by_skin[str(x.get("skinId"))] = dst.name

    for x in cat["characters"]:
        slug = slug_of(x)
        cid = str(x.get("characterId") or "")
        r = roster.get(cid, {})
        char_name = x.get("name") or r.get("name") or cid
        outfit = x.get("outfit") or skin_label.get(str(x.get("skinId"))) or ""
        scene = x.get("sceneLabel") or ""
        label = " · ".join(p for p in (outfit, scene) if p) or x.get("id") or slug
        static = bool(x.get("static"))
        # scanImageGalleries memberi id "<folder>/<stem>" untuk berkas gambar,
        # sedangkan scanModels memberi id "<folder>" untuk rig Spine. Kunci
        # _names.json / _manifest.json HARUS sama persis dengan id model.
        mid = (f"crosscore-cg/{slug}/{slug}" if static
               else f"crosscore/{slug}")
        rec = {
            "name": char_name,
            "title": outfit,
            "category": f"{x.get('rarity', '')}★" if x.get("rarity") else None,
            "group": x.get("englishName") or r.get("englishName"),
            "game": "crosscore-cg" if static else "crosscore",
            "characterId": cid,
            "skinId": str(x.get("skinId") or ""),
            "outfit": outfit,
            "sceneLabel": scene,
            "label": label,
            "englishName": x.get("englishName") or r.get("englishName"),
            "rarity": x.get("rarity"),
            "spineVersion": x.get("skeletonVersion"),
            "pma": x.get("premultipliedAlpha"),
            "animations": len(x.get("animations") or []),
            "static": static,
            "source": "crosscore.art",
        }
        names[mid] = rec
        # Gambar statis juga jadi model image, jangan lupa thumbnailnya.
        thumb = thumb_by_skin.get(str(x.get("skinId")))
        if thumb:
            manifest[mid] = thumb

    NAMES.parent.mkdir(parents=True, exist_ok=True)
    NAMES.write_text(json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True),
                     encoding="utf-8")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True),
                        encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah scene (uji)")
    a = ap.parse_args()
    t0 = time.time()
    try:
        cat = catalog()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    scenes = cat["characters"]
    if a.limit:
        scenes = scenes[:a.limit]
    print(f"[katalog] {len(scenes)} scene | {cat['coverage']} | sig {cat['sig']}",
          file=sys.stderr, flush=True)

    done = 0
    failed: list[str] = []
    files = 0
    nbytes = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(fetch_scene, x): x for x in scenes}
        for fut in concurrent.futures.as_completed(futs):
            x = futs[fut]
            try:
                r = fut.result()
                files += r["files"]
                nbytes += r["bytes"]
            except Exception as e:  # noqa: BLE001
                failed.append(f"{slug_of(x)}: {e}")
            done += 1
            if done % 25 == 0 or done == len(scenes):
                print(f"  {done}/{len(scenes)} scene | {nbytes / 1e6:.0f} MB | "
                      f"gagal {len(failed)}", file=sys.stderr, flush=True)

    build_metadata(cat)
    state = {
        "sig": cat["sig"],
        "catalogUrl": cat["catalogUrl"],
        "coverage": cat["coverage"],
        "scenes": sorted(slug_of(x) for x in cat["characters"]),
        "updated_at": int(time.time()),
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    res = {
        "ok": not failed,
        "source": "crosscore.art",
        "sig": cat["sig"],
        "coverage": cat["coverage"],
        "scenes": len(scenes),
        "downloaded": files,
        "bytes": nbytes,
        "failed": len(failed),
        "errors": failed[:8],
        "seconds": round(time.time() - t0, 1),
        "names": len(json.loads(NAMES.read_text(encoding="utf-8"))),
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
