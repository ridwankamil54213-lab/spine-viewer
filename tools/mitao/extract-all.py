#!/usr/bin/env python3
"""Ekstrak SEMUA bundle iOS Mitao Utopia jadi pohon berkas yang bisa dibrowse.

Tahap:
  1. Unduh + dekrip seluruh 3226 bundle IDOLAB2 v2 -> MITAO_STATE/all-bundles/
     (idempoten; yang sudah ada dilewati).
  2. Ekstrak tiap UnityFS pakai UnityPy ke MITAO_STATE/extracted/, dengan path
     SEMIRIP AssetPath asli di manifest (mis.
     Assets/Res/Textures/DynamicTextures/HeroIcon/HeroCard/HeroCard_10001.png).
     Sprite -> PNG, Texture2D -> PNG `__atlas`, TextAsset -> bytes. Objek tanpa
     pasangan AssetPath ditaruh di extracted/_bundles/<bundle>/.
     Tipe lain (prefab/anim/controller/audio) tetap utuh di all-bundles/ dan
     dicatat di extracted/_index.json supaya tidak ada yang hilang diam-diam.

Tujuan: user membuka File Browser, mencari sendiri ikon/ilustrasi yang mau
dijadikan thumbnail. Tidak ada screenshot manual, tidak ada pilihan otomatis.

Usage:
  /srv/venv-spine/bin/python tools/mitao/extract-all.py
  /srv/venv-spine/bin/python tools/mitao/extract-all.py --download-only
  /srv/venv-spine/bin/python tools/mitao/extract-all.py --workers 10
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import idol_v2 as v2  # noqa: E402
import UnityPy  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "update_mitao", str(ROOT / "tools" / "update-mitao.py"))
assert _spec is not None and _spec.loader is not None
up = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(up)

STATE = Path(os.environ.get("MITAO_STATE", "/srv/spine-assets/mitao"))
MANIFEST = STATE / "manifest.json"
ALL_BUNDLES = STATE / "all-bundles"
EXTRACTED = STATE / "extracted"
EXTRA = EXTRACTED / "_bundles"
INDEX = EXTRACTED / "_index.json"
CHUNK = 500

manifest = None
bundle_assets = None


def load_manifest():
    global manifest, bundle_assets
    manifest = json.load(open(MANIFEST))
    bundles = manifest["Bundles"]
    by_id = {i: b["BundleName"] for i, b in enumerate(bundles)}
    bundle_assets = collections.defaultdict(list)
    for a in manifest["Assets"]:
        bn = by_id.get(a["BundleID"])
        if bn:
            bundle_assets[bn].append(a)
    return bundles


def safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-+" else "_" for c in name)


def target_for(bn: str, obj_name: str, kind: str) -> Path:
    """Miripkan ke AssetPath asli kalau nama objeknya cocok."""
    for a in bundle_assets.get(bn, []):
        p = a["AssetPath"]
        stem = Path(p).stem
        addr = str(a.get("Address") or "")
        if obj_name == stem or obj_name == addr or obj_name == Path(p).name:
            base = Path(p).with_suffix("")
            if kind == "sprite":
                return EXTRACTED / base.with_suffix(".png")
            if kind == "texture":
                return EXTRACTED / (str(base) + "__atlas.png")
            if kind == "text":
                return EXTRACTED / p
            break
    return EXTRA / safe(bn) / f"{safe(obj_name)}__{kind}.png"


def extract_one(bn: str) -> dict:
    src = ALL_BUNDLES / bn
    stat = {"bundle": bn, "sprite": 0, "texture": 0, "text": 0,
            "other": collections.Counter(), "error": None, "written": 0}
    if not src.exists():
        stat["error"] = "bundle belum terunduh"
        return stat
    try:
        env = UnityPy.load(str(src))
        for o in env.objects:
            t = o.type.name
            try:
                d = o.read()
                nm = (getattr(d, "m_Name", None) or getattr(d, "name", "")
                      or f"pathid_{o.path_id}")
                if t == "Sprite":
                    img = d.image
                    if img is None:
                        continue
                    dest = target_for(bn, nm, "sprite")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    img.convert("RGBA").save(dest, "PNG")
                    stat["sprite"] += 1
                    stat["written"] += 1
                elif t == "Texture2D":
                    img = d.image
                    if img is None:
                        continue
                    dest = target_for(bn, nm, "texture")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    img.convert("RGBA").save(dest, "PNG")
                    stat["texture"] += 1
                    stat["written"] += 1
                elif t == "TextAsset":
                    raw = getattr(d, "m_Script", b"")
                    if isinstance(raw, str):
                        raw = raw.encode("utf-8", "surrogateescape")
                    if not raw:
                        continue
                    dest = target_for(bn, nm, "text")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(raw)
                    stat["text"] += 1
                    stat["written"] += 1
                else:
                    stat["other"][t] += 1
            except Exception:  # noqa: BLE001  (objek korup jangan gugurkan bundle)
                stat["other"][t] += 1
        stat["other"] = dict(stat["other"])
    except Exception as exc:  # noqa: BLE001
        stat["error"] = str(exc)[:200]
    return stat


def download_all(bundles: list, workers: int) -> dict:
    ALL_BUNDLES.mkdir(parents=True, exist_ok=True)
    # 1038 bundle skeleton sudah terunduh updater: hardlink saja, hemat 305 MiB.
    seed = STATE / "bundles"
    if seed.is_dir():
        for p in seed.iterdir():
            if p.is_file() and not (ALL_BUNDLES / p.name).exists():
                try:
                    os.link(p, ALL_BUNDLES / p.name)
                except OSError:
                    pass
    by_name = {b["BundleName"]: b for b in bundles}
    todo = [b["BundleName"] for b in bundles
            if not (ALL_BUNDLES / b["BundleName"]).exists()]
    print(f"unduh: {len(todo)}/{len(bundles)} bundle belum ada", file=sys.stderr,
          flush=True)
    rid, _ = up.release_info()
    done = failed = 0
    errors = []
    for start in range(0, len(todo), CHUNK):
        part = todo[start:start + CHUNK]
        cdn_names = [f"{by_name[n]['FileHash']}.bundle" for n in part]
        cdn_to_bn = {f"{by_name[n]['FileHash']}.bundle": n for n in part}
        resolved = up.resolve_files(rid, cdn_names)

        def get(cdn_name):
            bn = cdn_to_bn[cdn_name]
            dest = ALL_BUNDLES / bn
            url = resolved.get(cdn_name)
            if not url:
                return f"{bn}: tidak ada URL"
            try:
                blob = up.cdn_get(url, timeout=180)
                plain = v2.decrypt_bundle(
                    blob, bn, master_key=v2.MASTER_KEY,
                    derive_bundle=True, scope=v2.SCOPE)
                if not plain.startswith(b"UnityFS"):
                    return f"{bn}: hasil dekrip bukan UnityFS"
                dest.write_bytes(plain)
                return None
            except Exception as exc:  # noqa: BLE001
                return f"{bn}: {exc}"

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for err in ex.map(get, cdn_names):
                if err:
                    failed += 1
                    if len(errors) < 20:
                        errors.append(err)
                else:
                    done += 1
        print(f"  progres unduh {min(start + CHUNK, len(todo))}/{len(todo)}"
              f"  ok={done} gagal={failed}", file=sys.stderr, flush=True)
    return {"todo": len(todo), "downloaded": done, "failed": failed,
            "errors": errors}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--download-only", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    ALL_BUNDLES.mkdir(parents=True, exist_ok=True)
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    bundles = load_manifest()
    dl = download_all(bundles, args.workers)

    result = {"ok": dl["failed"] == 0, "download": dl,
              "bundle_total": len(bundles), "download_seconds": round(time.time() - t0, 1)}
    if not args.download_only:
        print("ekstraksi UnityPy dimulai…", file=sys.stderr, flush=True)
        index = {}
        tot = collections.Counter()
        errs = []
        names = [b["BundleName"] for b in bundles]
        # Thread pool: UnityPy sebagian besar I/O + dekode C, cukup 4 jalur.
        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, st in enumerate(ex.map(extract_one, names), 1):
                for k in ("sprite", "texture", "text", "written"):
                    tot[k] += st[k]
                for k, v in st["other"].items():
                    tot["other_" + k] += v
                if st["error"]:
                    errs.append({"bundle": st["bundle"], "error": st["error"]})
                index[st["bundle"]] = st
                if i % 200 == 0:
                    print(f"  progres ekstrak {i}/{len(names)}  gambar={tot['sprite'] + tot['texture']}"
                          f"  teks={tot['text']}  gagal={len(errs)}",
                          file=sys.stderr, flush=True)
        json.dump(index, open(INDEX, "w"), indent=0)
        result["extract"] = {
            "bundle": len(index),
            "sprite": tot["sprite"], "texture": tot["texture"],
            "text": tot["text"], "files_written": tot["written"],
            "other_types": {k[6:]: v for k, v in tot.items()
                            if k.startswith("other_")},
            "errors": len(errs), "error_samples": errs[:10],
            "index": str(INDEX),
        }
        result["ok"] = result["ok"] and len(errs) == 0
    result["all_bundles"] = str(ALL_BUNDLES)
    result["extracted"] = str(EXTRACTED)
    result["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
