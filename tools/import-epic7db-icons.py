#!/usr/bin/env python3
"""Unduh ikon filter Epic7DB ke public/thumbs/epic7-filters/.

Sumber: https://epic7db.com/heroes. Halaman ini memakai ikon untuk elemen,
class, zodiac, bintang, dan status effect. Status effect tidak muncul sebagai
<img> di halaman daftar, tetapi setiap hero memakai pola URL
/images/status_effects/<slug>.png, jadi slug dari data-statusEffects dan
<option> dipetakan ke URL itu.

Hasil:
  public/thumbs/epic7-filters/{elements,classes,zodiacs,stars,effects}/…
  public/thumbs/epic7-filters/_manifest.json
  data/epic7db-icons.json

Usage:
  python3 tools/import-epic7db-icons.py
"""
from __future__ import annotations

import concurrent.futures
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VIEW = Path(__file__).resolve().parents[1]
PAGE = "https://epic7db.com/heroes"
OUT = VIEW / "public" / "thumbs" / "epic7-filters"
MANIFEST = OUT / "_manifest.json"
DATA = VIEW / "data" / "epic7db-icons.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Referer": PAGE,
}
MAGIC = (
    b"\x89PNG\r\n\x1a\n",
    b"RIFF",
    b"\xff\xd8\xff",
    b"<svg",
)


def fetch_text(url: str, timeout: int = 90) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch(url: str, timeout: int = 40) -> bytes:
    """Unduh berkas gambar; tolak HTML fallback yang kadang diberikan CDN."""
    last = ""
    for attempt in range(4):
        u = url if attempt == 0 else f"{url}{'&' if '?' in url else '?'}_cb={time.time_ns()}-{attempt}"
        try:
            req = urllib.request.Request(u, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            if body and (body.lstrip().startswith(MAGIC) or body[:4] == b"RIFF"):
                return body
            last = f"bukan gambar ({body[:24]!r})"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", html.unescape(s or "").lower())


def main() -> int:
    page = fetch_text(PAGE)
    start = page.find('<div class="filters">')
    end = page.find('<div class="heroes-container">', start)
    section = page[start:end] if start >= 0 and end > start else ""
    if not section:
        raise RuntimeError("bagian filter Epic7DB tidak ditemukan")

    jobs: list[tuple[str, str, str, str]] = []
    icons: dict[str, dict[str, str]] = {
        "stars": {}, "element": {}, "class": {}, "zodiac": {}, "effect": {},
    }

    for m in re.finditer(r"<button\b([^>]*)>\s*(.*?)</button>", section, re.I | re.S):
        attrs, inner = m.group(1), m.group(2)
        kind = re.search(r'data-filter="([^"]+)"', attrs)
        value = re.search(r'data-value="([^"]+)"', attrs)
        src = re.search(r'<img\b[^>]*\bsrc="([^"]+)"', inner, re.I | re.S)
        if not (kind and value and src):
            continue
        k, v = kind.group(1), html.unescape(value.group(1))
        if k not in ("element", "class", "zodiac") or v == "all":
            continue
        ext = Path(urllib.parse.urlparse(src.group(1)).path).suffix.lower() or ".png"
        folder = {"element": "elements", "class": "classes", "zodiac": "zodiacs"}[k]
        rel = f"{folder}/{slug(v)}{ext}"
        icons[k][v] = rel
        jobs.append((k, v, urllib.parse.urljoin(PAGE, src.group(1)), rel))

    if len(icons["element"]) < 5 or len(icons["class"]) < 6 or len(icons["zodiac"]) < 12:
        raise RuntimeError("ikon filter Epic7DB tidak lengkap: "
                           + json.dumps({k: len(v) for k, v in icons.items()}))

    star_url = urllib.parse.urljoin(PAGE, "/images/stars/star.png")
    star_rel = "stars/star.png"
    for n in ("3", "4", "5"):
        icons["stars"][n] = star_rel
    jobs.append(("stars", "star", star_url, star_rel))

    # Kategori Buff / Debuff dipakai untuk metadata; semua efek tetap dapat
    # ikon PNG resminya dari Epic7DB.
    def select_values(select_id: str) -> set[str]:
        m = re.search(r'<select\b[^>]*id="' + re.escape(select_id) +
                      r'"[^>]*>(.*?)</select>', page, re.I | re.S)
        return set(re.findall(r'<option\s+value="([^"]+)"', m.group(1))) if m else set()

    buffs = select_values("buff-filter")
    debuffs = select_values("debuff-filter")
    effects: set[str] = set()
    for raw in re.findall(r'data-statusEffects="([^"]*)"', page):
        effects.update(x.strip() for x in html.unescape(raw).split(",") if x.strip())
    for m in re.finditer(r"<select\b[^>]*>(.*?)</select>", page, re.I | re.S):
        effects.update(html.unescape(v) for v in re.findall(r'<option\s+value="([^"]+)"', m.group(1)))
    effects = {e for e in effects if re.fullmatch(r"[a-z0-9][a-z0-9-]*", e)}
    if len(effects) < 50:
        raise RuntimeError(f"daftar status effect terlalu sedikit: {len(effects)}")

    for fx in sorted(effects):
        rel = f"effects/{fx}.png"
        icons["effect"][fx] = rel
        jobs.append(("effect", fx, urllib.parse.urljoin(
            PAGE, f"/images/status_effects/{fx}.png"), rel))

    # Fallback lokal kalau suatu hari Epic7DB menghapus satu ikon effect.
    neutral = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#334155" stroke="#94a3b8" stroke-width="2"/><path d="M10 16h12M16 10v12" stroke="#e2e8f0" stroke-width="3" stroke-linecap="round"/></svg>\n'''
    (OUT / "effects").mkdir(parents=True, exist_ok=True)
    (OUT / "effects" / "_neutral.svg").write_bytes(neutral)

    def download(job: tuple[str, str, str, str]) -> dict:
        kind, value, url, rel = job
        p = OUT / rel
        try:
            body = fetch(url)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_bytes(body)
            tmp.replace(p)
            return {"kind": kind, "value": value, "rel": rel, "ok": True, "bytes": len(body)}
        except Exception as e:  # noqa: BLE001
            # Ikon effect yang hilang memakai glyph netral; ikon filter utama
            # tetap dianggap error karena tidak ada pengganti visualnya.
            if kind == "effect":
                icons["effect"][value] = "effects/_neutral.svg"
                return {"kind": kind, "value": value, "rel": "effects/_neutral.svg",
                        "ok": False, "error": str(e)[:160]}
            return {"kind": kind, "value": value, "rel": rel, "ok": False,
                    "error": str(e)[:160]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        result = list(ex.map(download, jobs))

    failed = [r for r in result if not r["ok"]]
    critical = [r for r in failed if r["kind"] != "effect"]
    effects_kind = {
        fx: ("buff" if fx in buffs else "debuff" if fx in debuffs else "other")
        for fx in sorted(effects)
    }
    counts = {
        "element": len(icons["element"]), "class": len(icons["class"]),
        "zodiac": len(icons["zodiac"]), "star": 1, "effect": len(icons["effect"]),
    }
    manifest = {
        "source": PAGE,
        "fetchedAt": int(time.time()),
        "dir": "/thumbs/epic7-filters/",
        "icons": icons,
        "effectTypes": effects_kind,
        "counts": counts,
        "missingEffects": [r["value"] for r in failed if r["kind"] == "effect"],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1,
                                   sort_keys=True) + "\n", encoding="utf-8")
    DATA.write_text(json.dumps({
        "source": PAGE,
        "counts": counts,
        "effects": len(effects),
        "buffs": len(buffs),
        "debuffs": len(debuffs),
        "otherEffects": sum(1 for v in effects_kind.values() if v == "other"),
        "missingEffects": manifest["missingEffects"],
    }, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "ok": not critical,
        "icons": sum(1 for r in result if r["ok"]),
        "missingEffects": len(manifest["missingEffects"]),
        "failedCore": len(critical),
        "counts": counts,
        "buffs": len(buffs),
        "debuffs": len(debuffs),
    }
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0 if not critical else 1


if __name__ == "__main__":
    raise SystemExit(main())
