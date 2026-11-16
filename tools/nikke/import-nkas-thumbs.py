#!/usr/bin/env python3
"""Impor potret NIKKE dari NKAS.

Sumber:
  https://nkas-l2d.pages.dev/characters.json
    {"c010_00": "Rapi", ..., "c9000_00": "Alfred", ...}
  https://nkas.pages.dev/characters/mi_<kode>_s.png
    PNG 256x496; server memblokir request tanpa UA browser.

Kenapa overlay terpisah (`nikke-nkas`)?
  Filter & metadata masih memakai hasil `import-prydwen.py`, tetapi potret
  karakter diganti dari sumber NKAS. Manifest folder ini diproses PALING
  AKHIR oleh `thumbManifest()` sehingga menimpa `nikke-prydwen` dan `nikke`.

Skillcut sengaja tidak punya kartu sendiri: `nikkiVariantOf()` di server
memasukkan semua `*_skillcut` ke family root. Manifest tetap memuat id
skillcut supaya thumbnail di popup varian ikut potret karakter yang sama.

Hasil:
  public/thumbs/nikke-nkas/<kode>.webp
  public/thumbs/nikke-nkas/_manifest.json   id model -> nikke-nkas/<kode>.webp
  data/nikke-nkas-thumbs.json               jejak sumber + statistik

Usage:
  python3 tools/nikke/import-nkas-thumbs.py
"""
from __future__ import annotations

import concurrent.futures
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

VIEW = Path(__file__).resolve().parents[2]
LIST_URL = "https://nkas-l2d.pages.dev/characters.json"
IMAGE_BASE = "https://nkas.pages.dev/characters/"
THUMBS = VIEW / "public" / "thumbs" / "nikke-nkas"
DATA = VIEW / "data" / "nikke-nkas-thumbs.json"
NAMES = VIEW / "assets" / "nikke" / "_names.json"
SPINE_URL = os.environ.get("SPINE_URL", "http://127.0.0.1:3000")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": "https://nkas.pages.dev/",
}
CODE_RE = re.compile(r"^(?:catalog-)?(c\d{4}|c\d{3})")
KEY_RE = re.compile(r"^c\d{3,4}_\d{2}$")


def get(url: str, tries: int = 4, timeout: int = 60) -> bytes:
    last = None
    for i in range(tries):
        # Beberapa objek kena cached 403 walaupun UA sudah benar.
        u = url if i == 0 else url + ("&" if "?" in url else "?") + f"_cb={int(time.time()*1000)}"
        try:
            req = urllib.request.Request(u, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(min(8, 1.2 * (2 ** i)))
    raise RuntimeError(f"gagal {url}: {last}")


def image_url(key: str) -> str:
    return IMAGE_BASE + "mi_" + urllib.parse.quote(key) + "_s.png"


class Unavailable(Exception):
    """URL ada (HTTP 200) tapi mengembalikan halaman HTML, bukan potret."""


def download(key: str) -> tuple[str, int]:
    dest = THUMBS / f"{key}.webp"
    if dest.is_file() and dest.stat().st_size > 512:
        return key, 0
    data = get(image_url(key))
    if not data.startswith(b"\x89PNG"):
        raise Unavailable(key)
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=84, method=6)
    out = buf.getvalue()
    if not out.startswith(b"RIFF"):
        raise RuntimeError(f"{key}: konversi WebP gagal")
    dest.write_bytes(out)
    return key, len(out)


def model_ids() -> list[str]:
    try:
        req = urllib.request.Request(
            f"{SPINE_URL}/api/models?game=nikke&lean=1",
            headers={"User-Agent": "spine-viewer-import/1.0"})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.load(r)
        ids = [m["id"] for m in (d.get("models") or []) if m.get("id")]
        if len(ids) > 100:
            return ids
    except Exception:  # noqa: BLE001
        pass
    if NAMES.exists():
        return list(json.loads(NAMES.read_text(encoding="utf-8")).keys())
    return []


def choose_key(leaf: str, keys: set[str], by_code: dict[str, list[str]]) -> str | None:
    """Pilih kode potret terbaik untuk satu id model.

    Prioritas: kode persis -> prefiks terpanjang (`c017_01_skillcut` ->
    `c017_01`) -> keluarga `c017_*` -> `c017_00`.
    """
    s = re.sub(r"^catalog-", "", leaf)
    s = re.sub(r"--core-\d+$", "", s).replace("slillcut", "skillcut")
    if s in keys:
        return s
    # aim/cover/skillcut memakai nomor kostum yang sama dengan rig utama.
    pref = [k for k in keys if s.startswith(k + "_")]
    if pref:
        return max(pref, key=len)
    m = CODE_RE.match(s)
    if not m:
        return None
    code = m.group(1)
    opts = by_code.get(code) or []
    if not opts:
        # c9000_00 -> kode induk c9000 bila katalog memakai 4 digit.
        parent = re.match(r"^(c\d{3})", code)
        opts = by_code.get(parent.group(1), []) if parent else []
    if not opts:
        return None
    return "c017_00" if "c017_00" in opts else opts[0]


def main() -> int:
    t0 = time.time()
    listing = json.loads(get(LIST_URL).decode("utf-8", "replace"))
    if not isinstance(listing, dict) or len(listing) < 300:
        print(json.dumps({"ok": False, "error": "daftar NKAS tidak valid"},
                         ensure_ascii=False))
        return 1
    keys = set(listing)
    by_code: dict[str, list[str]] = {}
    for k in keys:
        m = CODE_RE.match(k)
        if m:
            by_code.setdefault(m.group(1), []).append(k)
    for v in by_code.values():
        v.sort(key=lambda x: (x != "c017_00" and not x.endswith("_00"), x))

    THUMBS.mkdir(parents=True, exist_ok=True)
    # File dari run sebelumnya tetap dihitung sebagai potret tersedia.
    available = {k for k in keys
                 if (THUMBS / f"{k}.webp").is_file()
                 and (THUMBS / f"{k}.webp").stat().st_size > 512}
    failed, unavailable = [], set()
    nbytes = 0
    todo = [k for k in sorted(keys) if k not in available]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(download, k): k for k in todo}
        for fut in concurrent.futures.as_completed(futs):
            k = futs[fut]
            try:
                nbytes += fut.result()[1]
                available.add(k)
            except Unavailable:
                unavailable.add(k)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{k}: {str(exc)[:120]}")

    # Hanya pakai kode yang benar-benar punya WebP; kalau varian utama tidak
    # tersedia, jatuh ke varian lain dari karakter yang sama.
    by_code = {c: sorted(k for k in v if k in available)
               for c, v in by_code.items()}
    by_code = {c: v for c, v in by_code.items() if v}
    ids = model_ids()
    mapping: dict[str, str] = {}
    unmatched = 0
    for mid in ids:
        leaf = mid.split("/")[-1]
        key = choose_key(leaf, available, by_code)
        if key:
            mapping[mid] = f"nikke-nkas/{key}.webp"
        else:
            unmatched += 1

    manifest = {mid: mapping[mid] for mid in sorted(mapping)}
    (THUMBS / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    DATA.write_text(json.dumps({
        "source": LIST_URL,
        "imageBase": IMAGE_BASE + "mi_<kode>_s.png",
        "fetchedAt": int(time.time()),
        "entries": len(keys),
        "models": len(mapping),
        "unmatched": unmatched,
        "unavailable": sorted(unavailable),
        "failed": failed[:12],
    }, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    res = {
        "ok": not failed,
        "entries": len(keys),
        "available": len(available),
        "unavailable": len(unavailable),
        "newFiles": len(todo) - len(unavailable) - len(failed),
        "bytes": nbytes,
        "modelIds": len(mapping),
        "unmatched": unmatched,
        "failed": failed[:8],
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
