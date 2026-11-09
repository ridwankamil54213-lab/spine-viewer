#!/usr/bin/env python3
"""Thumbnail Nikke dari poster ArtHub (`posters/nikki/`).

Repo Talors1225/arthub-viewer-web menyimpan 2102 poster WebP transparan,
satu per model, dengan nama `<id>--<variant>.webp`. `<variant>` diambil dari
`cutscenes[0].variant` di `nikki/nikki_chars.json` (nilainya `0` atau
`Catalog`) — cocok persis dengan suffix berkas di repo, jadi tidak perlu
menebak dari tree.

Dua model (`c330_aim_00`, `c550_aim_00`) tidak punya poster sendiri: fallback
ke poster root karakternya (`c330_00`, `c550_00`).

Bentuk: TIDAK di-crop, diperkecil agar muat 300x300 dengan aspect ratio utuh
(588x1280 -> ~138x300). CSS kartu `object-fit: contain` menangani sisi kosong.
Konversi lewat /usr/bin/ffmpeg (`libwebp`), bukan Pillow.

Keluaran: public/thumbs/nikke/<id>.webp + _manifest.json
          (kunci "nikke/<id>" -> "<id>.webp").

Usage: python3 tools/nikke/refresh-thumbs.py [--limit N] [--workers N]
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
OUT = Path(os.environ.get("NIKKE_THUMBS_OUT", str(VIEW / "public" / "thumbs" / "nikke")))
CATALOG = ("https://raw.githubusercontent.com/Talors1225/arthub-viewer-web/main/"
           "nikki/nikki_chars.json")
POSTER = ("https://raw.githubusercontent.com/Talors1225/arthub-viewer-web/main/"
          "posters/nikki/")
UA = "spine-viewer-nikke-updater/1.0"
MAX_SIDE = 300


def fetch(url: str, timeout: int = 90, retries: int = 3) -> bytes:
    curl = shutil.which("curl") or "/usr/bin/curl"
    last = None
    for attempt in range(retries):
        fd, tmp = tempfile.mkstemp(prefix="nikkethumb-", suffix=".bin")
        os.close(fd)
        try:
            p = subprocess.run(
                [curl, "-sSL", "--max-time", str(timeout), "-A", UA,
                 "-o", tmp, "-w", "%{http_code}", url],
                capture_output=True, timeout=timeout + 20)
            code = (p.stdout or b"").strip().decode("ascii", "replace")
            if p.returncode == 0 and code.startswith("2"):
                return Path(tmp).read_bytes()
            if code == "404":
                raise FileNotFoundError(url)
            last = f"HTTP {code}"
        except FileNotFoundError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def root_slug(slug: str) -> str | None:
    s = slug[8:] if slug.startswith("catalog-") else slug
    for pat in (r"^(c\d{3})_aim_(\d{2})$", r"^(c\d{3})_cover_(\d{2})$",
                r"^(c\d{3})_(\d{2})_skillcut$", r"^(c\d{3})_(\d{2})$"):
        m = re.match(pat, s)
        if m:
            return f"{m.group(1)}_{m.group(2)}"
    return None


def convert(data: bytes, dest: Path) -> bool:
    if dest.is_file() and dest.stat().st_size > 512:
        return True
    ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    src = dest.with_suffix(".src.webp")
    tmp = dest.with_suffix(".tmp.webp")
    try:
        src.write_bytes(data)
        p = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(src),
             "-vf", f"scale={MAX_SIDE}:{MAX_SIDE}:force_original_aspect_ratio=decrease",
             "-frames:v", "1", "-c:v", "libwebp", "-quality", "82",
             "-compression_level", "4", str(tmp)],
            capture_output=True, timeout=120)
        if p.returncode != 0 or not tmp.is_file():
            return False
        b = tmp.read_bytes()
        if not b.startswith(b"RIFF") or len(b) < 512:
            return False
        tmp.replace(dest)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        src.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)


def grab(ch: dict, variants: dict) -> tuple[str, str, str]:
    cid = ch["id"]
    variant = str((ch.get("cutscenes") or [{}])[0].get("variant", "0"))
    names = [f"{cid}--{variant}.webp"]
    root = root_slug(cid)
    if root and root != cid:
        names.append(f"{root}--{variants.get(root, 'Catalog')}.webp")
    dest = OUT / f"{cid}.webp"
    if dest.is_file() and dest.stat().st_size > 512:
        return cid, "skip", ""
    for name in names:
        try:
            data = fetch(POSTER + urllib.parse.quote(name))
        except FileNotFoundError:
            continue
        except Exception as e:  # noqa: BLE001
            return cid, "fail", str(e)[:100]
        if data.startswith(b"RIFF"):
            if convert(data, dest):
                return cid, "ok", ""
            # Sebagian poster adalah WebP animasi yang decoder ffmpeg tidak
            # bisa baca. Berkasnya sendiri valid untuk <img>, jadi simpan apa
            # adanya daripada membiarkan model tanpa thumbnail.
            try:
                dest.write_bytes(data)
                return cid, "asli", ""
            except Exception as e:  # noqa: BLE001
                return cid, "fail", str(e)[:100]
    return cid, "fail", "poster tidak ada"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=10)
    a = ap.parse_args()

    print("mengambil katalog ArtHub nikki…", file=sys.stderr, flush=True)
    chars = json.loads(fetch(CATALOG, timeout=120))["characters"]
    variants = {x["id"]: str((x.get("cutscenes") or [{}])[0].get("variant", "Catalog"))
                for x in chars}
    if a.limit:
        chars = chars[: a.limit]
    OUT.mkdir(parents=True, exist_ok=True)

    counts, errors = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        for i, (cid, status, err) in enumerate(
                pool.map(lambda c: grab(c, variants), chars), 1):
            counts[status] = counts.get(status, 0) + 1
            if status == "fail":
                errors.append(f"{cid}: {err}")
            if i % 300 == 0 or i == len(chars):
                print(f"  {i}/{len(chars)}", file=sys.stderr, flush=True)

    good = [c["id"] for c in chars if (OUT / f"{c['id']}.webp").is_file()
            and (OUT / f"{c['id']}.webp").stat().st_size > 512]
    manifest = {f"nikke/{cid}": f"{cid}.webp" for cid in good}
    if not a.limit:
        (OUT / "_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")

    print(json.dumps({
        "katalog": len(chars),
        "thumbs": counts,
        "manifest": len(manifest),
        "errors": errors[:12],
        "note": "mode uji — manifest tidak ditulis" if a.limit else "ok",
    }, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
