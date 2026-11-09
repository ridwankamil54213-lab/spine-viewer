#!/usr/bin/env python3
"""Unduh ulang model Nikke dari ArtHub (Talors1225/arthub-viewer-web/nikki).

Repo GitHub itu cuma menyimpan KATALOG + viewer, bukan berkas modelnya.
Aset aslinya ada di bucket R2 yang dipakai `arthub-cos.js`:

    katalog : raw.githubusercontent.com/Talors1225/arthub-viewer-web/main/
             nikki/nikki_chars.json           -> 2104 karakter
             nikki/character-names.json       -> 131 profil nama (opsional)
    aset    : https://pub-bdd986c6ec274f53b01df62ac49e02e2.r2.dev
             /nikki/spine_carved/<folder>/
             (PATH_REWRITES: /nikki/spine/ -> /nikki/spine_carved/)

Tiap karakter = satu cutscene: <nama>.skel (Spine binary 4.1.20) +
<nama>.atlas (`pma:true`) + satu/lebih halaman PNG yang disebut di atlas.

Aturan penulisan (sama seperti tools/mad-drama/refresh.py):
  * skel + atlas di-rename ke <id>.skel / <id>.atlas supaya id model stabil;
  * nama berkas HALAMAN tetap persis seperti baris di atlas — menggantinya
    bikin 404 walaupun filenya ada;
  * `spine_carved` dipakai apa adanya, tidak ada dekripsi/Unity bundle.

Idempoten: folder yang sudah punya skel + atlas + semua halaman dilewati.

Usage: python3 tools/nikke/refresh.py [--limit N] [--workers N]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("NIKKE_OUT", str(VIEW / "assets" / "nikke")))
CATALOG = ("https://raw.githubusercontent.com/Talors1225/arthub-viewer-web/main/"
           "nikki/nikki_chars.json")
NAMES = ("https://raw.githubusercontent.com/Talors1225/arthub-viewer-web/main/"
         "nikki/character-names.json")
# Sumber nama karakter (diminta user): halaman https://nkas.pages.dev/nikkes/
# memuat /nk_data/nikkegg/characters.json lewat _astro/nikkes.js. Field `img`
# berisi "si_c102_00_s" -> kode c102, dan `name` sudah bahasa Inggris.
NKAS = "https://nkas.pages.dev/nk_data/nikkegg/characters.json"
# Situs saudara NKAS (dipakai /nikkes/ juga lewat new.json). 571 entri
# "c013_00" -> "Marian" menutup NPC/enemy yang tidak ada di 206 entri utama.
NKAS_L2D = "https://nkas-l2d.pages.dev/characters.json"
ASSET_ROOT = "https://pub-bdd986c6ec274f53b01df62ac49e02e2.r2.dev"
UA = "spine-viewer-nikke-updater/1.0"
PAGE_EXT = (".png", ".webp", ".jpg", ".jpeg")

# Katalog ArtHub memakai label tipe berbahasa Tionghoa (剧情 / 过场, 目录素材,
# …). resourceType sudah berbahasa Inggris, jadi pakai itu untuk tampilan.
TYPE_LABEL = {
    "battle": "Battle", "lobby": "Lobby", "catalog": "Catalog",
    "skill": "Skill", "cutscene": "Cutscene", "other": "Other",
    "store": "Store", "idle": "Idle",
}


def fetch(url: str, timeout: int = 120, retries: int = 3) -> bytes:
    """curl; 404 -> FileNotFoundError, 5xx/timeout -> retry."""
    curl = shutil.which("curl") or "/usr/bin/curl"
    last = None
    for attempt in range(retries):
        fd, tmp = tempfile.mkstemp(prefix="nikkedl-", suffix=".bin")
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
                raise FileNotFoundError(url)
            last = f"HTTP {code} rc={p.returncode}"
        except FileNotFoundError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def load_json(url: str):
    return json.loads(fetch(url, timeout=120).decode("utf-8", "replace"))


def atlas_pages(atlas: bytes) -> list[str]:
    """Nama halaman = baris ber-ekstensi gambar sebelum baris `size:`.

    Beberapa atlas ArtHub diawali BOM UTF-8; kalau tidak dibuang, nama
    halaman pertama jadi `\\ufeffc010_00.png` dan URL-nya 404.
    """
    pages = []
    text = atlas.decode("utf-8-sig", "replace")
    for line in text.splitlines():
        s = line.strip().lstrip("\ufeff").strip()
        if s.lower().endswith(PAGE_EXT) and "/" not in s and "\\" not in s:
            pages.append(s)
    return list(dict.fromkeys(pages))


def grab(ch: dict, workers_state: dict) -> tuple[str, str, str]:
    """(id, status, err). status = ok | skip | fail."""
    cid = ch["id"]
    cut = (ch.get("cutscenes") or [{}])[0]
    folder = (cut.get("dir") or "").rstrip("/").split("/")[-1]
    skel_name = cut.get("skel") or f"{folder}.skel"
    atlas_name = cut.get("atlas") or f"{folder}.atlas"
    base = f"{ASSET_ROOT}/nikki/spine_carved/{urllib.parse.quote(folder)}"
    dest = OUT / cid

    # Idempoten: cukup cek keberadaan, jangan unduh ulang semua halaman.
    if (dest / f"{cid}.skel").is_file() and (dest / f"{cid}.atlas").is_file():
        pages = atlas_pages((dest / f"{cid}.atlas").read_bytes())
        if all((dest / p).is_file() for p in pages):
            return cid, "skip", ""

    try:
        skel = fetch(f"{base}/{urllib.parse.quote(skel_name)}")
        atlas = fetch(f"{base}/{urllib.parse.quote(atlas_name)}")
        pages = atlas_pages(atlas)
        if not pages:
            return cid, "fail", "atlas tanpa halaman gambar"
        blobs = {}
        for p in pages:
            blobs[p] = fetch(f"{base}/{urllib.parse.quote(p)}")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"{cid}.skel").write_bytes(skel)
        (dest / f"{cid}.atlas").write_bytes(atlas)
        for name, data in blobs.items():
            (dest / name).write_bytes(data)
        return cid, "ok", ""
    except FileNotFoundError as e:
        return cid, "fail", f"404 {str(e).split('/')[-1][:60]}"
    except Exception as e:  # noqa: BLE001
        return cid, "fail", str(e)[:110]


def load_nkas() -> tuple[dict, dict, dict]:
    """(kode cNNN -> nama, url -> nama, cNNN_NN -> nama) dari NKAS."""
    try:
        rows = json.loads(fetch(NKAS, timeout=90))
    except Exception:  # noqa: BLE001
        rows = []
    by_code, by_slug = {}, {}
    for x in rows:
        name = str(x.get("name") or "").strip()
        if not name:
            continue
        m = re.search(r"(c\d{3})", str(x.get("img") or ""))
        if m:
            by_code[m.group(1)] = name
        url = str(x.get("url") or "").strip().lower()
        # Url satu huruf ("d", "k") bikin false positive di slug; abaikan.
        if len(url) >= 3:
            by_slug[url] = name
    try:
        by_full = {str(k): str(v).strip() for k, v in
                   json.loads(fetch(NKAS_L2D, timeout=90)).items() if str(v).strip()}
    except Exception:  # noqa: BLE001
        by_full = {}
    return by_code, by_slug, by_full


def slug_name(slug: str, by_slug: dict) -> str | None:
    """Cocokkan url NKAS TERPANJANG yang terkandung dalam id model."""
    s = slug.lower()
    best = None
    for url, name in by_slug.items():
        if url in s and (best is None or len(url) > len(best[0])):
            best = (url, name)
    return best[1] if best else None


def build_names(chars: list, profiles: dict, by_code: dict, by_slug: dict,
                by_full: dict) -> dict:
    """Nama Inggris dari NKAS; label tipe dari resourceType (bukan Tionghoa)."""
    out = {}
    for ch in chars:
        cid = ch["id"]
        code = str(ch.get("characterCode") or "").strip()
        nk_code = by_code.get("c" + code.lstrip("c").zfill(3)) if code else None
        # Slug matching cuma untuk entri yang memang bertanda karakter.
        # Kalau dipakai bebas, "EVE" nyangkut di "EventScene_*", "Ade" di
        # "madeinrush_*", dan "Mica" di "chemical".
        nk_slug = slug_name(cid, by_slug) if str(ch.get("characterName") or "").strip() else None
        m = re.search(r"(c\d{3})_(?:aim_|cover_)?(\d{2})", cid)
        full = by_full.get(f"{m[1]}_{m[2]}") if m else None
        prof = profiles.get(code.lstrip("c")) if code else None
        prof_name = (prof or {}).get("characterNameEn") or ch.get("characterNameEn")
        raw_display = (ch.get("displayName") or ch.get("name") or cid).strip()
        # Bagian sebelum " · " biasanya ASCII ("Chapter4 Glass Back2").
        ascii_part = raw_display.split(" · ")[0].strip() or cid
        name = str(nk_code or full or nk_slug or prof_name or "").strip() or ascii_part
        # Jangkar terakhir: jangan biarkan aksara Tionghoa lolos ke UI.
        if re.search(r"[\u4e00-\u9fff]", name):
            cleaned = re.sub(r"\s+", " ", re.sub(r"[\u4e00-\u9fff]", "", name)).strip()
            # "角色 C013" -> "C013"; jangan biarkan jadi nama polos kalau
            # peta NKAS punya nama aslinya (Marian, Shifty, …).
            cm = re.fullmatch(r"[Cc](\d{3})", cleaned)
            if cm:
                cleaned = (by_full.get(f"c{cm[1]}_00")
                           or by_code.get(f"c{cm[1]}") or cleaned)
            name = cleaned or cid.split("/")[-1]
        # Nama kode polos dari katalog (mis. "C907") juga dapat nama aslinya.
        cm2 = re.fullmatch(r"[Cc](\d{3})", name)
        if cm2:
            name = (by_full.get(f"c{cm2[1]}_00")
                    or by_code.get(f"c{cm2[1]}") or name)
        rtype = ch.get("resourceType") or "other"
        tlabel = TYPE_LABEL.get(rtype, rtype.capitalize())
        out[f"nikke/{cid}"] = {
            "name": name,
            "display": f"{name} · {tlabel}",
            "characterName": name,
            "characterCode": code or None,
            "resourceType": rtype,
            "typeLabel": tlabel,
            "nameSource": ("nkas-code" if nk_code else "nkas-l2d" if full
                           else "nkas-slug" if nk_slug
                           else "arthub-profile" if prof_name else "catalog-ascii"),
            "source": "nkas.pages.dev/nikkes + arthub-viewer-web/nikki",
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--names-only", action="store_true",
                    help="regenerasi _names.json saja, tanpa unduh model")
    a = ap.parse_args()

    print("mengambil katalog ArtHub nikki…", file=sys.stderr, flush=True)
    catalog = load_json(CATALOG)
    chars = catalog["characters"]
    try:
        profiles = (load_json(NAMES).get("entries") or {})
    except Exception:  # noqa: BLE001
        profiles = {}
    by_code, by_slug, by_full = load_nkas()
    print(f"karakter {len(chars)} · profil {len(profiles)} · NKAS {len(by_code)} kode / "
          f"{len(by_full)} entri l2d", file=sys.stderr, flush=True)
    if a.limit:
        chars = chars[: a.limit]

    names = build_names(chars, profiles, by_code, by_slug, by_full)
    # Jangan timpa _names.json yang sudah Inggris kalau kedua sumber NKAS mati.
    names_ok = bool(by_code or by_full)
    if not names_ok:
        print("PERINGATAN: sumber NKAS tidak tersedia — _names.json tidak diubah",
              file=sys.stderr, flush=True)
    if a.names_only:
        if not names_ok:
            raise SystemExit("sumber NKAS tidak tersedia — _names.json tidak diubah")
        (OUT / "_names.json").write_text(
            json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")
        from collections import Counter
        src = Counter(v["nameSource"] for v in names.values())
        print(json.dumps({"mode": "names-only", "names": len(names),
                          "sources": dict(src)}, indent=1, ensure_ascii=False))
        return

    OUT.mkdir(parents=True, exist_ok=True)
    counts, errors = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        for i, (cid, status, err) in enumerate(
                pool.map(lambda c: grab(c, {}), chars), 1):
            counts[status] = counts.get(status, 0) + 1
            if status == "fail":
                errors.append(f"{cid}: {err}")
            if i % 200 == 0 or i == len(chars):
                print(f"  {i}/{len(chars)}", file=sys.stderr, flush=True)

    if not a.limit and names_ok:
        (OUT / "_names.json").write_text(
            json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")

    res = {
        "katalog": len(chars),
        "models": counts,
        "names": len(names),
        "errors": errors[:15],
        "note": "mode uji — _names.json tidak ditulis" if a.limit else "ok",
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
