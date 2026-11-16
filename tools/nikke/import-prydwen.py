#!/usr/bin/env python3
"""Impor potret & metadata karakter NIKKE dari Prydwen.

Sumber: https://www.prydwen.gg/nikke/characters
Halaman SSR Next.js menyisipkan seluruh daftar karakter di dalam string
`self.__next_f.push([1, "...\\"characters\\":[{...}]..."])`. Blob itu berisi
227 karakter lengkap dengan rarity / class / element / weapon / manufacturer /
squad / burstType / cardImage — jauh lebih kaya daripada markup kartunya.

Jembatan ke aset kita: `data/nikke-characters.json` (199 entri) memetakan
`url`/`name` -> `img` = `si_c010_00_s`, dan model kita ber-id `nikke/c010*`.
Jadi cocokkan karakter Prydwen ke entri itu, ambil kode `cNNN`, lalu sebarkan
ke SELURUH model dengan prefiks kode tersebut (rig utama, aim/cover/skillcut,
kostum `_NN`, dll). Karakter katalog tanpa padanan Prydwen tetap dapat metadata
filter (dari katalog) tetapi memakai thumbnail lama.

Hasil:
  public/thumbs/nikke-prydwen/<slug>_card.webp   227 potret 262x358
  public/thumbs/nikke-prydwen/*.webp             26 ikon (element/class/weapon/burst)
  public/thumbs/nikke-prydwen/_manifest.json     id model -> potret (override)
  data/nikke-prydwen.json                       byCode + pemetaan id model

Idempoten: berkas yang sudah ada dilewati. Daftar id model diambil dari
API lokal (SPINE_URL), dengan fallback ke assets/nikke/_names.json kalau
server sedang mati.

Usage:
    python3 tools/nikke/import-prydwen.py
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
PAGE = "https://www.prydwen.gg/nikke/characters"
SPINE_URL = os.environ.get("SPINE_URL", "http://127.0.0.1:3000")
THUMBS = VIEW / "public" / "thumbs" / "nikke-prydwen"
DATA = VIEW / "data" / "nikke-prydwen.json"
CATALOG = VIEW / "data" / "nikke-characters.json"
NAMES = VIEW / "assets" / "nikke" / "_names.json"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
}
ICON_RE = re.compile(r"https://cdn\.prydwen\.gg/images/nikke/icons/([A-Za-z0-9_\-]+\.webp)")
CODE_RE = re.compile(r"^(?:catalog-)?(c\d{3})")
# Singkatan senjata di katalog lama -> nama penuh ala Prydwen.
WEAPON = {
    "AR": "Assault Rifle", "SG": "Shotgun", "SMG": "SMG",
    "SR": "Sniper Rifle", "MG": "Minigun", "RL": "Rocket Launcher",
}


def get(url: str, tries: int = 4, timeout: int = 90) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(min(10, 1.5 * (2 ** i)))
    raise RuntimeError(f"gagal mengambil {url}: {last}")


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_characters(page: str) -> list[dict]:
    i = page.find('\\"characters\\":[')
    if i < 0:
        raise RuntimeError("blob characters tidak ketemu — markup Prydwen berubah")
    seg = page[i:].replace('\\"', '"')
    arr, _ = json.JSONDecoder().raw_decode(seg[seg.find("["):])
    if not isinstance(arr, list) or len(arr) < 100:
        raise RuntimeError(f"daftar karakter terlalu sedikit: {len(arr)}")
    return arr


def download(url: str) -> int:
    name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    dest = THUMBS / name
    if dest.exists() and dest.stat().st_size > 128:
        return 0
    data = get(url)
    if not (data.startswith(b"RIFF") or data.startswith(b"\x89PNG")):
        raise RuntimeError(f"{name}: bukan WebP/PNG valid")
    dest.write_bytes(data)
    return len(data)


def model_ids() -> list[str]:
    """Semua id model NIKKE, dari API hidup kalau ada, else dari _names.json."""
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


def main() -> int:
    t0 = time.time()
    if not CATALOG.exists():
        print(json.dumps({"ok": False, "error": "data/nikke-characters.json belum ada"}))
        return 1
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_url = {x["url"]: x for x in catalog if x.get("url")}
    by_name = {norm(x["name"]): x for x in catalog if x.get("name")}

    page = get(PAGE).decode("utf-8", "replace")
    chars = parse_characters(page)
    THUMBS.mkdir(parents=True, exist_ok=True)

    urls = {c["cardImage"] for c in chars if c.get("cardImage")}
    icons = set(ICON_RE.findall(page))
    urls |= {f"https://cdn.prydwen.gg/images/nikke/icons/{n}" for n in icons}
    failed = []
    nbytes = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(download, u): u for u in sorted(urls)}
        for fut in concurrent.futures.as_completed(futs):
            try:
                nbytes += fut.result()
            except Exception as exc:  # noqa: BLE001
                failed.append(str(exc)[:160])

    # Prydwen -> kode cNNN lewat katalog kita.
    by_code: dict[str, dict] = {}
    matched = 0
    for c in chars:
        rec = by_url.get(c.get("slug")) or by_name.get(norm(c.get("name") or ""))
        if not rec or not rec.get("img"):
            continue
        code = re.sub(r"^si_|_00_s$", "", rec["img"])
        if not CODE_RE.match(code):
            continue
        by_code[code] = {
            "slug": c.get("slug"),
            "name": c.get("name"),
            "rarity": c.get("rarity"),
            "class": c.get("class"),
            "element": c.get("element"),
            "weapon": c.get("weapon"),
            "manufacturer": c.get("manufacturer"),
            "squad": c.get("squad"),
            "burst": str(c.get("burstType") or ""),
            "image": urllib.parse.urlsplit(c.get("cardImage") or "").path.rsplit("/", 1)[-1] or None,
        }
        matched += 1
    # Karakter katalog yang tidak ada di Prydwen tetap dapat metadata filter.
    for rec in catalog:
        if not rec.get("img"):
            continue
        code = re.sub(r"^si_|_00_s$", "", rec["img"])
        if not CODE_RE.match(code) or code in by_code:
            continue
        by_code[code] = {
            "slug": rec.get("url"), "name": rec.get("name"),
            "rarity": rec.get("rarity"), "class": rec.get("class"),
            "element": rec.get("element"),
            "weapon": WEAPON.get(rec.get("weapon"), rec.get("weapon")),
            "manufacturer": rec.get("manufacturer"), "squad": rec.get("squad"),
            "burst": str(rec.get("burst") or ""), "image": None,
        }

    ids = model_ids()
    models: dict[str, str] = {}
    manifest: dict[str, str] = {}
    for mid in ids:
        leaf = mid.split("/")[-1]
        m = CODE_RE.match(leaf)
        if not m:
            continue
        code = m.group(1)
        info = by_code.get(code)
        if not info:
            continue
        models[mid] = code
        if info.get("image"):
            manifest[mid] = info["image"]

    DATA.write_text(json.dumps({
        "source": PAGE,
        "fetchedAt": int(time.time()),
        "characters": len(chars),
        "matchedPrydwen": matched,
        "codes": len(by_code),
        "byCode": by_code,
        "models": models,
    }, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (THUMBS / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")

    res = {
        "ok": not failed,
        "source": PAGE,
        "characters": len(chars),
        "matchedPrydwen": matched,
        "codes": len(by_code),
        "modelIds": len(models),
        "thumbOverrides": len(manifest),
        "images": len(urls),
        "bytes": nbytes,
        "failed": failed[:8],
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
