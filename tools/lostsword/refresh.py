#!/usr/bin/env python3
"""Sinkronkan Lost Sword dari https://lost-sword-l2d-viewer.pages.dev/.

Menggantikan pipeline ekstraksi XAPK mentah (tools/update-lostsword.py +
tools/extract-lostsword-video.py) yang menghasilkan 868 model bercampur
duplikat kapitalisasi (`Anessa` vs `anessa`), ratusan monster/prop mentah,
video High/Low dobel, dan nol thumbnail.

Sumber tunggal sekarang LIVE dari situs referensi:
  - HTML utama -> resolve dinamis `/assets/index-<hash>.js`
  - Katalog `jl=[{...}]` (143 entri: 130 Playable + 13 NPC) di-parse murni
    Python tanpa dependensi eksternal.
  - 276 folder Spine / 287 skeleton:
      standing/<folder>/<stem>.skel|.json + .atlas + .png (147 folder, 158 skel)
      chibi/<folder>/<stem>.skel + .atlas + .png          (78 folder, 78 skel)
      pet/<folder>/<stem>.skel + .atlas + .png            (51 folder, 51 skel)
  - 87 video cutscene (.mp4):
      skill-videos/Pc_*.mp4     (82 klip)
      memorial-videos/Pc_*.mp4  (5 klip)
  - Thumbnail WebP resmi:
      character-images/*.webp   (potret kartu 256x340)
      small-images/*.webp       (ikon chibi/battle)
      pet-images/*.webp         (ikon pet)

Saat migrasi dari tata letak XAPK lama (`lobbyunit/` + `High/`), berkas yang
identik di-seed dari disk lokal ke staging, sisanya diunduh dari situs,
divalidasi penuh, lalu pohon lama dipindah ke backup di luar repo
(`/srv/spine-assets/lostsword/apk-backup-<waktu>/`) sebelum swap atomik.

Keluaran:
  assets/lostsword/{standing,chibi,pet}/<folder>/...
  assets/lostsword/_names.json              (374 model/video + 84 family)
  assets/lostsword-video/{skill-videos,memorial-videos}/*.mp4
  public/thumbs/lostsword/*.webp + _manifest.json (374 kunci)

Usage:
  python3 tools/lostsword/refresh.py [--limit N] [--replace]
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2]
OUT_MODELS = VIEW / "assets" / "lostsword"
OUT_VIDEOS = VIEW / "assets" / "lostsword-video"
THUMBS = VIEW / "public" / "thumbs" / "lostsword"
STATE_DIR = Path(os.environ.get("LOSTSWORD_STATE", "/srv/spine-assets/lostsword"))
SITE = "https://lost-sword-l2d-viewer.pages.dev"
UA = "Mozilla/5.0 (X11; Linux x86_64) spine-viewer-lostsword/1.0"
WORKERS = 8

TOKEN_RE = re.compile(r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[^"\']+)')


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def san(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]", "-", str(name).strip())


def fetch(url: str, timeout: int = 120, retries: int = 3) -> bytes:
    curl = shutil.which("curl") or "/usr/bin/curl"
    last = None
    for attempt in range(retries):
        fd, tmp = tempfile.mkstemp(prefix="lsdl-", suffix=".bin")
        os.close(fd)
        try:
            p = subprocess.run(
                [curl, "-sSL", "--max-time", str(timeout), "-A", UA,
                 "-o", tmp, "-w", "%{http_code}", url],
                capture_output=True, timeout=timeout + 20,
            )
            code = (p.stdout or b"").strip().decode("ascii", "replace")
            if p.returncode == 0 and code.startswith("2"):
                data = Path(tmp).read_bytes()
                if data:
                    return data
            last = f"HTTP {code} rc={p.returncode}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"gagal mengunduh {url}: {last}")


def site_url(rel: str) -> str:
    clean = rel.lstrip("./").lstrip("/")
    quoted = "/".join(urllib.parse.quote(urllib.parse.unquote(seg)) for seg in clean.split("/"))
    return f"{SITE}/{quoted}"


def fetch_catalog() -> tuple[list[dict], str, str]:
    """Kembalikan (catalog_list, bundle_path, catalog_sha256_16)."""
    html = fetch(f"{SITE}/", timeout=45).decode("utf-8", "replace")
    m = re.search(r'<script[^>]+src="(/assets/index-[^"]+\.js)"', html)
    if not m:
        raise RuntimeError("bundle JS utama tidak ditemukan di HTML situs")
    bundle_path = m.group(1)
    js = fetch(f"{SITE}{bundle_path}", timeout=90).decode("utf-8", "replace")
    idx = js.find("memorialVideoPath")
    if idx < 0:
        raise RuntimeError("array katalog karakter tidak ditemukan di bundle JS")
    start = js.rfind("=[{", 0, idx)
    if start < 0:
        raise RuntimeError("awal array katalog tidak ditemukan")
    start += 1
    depth = 0
    in_str = False
    str_ch = ""
    esc = False
    end = len(js)
    for i in range(start, len(js)):
        c = js[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == str_ch:
                in_str = False
            continue
        if c in ('"', "'"):
            in_str = True
            str_ch = c
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    lit = js[start:end]
    parts = []
    for tok in TOKEN_RE.findall(lit):
        if tok.startswith('"'):
            parts.append(tok)
        elif tok.startswith("'"):
            inner = tok[1:-1].replace('\\"', '"').replace("\\'", "'")
            parts.append(json.dumps(inner))
        else:
            t = re.sub(r'(?<=[{,])\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*:', r'"\1":', tok)
            t = t.replace(":!0", ":true").replace(":!1", ":false").replace(":void 0", ":null")
            parts.append(t)
    raw_json = "".join(parts)
    catalog = json.loads(raw_json)
    sig = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()[:16]
    return catalog, bundle_path, sig


def referenced_pages(atlas_bytes: bytes) -> list[str]:
    out = []
    for line in atlas_bytes.decode("utf-8", "replace").splitlines():
        s = line.strip()
        if not s or line.startswith(" "):
            continue
        if s.lower().endswith((".png", ".webp", ".jpg", ".jpeg")):
            if s not in out:
                out.append(s)
    return out


def collect_spine_folders(catalog: list[dict]) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """{(kind, folderName): [(skelUrl, atlasUrl), ...]}."""
    folders: dict[tuple[str, str], list[tuple[str, str]]] = collections.OrderedDict()
    for c in catalog:
        for kind, key in (("standing", "standingSpines"),
                          ("chibi", "chibiSpines"),
                          ("pet", "petSpines")):
            for s in (c.get(key) or []):
                fn = s["folderName"]
                bucket = folders.setdefault((kind, fn), [])
                if s.get("isMultiLayer"):
                    for lk in ("frontLayer", "backLayer"):
                        sub = s.get(lk)
                        if sub and sub.get("skelUrl") and sub.get("atlasUrl"):
                            pair = (sub["skelUrl"], sub["atlasUrl"])
                            if pair not in bucket:
                                bucket.append(pair)
                elif s.get("skelUrl") and s.get("atlasUrl"):
                    pair = (s["skelUrl"], s["atlasUrl"])
                    if pair not in bucket:
                        bucket.append(pair)
    return folders


def collect_videos(catalog: list[dict]) -> list[str]:
    vids = []
    seen = set()
    for c in catalog:
        for v in (c.get("videos") or []):
            p = v.get("path")
            if p and p not in seen:
                seen.add(p)
                vids.append(p)
    return vids


def folder_complete(dest: Path, pairs: list[tuple[str, str]]) -> bool:
    if not dest.is_dir():
        return False
    for skel_url, atlas_url in pairs:
        sf = dest / os.path.basename(skel_url)
        af = dest / os.path.basename(atlas_url)
        if not (sf.is_file() and sf.stat().st_size > 16 and af.is_file() and af.stat().st_size > 16):
            return False
        pages = referenced_pages(af.read_bytes())
        if not pages:
            return False
        for pg in pages:
            pf = dest / pg
            if not (pf.is_file() and pf.stat().st_size > 64):
                return False
    return True


def build_seed_index(seed_roots: list[Path]) -> tuple[dict, dict]:
    """Index berkas lokal lama supaya migrasi tidak perlu unduh ulang 270 folder."""
    group_map = {"standing": "lobbyunit", "chibi": "unit", "pet": "pet"}
    by_gf: dict[tuple[str, str], list[Path]] = {}
    by_skel: dict[tuple[str, str], list[Path]] = {}
    for root in seed_roots:
        if not root.is_dir():
            continue
        for kind, old_g in list(group_map.items()) + [("standing", "standing"), ("chibi", "chibi"), ("pet", "pet")]:
            gp = root / old_g
            if not gp.is_dir():
                continue
            for d in gp.iterdir():
                if not d.is_dir():
                    continue
                by_gf.setdefault((kind, d.name.lower()), []).append(d)
                for f in d.iterdir():
                    if f.is_file() and f.suffix.lower() in (".skel", ".json"):
                        by_skel.setdefault((kind, f.name.lower()), []).append(d)
    return by_gf, by_skel


def copy_or_link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def try_seed_folder(kind: str, fn: str, pairs: list[tuple[str, str]],
                    dest: Path, by_gf: dict, _by_skel: dict) -> bool:
    cands = list(by_gf.get((kind, fn.lower()), [])) + list(by_gf.get((kind, san(fn).lower()), []))
    if kind == "pet" and fn == "Pet_Agravaine_01":
        cands += list(by_gf.get(("pet", "pet_agravain_01"), []))
    for src_dir in cands:
        flist = {f.name.lower(): f for f in src_dir.iterdir() if f.is_file()}
        if not all(os.path.basename(su).lower() in flist and os.path.basename(au).lower() in flist
                   for su, au in pairs):
            continue
        to_copy: list[tuple[Path, str]] = []
        ok_pages = True
        for su, au in pairs:
            sname = os.path.basename(su)
            aname = os.path.basename(au)
            sfile = flist[sname.lower()]
            afile = flist[aname.lower()]
            to_copy.append((sfile, sname))
            to_copy.append((afile, aname))
            pages = referenced_pages(afile.read_bytes())
            if not pages:
                ok_pages = False
                break
            for pg in pages:
                pfile = flist.get(pg.lower())
                if not pfile:
                    ok_pages = False
                    break
                to_copy.append((pfile, pg))
        if not ok_pages:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        for src_f, target_name in to_copy:
            copy_or_link(src_f, dest / target_name)
        if folder_complete(dest, pairs):
            return True
    return False


def download_spine_folder(kind: str, fn: str, pairs: list[tuple[str, str]], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for skel_url, atlas_url in pairs:
        sname = os.path.basename(skel_url)
        aname = os.path.basename(atlas_url)
        sbytes = fetch(site_url(skel_url), timeout=120)
        abytes = fetch(site_url(atlas_url), timeout=120)
        (dest / sname).write_bytes(sbytes)
        (dest / aname).write_bytes(abytes)
        pages = referenced_pages(abytes)
        if not pages:
            raise RuntimeError(f"atlas {atlas_url} tidak mendeklarasikan halaman PNG")
        base_dir = atlas_url.rsplit("/", 1)[0]
        for pg in pages:
            pbytes = fetch(site_url(f"{base_dir}/{pg}"), timeout=120)
            (dest / pg).write_bytes(pbytes)


def sync_models(folders: dict[tuple[str, str], list[tuple[str, str]]],
                target_root: Path, seed_roots: list[Path]) -> tuple[dict, list[str]]:
    by_gf, by_skel = build_seed_index(seed_roots)
    jobs = list(folders.items())
    counts = {"skip": 0, "seeded": 0, "downloaded": 0, "fail": 0}
    errors: list[str] = []

    def one(item) -> tuple[str, str]:
        (kind, fn), pairs = item
        dest = target_root / kind / san(fn)
        if folder_complete(dest, pairs):
            return "skip", ""
        if try_seed_folder(kind, fn, pairs, dest, by_gf, by_skel):
            return "seeded", ""
        try:
            download_spine_folder(kind, fn, pairs, dest)
            if folder_complete(dest, pairs):
                return "downloaded", ""
            return "fail", f"{kind}/{fn}: berkas belum lengkap sesudah unduh"
        except Exception as exc:  # noqa: BLE001
            return "fail", f"{kind}/{fn}: {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, (st, err) in enumerate(pool.map(one, jobs), 1):
            counts[st] = counts.get(st, 0) + 1
            if err:
                errors.append(err)
            if i % 50 == 0 or i == len(jobs):
                log(f"  spine {i}/{len(jobs)} (skip={counts['skip']} seed={counts['seeded']} "
                    f"dl={counts['downloaded']} fail={counts['fail']})")
    return counts, errors


def sync_videos(vpaths: list[str], target_root: Path,
                seed_roots: list[Path]) -> tuple[dict, list[str]]:
    seed_files: dict[str, Path] = {}
    for r in seed_roots:
        if not r.is_dir():
            continue
        for dp, _, fs in os.walk(r):
            # Utamakan High/ daripada Low/
            is_low = "/low/" in (dp.replace("\\", "/").lower() + "/")
            for f in fs:
                if f.lower().endswith(".mp4"):
                    k = f.lower()
                    if k not in seed_files or not is_low:
                        seed_files[k] = Path(dp) / f

    counts = {"skip": 0, "seeded": 0, "downloaded": 0, "fail": 0}
    errors: list[str] = []

    def one(vpath: str) -> tuple[str, str]:
        rel = vpath.lstrip("./").lstrip("/")
        dest = target_root / rel
        if dest.is_file() and dest.stat().st_size > 1024:
            return "skip", ""
        fname = os.path.basename(rel).lower()
        # Hati-hati: Pc_Galahad_01_Memorial.mp4 ada di skill-videos DAN memorial-videos
        # dengan isi berbeda! Jadi seed hanya untuk skill-videos atau kalau ukuran cocok.
        if rel.startswith("skill-videos/") and fname in seed_files and "memorial" not in fname:
            src = seed_files[fname]
            if src.stat().st_size > 1024:
                copy_or_link(src, dest)
                return "seeded", ""
        try:
            data = fetch(site_url(vpath), timeout=240)
            if len(data) < 1024:
                return "fail", f"{rel}: ukuran terlalu kecil ({len(data)}B)"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return "downloaded", ""
        except Exception as exc:  # noqa: BLE001
            return "fail", f"{rel}: {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, (st, err) in enumerate(pool.map(one, vpaths), 1):
            counts[st] = counts.get(st, 0) + 1
            if err:
                errors.append(err)
            if i % 25 == 0 or i == len(vpaths):
                log(f"  video {i}/{len(vpaths)} (skip={counts['skip']} seed={counts['seeded']} "
                    f"dl={counts['downloaded']} fail={counts['fail']})")
    return counts, errors


def build_metadata_and_thumbs(catalog: list[dict]) -> tuple[dict, dict, list[tuple[str, str]]]:
    """Bangun (_names.json payload, _manifest.json, daftar unduh thumbnail)."""
    folder_skels: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for c in catalog:
        for kind, key in (("standing", "standingSpines"),
                          ("chibi", "chibiSpines"),
                          ("pet", "petSpines")):
            for s in (c.get(key) or []):
                fn = san(s["folderName"])
                if s.get("isMultiLayer"):
                    for lk in ("frontLayer", "backLayer"):
                        sub = s.get(lk)
                        if sub and sub.get("skelUrl"):
                            folder_skels[(kind, fn)].add(os.path.basename(sub["skelUrl"]))
                elif s.get("skelUrl"):
                    folder_skels[(kind, fn)].add(os.path.basename(s["skelUrl"]))

    def model_id_for(kind: str, folder_name: str, skel_url: str) -> str:
        fn = san(folder_name)
        base_id = f"lostsword/{kind}/{fn}"
        if len(folder_skels[(kind, fn)]) > 1:
            stem = os.path.splitext(os.path.basename(skel_url))[0]
            return f"{base_id}#{stem}"
        return base_id

    def video_id_for(vpath: str) -> str:
        rel = vpath.lstrip("./").lstrip("/")
        return f"lostsword-video/{os.path.splitext(rel)[0]}"

    def thumb_file_for(prefix: str, rel_path: str | None) -> str | None:
        if not rel_path:
            return None
        base = urllib.parse.unquote(os.path.basename(rel_path))
        return f"{prefix}_{san(base)}"

    # Kelompokkan 143 entri katalog menjadi 84 family karakter (0 tabrakan aset)
    by_unit: dict[str, list[dict]] = collections.OrderedDict()
    lobby_entries: list[dict] = []
    for c in catalog:
        ch = c.get("chibiSpines") or []
        if c["id"] == "char_116":
            by_unit["chibi:./spine-assets/chibi/Ria/Ria.skel"].append(c)
            continue
        if ch:
            by_unit.setdefault("chibi:" + ch[0]["skelUrl"], []).append(c)
        elif c.get("variant") == "Lobby":
            lobby_entries.append(c)
        else:
            by_unit["solo:" + c["id"]] = [c]

    title_to_key: dict[str, str] = {}
    for k, items in by_unit.items():
        for it in items:
            t = (it.get("title") or "").strip().lower()
            if t and t not in title_to_key:
                title_to_key[t] = k
    lobby_map = {
        "bunny bedivere": "chibi:./spine-assets/chibi/Bedivere/Bedivere.skel",
        "maid elizabeth": "chibi:./spine-assets/chibi/Elizabeth/Elizabeth.skel",
        "eva": "chibi:./spine-assets/chibi/Eva/Eva.skel",
    }
    for c in lobby_entries:
        t = (c.get("title") or "").strip().lower()
        k = lobby_map.get(t) or title_to_key.get(t)
        if k and k in by_unit:
            by_unit[k].append(c)
        else:
            by_unit["solo:" + c["id"]] = [c]

    models_meta: dict[str, dict] = {}
    families_meta: list[dict] = []
    thumb_manifest: dict[str, str] = {}
    thumb_jobs: dict[str, str] = {}

    def register_thumb(model_id: str, prefix: str, rel_path: str | None,
                       fallback_rel: str | None = None) -> None:
        if model_id in thumb_manifest:
            return
        chosen = rel_path or fallback_rel
        if not chosen:
            return
        use_pfx = prefix if rel_path else "char"
        fname = thumb_file_for(use_pfx, chosen)
        if not fname:
            return
        thumb_manifest[model_id] = fname
        thumb_jobs[fname] = chosen

    for _, items in by_unit.items():
        base = items[0]
        char_name = (base.get("title") or base["name"]).strip()
        if base["id"] == "char_39":
            char_name = "Eva (Awakening)"
        category = base.get("category") or "Playable"
        # Kumpulkan semua nama varian/kostum supaya pencarian di sidebar
        # menemukan kartu root saat user mengetik "Bunny", "Silent Shadow", dst.
        search_tags = [char_name, category]
        for c in items:
            for fld in (c.get("title"), c.get("name"), c.get("variant"), c.get("petName")):
                if fld and fld not in search_tags:
                    search_tags.append(str(fld).strip())
        squad_summary = " · ".join(search_tags[1:])

        members: list[dict] = []
        seen: set[str] = set()

        def add_member(mid: str, lbl: str, entry: dict, kind_tag: str) -> None:
            if mid in seen:
                return
            seen.add(mid)
            members.append({"id": mid, "label": lbl})
            is_root = len(members) == 1
            models_meta[mid] = {
                "name": char_name if is_root else f"{char_name} — {lbl}",
                "label": lbl,
                "kind": kind_tag,
                "character": {
                    "name": char_name,
                    "title": (entry.get("title") or entry["name"]).strip(),
                    "category": entry.get("category") or category,
                    "variant": entry.get("variant") or None,
                    "petName": entry.get("petName") or None,
                    "isNew": any(bool(x.get("isNew")) for x in items) if is_root else bool(entry.get("isNew")),
                    "squad": squad_summary,
                    "source": "lost-sword-l2d-viewer.pages.dev",
                },
            }

        # 1) Standing spines
        for c in items:
            var = c.get("variant")
            title = (c.get("title") or c["name"]).strip()
            sub_title = title.split(":", 1)[1].strip() if ":" in title else ""
            st_list = c.get("standingSpines") or []
            for idx_s, s in enumerate(st_list):
                if s.get("isMultiLayer"):
                    for lk, sfx in (("frontLayer", "Lobby"), ("backLayer", "Lobby (Back)")):
                        sub = s.get(lk)
                        if sub and sub.get("skelUrl"):
                            mid = model_id_for("standing", s["folderName"], sub["skelUrl"])
                            lbl = "Utama" if not members else sfx
                            add_member(mid, lbl, c, "standing")
                            register_thumb(mid, "char", c.get("imagePath"), base.get("imagePath"))
                elif s.get("skelUrl"):
                    mid = model_id_for("standing", s["folderName"], s["skelUrl"])
                    if not members:
                        lbl = "Utama"
                    elif var == "Lobby":
                        lbl = "Lobby"
                    else:
                        parts = [p for p in (var, sub_title) if p]
                        if not parts and c["id"] == "char_116":
                            parts = ["NPC"]
                        lbl = " — ".join(parts) if parts else (s.get("label") or s["folderName"])
                        if len(st_list) > 1 and idx_s > 0:
                            lbl = f"{lbl} ({s['folderName'].split('_')[-1]})"
                    add_member(mid, lbl, c, "standing")
                    register_thumb(mid, "char", c.get("imagePath"), base.get("imagePath"))

        # 2) Chibi (Battle Mode) spines
        for c in items:
            for idx_s, s in enumerate(c.get("chibiSpines") or []):
                if s.get("skelUrl"):
                    mid = model_id_for("chibi", s["folderName"], s["skelUrl"])
                    if not members:
                        lbl = "Utama"
                    elif idx_s > 0:
                        lbl = f"Battle Mode ({s['folderName']})"
                    elif c["id"] == "char_116":
                        lbl = "Battle Mode (NPC)"
                    else:
                        lbl = "Battle Mode"
                    add_member(mid, lbl, c, "chibi")
                    register_thumb(mid, "small", c.get("smallImagePath"), c.get("imagePath") or base.get("imagePath"))

        # 3) Pet spines
        for c in items:
            var = c.get("variant")
            for s in (c.get("petSpines") or []):
                if s.get("skelUrl"):
                    mid = model_id_for("pet", s["folderName"], s["skelUrl"])
                    pname = c.get("petName") or s.get("label") or "Pet"
                    lbl = pname if pname.lower().startswith("pet") else f"Pet — {pname}"
                    if s["folderName"].lower().startswith("ps_") and var:
                        lbl = f"{lbl} ({var})"
                    add_member(mid, lbl, c, "pet")
                    register_thumb(mid, "pet", c.get("petImagePath"), c.get("imagePath") or base.get("imagePath"))

        # 4) Cutscene & Memorial Videos
        all_vpaths = {vv["path"] for cc in items for vv in (cc.get("videos") or []) if vv.get("path")}
        for c in items:
            var = c.get("variant")
            for v in (c.get("videos") or []):
                if v.get("path"):
                    vid = video_id_for(v["path"])
                    vlbl = v.get("label") or "Skill Cutscene"
                    if vlbl == "Memorial":
                        vlbl = "Cutscene — Memorial"
                    elif var and var not in ("None", None) and len(all_vpaths) > 1:
                        vlbl = f"{vlbl} ({var})"
                    add_member(vid, vlbl, c, "video")
                    register_thumb(vid, "char", c.get("imagePath"), base.get("imagePath"))

        if members:
            families_meta.append({
                "root": members[0]["id"],
                "name": char_name,
                "category": category,
                "members": members,
            })

    names_payload = {
        "source": "lost-sword-l2d-viewer.pages.dev",
        "entries": len(catalog),
        "families": families_meta,
        "models": models_meta,
    }
    return names_payload, thumb_manifest, sorted(thumb_jobs.items())


def sync_thumbs(jobs: list[tuple[str, str]], manifest: dict[str, str]) -> tuple[int, int, list[str]]:
    THUMBS.mkdir(parents=True, exist_ok=True)
    ok_count = 0
    dl_count = 0
    errors: list[str] = []

    def one(job: tuple[str, str]) -> tuple[str, str, str]:
        fname, rel = job
        dest = THUMBS / fname
        if dest.is_file() and dest.stat().st_size > 128:
            return fname, "skip", ""
        try:
            data = fetch(site_url(rel), timeout=90)
            if not (data.startswith(b"RIFF") or data.startswith(b"\x89PNG")):
                return fname, "fail", f"{rel}: bukan WebP/PNG valid"
            dest.write_bytes(data)
            return fname, "downloaded", ""
        except Exception as exc:  # noqa: BLE001
            return fname, "fail", f"{rel}: {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for fname, st, err in pool.map(one, jobs):
            if st in ("skip", "downloaded"):
                ok_count += 1
            if st == "downloaded":
                dl_count += 1
            if err:
                errors.append(err)

    # Hanya cantumkan kunci yang berkas thumbnail-nya benar-benar ada di disk
    clean_manifest = {
        k: v for k, v in sorted(manifest.items())
        if (THUMBS / v).is_file()
    }
    (THUMBS / "_manifest.json").write_text(
        json.dumps(clean_manifest, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    return ok_count, dl_count, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="uji sebagian entri tanpa menimpa metadata")
    ap.add_argument("--replace", action="store_true",
                    help="bangun ke staging lalu ganti pohon aset lama dengan backup di luar repo")
    args = ap.parse_args()

    t0 = time.time()
    log("mengambil katalog Lost Sword L2D Viewer…")
    catalog, bundle_path, sig = fetch_catalog()
    if args.limit:
        catalog = catalog[: args.limit]
    folders = collect_spine_folders(catalog)
    vpaths = collect_videos(catalog)
    log(f"katalog: {len(catalog)} entri · {len(folders)} folder Spine · {len(vpaths)} video · sig={sig}")

    # Deteksi otomatis apakah pohon aset masih memakai struktur XAPK lama (`lobbyunit/`)
    legacy_layout = (OUT_MODELS / "lobbyunit").is_dir() or (OUT_VIDEOS / "High").is_dir()
    do_replace = (args.replace or legacy_layout) and not args.limit

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    seed_model_roots = [OUT_MODELS] + sorted(STATE_DIR.glob("apk-backup-*/lostsword"), reverse=True)
    seed_video_roots = [OUT_VIDEOS] + sorted(STATE_DIR.glob("apk-backup-*/lostsword-video"), reverse=True)

    if do_replace:
        stg_models = STATE_DIR / "staging-models"
        stg_videos = STATE_DIR / "staging-videos"
        shutil.rmtree(stg_models, ignore_errors=True)
        shutil.rmtree(stg_videos, ignore_errors=True)
        stg_models.mkdir(parents=True, exist_ok=True)
        stg_videos.mkdir(parents=True, exist_ok=True)
        m_counts, m_errs = sync_models(folders, stg_models, seed_model_roots)
        v_counts, v_errs = sync_videos(vpaths, stg_videos, seed_video_roots)
        if m_errs or v_errs or (m_counts["skip"] + m_counts["seeded"] + m_counts["downloaded"]) < len(folders):
            raise RuntimeError(
                f"staging gagal divalidasi (model_err={len(m_errs)}, video_err={len(v_errs)}): "
                f"{(m_errs + v_errs)[:5]}"
            )
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_dir = STATE_DIR / f"apk-backup-{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        if OUT_MODELS.is_dir():
            shutil.move(str(OUT_MODELS), str(backup_dir / "lostsword"))
        if OUT_VIDEOS.is_dir():
            shutil.move(str(OUT_VIDEOS), str(backup_dir / "lostsword-video"))
        # Pindahkan juga cache XAPK 2,4 GB keluar repo kalau ada
        old_cache = VIEW / "cache" / "lostsword"
        if old_cache.is_dir():
            shutil.move(str(old_cache), str(backup_dir / "cache-lostsword"))
        shutil.move(str(stg_models), str(OUT_MODELS))
        shutil.move(str(stg_videos), str(OUT_VIDEOS))
        log(f"swap selesai -> backup lama di {backup_dir}")
    else:
        OUT_MODELS.mkdir(parents=True, exist_ok=True)
        OUT_VIDEOS.mkdir(parents=True, exist_ok=True)
        m_counts, m_errs = sync_models(folders, OUT_MODELS, seed_model_roots)
        v_counts, v_errs = sync_videos(vpaths, OUT_VIDEOS, seed_video_roots)

    if args.limit:
        print(json.dumps({
            "ok": not (m_errs or v_errs),
            "limit": args.limit,
            "models": m_counts,
            "videos": v_counts,
            "note": "mode uji — _names.json & _manifest.json tidak ditimpa",
        }, indent=1))
        return 0 if not (m_errs or v_errs) else 1

    names_payload, thumb_manifest, thumb_jobs = build_metadata_and_thumbs(catalog)
    names_payload["bundle"] = bundle_path
    names_payload["sig"] = sig
    (OUT_MODELS / "_names.json").write_text(
        json.dumps(names_payload, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    thumb_ok, thumb_dl, t_errs = sync_thumbs(thumb_jobs, thumb_manifest)

    res = {
        "ok": len(m_errs) == 0 and len(v_errs) == 0,
        "sig": sig,
        "bundle": bundle_path,
        "entries": len(catalog),
        "families": len(names_payload["families"]),
        "spineFolders": len(folders),
        "models": m_counts,
        "videos": v_counts,
        "videoTotal": len(vpaths),
        "names": len(names_payload["models"]),
        "thumbFiles": thumb_ok,
        "thumbDownloaded": thumb_dl,
        "manifestEntries": len(thumb_manifest),
        "replaced": do_replace,
        "errors": (m_errs + v_errs + t_errs)[:12],
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
