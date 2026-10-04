#!/usr/bin/env python3
"""Ekstrak model Spine Chaos Zero Nightmare dari SSRArchive -> folder spine-viewer.

Pakai ssra.py (baca pack) + sct.py (SCT->PNG) + SCSPParser CLI (scsp->json).

Untuk tiap `<base>.scsp` di arsip, ambil juga `<base>.atlas` + halaman `<*.sct>`
yang disebut atlas, lalu tulis:
    <out>/<dir>/<base>.json   (dari scsp)
    <out>/<dir>/<base>.atlas  (nama halaman .sct -> .png)
    <out>/<dir>/<png>         (dari sct)

Jalankan:
    python extract-czn.py --manifest gameres/manifest.ssra \
        --convert ./scsp2json --out /opt/spine-viewer/assets/chaoszero \
        --filter model/ --workers 8
"""
import argparse
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ssra  # noqa: E402
import sct   # noqa: E402

try:
    from PIL import Image
except Exception:
    Image = None


def log(*a):
    print(*a, flush=True)


def convert_scsp(exe: str, data: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".scsp", delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        r = subprocess.run([exe, tmp], capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", "replace")[:200])
        return r.stdout
    finally:
        os.unlink(tmp)


def pages_from_atlas(atlas_text: str):
    return [l.strip() for l in atlas_text.splitlines()
            if l.strip().lower().endswith((".sct", ".sct2", ".png"))
            and " " not in l.strip()]


def do_one(args_tuple):
    (arc_manifest, exe, out_root, base_path, filter_dir) = args_tuple
    # buka arsip per-proses (aman utk ProcessPoolExecutor)
    a = ssra.SSRA(arc_manifest)
    base = base_path[:-5]                       # buang .scsp
    name = os.path.basename(base)
    # satu model per folder, path arsip dipertahankan: <out>/<relpath-tanpa-ext>/
    dest = Path(out_root) / base
    dest.mkdir(parents=True, exist_ok=True)
    try:
        # 1. scsp -> json
        scsp = a.read(base_path)
        js = convert_scsp(exe, scsp)
        (dest / f"{name}.json").write_bytes(js)

        # 2. atlas (+ fix nama halaman)
        atlas_path = base + ".atlas"
        atlas = a.read(atlas_path).decode("utf-8", "replace")
        pages = pages_from_atlas(atlas)
        fixed = atlas
        for pg in pages:
            fixed = fixed.replace(pg + "\n", pg.rsplit(".", 1)[0] + ".png\n")
        (dest / f"{name}.atlas").write_text(fixed)

        # 3. halaman SCT -> PNG
        for pg in pages:
            if pg.lower().endswith(".png"):
                continue
            sct_path = os.path.join(os.path.dirname(base_path), pg).replace("\\", "/")
            try:
                d = a.read(sct_path)
            except KeyError:
                continue
            w, h, rgba = sct.decode_to_rgba(d)
            if Image is not None:
                Image.frombytes("RGBA", (w, h), rgba).save(dest / (pg.rsplit(".", 1)[0] + ".png"))
            else:
                raise RuntimeError("Pillow tidak ada")
        return (base_path, None)
    except Exception as e:
        return (base_path, f"{type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--convert", required=True, help="path ke scsp2json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--filter", default="model/")
    ap.add_argument("--prefix", default="", help="subfolder di dalam --out")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    a = ssra.SSRA(args.manifest)
    bases = [p for p in sorted(a.files)
             if p.startswith(args.filter) and p.endswith(".scsp") and not a.files[p]["encrypted"]]
    # hanya yang punya atlas
    bases = [p for p in bases if (p[:-5] + ".atlas") in a.files]
    if args.limit:
        bases = bases[:args.limit]
    log(f"model: {len(bases)}  filter={args.filter!r}  -> {args.out}")

    tasks = [(args.manifest, args.convert, args.out, p, args.prefix) for p in bases]
    ok = fail = 0
    fails = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for i, (path, err) in enumerate(ex.map(do_one, tasks), 1):
            if err:
                fail += 1
                fails.append((path, err))
            else:
                ok += 1
            if i % 50 == 0 or i == len(tasks):
                log(f"  {i}/{len(tasks)} ok={ok} fail={fail}")
    log(f"\nSELESAI ok={ok} fail={fail}")
    for p, e in fails[:25]:
        log("  GAGAL", p, "->", e)


if __name__ == "__main__":
    main()
