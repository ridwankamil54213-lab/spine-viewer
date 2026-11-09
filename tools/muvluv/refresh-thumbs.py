#!/usr/bin/env python3
"""Bikin thumbnail untuk rig Spine マブラヴ ガールズガーデンX dari game CG-nya.

Sumber: assets/muvluv-cg/*.png (ekstraksi ui_catalog, lihat README tools/muvluv).
Sasaran: 1243 model di assets/muvluv/ yang sebelumnya cuma punya badge huruf.

Aturan pemasangan (berurutan, pertama yang cocok menang):
  illust_portrait_  potret karakter 360x640   (paling diutamakan)
  cg_chara_         CG karakter 1920x1080
  cg_h_             CG H eksplisit 1920x1080  (atas permintaan user)
  cg_episode_ / cg_mecha_ / cg_story_        sisanya

Id model punya varian: e124105_F, 100201_B, 100001c, c101302, a10001 …
Jadi kandidat dasarnya = id utuh, id tanpa akhiran _F/_B/_S/_A, tanpa 'c',
lalu tanpa prefiks huruf. Satu potret dipakai bersama semua varian karakter.

Bentuk: TIDAK di-crop. Diperkecil agar muat kotak 300x300 dengan aspect ratio
utuh (360x640 -> ~169x300, 1920x1080 -> 300x169). CSS kartu sudah
`object-fit: contain`, jadi sisi kosongnya memang disengaja.

Konversi memakai /usr/bin/ffmpeg (bukan Pillow — interpreter systemd tidak
memilikinya). Idempoten: berkas .webp yang sudah ada dilewati.

Usage: python3 tools/muvluv/refresh-thumbs.py [--limit N]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
MODELS = VIEW / "assets" / "muvluv"
CG = VIEW / "assets" / "muvluv-cg"
OUT = VIEW / "public" / "thumbs" / "muvluv"
MAP_FILE = VIEW / "data" / "muvluv-thumb-sources.json"
MANIFEST = OUT / "_manifest.json"

# Urutan = prioritas. Semua keluarga CG boleh dipakai (termasuk H eksplisit).
SOURCES = (
    "illust_portrait_",
    "cg_chara_",
    "cg_h_",
    "cg_episode_",
    "cg_mecha_",
    "cg_story_",
)
SUFFIXES = ("_F", "_B", "_S", "_A")
MAX_SIDE = 300
WORKERS = 8


def base_candidates(model: str) -> list[tuple[str, str]]:
    """(cara, kandidat id dasar) — dipakai juga buat audit mapping."""
    out: list[tuple[str, str]] = [("exact", model)]
    for suf in SUFFIXES:
        if model.endswith(suf):
            out.append(("suf", model[: -len(suf)]))
    if model.endswith("c"):
        out.append(("c", model[:-1]))
    stripped = re.sub(r"^[a-z]+", "", model)
    if stripped != model:
        out.append(("strip", stripped))
    seen = set()
    uniq = []
    for kind, val in out:
        if val not in seen:
            seen.add(val)
            uniq.append((kind, val))
    return uniq


def resolve(model: str, cg_stems: set[str]) -> tuple[str, str] | None:
    """(nama berkas CG, cara cocok) atau None."""
    for kind, base in base_candidates(model):
        for src in SOURCES:
            key = src + base
            if key in cg_stems:
                return key + ".png", kind
    return None


def convert(png: Path, webp: Path) -> bool:
    if webp.is_file() and webp.stat().st_size > 512:
        return True
    ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    tmp = webp.with_suffix(".tmp.webp")
    try:
        p = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(png),
             "-vf", f"scale={MAX_SIDE}:{MAX_SIDE}:force_original_aspect_ratio=decrease",
             "-frames:v", "1", "-c:v", "libwebp", "-quality", "82",
             "-compression_level", "4", str(tmp)],
            capture_output=True, timeout=120,
        )
        if p.returncode != 0 or not tmp.is_file():
            return False
        data = tmp.read_bytes()
        if not data.startswith(b"RIFF") or len(data) < 512:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(webp)
        return True
    except Exception:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        return False
    finally:
        tmp.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah model (uji)")
    a = ap.parse_args()

    if not CG.is_dir() or not MODELS.is_dir():
        print("folder aset MuvLuv tidak ada", file=sys.stderr)
        sys.exit(1)

    cg_stems = {f.stem for f in CG.glob("*.png")}
    models = sorted(d.name for d in MODELS.iterdir() if d.is_dir())
    if a.limit:
        models = models[: a.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in OUT.glob("*.webp")}

    pairs: list[tuple[str, str, str]] = []  # (model, cg png, cara)
    unmatched: list[str] = []
    for m in models:
        hit = resolve(m, cg_stems)
        if hit:
            pairs.append((m, hit[0], hit[1]))
        else:
            unmatched.append(m)

    def one(pair) -> tuple[str, bool, str]:
        model, png, kind = pair
        return model, convert(CG / png, OUT / f"{model}.webp"), kind

    ok: list[tuple[str, str]] = []
    gagal: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for model, good, kind in pool.map(one, pairs):
            if good:
                ok.append((model, kind))
            else:
                gagal.append(model)

    manifest = {f"muvluv/{m}": f"{m}.webp" for m, _ in ok}
    ok_ids = {m for m, _ in ok}
    sources = {
        m: {"cg": png, "via": kind}
        for m, png, kind in pairs if m in ok_ids
    }
    if not a.limit:
        MANIFEST.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")
        MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        MAP_FILE.write_text(
            json.dumps(sources, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")

    by_kind: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for m, kind in ok:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        src = sources.get(m, {}).get("cg", "")
        tag = re.match(r"^[a-z_]+", src)
        key = tag.group(0) if tag else "?"
        by_source[key] = by_source.get(key, 0) + 1

    print(json.dumps({
        "models": len(models),
        "matched": len(pairs),
        "thumbOk": len(ok),
        "created": sum(1 for m, _ in ok if m not in existing),
        "unmatched": len(unmatched),
        "gagal": gagal[:10],
        "byCara": by_kind,
        "bySumber": by_source,
        "manifest": len(manifest),
        "unmatchedSample": unmatched[:12],
        "note": "mode uji — manifest tidak ditulis" if a.limit else "ok",
    }, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
