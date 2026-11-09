#!/usr/bin/env python3
"""Bangun metadata CrossCore dari ArtHub: nama, thumbnail, manifest.

Sumber (semuanya dari github.com/Talors1225/arthub-viewer-web, kecuali katalog
interaksi yang disajikan lewat R2 milik repo yang sama):

  crosscore/crosscore_chars.json               indeks 502 model Spine
  thumbs/index.json                           peta 1.004 thumbnail WebP
  thumbs/crosscore/<hash>.webp                berkas thumbnail
  crosscore-interaction/catalog/catalog.json  katalog 275 model interaksi (R2)

Keluaran:
  assets/crosscore/_names.json                 { "<model id>": {...} }
  public/thumbs/crosscore/_manifest.json
  public/thumbs/crosscore-interaction/_manifest.json

Pemetaan thumbnail tidak 1:1 dengan indeks: thumbs/index.json dibuat dari
katalog lama (555 entri), jadi sebagian kunci (varian "effect") tidak punya
model lagi. Kunci yang tidak bisa dipetakan ke folder model dilewati.

Idempoten: thumbnail yang sudah ada dilewati. Tidak menghapus apa pun.

Usage: python3 tools/crosscore/refresh-meta.py
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
A_CROSS = VIEW / "assets" / "crosscore"
A_INTER = VIEW / "assets" / "crosscore-interaction"
T_CROSS = VIEW / "public" / "thumbs" / "crosscore"
T_INTER = VIEW / "public" / "thumbs" / "crosscore-interaction"

GH_RAW = "https://raw.githubusercontent.com/Talors1225/arthub-viewer-web/main"
CHARS_URL = f"{GH_RAW}/crosscore/crosscore_chars.json"
THUMB_INDEX_URL = f"{GH_RAW}/thumbs/index.json"
THUMB_BASE = f"{GH_RAW}/thumbs/"
CATALOG_URL = ("https://pub-3be583976a374ca9aacd740e9d14ad96.r2.dev"
               "/crosscore-interaction/catalog/catalog.json")

HEADERS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
WORKERS = 8


class NotFound(Exception):
    """Berkas sumber memang tidak ada (404), jangan diulang."""


def fetch(url: str, timeout: int = 120, retries: int = 3) -> bytes:
    """curl lebih konsisten daripada urllib untuk GitHub raw + Cloudflare R2."""
    curl = shutil.which("curl") or "/usr/bin/curl"
    last = None
    for attempt in range(retries):
        fd, tmp = tempfile.mkstemp(prefix="ccdl-", suffix=".bin")
        os.close(fd)
        try:
            p = subprocess.run(
                [curl, "-sSL", "--max-time", str(timeout), "-A", HEADERS_UA,
                 "-o", tmp, "-w", "%{http_code}", url],
                capture_output=True, timeout=timeout + 20,
            )
            code = (p.stdout or b"").strip().decode("ascii", "replace")
            if p.returncode == 0 and code.startswith("2"):
                with open(tmp, "rb") as f:
                    return f.read()
            if code == "404":
                raise NotFound(url)
            last = f"HTTP {code} rc={p.returncode} {(p.stderr or b'')[:120]!r}"
        except NotFound:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        time.sleep(1.5 * (attempt + 1) if ("403" in str(last) or "429" in str(last))
                   else 0.8 * (attempt + 1))
    raise RuntimeError(f"gagal {url}: {last}")


def sanitize(s: str) -> str:
    """Sama persis dengan penamaan folder di skrip unduh CrossCore."""
    return "".join(ch if ch.isalnum() or ch in "_-." else "_" for ch in s)


def folder_from_dir(d: str) -> str:
    return sanitize(d.rstrip("/").rsplit("/", 1)[-1])


def load_json(url: str):
    return json.loads(fetch(url).decode("utf-8", "replace"))


def build_maps(chars: list, catalog: dict):
    """charId -> folder model, prefab -> entri model, id model -> entri."""
    char_by_id, char_by_folder = {}, {}
    for c in chars:
        cuts = c.get("cutscenes") or []
        if not cuts:
            continue
        folder = folder_from_dir(cuts[0].get("dir") or "")
        if not folder:
            continue
        char_by_id[str(c.get("id") or "")] = folder
        char_by_folder[folder] = c
    model_by_id, model_by_prefab = {}, {}
    for m in catalog.get("models") or []:
        model_by_id[str(m.get("id") or "")] = m
        prefab = m.get("prefab")
        if prefab:
            model_by_prefab[sanitize(str(prefab))] = m
    return char_by_id, char_by_folder, model_by_id, model_by_prefab


def thumb_targets(items: dict, char_by_id: dict, model_by_id: dict) -> tuple[dict, int]:
    """Petakan kunci thumbs/index.json -> (game, folder, url)."""
    out = {}
    skipped = 0
    for key, rel in items.items():
        if key.startswith("crosscore:"):
            parts = key.split(":")
            if len(parts) < 2:
                continue
            folder = char_by_id.get(parts[1])
            if not folder:
                skipped += 1
                continue
            game = "crosscore"
        elif key.startswith("crosscore-interaction:"):
            mid = key.split(":")[1]
            m = model_by_id.get(mid)
            prefab = (m or {}).get("prefab")
            if not prefab:
                skipped += 1
                continue
            folder = sanitize(str(prefab))
            game = "crosscore-interaction"
        else:
            continue
        ident = f"{game}/{folder}"
        if ident in out:
            continue  # beberapa varian -> ambil yang pertama
        out[ident] = (game, folder, THUMB_BASE + rel)
    return out, skipped


def manifest_keys(game: str, folder: str) -> list[str]:
    """Satu folder bisa berisi BEBERAPA skeleton.

    scanModels() lalu memberi id `<folder>#<stem>`, bukan `<folder>`. Kalau
    manifest tetap memakai id polos, thumbnail 7 folder multi-model ini tidak
    pernah tampil. Semua varian berbagi berkas WebP yang sama.
    """
    ident = f"{game}/{folder}"
    base_dir = A_CROSS if game == "crosscore" else A_INTER
    d = base_dir / folder
    if not d.is_dir():
        return [ident]
    skels = sorted(f.stem for f in d.iterdir()
                   if f.is_file() and f.suffix.lower() in (".json", ".skel"))
    if len(skels) > 1:
        return [f"{ident}#{s}" for s in skels]
    return [ident]


def download_thumbs(targets: dict) -> tuple[int, int, list[str], int]:
    T_CROSS.mkdir(parents=True, exist_ok=True)
    T_INTER.mkdir(parents=True, exist_ok=True)
    manifests = {"crosscore": {}, "crosscore-interaction": {}}

    def one(ident: str) -> tuple[str, bool, str]:
        game, folder, url = targets[ident]
        dest_dir = T_CROSS if game == "crosscore" else T_INTER
        name = f"{folder}.webp"
        dest = dest_dir / name
        if dest.exists() and dest.stat().st_size > 512:
            return ident, True, ""
        try:
            data = fetch(url, timeout=90)
            if not data.startswith(b"RIFF"):
                return ident, False, "bukan WebP"
            dest.write_bytes(data)
            return ident, True, ""
        except Exception as e:  # noqa: BLE001
            return ident, False, str(e)[:100]

    ok, bad = 0, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for ident, good, err in pool.map(one, list(targets)):
            if good:
                ok += 1
                game, folder, _ = targets[ident]
                for key in manifest_keys(game, folder):
                    manifests[game][key] = f"{folder}.webp"
            else:
                bad.append(f"{ident}: {err}")
    for game, man in manifests.items():
        dest_dir = T_CROSS if game == "crosscore" else T_INTER
        (dest_dir / "_manifest.json").write_text(
            json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return ok, len(bad), bad, sum(len(m) for m in manifests.values())


def build_names(char_by_folder: dict, model_by_prefab: dict) -> dict:
    """Katalog nama berdasarkan folder yang BENAR-BENAR ada di disk."""
    names = {}
    for d in sorted(A_CROSS.iterdir()) if A_CROSS.is_dir() else []:
        if not d.is_dir():
            continue
        c = char_by_folder.get(d.name)
        if not c:
            continue
        display = (c.get("displayName") or c.get("name") or d.name).strip()
        names[f"crosscore/{d.name}"] = {
            "name": display,
            "category": c.get("category") or None,
            "typeLabel": c.get("typeLabel") or None,
            "spineVersion": c.get("spineVersion") or None,
            "game": "crosscore",
        }
    for d in sorted(A_INTER.iterdir()) if A_INTER.is_dir() else []:
        if not d.is_dir():
            continue
        # Folder multi-layer berbentuk <prefab>__<layer>; induknya prefab.
        base = d.name.split("__", 1)[0]
        m = model_by_prefab.get(base)
        if not m:
            continue
        nm = (m.get("name") or base).strip()
        title = (m.get("title") or "").strip()
        names[f"crosscore-interaction/{d.name}"] = {
            "name": f"{nm} — {title}" if title else nm,
            "title": title or None,
            "group": m.get("group") or None,
            "modelId": m.get("id"),
            "game": "crosscore-interaction",
        }
    return names


def main() -> None:
    print("mengambil indeks ArtHub…", file=sys.stderr, flush=True)
    chars = (load_json(CHARS_URL).get("characters") or [])
    catalog = load_json(CATALOG_URL)
    items = (load_json(THUMB_INDEX_URL).get("items") or {})
    print(f"karakter {len(chars)} · model interaksi {len(catalog.get('models') or [])} · "
          f"thumbnail {len(items)}", file=sys.stderr, flush=True)

    char_by_id, char_by_folder, model_by_id, model_by_prefab = build_maps(chars, catalog)
    targets, skipped = thumb_targets(items, char_by_id, model_by_id)
    print(f"thumbnail terpetakan {len(targets)} · dilewati {skipped}", file=sys.stderr, flush=True)
    ok, bad, errs, manifest_entries = download_thumbs(targets)

    names = build_names(char_by_folder, model_by_prefab)
    A_CROSS.mkdir(parents=True, exist_ok=True)
    (A_CROSS / "_names.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    res = {
        "chars": len(chars),
        "catalogModels": len(catalog.get("models") or []),
        "thumbMapped": len(targets),
        "thumbSkipped": skipped,
        "thumbOk": ok,
        "thumbFailed": bad,
        "manifestEntries": manifest_entries,
        "names": len(names),
        "thumbErrors": errs[:10],
        "catalogSig": hashlib.sha256(json.dumps(catalog, sort_keys=True, ensure_ascii=False)
                                     .encode()).hexdigest()[:16],
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))
    if bad:
        print("GAGAL: sebagian thumbnail tidak terunduh", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
