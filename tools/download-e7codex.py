#!/usr/bin/env python3
"""Unduh seluruh model Spine Epic Seven dari e7codex.com.

Sumber: https://e7codex.com/data/units.json — satu berkas berisi 848 entri,
masing-masing dengan field `spine[]` berisi {json, atlas, version}. Semua
berkas asset berada di https://e7codex.com/assets/<id>/.

Yang diunduh per model:
  * <id>/<id>.json    skeleton Spine
  * <id>/<id>.atlas   deskripsi atlas
  * halaman atlas     PNG/WEBP yang disebut di baris atlas (biasanya 1,
                      tapi dibaca dari atlas-nya, bukan diasumsikan)

Situs dilindungi Cloudflare dan menolak User-Agent non-browser (403),
jadi setiap permintaan mengirim header browser + Referer.

Halaman atlas dibaca dari berkas .atlas: baris yang berakhiran .png/.webp
di bagian atas berkas. Berkas atlas dari tool ini punya baris kosong di
awal (CRLF ganda), jadi pencarian tidak boleh mengandalkan baris pertama.

Dipakai:
  python3 tools/download-e7codex.py --check      # hanya periksa jumlah
  python3 tools/download-e7codex.py --limit 20   # uji coba
  python3 tools/download-e7codex.py              # semua
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://e7codex.com"
UNITS_URL = f"{BASE}/data/units.json"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "epic7")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": f"{BASE}/",
    "Accept": "*/*",
}


def fetch(url: str, timeout: int = 60) -> bytes:
    """Ambil URL dengan header browser, ulangi beberapa kali kalau gagal."""
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            # 403 = rate limit Cloudflare: beri jeda lebih panjang.
            time.sleep(1.5 * (attempt + 1) if e.code == 403 else 0.8 * (attempt + 1))
        except Exception as e:  # noqa: BLE001 - jaringan apa pun, coba lagi
            last = e
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"gagal mengambil {url}: {last}")


def atlas_pages(atlas_text: str) -> list[str]:
    """Nama halaman tekstur yang disebut di berkas atlas."""
    pages = []
    for line in atlas_text.replace("\r", "").split("\n"):
        s = line.strip()
        if not s:
            continue
        # Baris halaman adalah nama berkas di awal atlas; entri region
        # sesudahnya selalu menjorok. Batasi ke kemunculan pertama saja.
        if s.lower().endswith((".png", ".webp", ".jpg")):
            pages.append(s)
            break
    return pages


def one_unit(entry: dict, session_lock=None) -> dict:
    """Unduh satu model. Mengembalikan ringkasan hasil."""
    uid = entry["id"]
    spines = entry.get("spine") or []
    if not spines:
        return {"id": uid, "ok": False, "err": "tidak ada field spine"}
    sp = spines[0]
    d = os.path.join(OUT, uid)
    os.makedirs(d, exist_ok=True)

    try:
        atlas_bytes = fetch(f"{BASE}/{sp['atlas']}")
        json_bytes = fetch(f"{BASE}/{sp['json']}")
    except Exception as e:  # noqa: BLE001
        return {"id": uid, "ok": False, "err": str(e)[:120]}

    # Nama berkas lokal disamakan dengan id supaya scanModels() menemukannya,
    # tapi atlas merujuk halaman dengan nama aslinya — jadi halaman disimpan
    # dengan nama dari atlas, bukan diganti.
    atlas_name = f"{uid}.atlas"
    json_name = f"{uid}.json"
    with open(os.path.join(d, atlas_name), "wb") as f:
        f.write(atlas_bytes)
    with open(os.path.join(d, json_name), "wb") as f:
        f.write(json_bytes)

    pages = atlas_pages(atlas_bytes.decode("utf8", "replace"))
    got_pages = 0
    for page in pages:
        try:
            data = fetch(f"{BASE}/assets/{uid}/{page}")
            with open(os.path.join(d, page), "wb") as f:
                f.write(data)
            got_pages += 1
        except Exception:
            pass

    # Validasi: skeleton harus punya bone, dan minimal satu tekstur harus ada.
    try:
        skel = json.loads(json_bytes)
        bones = len(skel.get("bones") or [])
        anims = len(skel.get("animations") or {})
    except Exception:
        bones, anims = 0, 0

    ok = bones > 0 and got_pages > 0
    return {
        "id": uid,
        "ok": ok,
        "bones": bones,
        "anims": anims,
        "pages": got_pages,
        "version": sp.get("version"),
        "kind": entry.get("kind"),
        "err": "" if ok else f"bones={bones} pages={got_pages}",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="hanya tampilkan jumlah")
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah model (uji coba)")
    ap.add_argument("--workers", type=int, default=6, help="unduhan paralel")
    args = ap.parse_args()

    print(f"mengambil daftar: {UNITS_URL}")
    units = json.loads(fetch(UNITS_URL))
    units = [u for u in units if u.get("spine")]
    print(f"{len(units)} model punya data spine")
    if args.check:
        return 0
    if args.limit:
        units = units[: args.limit]

    os.makedirs(OUT, exist_ok=True)
    results = []
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one_unit, u): u for u in units}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if done % 25 == 0 or done == len(units):
                okn = sum(1 for x in results if x["ok"])
                print(f"  {done}/{len(units)} selesai · ok {okn} · {time.time()-t0:.0f}s", flush=True)

    okn = [x for x in results if x["ok"]]
    bad = [x for x in results if not x["ok"]]
    print(f"\nselesai: {len(okn)} berhasil, {len(bad)} gagal, {time.time()-t0:.0f} detik")
    if bad:
        print("gagal:")
        for x in bad[:25]:
            print(f"  {x['id']}: {x['err']}")
    # Ringkasan ditulis ke berkas supaya bisa diperiksa tanpa mengulang unduh.
    with open("/tmp/e7codex-report.json", "w") as f:
        json.dump({"ok": len(okn), "bad": len(bad), "results": results}, f, indent=1)
    print("laporan: /tmp/e7codex-report.json")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
