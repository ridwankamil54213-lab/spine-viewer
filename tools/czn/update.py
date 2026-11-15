#!/usr/bin/env python3
"""Satu pembaru untuk metadata Chaos Zero Nightmare (game `chaoszero`).

Model Spinenya ADA di assets/chaoszero/ (aset game-side, dipulihkan dari
GDrive) dan TIDAK diunduh updater ini. Yang disegarkan cuma metadata wiki:
ikon filter, kartu skill, potret/thumbnail, dan _manifest.json yang
memetakan tiap model chaoszero ke potret karakternya.

PENTING: tools/czn/refresh.py TIDAK boleh dijalankan sebagai skrip di sini.
Skrip itu mengunduh rig komunitas ke assets/czn-rigs/ (pustaka lama yang
sudah diarsipkan atas permintaan user). refresh.py hanya dipakai sebagai
modul oleh build-thumb-manifest.py untuk fungsi wiki_roster().

Sumber yang dipantau:
  GitHub  BenNoSleep/czn-animation-viewer  index.json + commit main (versi)
  wiki    /api/czn/characters/list        roster (terenkripsi AES)
  wiki    /api/czn/cards/list             kartu skill (terenkripsi AES)

Kontrak server (lihat runUpdater di src/server.js):
  --check : cepat, TANPA mengunduh aset. Bandingkan tanda tangan sumber +
            himpunan id terhadap data/chaoszero-update-state.json. Cetak JSON
            ke stdout, progres ke stderr.
  --apply : jalankan berurutan fetch-icons.py, refresh-cards.py,
            capture-thumbs.cjs, normalize-thumbs.py, build-thumb-manifest.py,
            lalu simpan state baru.

State disimpan di data/chaoszero-update-state.json (data/*-state.json
diabaikan git). State lama data/czn-update-state.json sengaja ditinggalkan
karena masih memakai skema `rigs` milik pustaka komunitas. Kalau state belum
ada, --check melakukan bootstrap: catat kondisi sekarang sebagai baseline
supaya tidak langsung melapor "semua baru".

Usage:
    python3 tools/czn/update.py --check
    python3 tools/czn/update.py --apply
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

VIEW = Path(__file__).resolve().parents[2]
HERE = VIEW / "tools" / "czn"
STATE = VIEW / "data" / "chaoszero-update-state.json"
WIKI = "https://wiki.e7bot.top"
GH_RAW = "https://raw.githubusercontent.com/BenNoSleep/czn-animation-viewer/main/index.json"
GH_COMMIT = "https://api.github.com/repos/BenNoSleep/czn-animation-viewer/commits/main"
KEY = b"2egkWEkLvR9idARLvjqfJdWKfR24HJgY"
HEADERS = {
    "User-Agent": "spine-viewer-chaoszero-updater/1.0",
    "Referer": WIKI + "/",
    "Accept": "*/*",
}

# Urutan penting: capture menulis <portraitId>.png + cards.json, normalize
# menyamakan ukurannya, build-thumb-manifest mengganti nama jadi <charId>.png
# dan membangun _manifest.json untuk SELURUH model chaoszero.
STEPS = [
    ("ikon filter", [sys.executable, str(HERE / "fetch-icons.py")]),
    ("kartu skill", [sys.executable, str(HERE / "refresh-cards.py")]),
    ("thumbnail dari wiki", ["node", str(HERE / "capture-thumbs.cjs")]),
    ("normalisasi thumbnail", [sys.executable, str(HERE / "normalize-thumbs.py")]),
    ("manifest thumbnail chaoszero", [sys.executable, str(HERE / "build-thumb-manifest.py")]),
]
# refresh-cards.py (i=1) adalah data utama; sisanya kosmetik dan boleh
# dilewati kalau wiki/Chromium sedang rewel, tanpa menggagalkan apply.
COSMETIC = {0, 2, 3, 4}


def fetch(url: str, tries: int = 5) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(min(20, 2 * (2 ** i)) if e.code == 429 or e.code >= 500
                       else 1.0 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0 * (i + 1))
    raise RuntimeError(f"gagal mengambil {url}: {last}")


def decrypt(payload: str) -> str:
    raw = base64.b64decode(payload)
    dec = Cipher(algorithms.AES(KEY), modes.CBC(raw[:16])).decryptor()
    out = dec.update(raw[16:]) + dec.finalize()
    un = padding.PKCS7(128).unpadder()
    return (un.update(out) + un.finalize()).decode("utf-8")


def wiki_data(url: str) -> tuple[bytes, list]:
    raw = fetch(WIKI + url)
    body = json.loads(raw)
    if body.get("encrypted"):
        body = json.loads(decrypt(body["data"]))
    data = body.get("data", body)
    if not isinstance(data, list):
        raise RuntimeError(f"bentuk daftar {url} tidak dikenal")
    return raw, data


def disk_counts() -> dict:
    def n(p: Path, suffixes: tuple[str, ...], skip: str = "") -> int:
        if not p.is_dir():
            return 0
        return sum(1 for f in p.rglob("*")
                   if f.is_file() and f.name.lower().endswith(suffixes)
                   and f.name != skip)

    chaos = VIEW / "assets" / "chaoszero"
    models = n(chaos, (".json",), skip="_names.json")
    return {
        "models": models,
        # Cuma .webp: .webm adalah video duplikat untuk kartu yang sama,
        # jadi jumlah berkas akan selalu lebih besar dari jumlah kartu.
        "cards": n(VIEW / "assets" / "czn-cards", (".webp",)),
        "thumbs": n(VIEW / "public" / "thumbs" / "chaoszero", (".png",)),
        "icons": n(VIEW / "public" / "thumbs" / "czn-ui", (".webp", ".png")),
    }


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(tmp, STATE)


def snapshot() -> dict:
    """Ambil tanda tangan + himpunan id dari sumber (tanpa unduh aset)."""
    gh_index = fetch(GH_RAW)
    commit = json.loads(fetch(GH_COMMIT)).get("sha", "")
    roster_raw, roster = wiki_data("/api/czn/characters/list?lang=en")
    cards_raw, cards = wiki_data("/api/czn/cards/list?lang=en")

    roster_ids = {str(c["id"]) for c in roster}
    card_stems = {
        f"{bc}/{str(c.get('sct_name') or '')}"
        for c in cards
        if (bc := str((c.get("base_combatant") or {}).get("id") or "")) in roster_ids
        and c.get("sct_name")
    }
    sig = hashlib.sha256(gh_index + roster_raw + cards_raw).hexdigest()[:16]
    counts = disk_counts()
    return {
        "sig": sig,
        "commit": commit,
        "roster": sorted(roster_ids),
        "cards": sorted(card_stems),
        "counts": counts,
        "detail": {"roster": len(roster_ids), "cards": len(card_stems),
                   "models": counts["models"]},
    }


def version(s: dict) -> str:
    d = s.get("detail", {})
    thumbs = (s.get("counts") or {}).get("thumbs", 0)
    return (f"{(s.get('commit') or '')[:8]} · {d.get('roster', 0)} karakter / "
            f"{d.get('cards', 0)} kartu / {thumbs} thumbnail")


def check() -> dict:
    snap = snapshot()
    state = load_state()
    if not state.get("sig"):
        # Bootstrap: kondisi sekarang = baseline, jangan tawarkan unduh ulang.
        save_state({**snap, "updated_at": int(time.time())})
        return {"ok": True, "mode": "check", "changed": False, "new": 0,
                "new_ids": [], "previous": (snap["commit"] or "")[:8],
                "version": version(snap), "detail": snap["detail"],
                "expected": snap["detail"]["cards"],
                "have": snap["counts"]["cards"],
                "bootstrap": True}

    new_cards = sorted(set(snap["cards"]) - set(state.get("cards", [])))
    new_chars = sorted(set(snap["roster"]) - set(state.get("roster", [])))
    # Berkas hilang di disk juga berarti perlu dipulihkan.
    drift = snap["counts"] != state.get("counts")
    changed = (snap["sig"] != state.get("sig") or bool(new_cards)
               or bool(new_chars) or drift)
    new_ids = [f"czn-cards/{s}" for s in new_cards]
    return {
        "ok": True,
        "mode": "check",
        "version": version(snap),
        "commit": snap["commit"],
        "previous": (state.get("commit") or "")[:8],
        "changed": changed,
        "new": len(new_cards) + len(new_chars),
        "new_ids": new_ids,
        "expected": snap["detail"]["cards"],
        "have": snap["counts"]["cards"],
        "detail": {**snap["detail"], "new_cards": len(new_cards),
                   "new_chars": len(new_chars), "disk": snap["counts"]},
        "sources": {"github": snap["sig"], "wiki": "roster+cards"},
    }


def apply_update() -> dict:
    t0 = time.time()
    before = disk_counts()
    # Ambil gambaran sumber SEBELUM menjalankan tool (sesudahnya state baru).
    try:
        pre = check()
    except Exception:  # noqa: BLE001
        pre = {}
    snap_before = load_state()

    for i, (label, cmd) in enumerate(STEPS):
        print(f"[{i + 1}/{len(STEPS)}] {label} …", file=sys.stderr, flush=True)
        try:
            r = subprocess.run(cmd, cwd=str(VIEW), stdout=sys.stderr,
                               stderr=sys.stderr, timeout=1800)
        except Exception as e:  # noqa: BLE001
            if i in COSMETIC:
                print(f"  peringatan: {label} gagal ({e}), dilewati",
                      file=sys.stderr, flush=True)
                continue
            return {"ok": False, "error": f"{label} gagal: {e}"}
        if r.returncode != 0:
            if i in COSMETIC:
                print(f"  peringatan: {label} gagal (exit {r.returncode}), dilewati",
                      file=sys.stderr, flush=True)
                continue
            return {"ok": False, "error": f"{label} gagal (exit {r.returncode})"}

    after = disk_counts()
    downloaded = sum(max(0, after[k] - before[k]) for k in before)
    try:
        snap = snapshot()
    except Exception as e:  # noqa: BLE001
        print(f"  peringatan: tidak bisa menyegarkan state: {e}",
              file=sys.stderr, flush=True)
        snap = snap_before
    save_state({**snap, "updated_at": int(time.time())})

    new_ids = pre.get("new_ids", [])
    # Kalau apply dijalankan tepat setelah bootstrap check(), new_ids masih
    # kosong walau refresh-cards.py mengunduh kartu baru. Pakai selisih berkas
    # kartu sebagai fallback supaya dashboard tidak melapor "0 padahal ada".
    new_count = len(new_ids) or max(0, after["cards"] - before["cards"])
    return {
        "ok": True,
        "mode": "apply",
        "version": version(snap),
        "commit": snap.get("commit"),
        "new": new_count,
        "new_ids": new_ids,
        "new_models": new_ids,
        "downloaded": downloaded,
        # Selalu true supaya klien memanggil refresh() setelah apply, meski
        # jumlah berkas tidak bertambah (isi yang berubah tetap perlu masuk
        # daftar model). Server menandai forceModelRescan untuk request itu.
        "extracted": True,
        "disk_before": before,
        "disk_after": after,
        "seconds": round(time.time() - t0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    try:
        res = apply_update() if a.apply else check()
    except Exception as err:  # noqa: BLE001
        res = {"ok": False, "error": str(err)}
    # SATU-SATUNYA yang boleh ke stdout: blok JSON hasil. runUpdater memotong
    # log begitu melihat baris "{".
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
