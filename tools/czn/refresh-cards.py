#!/usr/bin/env python3
"""Bangun pustaka kartu skill CZN dari data resmi wiki e7bot.

Berbeda dengan tools/download-czn-cards.py lama yang MENEBAK nama berkas
(start_<id>_01..12, unique_<id>_01..12), script ini memakai indeks resmi
``GET /api/czn/cards/list`` sebagai satu-satunya kebenaran. Dari situ didapat:

  sct_name            nama berkas ilustrasi yang pasti ada
  base_combatant.id   pemilik kartu -> assets/czn-cards/<charid>/
  animation           apakah ada versi .webm
  name/ego/rarity/cost/sort  metadata untuk frame & tooltip di viewer
  desc_display        deskripsi kartu, memakai markup warna wiki

Daftar wiki dienkripsi AES-256-CBC (kunci sama dengan characters/list), 16 byte
pertama payload adalah IV. Hanya kartu milik 89 karakter roster yang diambil;
partner memang tidak punya kartu. sct_name bisa berulang (varian epiphany),
jadi dideduplikasi per (charid, sct_name) — tapi SEMUA deskripsi berbeda tetap
disimpan, diurutkan dengan kartu dasar lebih dulu.

Markup desc_display (<color_orange>, <cc>, <color_ego_*>, <u>, <br>, </>)
diterjemahkan ke HTML aman: semua teks di-escape, hanya tag yang dikenal yang
dikeluarkan (lihat desc_html). Warna mengikuti descriptionFormatter wiki.

Keluaran:
  assets/czn-cards/<charid>/<sct_name>.webp   (+ .webm kalau tersedia)
  assets/czn-cards/index.json                  { charid: {name,ego,cards:[...]} }
  public/czn-frame/card_ego_<ego>.webp        (2 varian yang belum ada)

Idempoten: berkas yang sudah ada dilewati. Tidak menghapus apa pun.

Usage: python3 tools/czn/refresh-cards.py
"""
from __future__ import annotations

import base64
import concurrent.futures
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

VIEW = Path(__file__).resolve().parents[2]
OUT = VIEW / "assets" / "czn-cards"
FRAMES = VIEW / "public" / "czn-frame"
WIKI = "https://wiki.e7bot.top"
DATA = WIKI + "/api/assets/file/czn/data/"
KEY = b"2egkWEkLvR9idARLvjqfJdWKfR24HJgY"
HEADERS = {
    "User-Agent": "spine-viewer-czn-cards/1.0",
    "Referer": WIKI + "/",
    "Accept": "*/*",
}
WORKERS = 4
RARITY = {
    "RARITY_COMMON": "common",
    "RARITY_RARE": "rare",
    "RARITY_LEGEND": "legend",
    "RARITY_UNIQUE": "unique",
}
# descriptionFormatter wiki: warna ego (gelap) dan versi _light.
EGO_COLOR = {
    "love": "#BC2643", "norms": "#168256", "narcissism": "#1E61B4",
    "creed": "#6D30C1", "instinct": "#DE6E00",
}
EGO_LIGHT = {
    "love": "#FF5A5A", "norms": "#4BCE7F", "narcissism": "#38A9FF",
    "creed": "#CC83FF", "instinct": "#FFB000",
}
ORANGE = "#FF8C00"
PLAIN_COLOR = {
    "color_red": "#FF0000", "color_blue": "#0000FF", "color_green": "#00FF00",
    "color_yellow": "#FFFF00", "color_purple": "#800080",
    "color_white": "#FFFFFF", "color_black": "#000000",
    "color_gray": "#808080", "color_darkgray": "#A9A9A9",
    "color_sr": "#ffc978", "color_r": "#87cafe", "color_d9d9d9": "#D9D9D9",
}
TAG = re.compile(r"<[^>]*>")


def fetch(url: str, tries: int = 6) -> bytes | None:
    """Ambil URL. None untuk 404 (kartu/animasi memang tidak ada).

    Wiki membatasi request (429) kalau terlalu banyak koneksi barengan, jadi
    429 dan 5xx ditunggu dengan backoff eksponensial sebelum dicoba lagi.
    """
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
            time.sleep(min(30, 3 * (2 ** i)) if e.code == 429 or e.code >= 500
                       else 1.2 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def decrypt(payload: str) -> str:
    raw = base64.b64decode(payload)
    dec = Cipher(algorithms.AES(KEY), modes.CBC(raw[:16])).decryptor()
    out = dec.update(raw[16:]) + dec.finalize()
    un = padding.PKCS7(128).unpadder()
    return (un.update(out) + un.finalize()).decode("utf-8")


def wiki_list(path: str) -> list:
    raw = fetch(WIKI + path)
    if raw is None:
        raise RuntimeError(f"{path} mengembalikan 404")
    body = json.loads(raw)
    if body.get("encrypted"):
        body = json.loads(decrypt(body["data"]))
    data = body.get("data", body)
    if not isinstance(data, list):
        raise RuntimeError(f"bentuk daftar {path} tidak dikenal")
    return data


def desc_plain(raw: str) -> str:
    """Teks polos untuk tooltip/aria-label: buang markup, <br> jadi baris baru."""
    s = re.sub(r"<br\s*/?>", "\n", raw or "", flags=re.I)
    s = TAG.sub("", s).replace("$", "").replace("^", "")
    return html.unescape(s).strip()


def desc_html(raw: str) -> str:
    """Markup wiki -> HTML aman.

    Semua potongan teks di-escape; hanya tag yang dikenal yang dikeluarkan.
    Tag asing dibuang, jadi tidak mungkin ada <script> / atribut liar masuk
    ke innerHTML viewer.
    """
    raw = raw or ""
    out: list[str] = []
    pos = 0
    for m in TAG.finditer(raw):
        out.append(html.escape(raw[pos:m.start()]))
        t = m.group(0).strip().lower()
        if t.startswith("<color_ego_"):
            mm = re.match(r"<color_ego_(\w+?)(_light)?>", t)
            if mm:
                col = (EGO_LIGHT if mm.group(2) else EGO_COLOR).get(mm.group(1))
                if col:
                    out.append(f'<span style="color:{col}">')
        elif t in ("<color_orange>", "<cc>") or t.startswith("<color_"):
            col = ORANGE if t in ("<color_orange>", "<cc>") else PLAIN_COLOR.get(t[1:-1], ORANGE)
            out.append(f'<span style="color:{col}">')
        elif t == "</>":
            out.append("</span>")
        elif t == "<u>":
            out.append("<u>")
        elif t == "</u>":
            out.append("</u>")
        elif t in ("<br>", "<br/>", "<br />"):
            out.append("<br>")
        # tag lain sengaja diabaikan
        pos = m.end()
    out.append(html.escape(raw[pos:]))
    return "".join(out).replace("$", "").strip()


def desc_score(c: dict) -> int:
    """Urutkan kartu dasar lebih dulu; varian epiphany (_rsp/_pot) belakangan."""
    i = str(c.get("id") or "")
    if "_rsp" in i or "_pot" in i:
        return 2
    return 0 if c.get("r_spark_cards") else 1


def is_webp(b: bytes) -> bool:
    return len(b) > 16 and b[:4] == b"RIFF" and b[8:12] == b"WEBP"


def is_webm(b: bytes) -> bool:
    return len(b) > 16 and b[:4] == b"\x1a\x45\xdf\xa3"


def main() -> None:
    roster = {str(c["id"]): c.get("name") or c["id"]
              for c in wiki_list("/api/czn/characters/list?lang=en")}
    cards = wiki_list("/api/czn/cards/list?lang=en")
    print(f"roster {len(roster)} karakter, {len(cards)} entri kartu wiki")

    # ---- 1. kumpulkan semua record per (charid, sct_name) ----------------
    grouped: dict[str, dict[str, list[dict]]] = {}
    for c in cards:
        bc = c.get("base_combatant") or {}
        cid = str(bc.get("id") or "")
        stem = str(c.get("sct_name") or "")
        if cid not in roster or not stem:
            continue
        grouped.setdefault(cid, {}).setdefault(stem, []).append(c)

    # ---- 2. bentuk metadata final: deskripsi base + semua varian ---------
    meta: dict[str, dict[str, dict]] = {}
    for cid, items in grouped.items():
        meta[cid] = {}
        for stem, records in items.items():
            recs = sorted(records, key=desc_score)
            base = recs[0]
            bc = base.get("base_combatant") or {}
            seen: set[str] = set()
            descs: list[dict] = []
            for r in recs:
                raw = r.get("desc_display") or ""
                txt = desc_plain(raw)
                if not txt or txt in seen:
                    continue
                seen.add(txt)
                descs.append({"text": txt, "html": desc_html(raw)})
            order = ["", "common", "rare", "unique", "legend"]
            rarity = ""
            for r in recs:
                alt = RARITY.get(r.get("rarity"), "")
                if order.index(alt) > order.index(rarity):
                    rarity = alt
            meta[cid][stem] = {
                "kind": stem.split("_")[0],
                "name": next((r.get("name") for r in recs if r.get("name")), stem),
                "ego": bc.get("ego") or "",
                "rarity": rarity,
                "cost": base.get("cost"),
                "sort": base.get("sort") or "",
                "animation": any(bool(r.get("animation")) for r in recs),
                "descs": descs,
            }

    total = sum(len(v) for v in meta.values())
    animated = sum(1 for v in meta.values() for r in v.values() if r["animation"])
    variants = sum(max(0, len(r["descs"]) - 1) for v in meta.values() for r in v.values())
    print(f"{len(meta)} karakter punya kartu · {total} ilustrasi unik · "
          f"{animated} beranimasi · {variants} varian deskripsi")
    if not total:
        raise RuntimeError("irisan kosong — batal")

    OUT.mkdir(parents=True, exist_ok=True)

    # ---- 3. unduh ilustrasi + animasi -----------------------------------
    jobs = []
    for cid, items in meta.items():
        for stem, rec in items.items():
            jobs.append((cid, stem, ".webp"))
            if rec["animation"]:
                jobs.append((cid, stem, ".webm"))

    def dl(job):
        cid, stem, ext = job
        dest = OUT / cid / (stem + ext)
        if dest.exists() and dest.stat().st_size > 100:
            return (cid, stem, ext, True)
        data = fetch(DATA + f"card_illustration/{stem}{ext}")
        ok = bool(data and (is_webp(data) if ext == ".webp" else is_webm(data)))
        if ok:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        return (cid, stem, ext, ok)

    missing_static: set[tuple[str, str]] = set()
    no_video = set()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(dl, j) for j in jobs]
        for fut in concurrent.futures.as_completed(futs):
            cid, stem, ext, ok = fut.result()
            if not ok and ext == ".webp":
                missing_static.add((cid, stem))
            if not ok and ext == ".webm":
                no_video.add((cid, stem))
            done += 1
            if done % 150 == 0:
                print(f"  {done}/{len(jobs)} berkas", flush=True)
    print(f"unduh selesai: {done} berkas, {len(missing_static)} ilustrasi 404, "
          f"{len(no_video)} animasi tidak tersedia")

    # ---- 4. tulis index.json --------------------------------------------
    index = {}
    for cid, items in sorted(meta.items()):
        entries = []
        for stem, rec in sorted(items.items()):
            if (cid, stem) in missing_static:
                continue
            primary = rec["descs"][0] if rec["descs"] else {"text": "", "html": ""}
            entries.append({
                "kind": rec["kind"],
                "file": stem + ".webp",
                "video": rec["animation"] and (cid, stem) not in no_video,
                "name": rec["name"],
                "ego": rec["ego"],
                "rarity": rec["rarity"],
                "cost": rec["cost"],
                "sort": rec["sort"],
                "desc": primary["text"],
                "descHtml": primary["html"],
                "descs": rec["descs"],
                "descCount": len(rec["descs"]),
            })
        index[cid] = {"name": roster[cid], "ego": next(iter(items.values()))["ego"],
                      "cards": entries}
    (OUT / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(f"index.json: {len(index)} karakter / "
          f"{sum(len(v['cards']) for v in index.values())} kartu")

    # ---- 5. lengkapi frame ego yang belum ada ---------------------------
    FRAMES.mkdir(parents=True, exist_ok=True)
    for ego in ["instinct", "norms", "love", "creed", "narcissism"]:
        dest = FRAMES / f"card_ego_{ego}.webp"
        if dest.exists() and dest.stat().st_size > 100:
            continue
        data = fetch(DATA + f"card/card_ego_{ego}.webp")
        if data and is_webp(data):
            dest.write_bytes(data)
            print(f"  frame ego baru: {dest.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print("GAGAL:", exc, file=sys.stderr)
        sys.exit(1)
