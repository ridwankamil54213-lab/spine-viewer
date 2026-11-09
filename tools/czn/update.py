#!/usr/bin/env python3
"""Satu pembaru untuk seluruh data Chaos Zero Nightmare.

Menggantikan tools/update-czn.py lama (git fetch + czn-rigs.py/czn-thumbs.py)
yang bergantung pada clone lokal /opt/re-targets/czn-repo dan akan MENIMPA
_names.json / _manifest.json baru dengan metadata versi lama.

Sumber yang dipantau:
  GitHub  BenNoSleep/czn-animation-viewer  index.json + commit main
  wiki    /api/czn/characters/list        roster (terenkripsi AES)
  wiki    /api/czn/cards/list             kartu skill (terenkripsi AES)

Kontrak server (lihat runUpdater di src/server.js):
  --check : cepat, TANPA mengunduh aset. Bandingkan tanda tangan sumber +
            himpunan id terhadap data/czn-update-state.json. Cetak JSON ke
            stdout, progres ke stderr.
  --apply : jalankan berurutan tools/czn/refresh.py, fetch-icons.py,
            refresh-cards.py, capture-thumbs.cjs, lalu simpan state baru.

State disimpan di data/czn-update-state.json (data/*-state.json diabaikan
git). Kalau state belum ada, --check melakukan bootstrap: catat kondisi
sekarang sebagai baseline supaya tidak langsung melapor "semua baru".

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
import re
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
STATE = VIEW / "data" / "czn-update-state.json"
WIKI = "https://wiki.e7bot.top"
GH_RAW = "https://raw.githubusercontent.com/BenNoSleep/czn-animation-viewer/main/index.json"
GH_COMMIT = "https://api.github.com/repos/BenNoSleep/czn-animation-viewer/commits/main"
KEY = b"2egkWEkLvR9idARLvjqfJdWKfR24HJgY"
HEADERS = {
    "User-Agent": "spine-viewer-czn-updater/1.0",
    "Referer": WIKI + "/",
    "Accept": "*/*",
}
STEPS = [
    ("roster + rig + manifest", [sys.executable, str(HERE / "refresh.py")]),
    ("ikon filter", [sys.executable, str(HERE / "fetch-icons.py")]),
    ("kartu skill", [sys.executable, str(HERE / "refresh-cards.py")]),
    ("thumbnail dari web", ["node", str(HERE / "capture-thumbs.cjs")]),
]
# Ikon & thumbnail bersifat kosmetik: kalau wiki sedang rewel, jangan gagalkan
# seluruh pembaruan model/kartu yang sudah berhasil.
COSMETIC = {1, 3}


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


def char_id(rec: dict) -> str | None:
    m = re.match(r"^(\d+)", str(rec.get("id") or rec.get("slug") or ""))
    return m.group(1) if m else None


def disk_counts() -> dict:
    def n(p: Path, suffixes: tuple[str, ...]) -> int:
        return sum(1 for f in p.rglob("*") if f.is_file() and f.name.lower().endswith(suffixes)) if p.is_dir() else 0
    return {
        "rigs": n(VIEW / "assets/czn-rigs", (".json", ".atlas", ".webp")),
        "cards": n(VIEW / "assets/czn-cards", (".webp", ".webm")),
        "thumbs": n(VIEW / "public/thumbs/czn-rigs", (".png",)),
        "icons": n(VIEW / "public/thumbs/czn-ui", (".webp", ".png")),
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
    """Ambil tanda tangan + himpunan id dari ketiga sumber (tanpa unduh aset)."""
    gh_index = fetch(GH_RAW)
    commit = json.loads(fetch(GH_COMMIT)).get("sha", "")
    roster_raw, roster = wiki_data("/api/czn/characters/list?lang=en")
    cards_raw, cards = wiki_data("/api/czn/cards/list?lang=en")

    roster_ids = {str(c["id"]) for c in roster}
    idx = json.loads(gh_index)
    rig_slugs = {r.get("slug") or r.get("id") for r in idx.get("rigs", [])
                 if char_id(r) in roster_ids}
    card_stems = {
        f"{bc}/{str(c.get('sct_name') or '')}"
        for c in cards
        if (bc := str((c.get("base_combatant") or {}).get("id") or "")) in roster_ids
        and c.get("sct_name")
    }
    sig = hashlib.sha256(gh_index + roster_raw + cards_raw).hexdigest()[:16]
    return {
        "sig": sig,
        "commit": commit,
        "roster": sorted(roster_ids),
        "rigs": sorted(rig_slugs),
        "cards": sorted(card_stems),
        "counts": disk_counts(),
        "detail": {"roster": len(roster_ids), "rigs": len(rig_slugs),
                   "cards": len(card_stems)},
    }


def version(s: dict) -> str:
    d = s.get("detail", {})
    return f"{(s.get('commit') or '')[:8]} · {d.get('roster', 0)} karakter / {d.get('rigs', 0)} rig / {d.get('cards', 0)} kartu"


def check() -> dict:
    snap = snapshot()
    state = load_state()
    if not state.get("sig"):
        # Bootstrap: kondisi sekarang = baseline, jangan tawarkan unduh ulang.
        save_state({**snap, "updated_at": int(time.time())})
        return {"ok": True, "mode": "check", "changed": False, "new": 0,
                "new_ids": [], "previous": (snap["commit"] or "")[:8],
                "version": version(snap), "detail": snap["detail"],
                "bootstrap": True}

    new_rigs = sorted(set(snap["rigs"]) - set(state.get("rigs", [])))
    new_cards = sorted(set(snap["cards"]) - set(state.get("cards", [])))
    new_chars = sorted(set(snap["roster"]) - set(state.get("roster", [])))
    # Berkas hilang di disk juga berarti perlu dipulihkan.
    drift = snap["counts"] != state.get("counts")
    changed = snap["sig"] != state.get("sig") or bool(new_rigs) or bool(new_cards) or drift
    new_ids = [f"czn-rigs/{s}" for s in new_rigs]
    return {
        "ok": True,
        "mode": "check",
        "version": version(snap),
        "commit": snap["commit"],
        "previous": (state.get("commit") or "")[:8],
        "changed": changed,
        "new": len(new_rigs) + len(new_cards) + len(new_chars),
        "new_ids": new_ids,
        "detail": {**snap["detail"], "new_rigs": len(new_rigs),
                   "new_cards": len(new_cards), "new_chars": len(new_chars),
                   "disk": snap["counts"]},
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
                print(f"  peringatan: {label} gagal ({e}), dilewati", file=sys.stderr, flush=True)
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
        print(f"  peringatan: tidak bisa menyegarkan state: {e}", file=sys.stderr, flush=True)
        snap = snap_before
    save_state({**snap, "updated_at": int(time.time())})

    new_ids = pre.get("new_ids", [])
    return {
        "ok": True,
        "mode": "apply",
        "version": version(snap),
        "commit": snap.get("commit"),
        "new": len(new_ids),
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
