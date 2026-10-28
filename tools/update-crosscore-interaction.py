#!/usr/bin/env python3
"""Tambah model CrossCore *interaktif* dari ArtHub ke viewer.

Bedanya dengan `update-crosscore-arthub.py`
===========================================

Skrip itu memakai index `crosscore_chars.json` — katalog model biasa (555
model). CrossCore juga punya katalog **interaksi** terpisah:

    katalog : https://pub-3be583976a374ca9aacd740e9d14ad96.r2.dev/crosscore-interaction/catalog/catalog.json
    bucket  : https://pub-3be583976a374ca9aacd740e9d14ad96.r2.dev

Isinya 275 model (270 playable) dengan 2.041 aksi interaktif, 4.155 audio cue,
dan 324 prefab yang mendefinisikan layer + posisi render.

Kunci path: MENGAPA 404
========================

Field `atlas`/`skeleton` di prefab menulis `/crosscore-interaction/spine/...`
tetapi objek di R2 sebenarnya ada di bawah `/crosscore/spine/...`. Viewer
ArtHub menulis ulang prefix ini (lihat PATH_REWRITES di arthub-cos.js):

    /crosscore-interaction/spine/  ->  /crosscore/spine/

Tanpa penulisan ulang itu, SEMUA unduhan 404. Ini sumber kebingungan pertama.

Selain itu path di prefab sudah dalam bentuk percent-encoded (`%E8%A7%92...`)
untuk nama kategori non-ASCII (角色动态 / 剧情CG). Path harus di-`unquote`
dulu, baru di-`quote` utuh — kalau di-quote dua kali, hasilnya 404.

Nama berkas tidak selalu sama dengan nama folder
================================================

Contoh nyata:
    folder : spine/角色动态/60310_skin_tizona03_spine/
    berkas : 60310_skin_Tizona03.atlas   (huruf besar T, tanpa `_spine`)

Jadi nama berkas WAJIB diambil dari field prefab, bukan ditebak dari folder.

Pemakaian
=========
    python tools/update-crosscore-interaction.py --check
    python tools/update-crosscore-interaction.py --apply [--limit N] [--workers 5]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import urllib.parse
import urllib.request

CATALOG = ("https://pub-3be583976a374ca9aacd740e9d14ad96.r2.dev"
           "/crosscore-interaction/catalog/catalog.json")
BUCKET = "https://pub-3be583976a374ca9aacd740e9d14ad96.r2.dev"
PREFIX_FROM = "/crosscore-interaction/"
PREFIX_TO = "/crosscore/"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
OUT_DIR = os.path.join(REPO, "assets", "crosscore-interaction")

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36"


def log(*a) -> None:
    print(*a, flush=True)


def fetch(url: str, timeout: int = 150, retries: int = 3) -> bytes:
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"{url} gagal: {last}")


def url_for(raw_path: str) -> str:
    """Path prefab -> URL R2 yang benar.

    1. unquote dulu (prefab menyimpan %E8%A7%92... untuk nama non-ASCII)
    2. tulis ulang prefix /crosscore-interaction/ -> /crosscore/
    3. quote ulang seluruh path
    """
    p = urllib.parse.unquote(raw_path)
    if p.startswith(PREFIX_FROM):
        p = PREFIX_TO + p[len(PREFIX_FROM):]
    return BUCKET + urllib.parse.quote(p, safe="/")


def load_prefabs() -> dict:
    data = json.loads(fetch(CATALOG).decode("utf-8", "replace"))
    return data.get("prefabs") or {}


def model_name(prefab_key: str, layer_path: str) -> str:
    """Nama folder viewer: prefab + layer, aman untuk path."""
    raw = prefab_key if layer_path in ("", "pos/main") else f"{prefab_key}__{layer_path}"
    return "".join(ch if ch.isalnum() or ch in "_-." else "_" for ch in raw)


def atlas_pages(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip().lstrip("\ufeff").strip()
        if s.lower().endswith((".png", ".jpg", ".jpeg")) and ":" not in s:
            out.append(s)
    return out


def convert_atlas(text: str) -> str:
    if "bounds:" not in text:
        return text
    out = []
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("bounds:"):
            ind = line[: len(line) - len(line.lstrip())]
            parts = [v.strip() for v in st.split(":", 1)[1].split(",")]
            if len(parts) == 4:
                x, y, w, h = parts
                out.append(f"{ind}xy: {x}, {y}")
                out.append(f"{ind}size: {w}, {h}")
                continue
        if st.startswith("scale:"):
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def build_jobs(prefabs: dict) -> list[dict]:
    jobs, seen = [], set()
    for key, pf in prefabs.items():
        for L in (pf.get("layers") or []):
            atlas, skel = L.get("atlas"), L.get("skeleton")
            if not atlas or not skel:
                continue
            name = model_name(key, L.get("path") or "")
            if name in seen:
                continue
            seen.add(name)
            jobs.append({
                "name": name,
                "atlas": atlas,
                "skeleton": skel,
                "format": L.get("format") or "json",
                "x": L.get("x"), "y": L.get("y"),
                "sx": L.get("sx"), "sy": L.get("sy"),
            })
    return jobs


def download_one(job: dict) -> tuple[str, int, str | None]:
    dest = os.path.join(OUT_DIR, job["name"])
    try:
        skel = fetch(url_for(job["skeleton"]))
        atlas_raw = fetch(url_for(job["atlas"]))
    except Exception as e:  # noqa: BLE001
        return job["name"], 0, str(e)[:70]

    os.makedirs(dest, exist_ok=True)

    # nama berkas asli dari prefab
    skel_name = urllib.parse.unquote(job["skeleton"]).rsplit("/", 1)[-1]
    if not skel_name.lower().endswith((".json", ".skel")):
        skel_name = skel_name.rsplit(".", 1)[0] + ".json"
    atlas_name = skel_name.rsplit(".", 1)[0] + ".atlas"

    with open(os.path.join(dest, skel_name), "wb") as fh:
        fh.write(skel)
    atlas_text = convert_atlas(atlas_raw.decode("utf-8", "replace"))
    with open(os.path.join(dest, atlas_name), "w", encoding="utf-8") as fh:
        fh.write(atlas_text)

    # halaman tekstur: ambil dari folder yang sama dengan atlas
    base = urllib.parse.unquote(job["atlas"]).rsplit("/", 1)[0]
    n = 2
    for page in atlas_pages(atlas_text):
        png = None
        for variant in (page, page.lower(), page.upper()):
            try:
                png = fetch(url_for(f"{base}/{variant}"))
                break
            except Exception:
                continue
        if png is None:
            continue
        with open(os.path.join(dest, page), "wb") as fh:
            fh.write(png)
        n += 1
    return job["name"], n, None


def main() -> int:
    ap = argparse.ArgumentParser(description="CrossCore interaktif dari ArtHub")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    log("membaca katalog interaksi CrossCore…")
    prefabs = load_prefabs()
    jobs = build_jobs(prefabs)
    log(f"prefab: {len(prefabs)} | model (layer): {len(jobs)}")

    existing = {d for d in os.listdir(OUT_DIR) if os.path.isdir(os.path.join(OUT_DIR, d))}
    todo = [j for j in jobs if j["name"] not in existing]
    log(f"sudah ada: {len(existing)} | belum: {len(todo)}")
    if args.limit:
        todo = todo[: args.limit]

    if not args.apply:
        log(json.dumps({"prefabs": len(prefabs), "models": len(jobs),
                        "have": len(existing), "new": len(todo),
                        "note": "putar --apply"}, indent=1))
        for j in todo[:10]:
            log(f"  {j['name']}")
        return 0

    ok, failed = 0, []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(download_one, j) for j in todo]
        for i, fut in enumerate(cf.as_completed(futures), 1):
            try:
                name, _n, err = fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append(str(e)[:60])
                continue
            if err:
                failed.append(f"{name}: {err}")
            else:
                ok += 1
            if i % 20 == 0 or i == len(todo):
                log(f"  {i}/{len(todo)} | ok {ok} | gagal {len(failed)}")

    log(json.dumps({"ok": ok, "gagal": len(failed), "sampel": failed[:5]},
                   indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
