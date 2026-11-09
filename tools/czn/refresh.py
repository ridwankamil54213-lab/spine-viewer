#!/usr/bin/env python3
"""Refresh the Chaos Zero Nightmare library from its two authoritative sources.

Sources
-------
rigs    BenNoSleep/czn-animation-viewer (GitHub, branch ``main``), folder ``rigs/``.
roster  e7bot wiki ``/api/czn/characters/list`` — the exact same (AES-encrypted)
        list that drives the Combatant and Partner tabs. Only rigs whose
        character id is in that roster are downloaded; monsters, NPCs, gods and
        unused portraits are skipped.

The wiki serves the roster encrypted with AES-256-CBC. The key is published in
its own JS bundle; the first 16 bytes of the payload are the IV.

Outputs
-------
assets/czn-rigs/<slug>/<slug>.json|atlas + texture page
assets/czn-rigs/_names.json                     (slug -> wiki display name)
public/thumbs/czn-rigs/_manifest.json            (model id -> <charid>.png)

Thumbnails themselves are captured from the live wiki by
``tools/czn/capture-thumbs.cjs`` — run that after (or before) this script.

Idempotent: existing downloads / converted rigs are skipped. No commit, no
deletion of anything outside ``assets/czn-rigs``.

Usage: python3 tools/czn/refresh.py
"""
from __future__ import annotations

import base64
import concurrent.futures
import gzip
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

VIEW = Path(__file__).resolve().parents[2]
ASSETS = VIEW / "assets" / "czn-rigs"
THUMBS = VIEW / "public" / "thumbs" / "czn-rigs"
STAGE = Path("/tmp/czn-repo/rigs")

REPO = "BenNoSleep/czn-animation-viewer"
BRANCH = "main"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
TREE_API = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
INDEX_URL = f"{RAW}index.json"
WIKI_LIST = "https://wiki.e7bot.top/api/czn/characters/list?lang=en"
WIKI_KEY = b"2egkWEkLvR9idARLvjqfJdWKfR24HJgY"  # 32 bytes, AES-256
IMG = re.compile(r"\.(png|webp|jpg|jpeg)$", re.I)
WORKERS = 16


def fetch(url: str, tries: int = 4) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "spine-viewer-czn-refresh/1.0"}
            )
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"gagal mengunduh {url}: {last}")


def wiki_roster() -> dict[str, dict]:
    payload = json.loads(fetch(WIKI_LIST))
    if not payload.get("encrypted"):
        chars = payload.get("data", [])
    else:
        raw = base64.b64decode(payload["data"])
        iv, ct = raw[:16], raw[16:]
        dec = Cipher(algorithms.AES(WIKI_KEY), modes.CBC(iv)).decryptor()
        out = dec.update(ct) + dec.finalize()
        unpad = padding.PKCS7(128).unpadder()
        out = unpad.update(out) + unpad.finalize()
        body = json.loads(out.decode("utf-8"))
        chars = body.get("data", body)
    if not isinstance(chars, list):
        raise RuntimeError("bentuk daftar karakter wiki tidak dikenal")
    roster = {str(c["id"]): c for c in chars}
    kinds = {}
    for c in chars:
        kinds[c.get("char_type", "?")] = kinds.get(c.get("char_type", "?"), 0) + 1
    print(f"roster wiki: {len(roster)} karakter {kinds}")
    return roster


def char_id(rec: dict) -> str | None:
    m = re.match(r"^(\d+)", str(rec.get("id") or rec.get("slug") or ""))
    return m.group(1) if m else None


def atlas_page(atlas: Path) -> str | None:
    try:
        lines = atlas.read_text(encoding="latin1").splitlines()
    except OSError:
        return None
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and re.match(r"\s*size:", lines[i + 1]) and IMG.search(line.strip()):
            return line.strip()
    return None


def main() -> None:
    roster = wiki_roster()
    tree = json.loads(fetch(TREE_API))
    if tree.get("truncated"):
        raise RuntimeError("GitHub tree terpotong; pakai estrategi lain")
    entries = [
        e for e in tree["tree"]
        if e["path"].startswith("rigs/") and e["type"] == "blob" and e["path"].count("/") == 2
    ]
    catalog = json.loads(fetch(INDEX_URL))
    rigs = catalog.get("rigs", [])
    selected = [r for r in rigs if char_id(r) in roster]
    slugs = {r["slug"] for r in selected}
    files = [e for e in entries if e["path"].split("/")[1] in slugs]
    total_bytes = sum(e.get("size", 0) for e in files)
    print(f"rig terpilih: {len(selected)}/{len(rigs)}  file: {len(files)}  {total_bytes/1e6:.1f} MB")
    if not selected:
        raise RuntimeError("irisan kosong — batal")

    # ---- 1. unduh hanya file yang dibutuhkan -----------------------------
    STAGE.mkdir(parents=True, exist_ok=True)
    missing = []
    for e in files:
        slug, name = e["path"].split("/")[1], e["path"].split("/")[2]
        dest = STAGE / slug / name
        size = e.get("size", 0)
        if dest.exists() and (not size or dest.stat().st_size == size):
            continue
        missing.append((e["path"], dest, size))

    def dl(item):
        rel, dest, size = item
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = RAW + urllib.parse.quote(rel, safe="/")
        data = fetch(url)
        if size and len(data) != size:
            raise RuntimeError(f"ukuran beda {rel}: {len(data)} != {size}")
        dest.write_bytes(data)
        return len(data)

    if missing:
        print(f"mengunduh {len(missing)} file ({len(files)-len(missing)} sudah ada) ...")
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = {pool.submit(dl, it): it for it in missing}
            for fut in concurrent.futures.as_completed(futs):
                fut.result()  # fail loud, jangan diam-diam bikin rig rusak
                done += 1
                if done % 150 == 0:
                    print(f"  {done}/{len(missing)}")
        print(f"unduh selesai: {done} file")
    else:
        print("semua file sudah ada, lewati unduh")

    # ---- 2. konversi ke format yang dikenal scanner ---------------------
    ASSETS.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    converted = skipped = 0
    for slug in sorted(slugs):
        src = STAGE / slug
        if not src.is_dir():
            continue
        cand = list(src.iterdir())
        sj = next((f for f in cand if f.suffix.lower() == ".json"), None)
        sa = next((f for f in cand if f.suffix.lower() == ".atlas"), None)
        img = next((f for f in cand if IMG.search(f.name)), None)
        if not sj or not sa:
            print(f"  lewati {slug}: json/atlas tidak ada")
            continue
        dest = ASSETS / slug
        if (dest / f"{slug}.json").exists() and (dest / f"{slug}.atlas").exists():
            skipped += 1
            continue
        dest.mkdir(parents=True, exist_ok=True)
        raw = sj.read_bytes()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        (dest / f"{slug}.json").write_bytes(raw)
        shutil.copy(sa, dest / f"{slug}.atlas")
        if img:
            # Atlas menyebut nama halaman ASLI (mis. 1003.webp), bukan slug.
            page = atlas_page(sa) or img.name
            shutil.copy(img, dest / page)
        converted += 1
    print(f"konversi: {converted} rig baru, {skipped} sudah ada")

    # ---- 3. nama dari wiki + manifest thumbnail -------------------------
    names = {}
    manifest = {}
    for r in selected:
        slug = r["slug"]
        cid = char_id(r)
        assert cid is not None, f"rig tanpa id karakter: {slug}"
        c = roster[cid]
        names[slug] = {
            "name": c.get("name") or c.get("names", {}).get("en") or cid,
            "kind": "",
            "subtype": r.get("subtype"),
            "charType": c.get("char_type"),
            "ego": c.get("ego"),
            "job": c.get("job"),
            "rarity": c.get("rarity"),
        }
        manifest[f"czn-rigs/{slug}"] = f"{cid}.png"
    (ASSETS / "_names.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (THUMBS / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"_names.json: {len(names)}  _manifest.json: {len(manifest)}")
    print("Selesai. Jalankan tools/czn/capture-thumbs.cjs untuk thumbnail, lalu ?refresh=1.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print("GAGAL:", exc, file=sys.stderr)
        sys.exit(1)
