#!/usr/bin/env python3
"""Tambah model Spine NIKKE dan Brown Dust 2 dari ArtHub viewer.

Sumber (sama seperti update-majsoul.py):

    index NIKKE : https://talors1225.github.io/arthub-viewer-web/nikki/nikki_chars.json
    index BD2   : https://talors1225.github.io/arthub-viewer-web/bd2/bd2_chars.json
    bucket      : https://pub-bdd986c6ec274f53b01df62ac49e02e2.r2.dev

Tidak ada enkripsi. Struktur index per entri:

    "cutscenes": [
      { "variant": "0",
        "dir":  "spine/Chapter4_Glass_Back2/",
        "skel": "Chapter4_Glass_Back2.skel",     # BD2 memakai .skel.bytes
        "atlas": "Chapter4_Glass_Back2.atlas" }  # BD2 memakai .atlas.txt
    ]

Catatan penting tentang path di CDN: aset NIKKE ada di bawah `nikki/spine_carved/`,
BUKAN `nikki/spine/` (lihat PATH_REWRITES di arthub-cos.js). BD2 memakai
`bd2/spine/...` apa adanya.

Pemakaian
=========
    python update-arthub.py --game nikke --check
    python update-arthub.py --game nikke --apply --workers 8
    python update-arthub.py --game bd2 --apply
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import urllib.parse
import urllib.request

BUCKET = "https://pub-bdd986c6ec274f53b01df62ac49e02e2.r2.dev"
PAGES = "https://talors1225.github.io/arthub-viewer-web"

GAMES = {
    "nikke": {
        "index": f"{PAGES}/nikki/nikki_chars.json",
        # index menulis path relatif "spine/..." (tanpa prefiks game), sedangkan
        # di CDN letaknya "nikki/spine_carved/...". arthub-cos.js melakukan
        # penulisan ulang yang sama.
        "prefix_from": "spine/",
        "prefix_to": "nikki/spine_carved/",
        "out": "nikke",
    },
    "bd2": {
        "index": f"{PAGES}/bd2/bd2_chars.json",
        "prefix_from": "spine/",
        "prefix_to": "bd2/spine/",
        "out": "bd2-arthub",
    },
}

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..")) or "/opt/spine-viewer"
# tools/ ada di dalam repo, jadi naik satu tingkat.
REPO = os.path.abspath(os.path.join(HERE, ".."))

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36"


def log(*a) -> None:
    print(*a, flush=True)


def fetch(url: str, timeout: int = 90, retries: int = 3) -> bytes:
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"{url} gagal: {last}")


def remote_path(game: str, rel: str) -> str:
    """Petakan path relatif index ke path CDN sebenarnya."""
    cfg = GAMES[game]
    rel = rel.lstrip("/")
    if rel.startswith(cfg["prefix_from"]):
        rel = cfg["prefix_to"] + rel[len(cfg["prefix_from"]):]
    return f"{BUCKET}/{urllib.parse.quote(rel)}"


def atlas_pages(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.lower().endswith((".png", ".jpg", ".jpeg")) and ":" not in s:
            out.append(s)
    return out


def convert_atlas(text: str) -> str:
    """`bounds:` (format lama) -> `xy:`/`size:` bila perlu."""
    if "bounds:" not in text:
        return text
    out = []
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("bounds:"):
            ind = line[: len(line) - len(line.lstrip())]
            vals = st.split(":", 1)[1]
            parts = [v.strip() for v in vals.split(",")]
            if len(parts) == 4:
                x, y, w, h = parts
                out.append(f"{ind}xy: {x}, {y}")
                out.append(f"{ind}size: {w}, {h}")
                continue
        if st.startswith("scale:"):
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def load_models(game: str) -> list[dict]:
    """Ratakan semua entri cutscenes/variants menjadi daftar model."""
    data = json.loads(fetch(GAMES[game]["index"]).decode("utf-8", "replace"))
    models, seen = [], set()
    for ch in data.get("characters", []):
        subs = ch.get("cutscenes") or ch.get("variants") or ch.get("models") or []
        if not subs and ch.get("skel"):
            subs = [ch]
        for s in subs:
            skel = s.get("skel") or ""
            if not skel:
                continue
            name = os.path.basename(skel)
            for suf in (".bytes", ".txt"):
                if name.endswith(suf):
                    name = name[: -len(suf)]
            stem = name.rsplit(".", 1)[0] if "." in name else name
            key = stem
            if key in seen:
                continue
            seen.add(key)
            models.append({
                "name": "".join(c if c.isalnum() or c in "_-." else "_" for c in stem),
                "dir": s.get("dir") or "",
                "skel": skel,
                "atlas": s.get("atlas") or "",
                "label": ch.get("name") or stem,
            })
    return models


def download_one(game: str, m: dict, out_dir: str) -> tuple[str, int, str | None]:
    dest = os.path.join(out_dir, m["name"])
    try:
        skel = fetch(remote_path(game, m["dir"] + m["skel"]))
        atlas_raw = fetch(remote_path(game, m["dir"] + m["atlas"]))
    except Exception as e:  # noqa: BLE001
        return m["name"], 0, str(e)[:70]

    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, f"{m['name']}.skel"), "wb") as fh:
        fh.write(skel)
    atlas_text = convert_atlas(atlas_raw.decode("utf-8", "replace"))
    with open(os.path.join(dest, f"{m['name']}.atlas"), "w", encoding="utf-8") as fh:
        fh.write(atlas_text)

    n = 2
    for page in atlas_pages(atlas_text):
        try:
            png = fetch(remote_path(game, m["dir"] + page))
        except Exception:
            continue
        with open(os.path.join(dest, page), "wb") as fh:
            fh.write(png)
        n += 1
    return m["name"], n, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Ambil Spine NIKKE/BD2 dari ArtHub")
    ap.add_argument("--game", required=True, choices=sorted(GAMES))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    out_dir = os.path.join(REPO, "assets", GAMES[args.game]["out"])
    os.makedirs(out_dir, exist_ok=True)

    log(f"membaca index {args.game}…")
    models = load_models(args.game)
    existing = {d for d in os.listdir(out_dir) if os.path.isdir(os.path.join(out_dir, d))}
    log(f"model di index: {len(models)} | sudah ada: {len(existing)}")

    todo = [m for m in models if m["name"] not in existing]
    log(f"belum ada: {len(todo)}")
    if args.limit:
        todo = todo[: args.limit]

    if not args.apply:
        log(json.dumps({"total": len(models), "have": len(existing), "new": len(todo),
                        "out": out_dir, "note": "putar --apply"}, indent=1))
        return 0

    ok, failed = 0, []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(download_one, args.game, m, out_dir) for m in todo]
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
            if i % 50 == 0 or i == len(todo):
                log(f"  {i}/{len(todo)} | ok {ok} | gagal {len(failed)}")

    log(json.dumps({"ok": ok, "gagal": len(failed), "sampel": failed[:5]},
                   indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
