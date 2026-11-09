#!/usr/bin/env python3
"""Satu pembaru Nikke: Goddess of Victory.

Dua sumber, dua peran:
  * NKAS https://nkas.pages.dev/nikkes/ -> daftar karakter KANONIK + nama
    Inggris (/nk_data/nikkegg/characters.json), dibantu
    nkas-l2d.pages.dev/characters.json untuk NPC/enemy.
  * ArtHub arthub-viewer-web/nikki     -> katalog rig + berkas model di R2.

Yang dipantau updater ini adalah NKAS: karakter baru, hash sumber nama, dan
jumlah nama yang benar-benar terpakai di _names.json. ArtHub tetap dipantau
untuk ketersediaan aset. tools/nikke/refresh.py menulis _names.json dari NKAS
dan mengunduh model dari ArtHub; refresh-thumbs.py mengunduh poster.

Kontrak server (UPDATERS["nikke"] di src/server.js):
  --check : cepat, TANPA mengunduh model. Bandingkan hash ArtHub + hash NKAS
            + daftar kode karakter NKAS + isi disk dengan
            data/nikke-update-state.json.
  --apply : segarkan nama dari NKAS, unduh model dari ArtHub, segarkan
            thumbnail, simpan state. cfg.rescan:true memaksa /api/models
            dipindai ulang.

Usage:
    python3 tools/nikke/update.py --check
    python3 tools/nikke/update.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STATE = VIEW / "data" / "nikke-update-state.json"
REFRESH = HERE / "refresh.py"
REFRESH_THUMBS = HERE / "refresh-thumbs.py"
ASSETS = VIEW / "assets" / "nikke"
THUMBS = VIEW / "public" / "thumbs" / "nikke"

# Model datang dari ArtHub; NAMA dan daftar karakter kanonik datang dari NKAS.
CATALOG = ("https://raw.githubusercontent.com/Talors1225/arthub-viewer-web/main/"
           "nikki/nikki_chars.json")
NKAS = "https://nkas.pages.dev/nk_data/nikkegg/characters.json"
NKAS_L2D = "https://nkas-l2d.pages.dev/characters.json"
UA = "spine-viewer-nikke-updater/1.0"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def source_state() -> dict:
    """Baca ketiga sumber. NKAS opsional supaya --check tetap jalan saat mati."""
    def get(url: str, required: bool = False) -> bytes:
        p = subprocess.run(
            ["/usr/bin/curl", "-sSL", "--max-time", "120", "-A", UA, url],
            capture_output=True, timeout=150)
        if p.returncode != 0 or not p.stdout:
            if required:
                raise RuntimeError(f"gagal membaca {url}")
            return b""
        return p.stdout

    arthub = get(CATALOG, True)
    nkas = get(NKAS)
    nkas_l2d = get(NKAS_L2D)
    try:
        chars = json.loads(arthub)["characters"]
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"katalog nikki tidak valid: {e}") from e
    try:
        rows = json.loads(nkas) if nkas else []
    except Exception:  # noqa: BLE001
        rows = []

    # "img": "si_c102_00_s" -> kode c102, "name" sudah bahasa Inggris.
    names = {}
    for x in rows:
        m = re.search(r"(c\d{3})", str(x.get("img") or ""))
        nm = str(x.get("name") or "").strip()
        if m and nm:
            names[m.group(1)] = nm
    codes = sorted(names)
    arthub_codes = {
        "c" + str(ch.get("characterCode")).strip().lstrip("c").zfill(3)
        for ch in chars if str(ch.get("characterCode") or "").strip()
    }
    return {
        "sig": sha(arthub + b"\0" + nkas + b"\0" + nkas_l2d),
        "arthubSig": sha(arthub),
        "nkasSig": sha(nkas + b"\0" + nkas_l2d),
        "expected": len(chars),
        "nkas": {
            "characters": len(rows),
            "codes": codes,
            "names": names,
            # Karakter yang sudah ada di NKAS tapi belum punya rig di ArtHub.
            "belumAdaDiArtHub": sorted(set(codes) - arthub_codes),
        },
    }


def disk_state() -> dict:
    def folders() -> int:
        return sum(1 for p in ASSETS.iterdir() if p.is_dir()) if ASSETS.is_dir() else 0

    def names() -> int:
        try:
            return len(json.loads((ASSETS / "_names.json").read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return 0

    def thumbs() -> int:
        return len(list(THUMBS.glob("*.webp"))) if THUMBS.is_dir() else 0

    def thumb_manifest() -> int:
        try:
            return len(json.loads((THUMBS / "_manifest.json").read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return 0

    return {"folders": folders(), "names": names(),
            "thumbs": thumbs(), "thumbManifest": thumb_manifest()}


def nkas_name_count() -> int:
    """Berapa model yang namanya benar-benar berasal dari NKAS."""
    try:
        d = json.loads((ASSETS / "_names.json").read_text(encoding="utf-8"))
        return sum(1 for v in d.values()
                   if str(v.get("nameSource") or "").startswith("nkas-"))
    except Exception:  # noqa: BLE001
        return 0


def load_state() -> dict | None:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def save_state(src: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "sig": src["sig"],
        "arthubSig": src["arthubSig"],
        "nkasSig": src["nkasSig"],
        "nkasCodes": src["nkas"]["codes"],
        "nkasCharacters": src["nkas"]["characters"],
        "nkasNames": nkas_name_count(),
        "disk": disk_state(),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=1, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    try:
        src = source_state()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}, indent=1))
        return 1

    state = load_state()
    disk = disk_state()
    nk = src["nkas"]
    expected = src["expected"]
    used = nkas_name_count()

    if not a.apply:
        alasan = []
        # State lama (format pra-NKAS) dan state pertama: sinkron diam-diam,
        # jangan anggap 206 karakter sebagai "baru" dan jangan nyalakan titik
        # merah palsu.
        bootstrapped = state is None or not state.get("nkasCodes")
        prev_codes = set((state or {}).get("nkasCodes") or [])
        if bootstrapped:
            save_state(src)
            state = load_state()
            prev_codes = set(nk["codes"])
        else:
            assert state is not None  # bootstrapped False berarti state ada
            if state.get("sig") != src["sig"]:
                if state.get("arthubSig") and state["arthubSig"] != src["arthubSig"]:
                    alasan.append("katalog ArtHub nikki berubah")
                if state.get("nkasSig") and state["nkasSig"] != src["nkasSig"]:
                    alasan.append("sumber nama NKAS berubah")
                if not state.get("arthubSig") and not state.get("nkasSig"):
                    alasan.append("katalog ArtHub / NKAS berubah")
            if state.get("disk") != disk:
                alasan.append("isi model Nikke berubah")
            if state.get("nkasNames") != used:
                alasan.append("jumlah nama NKAS terpakai berubah")

        baru = [c for c in nk["codes"] if c not in prev_codes]
        if baru:
            ringkas = ", ".join(f"{c} {nk['names'][c]}" for c in baru[:5])
            if len(baru) > 5:
                ringkas += f" (+{len(baru) - 5} lagi)"
            alasan.append(f"NKAS: {len(baru)} karakter baru ({ringkas})")
        missing = max(0, expected - disk["folders"])
        if missing:
            alasan.append(f"{missing} model belum terunduh")

        print(json.dumps({
            "ok": True,
            "mode": "check",
            "changed": bool(alasan),
            "alasan": alasan,
            "new": missing,
            "expected": expected,
            "disk": disk,
            "nkas": {
                "sumber": "nkas.pages.dev/nikkes",
                "karakter": nk["characters"],
                "kode": len(nk["codes"]),
                "sig": src["nkasSig"],
                "baru": [{"kode": c, "nama": nk["names"][c]} for c in baru],
                "belumAdaDiArtHub": nk["belumAdaDiArtHub"][:20],
                "belumAdaJumlah": len(nk["belumAdaDiArtHub"]),
                "namaTerpakai": used,
            },
            "seconds": round(time.time() - t0, 2),
        }, indent=1, ensure_ascii=False))
        return 0

    # --- apply: nama dari NKAS dulu, baru model + thumbnail dari ArtHub ---
    pn = subprocess.run([sys.executable, str(REFRESH), "--names-only"],
                        capture_output=True, text=True, timeout=600)
    p = subprocess.run([sys.executable, str(REFRESH), "--workers", "10"],
                       capture_output=True, text=True, timeout=3600)
    pt = subprocess.run([sys.executable, str(REFRESH_THUMBS), "--workers", "10"],
                        capture_output=True, text=True, timeout=3600)
    for line in (pn.stderr + "\n" + p.stderr + "\n" + pt.stderr).splitlines():
        print(f"  {line}", file=sys.stderr, flush=True)

    def parse(out):
        start = out.find("{")
        if start < 0:
            return {}
        try:
            d, _ = json.JSONDecoder().raw_decode(out[start:])
            return d
        except Exception:  # noqa: BLE001
            return {}

    ndetail = parse(pn.stdout)
    detail = parse(p.stdout)
    tdetail = parse(pt.stdout)
    save_state(source_state())
    models = detail.get("models") or {}
    tcounts = tdetail.get("thumbs") or {}
    errors = ((detail.get("errors") or []) + (tdetail.get("errors") or []))[:10]
    if pn.returncode != 0:
        errors.insert(0, "segarkan nama NKAS gagal — _names.json lama dipertahankan")
    res = {
        # Model & thumbnail tetap penentu sukses; NKAS mati cuma peringatan.
        "ok": p.returncode == 0 and pt.returncode == 0,
        "namaOk": pn.returncode == 0,
        "mode": "apply",
        "new": int(models.get("ok", 0) or 0),
        "gagal": len(errors),
        "detail": {
            "model": int(models.get("ok", 0) or 0),
            "sudahAda": int(models.get("skip", 0) or 0),
            "nama": int(detail.get("names", 0) or 0),
            "katalog": int(detail.get("katalog", 0) or 0),
            "thumbnail": int(tcounts.get("ok", 0) or 0) + int(tcounts.get("asli", 0) or 0),
            "thumbManifest": int(tdetail.get("manifest", 0) or 0),
            "namaSumber": ndetail.get("sources") or {},
            "nkas": {
                "sumber": "nkas.pages.dev/nikkes",
                "karakter": nk["characters"],
                "kode": len(nk["codes"]),
                "namaTerpakai": nkas_name_count(),
            },
        },
        "disk": disk_state(),
        "errors": errors,
        "seconds": round(time.time() - t0, 1),
        "catatan": "server memindai ulang /api/models otomatis (cfg.rescan)",
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
