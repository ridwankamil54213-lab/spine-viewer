#!/usr/bin/env python3
"""Impor potret & metadata karakter Lost Sword dari Prydwen.

Sumber: https://www.prydwen.gg/lost-sword/characters
Halaman itu sudah merender seluruh kartu karakter di HTML (Next.js SSR), jadi
tidak perlu browser/API: tiap `.avatar-card` berisi

    <a href="/lost-sword/characters/<slug>">
      <div class="avatar pw-card lost rarity-5 ...">
        <img src="https://cdn.prydwen.gg/images/lost-sword/characters/<slug>_card.webp">
        <span class="floating-element lost">
          <img alt="Chaos"  src=".../icons/element_chaos.webp">
          <img alt="Archer" src=".../icons/class_archer.webp">
          <img alt="Back"   src=".../icons/position_backward.webp">
        </span>
        <span class="emp-name">Agravaine</span>

Hasil:
  public/thumbs/lostsword-prydwen/<slug>_card.webp   71 potret 140x180
  public/thumbs/lostsword-prydwen/*_*.webp           ikon elemen/kelas/posisi
  public/thumbs/lostsword-prydwen/_manifest.json     id model -> kartu potret
  data/lostsword-prydwen.json                       metadata per id model

Pencocokan nama memakai normalisasi (huruf kecil, tanpa tanda baca) terhadap
`assets/lostsword/_names.json` (ditulis refresh.py dari katalog live). Beberapa
nama Prydwen adalah alias kostum, dipetakan lewat ALIASES. Family tanpa
padanan tetap memakai thumbnail lama dari L2D viewer.

Idempoten: berkas yang sudah ada dilewati. Aman dijalankan ulang setelah
refresh.py mengubah _names.json.

Usage:
    python3 tools/lostsword/import-prydwen.py
"""
from __future__ import annotations

import concurrent.futures
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
PAGE = "https://www.prydwen.gg/lost-sword/characters"
THUMBS = VIEW / "public" / "thumbs" / "lostsword-prydwen"
DATA = VIEW / "data" / "lostsword-prydwen.json"
NAMES = VIEW / "assets" / "lostsword" / "_names.json"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
}
# Nama Prydwen -> nama family di katalog L2D viewer kita.
ALIASES = {
    "cowqueen belsey": "Belsey",
    "rita (maid)": "Maid Rita",
}
CARD_RE = re.compile(
    r'<a href="/lost-sword/characters/([^"]+)">(.*?)</a>', re.S)
RARITY_RE = re.compile(r"rarity-(\d)")
IMG_RE = re.compile(r'src="([^"]+_card\.webp)"')
NAME_RE = re.compile(r'<span class="emp-name">(.*?)</span>', re.S)
ICON_RE = re.compile(r'alt="([^"]+)"[^>]*src="([^"]*/icons/([^"/]+\.webp))"')


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


def parse_cards(page: str) -> list[dict]:
    out = []
    for slug, body in CARD_RE.findall(page):
        rarity = RARITY_RE.search(body)
        image = IMG_RE.search(body)
        name = NAME_RE.search(body)
        if not (rarity and image and name):
            continue
        rec = {
            "slug": slug,
            "name": html.unescape(name.group(1)).strip(),
            "rarity": int(rarity.group(1)),
            "image": image.group(1),
            "element": None,
            "class": None,
            "position": None,
        }
        for alt, url, fname in ICON_RE.findall(body):
            if fname.startswith("element_"):
                rec["element"] = alt
            elif fname.startswith("class_"):
                rec["class"] = alt
            elif fname.startswith("position_"):
                rec["position"] = alt
        out.append(rec)
    return out


def download(url: str) -> int:
    name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    dest = THUMBS / name
    if dest.exists() and dest.stat().st_size > 128:
        return 0
    data = get(url)
    if not data.startswith(b"RIFF") and not data.startswith(b"\x89PNG"):
        raise RuntimeError(f"{name}: bukan WebP/PNG valid")
    dest.write_bytes(data)
    return len(data)


def main() -> int:
    t0 = time.time()
    if not NAMES.exists():
        print(json.dumps({"ok": False, "error": "_names.json belum ada; jalankan refresh.py dulu"}))
        return 1
    families = json.loads(NAMES.read_text(encoding="utf-8")).get("families", [])
    our_names = {norm(f["name"]): f["name"] for f in families}
    by_name = {f["name"]: f for f in families}

    page = get(PAGE).decode("utf-8", "replace")
    cards = parse_cards(page)
    if len(cards) < 50:
        print(json.dumps({"ok": False,
                          "error": f"hanya {len(cards)} kartu terparse — markup Prydwen berubah"}))
        return 1
    THUMBS.mkdir(parents=True, exist_ok=True)

    # Kumpulkan semua URL gambar (kartu + ikon) lalu unduh paralel.
    # Ikon elemen/kelas/posisi diambil dari seluruh halaman sekali saja.
    urls = {c["image"] for c in cards}
    for _alt, url, _fname in ICON_RE.findall(page):
        urls.add(url)
    failed = []
    nbytes = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(download, u): u for u in sorted(urls)}
        for fut in concurrent.futures.as_completed(futs):
            try:
                nbytes += fut.result()
            except Exception as exc:  # noqa: BLE001
                failed.append(str(exc)[:160])

    # Petakan kartu Prydwen -> family kita.
    matched: dict[str, dict] = {}
    for c in cards:
        key = norm(c["name"])
        target = our_names.get(key) or ALIASES.get(c["name"].lower())
        if not target or target not in by_name:
            continue
        matched[target] = {
            "slug": c["slug"],
            "name": c["name"],
            "rarity": c["rarity"],
            "element": c["element"],
            "class": c["class"],
            "position": c["position"],
            "image": urllib.parse.urlsplit(c["image"]).path.rsplit("/", 1)[-1],
        }

    # Sebarkan metadata & thumbnail ke SELURUH anggota family (semua varian
    # kostum / Battle Mode / Pet / video memakai potret karakter yang sama).
    models: dict[str, dict] = {}
    manifest: dict[str, str] = {}
    for fam_name, meta in matched.items():
        for member in by_name[fam_name].get("members", []):
            mid = member.get("id")
            if not mid:
                continue
            models[mid] = meta
            manifest[mid] = meta["image"]
    DATA.write_text(json.dumps({
        "source": PAGE,
        "fetchedAt": int(time.time()),
        "characters": len(cards),
        "matchedFamilies": len(matched),
        "models": models,
    }, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (THUMBS / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")

    res = {
        "ok": not failed,
        "source": PAGE,
        "characters": len(cards),
        "matchedFamilies": len(matched),
        "modelIds": len(models),
        "images": len(urls),
        "bytes": nbytes,
        "unmatchedPrydwen": [c["name"] for c in cards
                             if (our_names.get(norm(c["name"])) or
                                 ALIASES.get(c["name"].lower())) not in by_name][:8],
        "familiesWithoutCard": [f["name"] for f in families if f["name"] not in matched],
        "failed": failed[:8],
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
