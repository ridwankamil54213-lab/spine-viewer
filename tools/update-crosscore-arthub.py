#!/usr/bin/env python3
"""Tambah model CrossCore yang belum ada di viewer, dari ArtHub.

Latar belakang
==============

`tools/update-crosscore.py` (yang lama) mengambil dari mirror GitHub dan
melaporkan "80/80 installed, 0 missing". Tapi ArtHub punya index CrossCore
sendiri yang lebih baru:

    index  : https://talors1225.github.io/arthub-viewer-web/crosscore/crosscore_chars.json
    bucket : https://pub-3be583976a374ca9aacd740e9d14ad96.r2.dev

Perbandingan nama folder menyesatkan: index memakai nama BERKAS
(`20110_Arpeggio_character`) sedangkan viewer menyimpan per nama FOLDER
(`20110_break_arpeggio_spine`). Selisih awal 103 model menyusut jadi 56
setelah nama folder sumber ikut dicocokkan. Skrip ini memakai pencocokan
yang sama supaya tidak mengunduh ulang yang sudah ada.

Semua entri berbentuk JSON (Spine 4.2.20 / 4.2.38) sehingga tidak perlu
konversi — viewer sudah punya runtime 4.2.

CATATAN: `dir` memuat karakter non-ASCII (mis. `spine/剧情CG/...`).
Setiap path di-quote sebelum dipakai, kalau tidak R2 menolak.

Pemakaian
=========
    python tools/update-crosscore-arthub.py --check
    python tools/update-crosscore-arthub.py --apply [--limit N] [--workers 6]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import urllib.parse
import urllib.request

INDEX = "https://talors1225.github.io/arthub-viewer-web/crosscore/crosscore_chars.json"
BUCKET = "https://pub-3be583976a374ca9aacd740e9d14ad96.r2.dev"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
OUT_DIR = os.path.join(REPO, "assets", "crosscore")

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


def remote(rel: str) -> str:
    return f"{BUCKET}/crosscore/" + urllib.parse.quote(rel.lstrip("/"), safe="/")


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


def load_models() -> list[dict]:
    data = json.loads(fetch(INDEX).decode("utf-8", "replace"))
    out = []
    for c in data.get("characters", []):
        for s in (c.get("cutscenes") or []):
            skel = s.get("skel") or ""
            if not skel:
                continue
            dname = (s.get("dir") or "").rstrip("/").rsplit("/", 1)[-1]
            name = os.path.basename(skel)
            for suf in (".bytes", ".txt"):
                if name.endswith(suf):
                    name = name[: -len(suf)]
            stem = name.rsplit(".", 1)[0] if "." in name else name
            out.append({
                "stem": stem,
                "dname": dname,
                # folder di viewer memakai nama DIR (bukan nama berkas)
                "name": "".join(ch if ch.isalnum() or ch in "_-." else "_" for ch in dname) or stem,
                "dir": s.get("dir") or "",
                "skel": skel,
                "atlas": s.get("atlas") or "",
                "ver": c.get("spineVersion") or "",
            })
    return out


def download_one(m: dict) -> tuple[str, int, str | None]:
    dest = os.path.join(OUT_DIR, m["name"])
    try:
        skel = fetch(remote(m["dir"] + m["skel"]))
        atlas_raw = fetch(remote(m["dir"] + m["atlas"]))
    except Exception as e:  # noqa: BLE001
        return m["name"], 0, str(e)[:70]

    os.makedirs(dest, exist_ok=True)

    skel_name = os.path.basename(m["skel"])
    for suf in (".bytes", ".txt"):
        if skel_name.endswith(suf):
            skel_name = skel_name[: -len(suf)]
    if not skel_name.lower().endswith((".json", ".skel")):
        skel_name = skel_name.rsplit(".", 1)[0] + ".json"
    atlas_name = skel_name.rsplit(".", 1)[0] + ".atlas"

    with open(os.path.join(dest, skel_name), "wb") as fh:
        fh.write(skel)
    atlas_text = convert_atlas(atlas_raw.decode("utf-8", "replace"))
    with open(os.path.join(dest, atlas_name), "w", encoding="utf-8") as fh:
        fh.write(atlas_text)

    n = 2
    for page in atlas_pages(atlas_text):
        png = None
        for variant in (page, page.lower(), page.upper()):
            try:
                png = fetch(remote(m["dir"] + variant))
                break
            except Exception:
                continue
        if png is None:
            continue
        with open(os.path.join(dest, page), "wb") as fh:
            fh.write(png)
        n += 1
    return m["name"], n, None


def main() -> int:
    ap = argparse.ArgumentParser(description="CrossCore tambahan dari ArtHub")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    log("membaca index CrossCore (ArtHub)…")
    models = load_models()
    existing = {d for d in os.listdir(OUT_DIR) if os.path.isdir(os.path.join(OUT_DIR, d))}

    # Cocokkan dengan nama folder ATAU nomor ID di awal nama. Viewer menyimpan
    # 555 folder dengan nama folder sumber (mis. `20110_break_arpeggio_spine`),
    # sementara index memakai nama berkas (`20110_Arpeggio_character`).
    def already(m: dict) -> bool:
        if m["name"] in existing or m["dname"] in existing or m["stem"] in existing:
            return True
        prefix = m["stem"].split("_")[0]
        if prefix.isdigit():
            return any(e.startswith(prefix + "_") for e in existing)
        return False

    todo = [m for m in models if not already(m)]
    log(f"index: {len(models)} | folder viewer: {len(existing)} | belum ada: {len(todo)}")
    if args.limit:
        todo = todo[: args.limit]

    if not args.apply:
        log(json.dumps({"total": len(models), "have": len(existing), "new": len(todo),
                        "note": "putar --apply"}, indent=1))
        for m in todo[:15]:
            log(f"  {m['name']}  ({m['ver']})")
        return 0

    ok, failed = 0, []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(download_one, m) for m in todo]
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
            if i % 10 == 0 or i == len(todo):
                log(f"  {i}/{len(todo)} | ok {ok} | gagal {len(failed)}")

    log(json.dumps({"ok": ok, "gagal": len(failed), "sampel": failed[:5]},
                   indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
